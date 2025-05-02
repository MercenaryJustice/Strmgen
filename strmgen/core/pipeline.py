# strmgen/core/pipeline.py

import threading
import requests
import fnmatch
from pathlib import Path
from datetime import datetime

from .config import settings
from .auth import refresh_access_token_if_needed
from ..services.streams import fetch_streams_by_group_name
from ..services._24_7 import process_24_7
from ..services.movies import process_movie
from ..services.tv import process_tv
from .logger import setup_logger

from celery import shared_task

logger = setup_logger(__name__)

# ─── Scheduler + history ────────────────────────────────────────────────────
schedule_history: dict[str, datetime] = {}

@shared_task(name="strmgen.core.pipeline.run_pipeline")
def run_pipeline():
    """
    Celery task wrapper around your CLI/main pipeline.
    """
    # If your cli_main currently takes a stop_event, you can
    # refactor it to pull a global flag or simply run to completion.
    cli_main()



# ─── Thread‐based runner ─────────────────────────────────────────────────────
processor_thread: threading.Thread | None = None
stop_event = threading.Event()

def _thread_target():
    try:
        cli_main()
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


# ─── Core pipeline logic ─────────────────────────────────────────────────────
def cli_main():
    logger.info("Pipeline starting")
    token = refresh_access_token_if_needed()
    headers = {"Authorization": f"Bearer {token}"}


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

        logger.info("Processing %s group: %s", label, grp)
        try:
            streams = fetch_streams_by_group_name(grp, headers)
        except Exception:
            logger.exception("Error fetching streams for %s", grp)
            continue

        for stream in streams:
            logger.info("  %s → %s (ID %s)", label, stream.name, stream.id)
            proc_fn(
                stream,
                Path(settings.output_root),
                grp,
                headers
            )


# ─── CLI entrypoint ─────────────────────────────────────────────────────────
if __name__ == "__main__":
    cli_main()