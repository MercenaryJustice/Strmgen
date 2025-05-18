# strmgen/api/routers/logs.py

import asyncio

from fastapi import APIRouter
from sse_starlette.sse import EventSourceResponse
from strmgen.core.logger import log_queue, setup_logger

router = APIRouter(tags=["logs"])
logger = setup_logger(__name__)

# In‑memory list of queues for progress events
progress_listeners: list[asyncio.Queue] = []


@router.get("/stream/logs", name="logs.stream_logs")
async def stream_logs():
    """
    SSE endpoint: stream every log line as it’s logged.
    """
    logger.info("Client connected to SSE log stream")
    async def event_generator():
       try:
            while True:
                line = await log_queue.get()
                yield f"* {line}\n\n"
       except asyncio.CancelledError:
           logger.info("Client disconnected from SSE log stream")
           return
    return EventSourceResponse(event_generator())


@router.get("/status", name="logs.get_status")
async def stream_status():
    """
    SSE endpoint: stream progress events for media processing.
    """
    q = asyncio.Queue(maxsize=100)
    progress_listeners.append(q)

    async def event_generator():
        try:
            while True:
                data = await q.get()
                yield f"event: progress\ndata: {data}\n\n"
        finally:
            progress_listeners.remove(q)

    return EventSourceResponse(event_generator())