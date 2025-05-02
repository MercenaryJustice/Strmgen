# strmgen/api/routers/logs.py

import os
import asyncio
from typing import Optional, List
from pathlib import Path
from collections import deque

import aiofiles
from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from starlette.websockets import WebSocketState

from strmgen.core.logger import LOG_PATH, setup_logger
from strmgen.api.schemas import LogsResponse, ClearResponse

# Configuration
MAX_LOG_LINES = 10_000

router = APIRouter(tags=["Logs"])
logger = setup_logger("LOGS")


async def tail_f(path: Path):
    """
    Asynchronously yield new lines appended to `path` (like `tail -f`).
    Uses aiofiles to avoid blocking the event loop.
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


def tail_lines_sync(path: Path, n: int) -> List[str]:
    """
    Return the last n lines of the file at `path` using a deque.
    """
    try:
        with path.open("r", encoding="utf-8") as f:
            return list(deque(f, maxlen=n))
    except Exception:
        logger.exception("Error reading last lines from %s", path)
        raise HTTPException(status_code=500, detail="Could not read log file")


@router.get("", response_model=LogsResponse)
async def get_logs(limit: Optional[int] = None):
    """
    GET /api/v1/logs?limit={n}
    Return the last `limit` log lines (or all if not specified).
    """
    logger.info("GET /api/v1/logs called with limit=%s", limit)
    if not LOG_PATH.exists():
        return LogsResponse(total=0, logs=[])

    if limit is not None:
        if limit <= 0 or limit > MAX_LOG_LINES:
            raise HTTPException(
                status_code=400,
                detail=f"limit must be between 1 and {MAX_LOG_LINES}"
            )
        lines = tail_lines_sync(LOG_PATH, limit)
        try:
            with LOG_PATH.open("r", encoding="utf-8") as f:
                total = sum(1 for _ in f)
        except Exception:
            logger.exception("Error counting lines in %s", LOG_PATH)
            total = len(lines)
    else:
        try:
            content = LOG_PATH.read_text(encoding="utf-8")
        except Exception:
            logger.exception("Error reading full log file")
            raise HTTPException(status_code=500, detail="Could not read log file")
        lines = content.splitlines()
        total = len(lines)

    return LogsResponse(total=total, logs=lines)


@router.get("/download")
def download_logs():
    """
    GET /api/v1/logs/download
    Stream the entire log file as plain text.
    """
    logger.info("GET /api/v1/logs/download called")
    if not LOG_PATH.exists():
        raise HTTPException(status_code=404, detail="Log file not found")

    def file_iterator():
        with LOG_PATH.open("rb") as f:
            for chunk in iter(lambda: f.read(8192), b""):
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
    Clear the contents of the log file.
    """
    logger.info("POST /api/v1/logs/clear called")
    try:
        LOG_PATH.write_text("", encoding="utf-8")
        logger.info("Cleared log file via API")
    except Exception:
        logger.exception("Could not clear logs")
        raise HTTPException(status_code=500, detail="Could not clear logs")
    return ClearResponse(status="cleared")


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

