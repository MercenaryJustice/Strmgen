import asyncio
import json

from fastapi import APIRouter
from strmgen.pipeline.runner import (
    start_background_run,
    stop_background_run,
    is_running
)
from strmgen.api.schemas import StatusResponse
from sse_starlette.sse import EventSourceResponse

router = APIRouter(tags=["process"])

@router.post("/run", name="process.run")
async def run_now():
    start_background_run()
    return {"status": "started"}

@router.post("/stop", name="process.stop")
async def stop_now():
    stop_background_run()
    return {"status": "stopped"}

@router.get("/status", response_model=StatusResponse, name="process.get_status")
async def pipeline_status():
    """
    HTTP endpoint for status.
    Uses the same is_running() helper as the WebSocket.
    """
    return StatusResponse(running=is_running())


@router.get("/stream/status", name="process.stream_status")
async def stream_status_sse():
    """
    SSE endpoint: stream {"running": bool} every second via EventSource.
    """
    async def event_generator():
        while True:
            yield f"data: {json.dumps({'running': is_running()})}\n\n"
            await asyncio.sleep(1)

    return EventSourceResponse(
        event_generator(),
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no"
        }
    )


