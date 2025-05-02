import asyncio

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from strmgen.core.pipeline import (
    start_background_run,
    stop_background_run,
    is_running
)
from strmgen.api.schemas import StatusResponse

router = APIRouter(tags=["process"])

@router.post("/run")
async def run_now():
    start_background_run()
    return {"status": "started"}

@router.post("/stop", response_model=StatusResponse)
async def stop_now():
    stop_background_run()                # ← centralized stop
    return StatusResponse(running=is_running())

@router.get("/status", response_model=StatusResponse)
async def pipeline_status():
    """
    HTTP endpoint for status.
    Uses the same is_running() helper as the WebSocket.
    """
    return StatusResponse(running=is_running())

@router.websocket("/ws/status")
async def websocket_status(websocket: WebSocket):
    """
    WS endpoint that pushes {"running": bool} every second,
    using the same is_running() helper.
    """
    await websocket.accept()
    print("🛰️  New WS client for status updates")
    try:
        while True:
            running = is_running()
            print(f"🛰️  sending running={running}")
            await websocket.send_json({"running": running})
            await asyncio.sleep(1)
    except WebSocketDisconnect:
        print("🛰️  Client disconnected")