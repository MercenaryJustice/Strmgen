from fastapi import APIRouter
from fastapi import APIRouter, HTTPException
from strmgen.core.pipeline import (
    start_background_run,
    stop_background_run,
    is_running,
    processor_thread,
    stop_event
)
router = APIRouter(prefix="/process", tags=["Control"])

@router.post("/run_now")
async def run_now():
    start_background_run()
    return {"status": "started"}

@router.post("/stop_now")
async def stop_now():
    if not processor_thread or not processor_thread.is_alive():
        raise HTTPException(409, "Not running")
    stop_event.set()
    return {"status": "stopping"}

@router.get("/status")
async def status():
    return {"running": bool(processor_thread and processor_thread.is_alive())}