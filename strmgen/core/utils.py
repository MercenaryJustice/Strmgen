# strmgen/utils.py
"""
Utility functions, directory handling, Jinja2-backed NFO templating, and TMDb filtering.
"""
from pathlib import Path
from typing import List, Any, Optional, Dict, Callable, TypeVar

from jinja2 import Environment, select_autoescape
from .logger import setup_logger
from .config import settings
from .models import DispatcharrStream, TVShow, Movie, EpisodeMeta, SeasonMeta

logger = setup_logger(__name__)
# Initialize Jinja2 environment for XML escaping
env = Environment(
    # loader=FileSystemLoader("path/to/your/templates"),
    autoescape=select_autoescape(["xml"]),
    trim_blocks=True,      # drop the first newline after a block
    lstrip_blocks=True     # strip leading spaces/tabs from the start of a line to a block
)

# ─── Type Utilities ───────────────────────────────────────────────────────────

def ensure_str(value: Any) -> str:
    """Ensure the given value is returned as a string. None becomes empty string."""
    if isinstance(value, str):
        return value
    if value is None:
        return ""
    return str(value)

# ─── Path Helpers ─────────────────────────────────────────────────────────────

def target_folder(root: Path, category: str, group: str, name: Optional[str]) -> Path:
    """Construct and create the target folder path. If name is None, omit it from the path."""
    folder = root / category / group
    if name:
        folder = folder / name
    safe_mkdir(folder)
    return folder

# ─── Conditional Writer ──────────────────────────────────────────────────────
T = TypeVar("T", Movie, TVShow, EpisodeMeta, SeasonMeta)

def write_if(
    cond: bool,
    stream: DispatcharrStream,
    tmdb: T,
    writer_fn: Callable[[DispatcharrStream, T], None],
) -> None:
    """
    Call writer_fn(stream, tmdb) if cond is True.
    """
    if cond:
        writer_fn(stream, tmdb)

# ─── NFO Templates ────────────────────────────────────────────────────────────
TVSHOW_TEMPLATE = """<tvshow>
  <title>{{ show.name | e }}</title>
  <originaltitle>{{ show.original_name | e }}</originaltitle>
  <plot>{{ show.overview | e }}</plot>
  <tmdbid>{{ show.id }}</tmdbid>
  <year>{{ show.first_air_date[:4] if show.first_air_date else '' }}</year>
  <premiered>{{ show.first_air_date }}</premiered>
  <rating>{{ show.vote_average }}</rating>
  <votes>{{ show.vote_count }}</votes>
  {% for genre in show.genre_names %}
  <genre>{{ genre }}</genre>
  {% endfor %}
  <status>{{ show.raw.get('status', '') }}</status>
  <studio>{{ show.raw.get('networks', [])[0]['name'] if show.raw.get('networks') else '' }}</studio>
</tvshow>"""

EPISODE_TEMPLATE = """<episodedetails>
  <title>{{ episode.name | e }}</title>
  <season>{{ episode.season_number }}</season>
  <episode>{{ episode.episode_number }}</episode>
  <plot>{{ episode.overview | e }}</plot>
  <aired>{{ episode.air_date }}</aired>
  <rating>{{ episode.vote_average }}</rating>
  <votes>{{ episode.vote_count }}</votes>
  <tmdbid>{{ episode.id }}</tmdbid>
</episodedetails>"""

MOVIE_TEMPLATE = """
<movie>
  <title>{{ movie.title | e }}</title>
  <originaltitle>{{ movie.original_title | e }}</originaltitle>
  <sorttitle>{{ movie.title | e }}</sorttitle>
  <year>{{ movie.release_date[:4] if movie.release_date else '' }}</year>
  <releasedate>{{ movie.release_date }}</releasedate>
  <plot>{{ movie.overview | e }}</plot>
  <runtime>{{ movie.raw.get('runtime', '') }}</runtime>
  <rating>{{ movie.vote_average }}</rating>
  <votes>{{ movie.vote_count }}</votes>
  <tmdbid>{{ movie.id }}</tmdbid>
  {% for genre in movie.genre_ids %}
  <genre>{{ genre.name | e }}</genre>
  {% endfor %}
  <studio>{{ movie.raw.get('production_companies', [])[0]['name'] if movie.raw.get('production_companies') else '' }}</studio>
  <country>{{ movie.raw.get('production_countries', [])[0]['name'] if movie.raw.get('production_countries') else '' }}</country>
  <status>{{ movie.raw.get('status', '') }}</status>
</movie>
"""

# ─── Templating Functions ─────────────────────────────────────────────────────

def write_tvshow_nfo(stream: DispatcharrStream, show: TVShow) -> None:
    """Write a TV-show NFO using TVSHOW_TEMPLATE."""
    template = env.from_string(TVSHOW_TEMPLATE)
    xml = template.render(stream=stream, show=show)
    path = stream.nfo_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(xml, encoding="utf-8")
    logger.info(f"[NFO] ✅ Wrote NFO: {path}")


def write_episode_nfo(stream: DispatcharrStream, episode: EpisodeMeta) -> None:
    """Write an Episode NFO using EPISODE_TEMPLATE."""
    template = env.from_string(EPISODE_TEMPLATE)
    xml = template.render(stream=stream, show=episode)
    path = stream.nfo_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(xml, encoding="utf-8")
    logger.info(f"[NFO] ✅ Wrote NFO: {path}")


def write_movie_nfo(stream: DispatcharrStream, movie: Movie) -> None:
    """Write a Movie NFO using MOVIE_TEMPLATE."""
    template = env.from_string(MOVIE_TEMPLATE)
    xml = template.render(stream=stream, movie=movie)
    path = stream.nfo_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(xml, encoding="utf-8")
    logger.info(f"[NFO] ✅ Wrote NFO: {path}")

# ─── TMDb Missing Fields Validators ───────────────────────────────────────────

def tmdb_missing_nfo_movie_fields(meta: Dict[str, Any]) -> List[str]:
    """Return list of missing fields required for movie NFO generation."""
    required = ['title', 'release_date', 'overview', 'vote_average', 'id']
    return [k for k in required if k not in meta or meta.get(k) is None]


def tmdb_missing_nfo_tv_fields(meta: Dict[str, Any]) -> List[str]:
    """Return list of missing fields required for TV episode NFO generation."""
    required = ['name', 'season_number', 'episode_number', 'overview', 'id']
    return [k for k in required if k not in meta or meta.get(k) is None]

# ─── TMDb Filtering ──────────────────────────────────────────────────────────

def filter_by_threshold(
    name: str,
    meta: Optional[Dict[str, Any]]
) -> bool:
    """
    Return False and log if any TMDb threshold is not met, specifying reasons.
    """
    if meta is None:
        return True

    failed_reasons: List[str] = []

    # ─── Rating check ─────────────────────────────────────────────
    rating = meta.get('vote_average', 0.0)
    if rating < settings.minimum_tmdb_rating:
        failed_reasons.append(f"rating {rating} < {settings.minimum_tmdb_rating}")

    # ─── Vote count check ─────────────────────────────────────────
    votes = meta.get('vote_count', 0)
    if votes < settings.minimum_tmdb_votes:
        failed_reasons.append(f"votes {votes} < {settings.minimum_tmdb_votes}")

    # ─── Popularity check ─────────────────────────────────────────
    popularity = meta.get('popularity', 0.0)
    if popularity < settings.minimum_tmdb_popularity:
        failed_reasons.append(f"popularity {popularity} < {settings.minimum_tmdb_popularity}")

    # ─── Year check ───────────────────────────────────────────────
    year_str = meta.get("release_date") or meta.get("first_air_date") or ""
    year = int(year_str[:4]) if len(year_str) >= 4 and year_str[:4].isdigit() else None
    if year and year < settings.minimum_year:
        failed_reasons.append(f"year {year} < {settings.minimum_year}")

    # ─── Final check ──────────────────────────────────────────────
    if failed_reasons:
        reason_str = "; ".join(failed_reasons)
        logger.info(f"[TMDB] ❌ Filter failed for title: {name}. Reasons: {reason_str}")
        return False

    return True

