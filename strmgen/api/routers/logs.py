# strmgen/api/routers/logs.py
import logging
import asyncio

from fastapi import APIRouter
from sse_starlette.sse import EventSourceResponse
from strmgen.core.logger import log_queue

router = APIRouter(tags=["logs"])
logger = logging.getLogger(__name__)

# In‑memory list of queues for progress events
progress_listeners: list[asyncio.Queue] = []


import re
from fastapi import Request
from logging import _nameToLevel

@router.get("/stream/logs", name="logs.stream_logs")
async def stream_logs(request: Request):
    """
    SSE endpoint: stream logs filtered by ?level=INFO and ?category=TMDB,EMBY
    """
    level_str = request.query_params.get("level", "INFO").upper()
    raw_categories = request.query_params.get("category", "MOVIE,TV")
    categories = {c.strip().upper() for c in raw_categories.split(",") if c.strip()}
    level = _nameToLevel.get(level_str, logging.INFO)

    logger.info("Client connected to SSE stream with level=%s and categories=%s", level_str, categories or "*")

    async def event_generator():
        try:
            while True:
                line = await log_queue.get()

                # Level check
                if m := re.search(r"\b(INFO|DEBUG|WARNING|ERROR|CRITICAL)\b", line):
                    line_level = _nameToLevel.get(m.group(1), logging.INFO)
                    if line_level < level:
                        continue

                # Category match (if specified)
                if categories:
                    cat_match = re.search(r"\[(.*?)\]", line)
                    if not cat_match:
                        continue
                    log_cat = cat_match.group(1).upper()
                    if not any(cat in log_cat for cat in categories):
                        continue

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