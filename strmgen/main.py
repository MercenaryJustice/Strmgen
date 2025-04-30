# strmgen/main.py

import asyncio
import json
from pathlib import Path
from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from apscheduler.triggers.cron import CronTrigger
from apscheduler.events import EVENT_JOB_EXECUTED

from strmgen.core.config import settings, CONFIG_PATH, _json_cfg
from strmgen.core.pipeline import (
    scheduler,
    start_background_run,
    stop_event,
    processor_thread,
    schedule_history
)
from strmgen.core.pipeline import _record_daily_run
from strmgen.core.logger import LOG_PATH
from strmgen.web_ui.routes import router as ui_router

# ─── FastAPI & lifespan ─────────────────────────────────────────────────────
app = FastAPI(title="STRMGen API & UI", debug=True)

@app.on_event("startup")
async def on_startup():
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
            replace_existing=True
        )
        scheduler.add_listener(_record_daily_run, EVENT_JOB_EXECUTED)
    else:
        # if you want to disable entirely
        app.logger.info("Scheduled task is disabled (enable_scheduled_task=false)")

@app.on_event("shutdown")
async def on_shutdown():
    scheduler.shutdown(wait=False)

# ─── Static / UI ─────────────────────────────────────────────────────────────
BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR / "web_ui" / "static"
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

@app.get("/favicon.ico", include_in_schema=False)
async def favicon():
    return FileResponse(STATIC_DIR / "img" / "strmgen_icon.png")

app.include_router(ui_router)


# ─── Schedule endpoints ─────────────────────────────────────────────────────
class ScheduleUpdate(BaseModel):
    hour: int
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
    h, m = update.hour, update.minute
    if not (0 <= h < 24 and 0 <= m < 60):
        raise HTTPException(400, "hour must be 0–23 and minute 0–59")

    # in‐memory reschedule
    scheduler.reschedule_job("daily_run", trigger=CronTrigger(hour=h, minute=m))

    # persist into config.json
    _json_cfg["scheduled_hour"]   = h
    _json_cfg["scheduled_minute"] = m
    try:
        CONFIG_PATH.write_text(json.dumps(_json_cfg, indent=2), encoding="utf-8")
    except Exception:
        app.logger.exception("Failed to persist schedule to config.json")

    next_run = scheduler.get_job("daily_run").next_run_time
    return {
        "hour":     h,
        "minute":   m,
        "next_run": next_run.isoformat() if next_run else None,
    }


# ─── Logs endpoints ─────────────────────────────────────────────────────────
@app.get("/api/logs", include_in_schema=False)
async def get_logs():
    if not LOG_PATH.exists():
        return {"logs": []}
    try:
        lines = LOG_PATH.read_text(encoding="utf-8").splitlines()
    except Exception:
        app.logger.exception("Failed to read log file")
        raise HTTPException(500, "Could not read logs")
    return {"logs": lines}

@app.websocket("/ws/logs")
async def websocket_logs(ws: WebSocket):
    await ws.accept()
    if not LOG_PATH.exists():
        await ws.send_text("No log file found.")
        await ws.close()
        return

    with LOG_PATH.open("r", encoding="utf-8") as f:
        f.seek(0, 2)  # go to EOF
        try:
            while True:
                line = f.readline()
                if line:
                    await ws.send_text(line.rstrip("\n"))
                else:
                    await asyncio.sleep(0.5)
        except WebSocketDisconnect:
            app.logger.debug("WebSocket client disconnected")
        except Exception:
            app.logger.exception("Error in websocket tail")
        finally:
            # ensure close only once
            try:
                await ws.close()
            except RuntimeError:
                pass

@app.post("/api/clear_logs", include_in_schema=False)
async def clear_logs():
    if LOG_PATH.exists():
        try:
            LOG_PATH.write_text("")
            app.logger.info("Cleared log file via API")
        except Exception:
            app.logger.exception("Failed to clear logs")
            raise HTTPException(500, "Could not clear logs")
    return {"status": "cleared"}


# ─── Run/Stop/Status endpoints ───────────────────────────────────────────────
@app.post("/api/run", include_in_schema=False)
async def run_pipeline():
    start_background_run()
    return {"status": "started"}

@app.post("/api/stop", include_in_schema=False)
async def stop_pipeline():
    if not (processor_thread and processor_thread.is_alive()):
        raise HTTPException(409, "Processing not running")
    stop_event.set()
    app.logger.info("Stop signal sent")
    return {"status": "stopping"}

@app.get("/api/status", include_in_schema=False)
async def pipeline_status():
    return {"running": bool(processor_thread and processor_thread.is_alive())}