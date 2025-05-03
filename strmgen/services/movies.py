from pathlib import Path
from typing import Optional, Dict

from ..core.config import settings
from .subtitles import download_movie_subtitles
from .streams import write_strm_file
from ..core.models import DispatcharrStream
from .tmdb import Movie, get_movie, download_if_missing
from ..core.utils import clean_name, target_folder, write_if, write_movie_nfo, filter_by_threshold
from ..core.logger import setup_logger
from ..core.state import mark_skipped, is_skipped
from strmgen.core.state import SkippedStream, set_reprocess
from strmgen.services.streams import get_stream_by_id
from strmgen.core.auth import get_auth_headers

logger = setup_logger(__name__)
TITLE_YEAR_RE = settings.MOVIE_TITLE_YEAR_RE

log_tag = "[MOVIE] 🖼️"

class MoviePaths:
    @staticmethod
    def base_folder(root: Path, group: str, title: str, year: Optional[int]) -> Path:
        """Return and ensure the base folder for a movie."""
        folder = target_folder(root, "Movies", group, f"{title} ({year})")
        return folder

    @staticmethod
    def strm_path(folder: Path, title: str) -> Path:
        """Path for the .strm file."""
        return folder / f"{title}.strm"

    @staticmethod
    def nfo_path(folder: Path, title: str) -> Path:
        """Path for the NFO file."""
        return folder /f"{title}.nfo"

    @staticmethod
    def poster_path(folder: Path) -> Path:
        """Path for the poster image."""
        return folder / f"poster.jpg"

    @staticmethod
    def backdrop_path(folder: Path) -> Path:
        """Path for the backdrop image."""
        return folder / f"fanart.jpg"


def process_movie(
    stream: DispatcharrStream,
    root: Path,
    group: str,
    headers: Dict[str, str]
) -> None:
    """
    Process a single Movie entry:
      1. Clean title from filename
      2. Lookup & cache TMDb metadata
      3. Filter by rating/vote/popularity thresholds
      4. Write .strm, .nfo, download images, and subtitles
    """
    # Strip file extension and sanitize title
    m = TITLE_YEAR_RE.match(stream.name)
    if m:
        raw_title, raw_year = m.group(1), m.group(2)
        title = clean_name(raw_title)
        year = int(raw_year)
    else:
        title = clean_name(stream.name)
        year = None
    logger.info("[MOVIE] 🎬 Processing movie: %s", title)

    # Fetch movie metadata
    movie: Optional[Movie] = get_movie(title, year)
    if not movie:
        return


    if is_skipped("MOVIE", movie.id):
        logger.info("[MOVIE] ⏭️ Skipped movie (cached): %s", title)
        return

    if not filter_by_threshold(stream.name, movie.raw if movie else None):
        mark_skipped("MOVIE", group, movie, stream)
        logger.info("[MOVIE] 🚫 Movie '%s' failed threshold filters", title)
        return

    if not movie:
        logger.info("[MOVIE] 🚫 '%s' not found", title)
        return

    # Prepare paths
    folder = MoviePaths.base_folder(root, group, title, movie.year)

    if not year:
        year = movie.year
        title = f"{title} ({year})"

    strm_file = MoviePaths.strm_path(folder, title)

    # Write .strm
    if not write_strm_file(strm_file, headers, stream):
        logger.warning("[MOVIE] ❌ Failed writing .strm for: %s", strm_file)
        return

    # Write NFO & download assets
    if settings.write_nfo and movie:
        nfo_file = MoviePaths.nfo_path(folder, title)
        write_if(True, nfo_file, write_movie_nfo, movie.raw)
        download_if_missing(log_tag, f"{title} poster", movie.poster_path, MoviePaths.poster_path(folder))
        download_if_missing(log_tag, f"{title} backdrop", movie.backdrop_path, MoviePaths.backdrop_path(folder))

    # Download subtitles
    if settings.opensubtitles_download and movie:
        logger.info("[MOVIE] 🔽 Downloading subtitles for: %s", title)
        tmdb_id = movie.raw.get("imdb_id") or str(movie.id)
        download_movie_subtitles(movie, folder, tmdb_id=tmdb_id)


def reprocess_movie(skipped: SkippedStream) -> bool:
    """
    Re‐run process_movie on a single skipped movie, fetching its DispatcharrStream by ID.
    """
    # 1) Fetch the original DispatcharrStream

    try:
        if skipped["dispatcharr_id"] is None:
            logger.error(
                "Cannot reprocess movie %s (%s): no Dispatcharr ID",
                skipped["name"], skipped["tmdb_id"]
            )
            return False
        if skipped["dispatcharr_id"] == 0:
            logger.error(
                "Cannot reprocess movie %s (%s): Dispatcharr ID is 0",
                skipped["name"], skipped["tmdb_id"]
            )
            return False
        headers = get_auth_headers()
        raw = get_stream_by_id(
            skipped["dispatcharr_id"], headers=headers, timeout=10
        )
        if not raw:
            logger.error(
                "Cannot reprocess movie %s (%s): no DispatcharrStream found. Delete from skipped list.",
                skipped["name"], skipped["tmdb_id"]
            )
            return False
        stream = DispatcharrStream.from_dict(raw)
    except Exception as e:
        logger.error(
            "Cannot fetch DispatcharrStream for movie %s (dispatcharr_id=%s): %s",
            skipped["name"], skipped["dispatcharr_id"], e,
            exc_info=True
        )
        return False

    # 2) Pass into your normal pipeline
    root    = Path(settings.output_root)

    try:
        process_movie(stream, root, skipped["group"], headers)
        set_reprocess(skipped["tmdb_id"], False)
        logger.info("✅ Reprocessed movie %s (%s)", skipped["name"], skipped["tmdb_id"])
        return True

    except Exception as e:
        logger.error(
            "Reprocess failed for movie %s (%s): %s",
            skipped["name"], skipped["tmdb_id"], e,
            exc_info=True
        )
        return False