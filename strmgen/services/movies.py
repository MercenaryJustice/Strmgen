# strmgen/services/movies.py

import asyncio
from pathlib import Path
from typing import Optional, Dict

from ..core.config import settings
from .subtitles import download_movie_subtitles
from .streams import write_strm_file, get_stream_by_id
from ..core.models import DispatcharrStream
from .tmdb import get_movie, download_if_missing
from ..core.utils import clean_name, target_folder, write_if, write_movie_nfo, filter_by_threshold
from ..core.logger import setup_logger
from ..core.state import mark_skipped, is_skipped, SkippedStream, set_reprocess
from ..core.auth import get_auth_headers

logger = setup_logger(__name__)
TITLE_YEAR_RE = settings.MOVIE_TITLE_YEAR_RE
log_tag = "[MOVIE] 🖼️"


class MoviePaths:
    @staticmethod
    def base_folder(root: Path, group: str, title: str, year: Optional[int]) -> Path:
        """Return (and create) the folder for a movie."""
        return target_folder(root, "Movies", group, f"{title} ({year})")

    @staticmethod
    def strm_path(folder: Path, title: str) -> Path:
        """Path for the .strm file."""
        return folder / f"{title}.strm"

    @staticmethod
    def nfo_path(folder: Path, title: str) -> Path:
        """Path for the .nfo file."""
        return folder / f"{title}.nfo"

    @staticmethod
    def poster_path(folder: Path) -> Path:
        """Path for the poster image."""
        return folder / "poster.jpg"

    @staticmethod
    def backdrop_path(folder: Path) -> Path:
        """Path for the backdrop (fanart) image."""
        return folder / "fanart.jpg"


async def process_movie(
    stream: DispatcharrStream,
    root: Path,
    group: str,
    headers: Dict[str, str]
) -> None:
    """
    Async processing for movie streams:
      1. Clean & parse title/year
      2. Lookup & cache TMDb metadata
      3. Filter by threshold
      4. Write .strm, .nfo, download poster/fanart, and subtitles
    """
    # 1) Clean title and parse year if present
    m = TITLE_YEAR_RE.match(stream.name)
    if m:
        raw_title, raw_year = m.group(1), m.group(2)
        title = clean_name(raw_title)
        year = int(raw_year)
    else:
        title = clean_name(stream.name)
        year = None

    logger.info("[MOVIE] 🎬 Processing movie: %s", title)

    # 2) Fetch movie metadata (offload sync call)
    movie = await get_movie(title, year)
    if not movie:
        logger.info("[MOVIE] 🚫 '%s' not found in TMDb", title)
        return

    # 3) Skip if already marked
    if await asyncio.to_thread(is_skipped, "MOVIE", movie.id):
        logger.info("[MOVIE] ⏭️ Skipped (cached): %s", title)
        return

    # 4) Threshold filtering
    ok = await asyncio.to_thread(filter_by_threshold, stream.name, getattr(movie, "raw", None))
    if not ok:
        await asyncio.to_thread(mark_skipped, "MOVIE", group, movie, stream)
        logger.info("[MOVIE] 🚫 Failed threshold filters: %s", title)
        return

    # 5) Prepare output paths
    folder = await asyncio.to_thread(MoviePaths.base_folder, root, group, title, movie.year)
    if not year:
        year = movie.year
        title = f"{title} ({year})"
    strm_file = await asyncio.to_thread(MoviePaths.strm_path, folder, title)

    # 6) Write .strm
    wrote = await write_strm_file(strm_file, headers, stream)
    if not wrote:
        logger.warning("[MOVIE] ❌ Failed writing .strm for: %s", strm_file)
        return

    # 7) Write NFO & download poster/fanart
    if settings.write_nfo:
        nfo_file = await asyncio.to_thread(MoviePaths.nfo_path, folder, title)
        await asyncio.to_thread(write_if, True, nfo_file, write_movie_nfo, movie.raw)

        poster_url = getattr(movie, "poster_path", None)
        if poster_url:
            poster_dest = await asyncio.to_thread(MoviePaths.poster_path, folder)
            await asyncio.to_thread(download_if_missing, log_tag, f"{title} poster", poster_url, poster_dest)

        backdrop_url = getattr(movie, "backdrop_path", None)
        if backdrop_url:
            backdrop_dest = await asyncio.to_thread(MoviePaths.backdrop_path, folder)
            await asyncio.to_thread(download_if_missing, log_tag, f"{title} backdrop", backdrop_url, backdrop_dest)

    # 8) Download subtitles if enabled
    if settings.opensubtitles_download:
        logger.info("[MOVIE] 🔽 Downloading subtitles for: %s", title)
        await download_movie_subtitles(movie, folder, str(movie.id))


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
        raw     = await get_stream_by_id(did, headers, timeout=10)
        if not raw:
            logger.error("No DispatcharrStream for reprocess: %s", skipped["name"])
            return False

        stream = DispatcharrStream.from_dict(raw)
    except Exception as e:
        logger.error("Error fetching stream for reprocess %s: %s", skipped["name"], e)
        return False

    root = Path(settings.output_root)
    try:
        await process_movie(stream, root, skipped["group"], headers)
        await asyncio.to_thread(set_reprocess, skipped["tmdb_id"], False)
        logger.info("✅ Reprocessed movie: %s", skipped["name"])
        return True
    except Exception as e:
        logger.error("Reprocess failed for %s: %s", skipped["name"], e)
        return False