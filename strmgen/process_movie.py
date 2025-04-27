import re
from pathlib import Path
from typing import Optional, Dict

from config import settings
from subtitles import download_movie_subtitles
from streams import write_strm_file
from tmdb_helpers import Movie, get_movie, download_if_missing
from utils import clean_name, target_folder, write_if, write_movie_nfo, tmdb_missing_nfo_movie_fields, filter_by_threshold
from log import setup_logger

logger = setup_logger(__name__)
TITLE_YEAR_RE = re.compile(r"^(.+?)\s*\((\d{4})\)$")
_skipped_movies = set()

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
    name: str,
    sid: int,
    root: Path,
    group: str,
    headers: Dict[str, str],
    url: str,
) -> None:
    """
    Process a single Movie entry:
      1. Clean title from filename
      2. Lookup & cache TMDb metadata
      3. Filter by rating/vote/popularity thresholds
      4. Write .strm, .nfo, download images, and subtitles
    """
    # Strip file extension and sanitize title
    m = TITLE_YEAR_RE.match(name)
    if m:
        raw_title, raw_year = m.group(1), m.group(2)
        title = clean_name(raw_title)
        year = int(raw_year)
    else:
        title = clean_name(name)
        year = None
    logger.info("[MOVIE] 🎬 Processing movie: %s", title)

    if title in _skipped_movies:
        logger.info("[MOVIE] ⏭️ Skipped movie (cached): %s", title)
        return

    # Fetch movie metadata
    movie: Optional[Movie] = get_movie(title, year)
    if not filter_by_threshold(_skipped_movies, name, movie.raw if movie else None):
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
    if not write_strm_file(strm_file, sid, headers, url):
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
        download_movie_subtitles(title, folder, tmdb_id=tmdb_id)
