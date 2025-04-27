# strmgen/main.py

import threading
import asyncio
import requests
import fnmatch
import json

from pathlib import Path
from datetime import datetime, timezone
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.events import EVENT_JOB_EXECUTED

from .config import settings, CONFIG_PATH, _json_cfg
from .auth import refresh_access_token_if_needed
from .streams import fetch_streams_by_group_name
from .process_24_7 import process_24_7
from .process_movie import process_movie
from .process_tv import process_tv
from .log import setup_logger, LOG_PATH
from .tmdb_helpers import _load_tv_genres
from .web_ui.routes import router as ui_router

logger = setup_logger(__name__)

# ─── Scheduler + history + config ───────────────────────────────────────────
scheduler = AsyncIOScheduler()
schedule_history: dict[str, datetime] = {}
# seed schedule_config from settings so it matches your JSON at startup
schedule_config = {
    "hour":   settings.scheduled_hour,
    "minute": settings.scheduled_minute,
}

def _record_daily_run(event):
    # this records the instant the scheduled job fired
    if event.job_id == "daily_run" and event.exception is None:
        ts = datetime.now(timezone.utc)
        schedule_history["daily_run"] = ts

        # also persist to config.json
        _json_cfg["last_run"] = ts.isoformat()
        try:
            CONFIG_PATH.write_text(json.dumps(_json_cfg, indent=2), encoding="utf-8")
        except Exception:
            logger.exception("Failed to persist last_run to config.json")

# ─── Thread target & starter ────────────────────────────────────────────────
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

# ─── Lifespan manager (replaces on_event) ──────────────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
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
        logger.info("Scheduled task is disabled (enable_scheduled_task=false)")

    try:
        yield
    finally:
        scheduler.shutdown(wait=False)

# ─── FastAPI app setup ─────────────────────────────────────────────────────
app = FastAPI(
    title="STRMGen API & UI",
    debug=True,
    lifespan=lifespan
)

# serve static files (CSS, JS, icons)
BASE_DIR   = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR / "web_ui" / "static"
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

@app.get("/favicon.ico", include_in_schema=False)
async def favicon():
    return FileResponse(STATIC_DIR / "img" / "strmgen_icon.png")

app.include_router(ui_router)

# ─── Schedule endpoints ─────────────────────────────────────────────────────
class ScheduleUpdate(BaseModel):
    hour:   int
    minute: int

@app.get("/api/schedule", include_in_schema=False)
async def get_schedule():
    job = scheduler.get_job("daily_run") if settings.enable_scheduled_task else None
    next_run = job.next_run_time if job else None
    last_run = schedule_history.get("daily_run") if job else None

    return {
        "enabled":  settings.enable_scheduled_task,
        "hour":     settings.scheduled_hour,
        "minute":   settings.scheduled_minute,
        "next_run": next_run.isoformat() if next_run else None,
        "last_run": last_run.isoformat()  if last_run else None,
    }

@app.post("/api/schedule", include_in_schema=False)
async def update_schedule(update: ScheduleUpdate):
    new_hour, new_minute = update.hour, update.minute
    if not (0 <= new_hour < 24 and 0 <= new_minute < 60):
        raise HTTPException(400, "hour must be 0–23 and minute 0–59")

    # 1) update in-memory scheduler_config & reschedule job
    schedule_config["hour"]   = new_hour
    schedule_config["minute"] = new_minute
    scheduler.reschedule_job(
        "daily_run",
        trigger=CronTrigger(hour=new_hour, minute=new_minute)
    )

    # 2) update the Pydantic settings & enable flag
    settings.scheduled_hour        = new_hour
    settings.scheduled_minute      = new_minute
    settings.enable_scheduled_task = True

    # 3) update the _json_cfg dict and persist to the same JSON
    _json_cfg["scheduled_hour"]        = new_hour
    _json_cfg["scheduled_minute"]      = new_minute
    _json_cfg["enable_scheduled_task"] = True
    try:
        CONFIG_PATH.write_text(
            json.dumps(_json_cfg, indent=2),
            encoding="utf-8"
        )
    except Exception:
        logger.exception("Failed to persist schedule to config.json")

    # 4) return the updated next_run timestamp
    next_run = scheduler.get_job("daily_run").next_run_time
    return {
        "hour":     new_hour,
        "minute":   new_minute,
        "next_run": next_run.isoformat() if next_run else None,
    }

# ─── Logs endpoints ─────────────────────────────────────────────────────────
@app.get("/api/logs", include_in_schema=False)
async def get_logs(limit: int = 500):
    """
    Return up to the last `limit` lines of the log.
    """
    if not LOG_PATH.exists():
        return {"logs": []}
    try:
        all_lines = LOG_PATH.read_text(encoding="utf-8").splitlines()
    except Exception:
        logger.exception("Failed to read log file")
        raise HTTPException(500, "Could not read logs")

    # slice to only the last `limit` entries
    sliced = all_lines[-limit:] if len(all_lines) > limit else all_lines
    return {"logs": sliced, "total": len(all_lines)}

@app.websocket("/ws/logs")
async def websocket_logs(ws: WebSocket):
    await ws.accept()

    # If no log file, send a message and close *once*
    if not LOG_PATH.exists():
        await ws.send_text("No log file found.")
        return await ws.close()

    # Otherwise tail the file
    with LOG_PATH.open("r", encoding="utf-8") as f:
        f.seek(0, 2)
        try:
            while True:
                line = f.readline()
                if line:
                    await ws.send_text(line.rstrip("\n"))
                else:
                    await asyncio.sleep(0.5)
        except WebSocketDisconnect:
            logger.debug("WebSocket client disconnected")
        except Exception:
            logger.exception("Error in websocket tail")
        finally:
            # only attempt to close once, swallowing any RuntimeError
            try:
                await ws.close()
            except RuntimeError:
                pass

@app.post("/api/clear_logs", include_in_schema=False)
async def clear_logs():
    if LOG_PATH.exists():
        try:
            LOG_PATH.write_text("")
            logger.info("Cleared log file via API")
        except Exception:
            logger.exception("Failed to clear logs")
            raise HTTPException(500, "Could not clear logs")
    return {"status": "cleared"}

# ─── Run/Stop/Status endpoints ───────────────────────────────────────────────
@app.post("/api/run", include_in_schema=False)
async def run_pipeline():
    start_background_run()
    return {"status": "started"}

@app.post("/api/stop", include_in_schema=False)
async def stop_pipeline():
    if not processor_thread or not processor_thread.is_alive():
        raise HTTPException(409, "Processing not running")
    stop_event.set()
    logger.info("Stop signal sent")
    return {"status": "stopping"}

@app.get("/api/status", include_in_schema=False)
async def pipeline_status():
    return {"running": bool(processor_thread and processor_thread.is_alive())}

# ─── Pipeline core ──────────────────────────────────────────────────────────
def cli_main(stop_event: threading.Event | None = None):
    logger.info("Pipeline starting")
    token = refresh_access_token_if_needed()
    headers = {"Authorization": f"Bearer {token}"}
    dispatcharr_url = getattr(settings, "dispatcharr_url", None)

    def should_stop() -> bool:
        return stop_event is not None and stop_event.is_set()

    # fetch groups
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

    # build lists
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

    if matched_tv:
        _load_tv_genres()

    # process each
    for grp, proc_fn, label in [
        *((g, process_24_7, "24/7") for g in matched_24_7),
        *((g, process_tv,   "TV" ) for g in matched_tv),
        *((g, process_movie,"Movie") for g in matched_movies)
    ]:
        if should_stop():
            logger.info("Stopped before %s group %s", label, grp)
            # record finish time
            ts = datetime.now(timezone.utc)
            schedule_history["daily_run"] = ts
            _json_cfg["last_run"] = ts.isoformat()
            try:
                CONFIG_PATH.write_text(json.dumps(_json_cfg, indent=2), encoding="utf-8")
            except Exception:
                logger.exception("Failed to persist last_run to config.json")
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
                ts = datetime.now(timezone.utc)
                schedule_history["daily_run"] = ts
                _json_cfg["last_run"] = ts.isoformat()
                try:
                    CONFIG_PATH.write_text(json.dumps(_json_cfg, indent=2), encoding="utf-8")
                except Exception:
                    logger.exception("Failed to persist last_run to config.json")
                return
            logger.info("  %s → %s (ID %s)", label, stream.name, stream.id)
            proc_fn(
                stream.name,
                stream.id,
                Path(settings.output_root),
                grp,
                headers,
                dispatcharr_url
            )

    # pipeline fully done
    ts = datetime.now(timezone.utc)
    schedule_history["daily_run"] = ts
    _json_cfg["last_run"] = ts.isoformat()
    try:
        CONFIG_PATH.write_text(json.dumps(_json_cfg, indent=2), encoding="utf-8")
    except Exception:
        logger.exception("Failed to persist last_run to config.json")

    if stop_event and stop_event.is_set():
        logger.info("Pipeline was stopped by user")
    else:
        logger.info("Pipeline completed successfully")

# ─── CLI entrypoint ─────────────────────────────────────────────────────────
if __name__ == "__main__":
    cli_main(stop_event=None)