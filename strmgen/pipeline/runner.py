# strmgen/pipeline/runner.py

import asyncio
import logging
import fnmatch
import logging

from datetime import datetime, timezone

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.events import EVENT_JOB_EXECUTED, JobExecutionEvent
from more_itertools import chunked

from strmgen.core.config import get_settings
from strmgen.core.auth import get_auth_headers
from strmgen.services.streams import fetch_streams_by_group_name
from strmgen.services.service_24_7 import process_24_7
from strmgen.services.movies import process_movies, movie_cache
from strmgen.services.tv import process_tv
from strmgen.core.logger import notify_progress
from strmgen.core.models.enums import MediaType
from strmgen.core.clients import async_client
from strmgen.core.control import set_processor_task, is_running

logger = logging.getLogger(__name__)

# ─── Scheduler & run‐history ────────────────────────────────────────────────
scheduler = AsyncIOScheduler()
schedule_history: dict[str, datetime] = {}

def _record_daily_run(event: JobExecutionEvent) -> None:
    if event.job_id == "daily_run" and event.exception is None:
        now = datetime.now(timezone.utc)
        schedule_history["daily_run"] = now

# ─── Background‐task control ────────────────────────────────────────────────
processor_task: asyncio.Task | None = None
MAIN_LOOP: asyncio.AbstractEventLoop | None = None

def start_background_run():
    global processor_task, MAIN_LOOP
    if MAIN_LOOP is None or not MAIN_LOOP.is_running():
        logger.error("Event loop not ready—cannot start pipeline")
        return
    if processor_task and not processor_task.done():
        logger.info("Scheduled run skipped: pipeline already running")
        return
    processor_task = MAIN_LOOP.create_task(run_pipeline())
    set_processor_task(processor_task)
    logger.info("Pipeline background task scheduled")

def stop_background_run() -> bool:
    global processor_task
    if processor_task and not processor_task.done():
        processor_task.cancel()
        logger.info("Stop signal sent to pipeline task")
        return True
    return False

# ─── Core async pipeline ────────────────────────────────────────────────────
async def run_pipeline():
    settings = get_settings()
    logger.info("Pipeline starting")
    try:
        headers = await get_auth_headers()

        # 1) Fetch all group names
        try:
            resp = await async_client.get(
                "/api/channels/streams/groups/",
                headers=headers,
                timeout=10
            )
            resp.raise_for_status()
            all_groups = resp.json()
            logger.info("Retrieved %d groups", len(all_groups))
        except Exception:
            logger.exception("Failed to fetch groups, aborting")
            return

        # 2) Filter groups by configured patterns
        if settings.process_groups_24_7:
            matched_24_7 = [
                g for g in all_groups
                if any(fnmatch.fnmatch(g, pat) for pat in settings.groups_24_7)
            ]
        else:
            matched_24_7 = []
        if settings.process_tv_series_groups:
            matched_tv = [
                g for g in all_groups
                if any(fnmatch.fnmatch(g, pat) for pat in settings.tv_series_groups)
            ]
        else:
            matched_tv = []
        if settings.process_movies_groups:
            matched_movies = [
                g for g in all_groups
                if any(fnmatch.fnmatch(g, pat) for pat in settings.movies_groups)
            ]
        else:
            matched_movies = []

        logger.info(f"Matched 24/7 groups ({len(matched_24_7)}), TV groups ({len(matched_tv)}), Movie groups ({len(matched_movies)})")
        if not (matched_24_7 or matched_tv or matched_movies):
            logger.info("No groups matched; pipeline will not run")
            return

        # Helper to process one category of groups
        async def process_category(groups, proc_fn, media_type):
            for grp in groups:
                if not is_running():
                    return
                streams = await fetch_streams_by_group_name(grp, media_type)
                batches = list(chunked(streams, settings.batch_size))
                for idx, batch in enumerate(batches, start=1):
                    logger.info("Starting batch %d/%d for group %s", idx, len(batches), grp)
                    await _process_batch(batch, grp, proc_fn)
                    if not is_running():
                        logger.info("Pipeline stopped during batch %d", idx)
                        return
                    await asyncio.sleep(settings.batch_delay_seconds)
                    notify_progress(
                        media_type=media_type,
                        group=grp,
                        current=idx,
                        total=len(batches),
                    )
                logger.info(f"[PIPELINE] ✅ Completed processing {media_type} streams for group: {grp}")
            if proc_fn == process_movies:
                movie_cache.clear()

        async def _process_batch(batch, grp, proc_fn):
            sem = asyncio.Semaphore(settings.concurrent_requests)
            async def worker(i, total, stream):
                async with sem:
                    if not is_running():
                        return
                    try:
                        await proc_fn([stream], grp, headers)
                    except Exception:
                        logger.exception("Stream %r failed in batch %d/%d for %s", stream, i, total, grp)
            total = len(batch)
            await asyncio.gather(*(worker(i, total, s) for i, s in enumerate(batch, start=1)))

        # 3) Run categories
        if matched_24_7:
            await process_category(matched_24_7, process_24_7, MediaType.STREAM_24_7)
        if matched_movies:
            await process_category(matched_movies, process_movies, MediaType.MOVIE)

        if matched_tv:
            for grp in matched_tv:
                if not is_running():
                    break
                streams = await fetch_streams_by_group_name(grp, MediaType.TV)
                logger.info("TV group %r has %d streams; delegating to process_tv()", grp, len(streams))
                try:
                    await process_tv(streams, grp)
                except Exception:
                    logger.exception("Fatal error in TV group %r; continuing", grp)

    except asyncio.CancelledError:
        logger.info("Pipeline task was cancelled")
    except Exception:
        logger.exception("Pipeline aborted due to unexpected error")
    finally:
        if processor_task and processor_task.cancelled():
            logger.info("Pipeline was cancelled")
        else:
            logger.info("Pipeline completed successfully")

# ─── Scheduler setup ────────────────────────────────────────────────────────
def schedule_on_startup():
    global MAIN_LOOP
    settings = get_settings()
    MAIN_LOOP = asyncio.get_running_loop()
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
def main():
    schedule_on_startup()
    start_background_run()
    asyncio.get_event_loop().run_forever()

if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s"
    )
    main()