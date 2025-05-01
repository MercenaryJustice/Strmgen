from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from strmgen.core.pipeline import (
    scheduler,
    schedule_history,
)
from apscheduler.triggers.cron import CronTrigger
from strmgen.core.config import CONFIG_PATH, _json_cfg, settings

router = APIRouter(prefix="/schedule", tags=["Schedule"])

class ScheduleUpdate(BaseModel):
    hour: int
    minute: int

@router.get("/get_schedule")
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

@router.post("/update_schedule")
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
