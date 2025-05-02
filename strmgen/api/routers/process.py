from fastapi import APIRouter, WebSocket, WebSocketDisconnect, HTTPException
from celery.result import AsyncResult
from strmgen.celery import celery_app
from strmgen.core.pipeline import run_pipeline     # the @shared_task
from strmgen.core.state import (
    set_current_task, get_current_task, clear_current_task
)
from strmgen.api.schemas import StatusResponse
import asyncio

router = APIRouter(tags=["process"])

@router.post("/run", response_model=StatusResponse)
async def run_now():
    # dispatch a new pipeline job
    result = run_pipeline.delay()
    set_current_task(result.id)
    return StatusResponse(running=True, task_id=result.id)

@router.post("/stop", response_model=StatusResponse)
async def stop_now():
    task_id = get_current_task()
    if task_id:
        # revoke and terminate the task
        AsyncResult(task_id, app=celery_app).revoke(terminate=True)
        clear_current_task()
    return StatusResponse(running=False, task_id=None)

@router.get("/status", response_model=StatusResponse)
async def pipeline_status():
    task_id = get_current_task()
    if not task_id:
        return StatusResponse(running=False, task_id=None)
    ar = AsyncResult(task_id, app=celery_app)
    # consider states: PENDING, STARTED → running; else finished
    is_run = ar.state in ("PENDING", "STARTED")
    return StatusResponse(running=is_run, task_id=task_id)

@router.websocket("/ws/status")
async def websocket_status(websocket: WebSocket):
    await websocket.accept()
    try:
        while True:
            status = await pipeline_status()
            await websocket.send_json(status.dict())
            await asyncio.sleep(1)
    except WebSocketDisconnect:
        pass