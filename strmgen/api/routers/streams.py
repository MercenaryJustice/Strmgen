from typing import List

from fastapi import APIRouter, HTTPException, Query, Body, Request

from strmgen.services.streams import (
    fetch_groups,
    fetch_streams_by_group_name,
    get_stream_by_id,
    is_stream_alive,
)
from strmgen.core.logger import setup_logger
from strmgen.core.state import (
    list_skipped,
    update_skipped_reprocess,
    SkippedStream
)

logger = setup_logger(__name__)

router = APIRouter(tags=["Streams"])

@router.get("/stream-groups", response_model=List[str])
async def api_groups():
    return fetch_groups()

@router.get("/streams-by-group/{group}")
async def api_streams(group: str, request: Request):
    try:
        headers = dict(request.headers)
        return fetch_streams_by_group_name(group, headers)
    except Exception as e:
        logger.error("Failed fetching streams: %s", e)
        raise HTTPException(500, "Error fetching streams")

@router.get("/stream-by-id/{stream_id}")
async def api_stream(stream_id: int, request: Request):
    headers = dict(request.headers)
    data = get_stream_by_id(stream_id, headers)
    if data is None:
        raise HTTPException(404, "Stream not found")
    return data

@router.get("/is-stream-alive/{stream_id}/alive")
async def api_stream_alive(stream_id: int, request: Request):
    headers = dict(request.headers)
    st = get_stream_by_id(stream_id, headers)
    if not st:
        raise HTTPException(404, "Stream not found")
    return {"alive": is_stream_alive(st["url"])}

@router.get("/skipped-streams", response_model=List[SkippedStream])
async def skipped_streams(stream_type: str | None = Query(None)):
    """
    List all skipped streams, optionally filtered by stream_type.
    """
    # Always return the list directly to match response_model=List[SkippedStream]
    rows = list_skipped(stream_type) if stream_type else list_skipped(None)
    return rows

@router.post("/skipped-streams/{stream_type}/{tmdb_id}/reprocess")
async def api_set_reprocess(
    stream_type: str,
    tmdb_id: int,
    payload: dict = Body(...),
):
    """
    Update the `reprocess` flag for a given skipped stream.
    """
    if "reprocess" not in payload:
        raise HTTPException(400, "Missing 'reprocess' in body")
    update_skipped_reprocess(tmdb_id, stream_type, bool(payload["reprocess"]))

    if bool(payload["reprocess"]):
        # Reprocess the stream
        try:
            skipped = list_skipped(stream_type, tmdb_id)
            for s in skipped:
                if s["tmdb_id"] == tmdb_id:
                    if s["stream_type"].lower() == "movie":
                        from strmgen.services.movies import reprocess_movie
                        reprocess_movie(s)
                    else:
                        from strmgen.services.tv import reprocess_tv
                        reprocess_tv(s)
                    break
        except Exception as e:
            logger.error("Failed to reprocess stream: %s", e)
            raise HTTPException(500, "Error reprocessing stream")
    return {"status": "ok"}