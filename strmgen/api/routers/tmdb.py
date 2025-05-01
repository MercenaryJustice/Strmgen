from fastapi import APIRouter, HTTPException
from strmgen.services.tmdb import fetch_movie_details, fetch_tv_details
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse

router = APIRouter(prefix="/tmdb", tags=["TMDb"])


@router.get(
    "/info/{stream_type}/{tmdb_id}",
    response_model=dict,       # or a more specific schema of your choosing
)
async def api_tmdb_info(stream_type: str, tmdb_id: int):
    if stream_type.lower() == "movie":
        info = fetch_movie_details(tmdb_id)
    else:
        info = fetch_tv_details(tmdb_id)

    if not info:
        raise HTTPException(404, f"No TMDb info for {stream_type} {tmdb_id}")

    # this converts Pydantic models (and any other odd types) into plain JSON-able dicts
    payload = jsonable_encoder(info)
    return JSONResponse(content=payload)