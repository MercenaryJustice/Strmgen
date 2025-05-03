# strmgen/core/pipeline.py

import threading
import requests
import fnmatch
import json
from pathlib import Path
from datetime import datetime, timezone
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.events import EVENT_JOB_EXECUTED

from .config import settings, CONFIG_PATH, _json_cfg
from .auth import get_auth_headers
from ..services.streams import fetch_streams_by_group_name
from ..services._24_7 import process_24_7
from ..services.movies import process_movie
from ..services.tv import process_tv
from .logger import setup_logger

logger = setup_logger(__name__)

# ─── Scheduler + history ────────────────────────────────────────────────────
scheduler = AsyncIOScheduler()
schedule_history: dict[str, datetime] = {}

def _record_daily_run(event):
    if event.job_id == "daily_run" and event.exception is None:
        now = datetime.now(timezone.utc)
        schedule_history["daily_run"] = now
        # also persist last_run in config.json
        _json_cfg["last_run"] = now.isoformat()
        try:
            CONFIG_PATH.write_text(json.dumps(_json_cfg, indent=2), encoding="utf-8")
        except Exception:
            logger.exception("Failed to persist last_run to config.json")


# ─── Thread‐based runner ─────────────────────────────────────────────────────
processor_thread: threading.Thread | None = None
stop_event = threading.Event()

def _thread_target():
    try:
        cli_main(stop_event=stop_event)
    except Exception:
        logger.exception("Error in pipeline thread")

def start_background_run():
    global processor_thread, stop_event
    if processor_thread and processor_thread.is_alive():
        logger.info("Scheduled run skipped: pipeline already running")
        return
    stop_event.clear()
    processor_thread = threading.Thread(target=_thread_target, daemon=True)
    processor_thread.start()
    logger.info("Pipeline thread started by scheduler/UI")

def stop_background_run():
    if processor_thread and processor_thread.is_alive():
        stop_event.set()
        logger.info("Stop signal sent")
        return True
    return False

def is_running() -> bool:
    return bool(processor_thread and processor_thread.is_alive())

def schedule_on_startup():
    """Call this once at app startup to configure the APScheduler job (if enabled)."""
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
    else:
        logger.info("Scheduled task disabled")

# ─── Core pipeline logic ─────────────────────────────────────────────────────
def cli_main(stop_event: threading.Event | None = None):
    logger.info("Pipeline starting")
    headers = get_auth_headers()

    def should_stop() -> bool:
        return stop_event is not None and stop_event.is_set()

    # 1) fetch all group names
    try:
        resp = requests.Session().get(
            f"{settings.api_base}/api/channels/streams/groups/",
            headers=headers,
            timeout=10
        )
        resp.raise_for_status()
        all_groups = resp.json()
        logger.info("Retrieved %d groups", len(all_groups))
    except Exception:
        logger.exception("Failed to fetch groups, aborting")
        return

    # 2) filter by your three categories
    matched_24_7  = [
        g for g in all_groups
        if settings.process_groups_24_7 and any(fnmatch.fnmatch(g, pat) for pat in settings.groups_24_7)
    ]
    matched_tv    = [
        g for g in all_groups
        if settings.process_tv_series_groups and any(fnmatch.fnmatch(g, pat) for pat in settings.tv_series_groups)
    ]
    matched_movies= [
        g for g in all_groups
        if settings.process_movies_groups and any(fnmatch.fnmatch(g, pat) for pat in settings.movies_groups)
    ]

    # 3) process each group in turn
    for grp, proc_fn, label in [
        *( (g, process_24_7,  "24/7") for g in matched_24_7   ),
        *( (g, process_tv,    "TV")   for g in matched_tv     ),
        *( (g, process_movie, "Movie")for g in matched_movies )
    ]:
        if should_stop():
            logger.info("Stopped before %s group %s", label, grp)
            return

        logger.info("Processing %s group: %s", label, grp)
        try:
            streams = fetch_streams_by_group_name(grp, headers)
        except Exception:
            logger.exception("Error fetching streams for %s", grp)
            continue

        for stream in streams:
            if should_stop():
                logger.info("Stopped during %s group %s", label, grp)
                return

            logger.info("  %s → %s (ID %s)", label, stream.name, stream.id)
            proc_fn(
                stream,
                Path(settings.output_root),
                grp,
                headers
            )

    # 4) final logging
    if stop_event.is_set():
        logger.info("Pipeline was stopped by user")
    else:
        logger.info("Pipeline completed successfully")


# ─── CLI entrypoint ─────────────────────────────────────────────────────────
if __name__ == "__main__":
    cli_main(stop_event=None)