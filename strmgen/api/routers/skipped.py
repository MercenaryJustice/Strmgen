from fastapi import APIRouter, HTTPException
from strmgen.core.db import SkippedStream, get_pg_pool
from strmgen.services.movies import reprocess_movie
from strmgen.services.tv    import reprocess_tv

router = APIRouter(tags=["skipped"])

@router.post("/reprocess", status_code=202, name="reprocess_stream")
async def reprocess_stream(skipped: SkippedStream):
    """
    Kick off a reprocess for a single skipped item.
    """
    fn = reprocess_movie if skipped["stream_type"] == "movie" else reprocess_tv
    success = await fn(skipped)
    if not success:
        raise HTTPException(500, f"Failed to reprocess {skipped['name']} ({skipped['tmdb_id']})")
    return {"status": "queued"}

@router.post("/clear", name="skipped.clear")
async def clear_skipped():
    pool = await get_pg_pool()
    async with pool.acquire() as conn:
        try:
            await conn.execute("TRUNCATE TABLE skipped_streams RESTART IDENTITY CASCADE;")
            return {"status": "ok"}
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))