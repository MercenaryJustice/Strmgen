# strmgen/core/pipeline.py

import asyncio
import logging
import fnmatch
import json
from pathlib import Path
from datetime import datetime, timezone

import httpx
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.events import EVENT_JOB_EXECUTED, JobExecutionEvent

from .config import settings, CONFIG_PATH, _json_cfg
from .auth import get_auth_headers
from ..services.streams import fetch_streams_by_group_name
from ..services._24_7 import process_24_7
from ..services.movies import process_movie
from ..services.tv import process_tv
from .logger import setup_logger

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
        async def process_category(groups, proc_fn, label):
            for grp in groups:
                if not is_running():
                    logger.info("Pipeline was stopped before %s group %s", label, grp)
                    return
                logger.info("Processing %s group: %s", label, grp)
                # fetch streams in a thread (because your existing service is sync)
                try:
                    streams = await fetch_streams_by_group_name(grp, headers)
                except Exception:
                    logger.exception("Error fetching streams for %s", grp)
                    continue

                for stream in streams:
                    if not is_running():
                        logger.info("Pipeline stopped during %s group %s", label, grp)
                        return
                    logger.info("  %s → %s (ID %s)", label, stream.name, stream.id)
                    # process each stream, but don’t let one bad stream kill the whole category
                    try:
                        await proc_fn(stream, Path(settings.output_root), grp, headers)
                    except Exception:
                        logger.exception(
                            "Error processing stream %s in group %s; skipping", stream.id, grp
                        )
                        continue

        # 3) Execute categories, but isolate failures per category
        for groups, fn, name in [
            (matched_24_7, process_24_7, "24/7"),
            (matched_tv,    process_tv,    "TV"),
            (matched_movies, process_movie, "Movie"),
        ]:
            try:
                await process_category(groups, fn, name)
            except Exception:
                logger.exception("Fatal error in %s category; continuing", name)

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
    scheduler.start()
    if settings.enable_scheduled_task:
        trigger = CronTrigger(
            hour=settings.scheduled_hour,
            minute=settings.scheduled_minute
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