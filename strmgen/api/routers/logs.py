# strmgen/api/routers/logs.py

import asyncio
import logging

from fastapi import APIRouter
from sse_starlette.sse import EventSourceResponse

from strmgen.core.logger import log_queue

router = APIRouter(tags=["logs"])
logger = logging.getLogger("LOGS")

# In‑memory list of queues for progress events
progress_listeners: list[asyncio.Queue] = []


@router.get("/stream/logs")
async def stream_logs():
    """
    SSE endpoint: stream every log line as it’s logged.
    """
    logger.info("Client connected to SSE log stream")
    async def event_generator():
        while True:
            line = await log_queue.get()
            yield f"data: {line}\n\n"
    return EventSourceResponse(event_generator())


@router.get("/status")
async def stream_status():
    """
    SSE endpoint: stream progress events for media processing.
    """
    q: asyncio.Queue = asyncio.Queue()
    progress_listeners.append(q)

    async def event_generator():
        try:
            while True:
                data = await q.get()
                yield f"event: progress\ndata: {data}\n\n"
        finally:
            progress_listeners.remove(q)

    return EventSourceResponse(event_generator())