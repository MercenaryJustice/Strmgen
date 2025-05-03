# strmgen/api/routers/logs.py

import os
import asyncio
from typing import Optional, List
from pathlib import Path
from collections import deque

import aiofiles
from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import StreamingResponse

from strmgen.core.logger import LOG_PATH, setup_logger
from strmgen.api.schemas import LogsResponse, ClearResponse

router = APIRouter(tags=["logs"])
logger = setup_logger("LOGS")

async def tail_f(path: Path):
    """
    Asynchronously yield new lines appended to `path` (like `tail -f`).
    """
    try:
        async with aiofiles.open(path, "r", encoding="utf-8") as f:
            await f.seek(0, os.SEEK_END)
            while True:
                line = await f.readline()
                if not line:
                    await asyncio.sleep(0.1)
                    continue
                yield line.rstrip("\n")
    except Exception:
        logger.exception("Error streaming from log file %s", path)
        raise

def tail_and_count(path: Path, n: Optional[int]) -> tuple[List[str], int]:
    """
    Return the last `n` lines of the log (or all lines if n is None),
    plus the total line count.
    """
    total = 0
    if n is None:
        with path.open("r", encoding="utf-8") as f:
            lines = f.read().splitlines()
        return lines, len(lines)

    dq: deque[str] = deque(maxlen=n)
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            total += 1
            dq.append(line.rstrip("\n"))
    return list(dq), total

@router.get("/", response_model=LogsResponse)
async def get_logs(limit: Optional[int] = Query(None, ge=1, le=10000)):
    """
    GET /api/v1/logs?limit={n}
    Return up to `limit` most recent log lines, plus the total count.
    """
    logger.info("GET /api/v1/logs called with limit=%s", limit)
    if not LOG_PATH.exists():
        raise HTTPException(status_code=404, detail="Log file not found")

    # offload blocking file‐read to a thread
    lines, total = await asyncio.to_thread(tail_and_count, LOG_PATH, limit)
    return LogsResponse(total=total, logs=lines)

@router.get("/download")
async def download_logs():
    """
    GET /api/v1/logs/download
    Stream the entire log file as plain text, attachment.
    """
    logger.info("GET /api/v1/logs/download called")
    if not LOG_PATH.exists():
        raise HTTPException(status_code=404, detail="Log file not found")

    async def file_iterator():
        async with aiofiles.open(LOG_PATH, "rb") as f:
            while True:
                chunk = await f.read(8192)
                if not chunk:
                    break
                yield chunk

    return StreamingResponse(
        file_iterator(),
        media_type="text/plain",
        headers={"Content-Disposition": f"attachment; filename={LOG_PATH.name}"}
    )

@router.post("/clear", response_model=ClearResponse)
async def clear_logs():
    """
    POST /api/v1/logs/clear
    Truncate (clear) the log file contents.
    """
    logger.info("POST /api/v1/logs/clear called")
    if not LOG_PATH.exists():
        raise HTTPException(status_code=404, detail="Log file not found")

    try:
        async with aiofiles.open(LOG_PATH, "w", encoding="utf-8") as f:
            # opening with "w" will truncate the file
            pass
        return ClearResponse(status="cleared")
    except Exception:
        logger.exception("Failed to clear log file %s", LOG_PATH)
        raise HTTPException(status_code=500, detail="Failed to clear log file")

@router.get("/stream")
async def stream_logs_sse():
    """
    GET /api/v1/logs/stream
    SSE endpoint: stream new log lines over EventSource.
    """
    logger.info("Client connected to SSE log stream")
    if not LOG_PATH.exists():
        raise HTTPException(status_code=404, detail="Log file not found")

    async def event_generator():
        async for line in tail_f(LOG_PATH):
            yield f"data: {line}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"}
    )