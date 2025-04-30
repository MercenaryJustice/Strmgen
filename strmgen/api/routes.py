# strmgen/api/routes.py

from typing import List, Optional
from fastapi import APIRouter, HTTPException, WebSocket, WebSocketDisconnect
from pydantic import BaseModel

import json
import asyncio

from strmgen.services.streams import (
    fetch_groups,
    fetch_streams_by_group_name,
    get_stream_by_id,
    is_stream_alive,
)
from strmgen.core.logger import LOG_PATH, setup_logger
from strmgen.core.pipeline import (
    start_background_run,
    stop_background_run,
    is_running,
    scheduler,
    schedule_history,
    processor_thread,
    stop_event
)
from apscheduler.triggers.cron import CronTrigger
from strmgen.core.config import CONFIG_PATH, _json_cfg, settings

logger = setup_logger(__name__)
router = APIRouter()

#
# Schedule models & endpoints
#
class ScheduleUpdate(BaseModel):
    hour: int
    minute: int

@router.get("/schedule")
async def get_schedule():
    job = scheduler.get_job("daily_run") if settings.enable_scheduled_task else None
    next_run = job.next_run_time if job else None
    last_run = schedule_history.get("daily_run") if job else None

    return {
        "enabled": settings.enable_scheduled_task,
        "hour": settings.scheduled_hour,
        "minute": settings.scheduled_minute,
        "next_run": next_run.isoformat() if next_run else None,
        "last_run": last_run.isoformat() if last_run else None,
    }

@router.post("/schedule")
async def update_schedule(u: ScheduleUpdate):
    if not (0 <= u.hour < 24 and 0 <= u.minute < 60):
        raise HTTPException(400, "hour must be 0–23 and minute 0–59")

    # reschedule in memory
    scheduler.reschedule_job(
        "daily_run",
        trigger=CronTrigger(hour=u.hour, minute=u.minute)
    )
    # persist
    _json_cfg["scheduled_hour"] = u.hour
    _json_cfg["scheduled_minute"] = u.minute
    try:
        CONFIG_PATH.write_text(json.dumps(_json_cfg, indent=2), encoding="utf-8")
    except Exception:
        logger.exception("Failed to persist schedule")

    next_run = scheduler.get_job("daily_run").next_run_time
    return {
        "hour": u.hour,
        "minute": u.minute,
        "next_run": next_run.isoformat() if next_run else None,
    }

#
# Logs
#
@router.get("/logs")
async def get_logs(limit: Optional[int] = None):
    if not LOG_PATH.exists():
        return {"total": 0, "logs": []}
    all_lines = LOG_PATH.read_text().splitlines()
    if limit:
        lines = all_lines[-limit:]
    else:
        lines = all_lines
    return {"total": len(all_lines), "logs": lines}

@router.post("/clear_logs")
async def clear_logs():
    try:
        LOG_PATH.write_text("")
        logger.info("Cleared log file via API")
    except Exception:
        logger.exception("Could not clear logs")
        raise HTTPException(500, "Could not clear logs")
    return {"status": "cleared"}

@router.websocket("/logs")
async def websocket_logs(ws: WebSocket):
    await ws.accept()
    if not LOG_PATH.exists():
        await ws.send_text("No log file found.")
        await ws.close()
        return

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
            logger.debug("Client disconnected")
        except Exception:
            logger.exception("Error in log websocket")
        finally:
            await ws.close()

#
# Pipeline control
#
@router.post("/run")
async def run_now():
    start_background_run()
    return {"status": "started"}

@router.post("/stop")
async def stop_now():
    if not processor_thread or not processor_thread.is_alive():
        raise HTTPException(409, "Not running")
    stop_event.set()
    return {"status": "stopping"}

@router.get("/status")
async def status():
    return {"running": bool(processor_thread and processor_thread.is_alive())}

#
# Streams API
#
@router.get("/groups", response_model=List[str])
async def api_groups():
    return fetch_groups()

@router.get("/streams/{group}")
async def api_streams(group: str):
    try:
        return fetch_streams_by_group_name(group)
    except Exception as e:
        logger.error("Failed fetching streams: %s", e)
        raise HTTPException(500, "Error fetching streams")

@router.get("/stream/{stream_id}")
async def api_stream(stream_id: int):
    data = get_stream_by_id(stream_id)
    if data is None:
        raise HTTPException(404, "Stream not found")
    return data

@router.get("/stream/{stream_id}/alive")
async def api_stream_alive(stream_id: int):
    st = get_stream_by_id(stream_id)
    if not st:
        raise HTTPException(404, "Stream not found")
    return {"alive": is_stream_alive(st["url"])}