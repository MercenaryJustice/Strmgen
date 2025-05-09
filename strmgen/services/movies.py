# strmgen/services/movies.py

import asyncio
from typing import Dict, List

from strmgen.core.config import settings
from .subtitles import download_movie_subtitles
from .streams import write_strm_file, get_dispatcharr_stream_by_id
from .tmdb import fetch_movie_details, download_if_missing
from strmgen.core.utils import write_if, write_movie_nfo, filter_by_threshold
from strmgen.core.logger import setup_logger
from strmgen.core.db import mark_skipped, is_skipped, SkippedStream
from strmgen.core.auth import get_auth_headers
from strmgen.core.control import is_running
from strmgen.core.models.dispatcharr import DispatcharrStream

logger = setup_logger(__name__)
TITLE_YEAR_RE = settings.MOVIE_TITLE_YEAR_RE
LOG_TAG = "[MOVIE] 🖼️"


async def process_movies(
    streams: List[DispatcharrStream],
    group: str,
    headers: Dict[str, str],
    reprocess: bool = False
) -> None:
    # bound concurrency for movie tasks
    sem = asyncio.Semaphore(settings.concurrent_requests)

    async def _process_one(stream: DispatcharrStream):
        # bail out if stop requested
        if not is_running():
            return

        async with sem:
            if not is_running():
                return

            # skip if already processed
            if not reprocess and stream.stream_type and await is_skipped(stream.stream_type.name, stream.id):
                logger.info(f"{LOG_TAG} 🚫 Skipped: {stream.name}")
                return

            title = stream.name
            year  = stream.year
            logger.info(f"{LOG_TAG} 🎬 Processing movie: {title}")

            # 1) Fetch TMDb metadata
            movie = await fetch_movie_details(title=title, year=year)
            if not is_running() or not movie:
                logger.info(f"{LOG_TAG} 🚫 '{title}' not found in TMDb")
                return

            # fill in missing year
            if not stream.year and movie.release_date:
                stream.year = int(movie.release_date[:4])
                stream._recompute_paths()

            # 2) Threshold filtering
            ok = await asyncio.to_thread(filter_by_threshold, stream.name, getattr(movie, "raw", None))
            if not is_running() or not ok:
                await asyncio.to_thread(mark_skipped, "MOVIE", group, movie, stream)
                logger.info(f"{LOG_TAG} 🚫 Failed threshold filters: {title}")
                return

            # 3) Write .strm
            wrote = await write_strm_file(stream)
            if not is_running() or not wrote:
                logger.warning(f"{LOG_TAG} ❌ Failed writing .strm for: {stream.strm_path}")
                return

            # 4) Write NFO & schedule artwork
            if settings.write_nfo:
                await asyncio.to_thread(write_if, True, stream, movie, write_movie_nfo)
                asyncio.create_task(download_if_missing(LOG_TAG, stream, movie))

            # 5) Schedule subtitles
            if settings.opensubtitles_download:
                logger.info(f"{LOG_TAG} 🔽 Downloading subtitles for: {title}")
                asyncio.create_task(download_movie_subtitles(movie, stream))

    # launch all movie tasks in parallel
    await asyncio.gather(*(_process_one(s) for s in streams))

    logger.info(f"{LOG_TAG} ✅ Completed processing Movie streams for group: {group}")


async def reprocess_movie(skipped: SkippedStream) -> bool:
    try:
        did = skipped["dispatcharr_id"]
        if not did:
            logger.error(f"{LOG_TAG} Cannot reprocess {skipped['name']}: invalid dispatcharr_id")
            return False

        headers = await get_auth_headers()
        stream  = await get_dispatcharr_stream_by_id(did, headers, timeout=10)
        if not is_running() or not stream:
            logger.error(f"{LOG_TAG} No DispatcharrStream for reprocess: {skipped['name']}")
            return False

    except Exception as e:
        logger.error(f"{LOG_TAG} Error fetching stream for reprocess {skipped['name']}: {e}")
        return False

    try:
        await process_movies([stream], skipped["group"], headers, reprocess=True)
        logger.info(f"{LOG_TAG} ✅ Reprocessed movie: {skipped['name']}")
        return True
    except Exception as e:
        logger.error(f"{LOG_TAG} Reprocess failed for {skipped['name']}: {e}", exc_info=True)
        return False