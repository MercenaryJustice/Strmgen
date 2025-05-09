import asyncio

from fastapi import APIRouter, HTTPException, Depends
from strmgen.pipeline.runner import (
    scheduler,
    schedule_history,
)
from apscheduler.triggers.cron import CronTrigger
from strmgen.core.config import save_settings, get_settings, Settings
from strmgen.api.schemas import ScheduleResponse, ScheduleUpdate

router = APIRouter(tags=["Schedule"])


@router.get("/schedule", response_model=ScheduleResponse, name="schedule.get_schedule")
async def get_schedule(cfg: Settings = Depends(get_settings)):
    job = scheduler.get_job("daily_run") if cfg.enable_scheduled_task else None
    next_run = job.next_run_time if job else None
    last_run = schedule_history.get("daily_run") if job else None

    return ScheduleResponse(
        enabled  = cfg.enable_scheduled_task,
        hour     = cfg.scheduled_hour,
        minute   = cfg.scheduled_minute,
        next_run = next_run.isoformat() if next_run else None,
        last_run = last_run.isoformat() if last_run else None,
    )

@router.post("/schedule", response_model=ScheduleResponse, name="schedule.update_schedule")
async def update_schedule(u: ScheduleUpdate,
    cfg: Settings = Depends(get_settings)
):
    if not (0 <= u.hour < 24 and 0 <= u.minute < 60):
        raise HTTPException(400, "hour must be 0–23 and minute 0–59")

    # reschedule in memory
    scheduler.reschedule_job(
        "daily_run",
        trigger=CronTrigger(hour=u.hour, minute=u.minute)
    )
    # Persist to disk via our helper
    cfg.scheduled_hour   = u.hour
    cfg.scheduled_minute = u.minute
    # offload config.json write so we don’t block the loop
    await asyncio.to_thread(save_settings, cfg)

    # Return the new schedule
    job      = scheduler.get_job("daily_run")
    next_run = job.next_run_time if job else None
    last_run = schedule_history.get("daily_run") if job else None
    
    return ScheduleResponse(
        enabled  = cfg.enable_scheduled_task,
        hour     = cfg.scheduled_hour,
        minute   = cfg.scheduled_minute,
        next_run = next_run.isoformat() if next_run else None,
        last_run = last_run.isoformat() if last_run else None,
    )