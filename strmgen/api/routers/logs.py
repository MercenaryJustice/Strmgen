
import asyncio

from typing import Optional
from fastapi import APIRouter, HTTPException, WebSocket, WebSocketDisconnect
from strmgen.core.logger import LOG_PATH, setup_logger

logger = setup_logger(__name__)


router = APIRouter(prefix="/logs", tags=["Logs"])

@router.get("/get_logs")
async def get_logs(limit: Optional[int] = None):
    if not LOG_PATH.exists():
        return {"total": 0, "logs": []}
    all_lines = LOG_PATH.read_text().splitlines()
    if limit:
        lines = all_lines[-limit:]
    else:
        lines = all_lines
    return {"total": len(all_lines), "logs": lines}

@router.post("/clear_logs")
async def clear_logs():
    try:
        LOG_PATH.write_text("")
        logger.info("Cleared log file via API")
    except Exception:
        logger.exception("Could not clear logs")
        raise HTTPException(500, "Could not clear logs")
    return {"status": "cleared"}

@router.websocket("/websocket_logs")
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