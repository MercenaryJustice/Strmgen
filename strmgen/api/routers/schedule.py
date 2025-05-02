from fastapi import APIRouter, HTTPException, Depends
from strmgen.api.schemas import ScheduleResponse

router = APIRouter(tags=["Schedule"])


@router.get("/schedule", response_model=ScheduleResponse)
async def get_schedule():
    raise HTTPException(501, "Scheduling is now handled by Celery Beat")

@router.post("/schedule", response_model=ScheduleResponse)
async def set_schedule():
    raise HTTPException(501, "Scheduling is now handled by Celery Beat")