# strmgen/core/pipeline.py

import asyncio
import logging
import fnmatch
import json
from datetime import datetime, timezone

import httpx
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.events import EVENT_JOB_EXECUTED, JobExecutionEvent
from more_itertools import chunked

from .config import settings, CONFIG_PATH, _json_cfg
from .auth import get_auth_headers
from ..services.streams import fetch_streams_by_group_name
from ..services._24_7 import process_24_7
from ..services.movies import process_movies
from ..services.tv import process_tv
from .logger import setup_logger, notify_progress
from ..core.models import MediaType
from ..api.routers.logs import notify_progress

logger = setup_logger(__name__)

# ─── Scheduler & run‑history ────────────────────────────────────────────────
scheduler = AsyncIOScheduler()
schedule_history: dict[str, datetime] = {}


def _record_daily_run(event: JobExecutionEvent) -> None:
    if event.job_id == "daily_run" and event.exception is None:
        now = datetime.now(timezone.utc)
        schedule_history["daily_run"] = now
        _json_cfg["last_run"] = now.isoformat()
        asyncio.create_task(_persist_cfg())

async def _persist_cfg() -> None:
    try:
        await asyncio.to_thread(
            CONFIG_PATH.write_text,
            json.dumps(_json_cfg, indent=2),
            "utf-8"
        )
    except Exception:
        logger.exception("Failed to persist last_run to config.json")

# ─── Background‑task control ────────────────────────────────────────────────
processor_task: asyncio.Task | None = None

def start_background_run():
    """Kick off the pipeline as a background asyncio task."""
    global processor_task
    if processor_task and not processor_task.done():
        logger.info("Scheduled run skipped: pipeline already running")
        return
    processor_task = asyncio.create_task(run_pipeline())
    logger.info("Pipeline background task started")

def stop_background_run() -> bool:
    """Cancel the running pipeline task, if any."""
    global processor_task
    if processor_task and not processor_task.done():
        processor_task.cancel()
        logger.info("Stop signal sent to pipeline task")
        return True
    return False

def is_running() -> bool:
    """Check whether the pipeline is currently running."""
    return bool(processor_task and not processor_task.done())

# ─── Core async pipeline ────────────────────────────────────────────────────
async def run_pipeline():
    logger.info("Pipeline starting")

    try:
        headers = await get_auth_headers()

        # 1) Fetch all group names
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.get(
                    f"{settings.api_base}/api/channels/streams/groups/",
                    headers=headers
                )
                resp.raise_for_status()
                all_groups = resp.json()
            logger.info("Retrieved %d groups", len(all_groups))
        except Exception:
            logger.exception("Failed to fetch groups, aborting")
            return

        # 2) Filter groups by your configured patterns
        matched_24_7 = [
            g for g in all_groups
            if settings.process_groups_24_7 and any(fnmatch.fnmatch(g, pat) for pat in settings.groups_24_7)
        ]
        matched_tv = [
            g for g in all_groups
            if settings.process_tv_series_groups and any(fnmatch.fnmatch(g, pat) for pat in settings.tv_series_groups)
        ]
        matched_movies = [
            g for g in all_groups
            if settings.process_movies_groups and any(fnmatch.fnmatch(g, pat) for pat in settings.movies_groups)
        ]

        # Helper to process one category of groups
        async def process_category(groups, proc_fn, media_type):
            for grp in groups:
                if not is_running(): return
                streams = await fetch_streams_by_group_name(grp, headers, media_type)
                total = len(streams)
                batches = list(chunked(streams, settings.batch_size))

                for idx, batch in enumerate(batches, start=1):
                    logger.info("Starting batch %d/%d for group %s", idx, len(batches), grp)
                    # process this batch (see next section)
                    await _process_batch(batch, grp, proc_fn, media_type, headers)
                    if not is_running():
                        logger.info("Pipeline stopped during batch %d", idx)
                        return
                    # brief pause to respect rate limits and give UI breathing room
                    await asyncio.sleep(settings.batch_delay_seconds)
                    logger.info("[BATCH] Completed %d/%d batches for group %s", idx, len(batches), grp)
                    notify_progress(media_type=media_type, group=grp, current=idx, total=len(batches))


        async def _process_batch(batch, grp, proc_fn, media_type, headers):
            sem = asyncio.Semaphore(settings.concurrent_requests)  # e.g. 5
            async def worker(idx: int, total: int, stream):
                async with sem:
                    if not is_running(): return
                    try:
                        await proc_fn([stream], grp, headers)
                    except Exception:
                        logger.exception("Stream %r failed in batch %d/%d for %s", stream, idx, total, grp)
            total = len(batch)
            await asyncio.gather(*(worker(i, total, s) for i, s in enumerate(batch, start=1)))
            


        # 3) Execute categories, but isolate failures per category
        await process_category(matched_24_7, process_24_7, MediaType._24_7)
        await process_category(matched_movies, process_movies, MediaType.MOVIE)

        # …then TV as one big group of streams, letting process_tv do its own batching
        for grp in matched_tv:
            if not is_running(): break
            streams = await fetch_streams_by_group_name(grp, headers, MediaType.TV)
            logger.info("TV group %r has %d total streams; delegating to process_tv()", grp, len(streams))
            try:
                await process_tv(streams, grp, headers)
            except Exception:
                logger.exception("Fatal error in TV group %r; continuing", grp)



    except asyncio.CancelledError:
        logger.info("Pipeline task was cancelled")
        return

    except Exception:
        logger.exception("Pipeline aborted due to unexpected error")
        return

    # 4) Final logging
    if processor_task and processor_task.cancelled():
        logger.info("Pipeline was cancelled")
    else:
        logger.info("Pipeline completed successfully")





# ─── Scheduler setup ────────────────────────────────────────────────────────
def schedule_on_startup():
    # 2) start the scheduler (reuses the running asyncio loop)
    scheduler.start()

    if settings.enable_scheduled_task:
        trigger = CronTrigger(
            hour=settings.scheduled_hour,
            minute=settings.scheduled_minute,
        )
        scheduler.add_job(
            start_background_run,
            trigger=trigger,
            id="daily_run",
            replace_existing=True,
        )
        scheduler.add_listener(_record_daily_run, EVENT_JOB_EXECUTED)
        logger.info(
            "Scheduled daily pipeline run at %02d:%02d UTC",
            settings.scheduled_hour,
            settings.scheduled_minute,
        )
    else:
        logger.info("Scheduled task disabled")

# ─── CLI entrypoint for ad‑hoc runs ─────────────────────────────────────────
if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s"
    )
    # Schedule and start one immediate run, then keep the loop alive
    schedule_on_startup()
    start_background_run()
    asyncio.get_event_loop().run_forever()