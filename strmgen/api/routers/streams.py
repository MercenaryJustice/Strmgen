import logging

from typing import List
from fastapi import APIRouter, HTTPException, Query, Body
from strmgen.services.streams import (
    fetch_groups
)
from strmgen.core.db import (
    list_skipped,
    update_skipped_reprocess,
    SkippedStream
)

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Streams"])

@router.get("/stream-groups", response_model=List[str])
async def api_groups():
    return await fetch_groups()



@router.get("/skipped-streams", response_model=List[SkippedStream], name="skipped.get_skipped_streams")
async def skipped_streams(stream_type: str | None = Query(None)):
    """
    List all skipped streams, optionally filtered by stream_type.
    """
    # Always return the list directly to match response_model=List[SkippedStream]
    rows = await list_skipped(stream_type) if stream_type else await list_skipped(None)
    return rows



@router.post("/skipped-streams/{stream_type}/{tmdb_id}/reprocess", name="skipped.reprocess_stream")
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
    await update_skipped_reprocess(tmdb_id, stream_type, bool(payload["reprocess"]))

    if bool(payload["reprocess"]):
        # Reprocess the stream
        try:
            skipped = list_skipped(stream_type, tmdb_id)
            for s in skipped:
                if s["tmdb_id"] == tmdb_id:
                    if s["stream_type"].lower() == "movie":
                        from strmgen.services.movies import reprocess_movie
                        await reprocess_movie(s)
                    else:
                        from strmgen.services.tv import reprocess_tv
                        await reprocess_tv(s)
                    break
        except Exception as e:
            logger.error("Failed to reprocess stream: %s", e)
            raise HTTPException(500, "Error reprocessing stream")
    return {"status": "ok"}