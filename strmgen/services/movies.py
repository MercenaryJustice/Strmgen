# strmgen/services/movies.py

import asyncio
from typing import Dict, List

from strmgen.core.config import get_settings
from .subtitles import download_movie_subtitles
from .streams import write_strm_file, get_dispatcharr_stream_by_id
from .tmdb import fetch_movie_details, download_if_missing
from strmgen.core.utils import write_if, write_movie_nfo, filter_by_threshold, safe_remove
from strmgen.core.logger import setup_logger
from strmgen.core.db import mark_skipped, is_skipped, SkippedStream
from strmgen.core.auth import get_auth_headers
from strmgen.core.control import is_running
from strmgen.core.models.dispatcharr import DispatcharrStream
from strmgen.services.emby import emby_movie_exists

logger = setup_logger(__name__)
settings = get_settings()
TITLE_YEAR_RE = settings.MOVIE_TITLE_YEAR_RE
LOG_TAG = "[MOVIE] 🖼️"

movie_cache = {}

async def process_movies(
    streams: List[DispatcharrStream],
    group: str,
    reprocess: bool = False
) -> None:
    """
    Process movie streams:
      1) TMDb lookup + threshold filtering
      2) Write .strm and .nfo
      3) Download artwork and subtitles asynchronously
    """
    settings = get_settings()
    sem = asyncio.Semaphore(settings.concurrent_requests)

    async def _process_one(stream: DispatcharrStream):
        if not is_running():
            return

        async with sem:
            if not is_running():
                return

            # Skip if already processed
            if not reprocess and await is_skipped(stream.stream_type.name, stream.id):
                logger.info(f"{LOG_TAG} 🚫 Skipped: {stream.name}")
                return

            title = stream.name
            year = stream.year
            logger.info(f"{LOG_TAG} 🎬 Processing movie: {title}")

            # Check movie_cache
            if stream.base_path.name in movie_cache:
                logger.info(f"{LOG_TAG} 🚫 Skipping duplicate (cache): {title}")
                if stream.base_path.exists():
                    await asyncio.to_thread(safe_remove, stream.base_path)
                    logger.info(f"{LOG_TAG} ✂️ Removed path due to duplicate: {stream.base_path}")
                await mark_skipped("MOVIE", group, {"title": title, "year": year}, stream)
                return

            # 1) Fetch TMDb metadata
            movie = await fetch_movie_details(title=title, year=year)
            if not is_running() or not movie:
                logger.info(f"{LOG_TAG} 🚫 '{title}' not found in TMDb")
                return

            # Fill missing year
            if not stream.year and movie.release_date:
                stream.year = int(movie.release_date[:4])
                stream._recompute_paths()

            # 2) Threshold filtering
            ok = await asyncio.to_thread(filter_by_threshold, stream.name, movie)
            if not is_running() or not ok:
                try:
                    await mark_skipped("MOVIE", group, movie, stream)
                    logger.info(f"{LOG_TAG} 🚫 Filter failed: {title}")
                    if stream.base_path.exists():
                        await asyncio.to_thread(safe_remove, stream.base_path)
                        logger.info(f"{LOG_TAG} ✂️ Removed path: {stream.base_path}")
                except Exception as e:
                    logger.info(f"{LOG_TAG} Exception occurred: {e}")
                return

            # check Emby first
            if settings.emby_api_key and await emby_movie_exists(movie.title, movie.year):
                logger.info(f"{LOG_TAG} 🚫 Already in Emby: {movie.title} ({movie.year})")
                if stream.base_path.exists():
                    await asyncio.to_thread(safe_remove, stream.base_path)
                    logger.info(f"{LOG_TAG} ✂️ Removed path: {stream.base_path}")
                await mark_skipped("MOVIE", group, movie, stream)
                return


            # 3) Write .strm
            wrote = await write_strm_file(stream)
            if not is_running() or not wrote:
                logger.warning(f"{LOG_TAG} ❌ .strm write failed: {stream.strm_path}")
                return

            # 4) Write NFO and schedule artwork downloads
            if settings.write_nfo:
                await asyncio.to_thread(write_if, True, stream, movie, write_movie_nfo)
                asyncio.create_task(download_if_missing(LOG_TAG, stream, movie))

            # 5) Schedule subtitles
            if settings.opensubtitles_download:
                logger.info(f"{LOG_TAG} 🔽 Downloading subtitles for: {title}")
                asyncio.create_task(download_movie_subtitles(movie, stream))

            # ✅ Add to movie_cache
            movie_cache[stream.base_path.name] = True

    await asyncio.gather(*(_process_one(s) for s in streams))


async def reprocess_movie(skipped: SkippedStream) -> bool:
    try:
        did = skipped.get("dispatcharr_id")
        if not did:
            logger.error(f"{LOG_TAG} Invalid dispatcharr_id for: {skipped.get('name')}")
            return False

        stream = await get_dispatcharr_stream_by_id(did)
        if not is_running() or not stream:
            logger.error(f"{LOG_TAG} No stream for reprocess: {skipped.get('name')}")
            return False
    except Exception as e:
        logger.error(f"{LOG_TAG} Error fetching stream: {e}")
        return False

    try:
        await process_movies([stream], skipped.get("group", ""), reprocess=True)
        logger.info(f"{LOG_TAG} ✅ Reprocessed movie: {skipped.get('name')}")
        return True
    except Exception as e:
        logger.error(f"{LOG_TAG} Reprocess failed: {e}", exc_info=True)
        return False
