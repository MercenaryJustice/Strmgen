# strmgen/utils.py
"""
Utility functions, directory handling, Jinja2-backed NFO templating, and TMDb filtering.
"""
import re
from pathlib import Path
from typing import List, Any, Optional, Dict, Callable

from jinja2 import Environment, select_autoescape
from .logger import setup_logger
from .config import settings

logger = setup_logger(__name__)
# Initialize Jinja2 environment for XML escaping
env = Environment(
    # loader=FileSystemLoader("path/to/your/templates"),
    autoescape=select_autoescape(["xml"]),
    trim_blocks=True,      # drop the first newline after a block
    lstrip_blocks=True     # strip leading spaces/tabs from the start of a line to a block
)

# ─── Filesystem Helpers ───────────────────────────────────────────────────────

def safe_mkdir(path: Path) -> None:
    """Safely create a directory tree if not exists."""
    try:
        path.mkdir(parents=True, exist_ok=True)
        logger.debug("Created directory: %s", path)
    except Exception as e:
        logger.error("Failed to create directory %s: %s", path, e)

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

def write_if(cond: bool, path: Path, writer_fn: Callable[..., None], *args: Any) -> None:
    """Call writer_fn(*args, path) only if cond is True."""
    if cond:
        writer_fn(*args, path)

# ─── NFO Templates ────────────────────────────────────────────────────────────
TVSHOW_TEMPLATE = """<tvshow>
  <title>{{ name | e }}</title>
  <originaltitle>{{ original_name | e }}</originaltitle>
  <plot>{{ overview | e }}</plot>
  <tmdbid>{{ id }}</tmdbid>
  <year>{{ first_air_date[:4] if first_air_date else '' }}</year>
  <premiered>{{ first_air_date }}</premiered>
  <rating>{{ vote_average }}</rating>
  <votes>{{ vote_count }}</votes>
  {% for genre in genre_names %}
  <genre>{{ genre }}</genre>
  {% endfor %}
  <status>{{ status }}</status>
  <studio>{{ networks[0]['name'] if networks else '' }}</studio>
</tvshow>"""

EPISODE_TEMPLATE = """<episodedetails>
  <title>{{ name | e }}</title>
  <season>{{ season_number }}</season>
  <episode>{{ episode_number }}</episode>
  <plot>{{ overview | e }}</plot>
  <aired>{{ air_date }}</aired>
  <rating>{{ vote_average }}</rating>
  <votes>{{ vote_count }}</votes>
  <tmdbid>{{ id }}</tmdbid>
</episodedetails>"""

MOVIE_TEMPLATE = """<movie>
  <title>{{ title | e }}</title>
  <originaltitle>{{ original_title | e }}</originaltitle>
  <sorttitle>{{ title | e }}</sorttitle>
  <year>{{ release_date[:4] if release_date else '' }}</year>
  <releasedate>{{ release_date }}</releasedate>
  <plot>{{ overview | e }}</plot>
  <runtime>{{ runtime }}</runtime>
  <rating>{{ vote_average }}</rating>
  <votes>{{ vote_count }}</votes>
  <tmdbid>{{ id }}</tmdbid>
  <genre>{{ genres[0]['name'] if genres else '' }}</genre>
  <studio>{{ production_companies[0]['name'] if production_companies else '' }}</studio>
  <country>{{ production_countries[0]['name'] if production_countries else '' }}</country>
  <status>{{ status }}</status>
</movie>"""

# ─── Templating Functions ─────────────────────────────────────────────────────

def render_nfo(template_str: str, context: Dict[str, Any]) -> str:
    """Render an NFO from a Jinja2 template string and context dict."""
    template = env.from_string(template_str)
    return template.render(**context)


def write_nfo(template_str: str, context: Dict[str, Any], path: Path) -> None:
    """Render and write NFO XML to disk, with logging."""
    # 1) Make sure the directory exists
    path.parent.mkdir(parents=True, exist_ok=True)

    xml = render_nfo(template_str, context)
    try:
        path.write_text(xml, encoding="utf-8")
        logger.info("[NFO] Wrote NFO: %s", path)
    except Exception as e:
        logger.error("[NFO] Failed to write NFO %s: %s", path, e)


def write_tvshow_nfo(meta: Dict[str, Any], path: Path) -> None:
    """Write a TV-show NFO using TVSHOW_TEMPLATE."""
    write_nfo(TVSHOW_TEMPLATE, meta, path)


def write_episode_nfo(meta: Dict[str, Any], path: Path) -> None:
    """Write an Episode NFO using EPISODE_TEMPLATE."""
    write_nfo(EPISODE_TEMPLATE, meta, path)


def write_movie_nfo(meta: Dict[str, Any], path: Path) -> None:
    """Write a Movie NFO using MOVIE_TEMPLATE."""
    write_nfo(MOVIE_TEMPLATE, meta, path)

# ─── TMDb Missing Fields Validators ───────────────────────────────────────────

def tmdb_missing_nfo_movie_fields(meta: Dict[str, Any]) -> List[str]:
    """Return list of missing fields required for movie NFO generation."""
    required = ['title', 'release_date', 'overview', 'vote_average', 'id']
    return [k for k in required if k not in meta or meta.get(k) is None]


def tmdb_missing_nfo_tv_fields(meta: Dict[str, Any]) -> List[str]:
    """Return list of missing fields required for TV episode NFO generation."""
    required = ['name', 'season_number', 'episode_number', 'overview', 'id']
    return [k for k in required if k not in meta or meta.get(k) is None]

# ─── Filename Utilities ───────────────────────────────────────────────────────

def clean_name(name: str) -> str:
    """Sanitize and strip optional tokens from a name."""
    if settings.remove_strings:
        for token in settings.remove_strings:
            name = name.replace(token, "")
    return re.sub(r'[<>:"/\\|?*]', "", name)

def remove_prefixes(title: str) -> str:
    for bad in settings.remove_strings:
        title = title.replace(bad, "").strip()
    return title

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
