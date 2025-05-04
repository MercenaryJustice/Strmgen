import asyncio
import json

from fastapi import APIRouter
from fastapi.responses import StreamingResponse
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

@router.post("/stop")
async def stop_now():
    stop_background_run()
    return {"status": "stopped"}

@router.get("/status", response_model=StatusResponse)
async def pipeline_status():
    """
    HTTP endpoint for status.
    Uses the same is_running() helper as the WebSocket.
    """
    return StatusResponse(running=is_running())


@router.get("/stream/status")
async def stream_status_sse():
    """
    SSE endpoint: stream {"running": bool} every second via EventSource.
    """
    async def event_generator():
        while True:
            running = is_running()
            yield f"data: {json.dumps({'running': running})}\n\n"
            await asyncio.sleep(1)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no"    # disable nginx buffering if used
        }
    )


