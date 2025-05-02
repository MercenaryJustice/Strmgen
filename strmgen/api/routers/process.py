from fastapi import APIRouter
from fastapi import APIRouter, HTTPException
from strmgen.core.pipeline import (
    start_background_run,
    stop_background_run,
    is_running,
    processor_thread,
    stop_event
)
from strmgen.api.schemas import StatusResponse

router = APIRouter(tags=["Control"])

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

@router.get("/status", include_in_schema=False)
async def pipeline_status():
    return {"running": bool(processor_thread and processor_thread.is_alive())}