
import asyncio

from typing import Optional
from fastapi import APIRouter, HTTPException, WebSocket, WebSocketDisconnect
from strmgen.core.logger import LOG_PATH, setup_logger
from strmgen.api.schemas import LogsResponse, ClearResponse

logger = setup_logger(__name__)


router = APIRouter(prefix="/logs", tags=["Logs"])

@router.get("/logs", response_model=LogsResponse)
async def get_logs(limit: Optional[int] = None):
    if not LOG_PATH.exists():
        return LogsResponse(total=0, logs=[])
    all_lines = LOG_PATH.read_text().splitlines()
    if limit:
        lines = all_lines[-limit:]
    else:
        lines = all_lines
    return LogsResponse(total=len(all_lines), logs=lines)

@router.post("/clear-logs", response_model=ClearResponse, status_code=200)
async def clear_logs():
    try:
        LOG_PATH.write_text("")
        logger.info("Cleared log file via API")
    except Exception:
        logger.exception("Could not clear logs")
        raise HTTPException(500, "Could not clear logs")
    return ClearResponse(status="cleared")

@router.websocket("/websocket-logs")
async def websocket_logs(ws: WebSocket):
    await ws.accept()
    if not LOG_PATH.exists():
        await ws.send_text("No log file found.")
        await ws.close()
        return

    with LOG_PATH.open("r", encoding="utf-8") as f:
        f.seek(0, 2)
        try:
            while True:
                line = f.readline()
                if line:
                    await ws.send_text(line.rstrip("\n"))
                else:
                    await asyncio.sleep(0.5)
        except WebSocketDisconnect:
            logger.debug("Client disconnected")
        except Exception:
            logger.exception("Error in log websocket")
        finally:
            await ws.close()