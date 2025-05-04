# strmgen/services/movies.py

import asyncio
from typing import Dict

from ..core.config import settings
from .subtitles import download_movie_subtitles
from .streams import write_strm_file, get_dispatcharr_stream_by_id
from ..core.models import DispatcharrStream
from .tmdb import get_movie, download_if_missing
from ..core.utils import write_if, write_movie_nfo, filter_by_threshold
from ..core.logger import setup_logger
from ..core.state import mark_skipped, is_skipped, SkippedStream
from ..core.auth import get_auth_headers
from ..core.fs_utils import safe_mkdir

logger = setup_logger(__name__)
TITLE_YEAR_RE = settings.MOVIE_TITLE_YEAR_RE
log_tag = "[MOVIE] 🖼️"





async def process_movies(
    streams: list[DispatcharrStream],
    group: str,
    headers: Dict[str, str],
    reprocess: bool = False
) -> None:
    """
    Async processing for movie streams:
      1. Clean & parse title/year
      2. Lookup & cache TMDb metadata
      3. Filter by threshold
      4. Write .strm, .nfo, download poster/fanart, and subtitles
    """
    for stream in streams:
        try:
            if not reprocess and stream.stream_type and is_skipped(stream.stream_type, stream.id):
                logger.info("[MOVIE] 🚫 Skipped: %s", stream.name)
                continue

            title = stream.name
            year = stream.year

            logger.info("[MOVIE] 🎬 Processing movie: %s", title)

            # 2) Fetch movie metadata (offload sync call)
            movie = await get_movie(title, year)
            if not movie:
                logger.info("[MOVIE] 🚫 '%s' not found in TMDb", title)
                return

            if not stream.year and movie.release_date:
                # Update stream with TMDb year if not set
                stream.year = int(movie.release_date[:4])
                stream._recompute_paths()

            # 4) Threshold filtering
            ok = await asyncio.to_thread(filter_by_threshold, stream.name, getattr(movie, "raw", None))
            if not ok:
                await asyncio.to_thread(mark_skipped, "MOVIE", group, movie, stream)
                logger.info("[MOVIE] 🚫 Failed threshold filters: %s", title)
                return

            if not stream.strm_path.parent.exists():
                safe_mkdir(stream.strm_path.parent)


            # 5) Write .strm
            wrote = await write_strm_file(headers, stream)
            if not wrote:
                logger.warning("[MOVIE] ❌ Failed writing .strm for: %s", stream.strm_path)
                return

            # 6) Write NFO & download poster/fanart
            if settings.write_nfo:
                await asyncio.to_thread(write_if, True, stream, movie, write_movie_nfo)

                asyncio.create_task(
                    download_if_missing(log_tag, stream, movie)
                )

            # 7) Download subtitles if enabled
            if settings.opensubtitles_download:
                logger.info("[MOVIE] 🔽 Downloading subtitles for: %s", title)
                asyncio.create_task(download_movie_subtitles(movie, stream))
        except Exception as e:
            logger.error("[MOVIE] ❌ Error processing movie %s: %s", stream.name, e)
    logger.info("Completed processing Movies streams for group: %s", group)




async def reprocess_movie(skipped: SkippedStream) -> bool:
    """
    Async reprocess for a skipped movie entry.
    """
    try:
        did = skipped["dispatcharr_id"]
        if not did:
            logger.error("Cannot reprocess %s: invalid dispatcharr_id", skipped["name"])
            return False

        headers = await get_auth_headers()
        stream     = await get_dispatcharr_stream_by_id(did, headers, timeout=10)
        if not stream:
            logger.error("No DispatcharrStream for reprocess: %s", skipped["name"])
            return False
    except Exception as e:
        logger.error("Error fetching stream for reprocess %s: %s", skipped["name"], e)
        return False

    try:
        await process_movies([stream], skipped["group"], headers)
        #await asyncio.to_thread(set_reprocess, skipped["tmdb_id"], False)
        logger.info("✅ Reprocessed movie: %s", skipped["name"])
        return True
    except Exception as e:
        logger.error("Reprocess failed for %s: %s", skipped["name"], e)
        return False