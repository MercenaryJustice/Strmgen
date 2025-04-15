
import requests
from dataclasses import dataclass
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from difflib import SequenceMatcher
from typing import Optional, Dict, List
from config import settings
from utils import clean_name
from log import setup_logger
logger = setup_logger(__name__)

@dataclass
class Movie:
    id: int
    title: str
    original_title: str
    overview: str
    poster_path: Optional[str]
    backdrop_path: Optional[str]
    release_date: str
    adult: bool
    original_language: str
    genre_ids: List[int]
    popularity: float
    video: bool
    vote_average: float
    vote_count: int
    raw: Dict

    @property
    def year(self) -> Optional[int]:
        """
        Return the four-digit year from release_date (YYYY-MM-DD),
        or None if release_date is empty or invalid.
        """
        if not self.release_date or len(self.release_date) < 4:
            return None
        try:
            return int(self.release_date[:4])
        except ValueError:
            return None


@dataclass
class TVShow:
    id: int
    name: str
    original_name: str
    overview: str
    poster_path: Optional[str]
    backdrop_path: Optional[str]
    media_type: str
    adult: bool
    original_language: str
    genre_ids: List[int]
    popularity: float
    first_air_date: str
    vote_average: float
    vote_count: int
    origin_country: List[str]
    external_ids: Dict[str, str]
    raw: Dict

@dataclass
class SeasonMeta:
    id: int
    name: str
    overview: str
    air_date: str
    episodes: List[Dict]
    poster_path: Optional[str]
    season_number: int
    vote_average: float
    raw: Dict

@dataclass
class EpisodeMeta:
    air_date: str
    crew: List[Dict]
    episode_number: int
    guest_stars: List[Dict]
    name: str
    overview: str
    id: int
    production_code: str
    runtime: Optional[int]
    season_number: int
    still_path: Optional[str]
    vote_average: float
    vote_count: int
    raw: Dict

TMDB_SESSION = requests.Session()
DOWNLOAD_EXECUTOR = ThreadPoolExecutor(max_workers=8)

_tmdb_show_cache = {}
_tmdb_season_cache = {}
_tmdb_episode_cache = {}
_tmdb_movie_cache = {}

def tmdb_get(endpoint: str, params: dict) -> dict:
    params.update({"api_key": settings.tmdb_api_key, "language": settings.tmdb_language})
    r = TMDB_SESSION.get(f"https://api.themoviedb.org/3{endpoint}", params=params, timeout=10)
    r.raise_for_status()
    return r.json()


def search_any_tmdb(title: str) -> Optional[dict]:
    if not settings.tmdb_api_key:
        return None
    try:
        data = tmdb_get("/search/multi", {"query": title})
        results = data.get("results") or []
        for r in results:
            name = r.get("title") or r.get("name")
            if name and name.strip().lower() == title.strip().lower():
                return r
        return results[0] if results else None
    except requests.RequestException as e:
        logger.error("[TMDB] ❌ TMDb multi-search failed for '%s': %s", title, e)
        return None

def _raw_lookup_movie(title: str, year: int) -> Optional[dict]:
    params = {"query": title}
    if year:
        params["year"] = year
    try:
        data = tmdb_get("/search/movie", params)
        results = data.get("results") or []
        result = results[0] if results else None
        return result
    except requests.RequestException as e:
        logger.error("[TMDB] ❌ get_movie failed for '%s' (year=%s): %s", title, year, e)
        return None


def get_movie(title: str, year: int) -> Optional[Movie]:
    """Fetch and cache TMDb movie metadata, returning a typed Movie."""
    cached = settings.tmdb_movie_cache.get(title)
    if isinstance(cached, Movie):
        return cached
    if settings.tmdb_api_key:
        logger.info("[TMDB] 🔍 Looking up movie: %s", title)
        raw = _raw_lookup_movie(title, int)
        if raw:
            movie = Movie(
                id=raw.get("id", 0),
                title=raw.get("title", title),
                original_title=raw.get("original_title", ""),
                overview=raw.get("overview", ""),
                poster_path=raw.get("poster_path"),
                backdrop_path=raw.get("backdrop_path"),
                release_date=raw.get("release_date", ""),
                adult=raw.get("adult", False),
                original_language=raw.get("original_language", ""),
                genre_ids=raw.get("genre_ids", []),
                popularity=raw.get("popularity", 0.0),
                video=raw.get("video", False),
                vote_average=raw.get("vote_average", 0.0),
                vote_count=raw.get("vote_count", 0),
                raw=raw,
            )
            settings.tmdb_movie_cache[title] = movie
            return movie
    return None

def _download_image(path: str, dest: Path):
    if settings.write_nfo_only_if_not_exists and dest.exists():
        logger.info("[TMDB] ⚠️ Skipped image (exists): %s", dest)
        return
    url = f"https://image.tmdb.org/t/p/{settings.tmdb_image_size}{path}"
    try:
        r = TMDB_SESSION.get(url, stream=True, timeout=10)
        r.raise_for_status()
        with dest.open("wb") as f:
            for chunk in r.iter_content(1024):
                f.write(chunk)
        logger.info("[TMDB] 🖼️ Downloaded image: %s", dest)
    except requests.RequestException as e:
        logger.error("[TMDB] ❌ Failed to download %s: %s", url, e)

def download_if_missing(log_tag: str, label: str, path_val: Optional[str], dest: Path) -> None:
    """Download an asset if it's missing, logging skip or download."""
    if not path_val:
        return
    if dest.exists():
        logger.info(f"{log_tag} Skipping %s (exists): %s", label, dest)
    else:
        logger.info(f"{log_tag} Downloading %s: %s", label, dest)
        download_image(path_val, dest)


def download_image(path: str, dest: Path) -> bool:
    DOWNLOAD_EXECUTOR.submit(_download_image, path, dest)

def tmdb_lookup_tv_show(show: str) -> Optional[dict]:
    """
    Look up a TV show in TMDb, returning the result whose name best matches the query.
    Caches by the original query string.
    """
    if show in _tmdb_show_cache:
        return _tmdb_show_cache[show]

    data = tmdb_get("/search/multi", {"query": show})
    results = data.get("results", []) or []

    # Prefer TV media_type; if none, fall back to any result
    candidates = [r for r in results if r.get("media_type") == "tv"]
    if not candidates:
        candidates = results

    def similarity(item: dict) -> float:
        name = item.get("name") or item.get("title") or ""
        return SequenceMatcher(None, show.lower(), name.lower()).ratio()

    best_match = max(candidates, key=similarity) if candidates else None
    _tmdb_show_cache[show] = best_match
    return best_match



def lookup_show(show_name: str) -> Optional[TVShow]:
    """Fetch and cache TMDb show metadata, returning a typed TVShow."""
    cached = settings.tmdb_show_cache.get(show_name)
    if isinstance(cached, TVShow):
        return cached
    if settings.tmdb_api_key:
        logger.info("[TMDB] 🔍 Looking up show: %s", show_name)
        raw = tmdb_lookup_tv_show(show_name)
        if raw:
            tv = TVShow(
                id=raw.get("id"),
                name=clean_name(raw.get("name", show_name)),
                original_name=raw.get("original_name", ""),
                overview=raw.get("overview", ""),
                poster_path=raw.get("poster_path"),
                backdrop_path=raw.get("backdrop_path"),
                media_type=raw.get("media_type", ""),
                adult=raw.get("adult", False),
                original_language=raw.get("original_language", ""),
                genre_ids=raw.get("genre_ids", []),
                popularity=raw.get("popularity", 0.0),
                first_air_date=raw.get("first_air_date", ""),
                vote_average=raw.get("vote_average", 0.0),
                vote_count=raw.get("vote_count", 0),
                origin_country=raw.get("origin_country", []),
                external_ids=raw.get("external_ids", {}),
                raw=raw,
            )
            settings.tmdb_show_cache[show_name] = tv
            return tv
    return None


def get_season_meta(show_id: int, season: int) -> Optional[SeasonMeta]:
    """Fetch and cache TMDb season metadata, returning a typed SeasonMeta."""
    key = (show_id, season)
    cached = settings.tmdb_season_cache.get(key)
    if isinstance(cached, SeasonMeta):
        return cached
    try:
        logger.info("[TMDB] 🔄 Fetching season %02d for show ID %s", season, show_id)
        raw = tmdb_get(f"/tv/{show_id}/season/{season}", {})
        meta = SeasonMeta(
            id=raw.get("id", 0),
            name=raw.get("name", ""),
            overview=raw.get("overview", ""),
            air_date=raw.get("air_date", ""),
            episodes=raw.get("episodes", []),
            poster_path=raw.get("poster_path"),
            season_number=raw.get("season_number", season),
            vote_average=raw.get("vote_average", 0.0),
            raw=raw,
        )
        settings.tmdb_season_cache[key] = meta
        return meta
    except Exception as e:
        logger.warning("[TMDB] ⚠️ Season lookup failed: %s", e)
        settings.tmdb_season_cache[key] = None
        return None


def get_episode_meta(show_id: int, season: int, ep: int) -> Optional[EpisodeMeta]:
    """Fetch and cache TMDb episode metadata, returning a typed EpisodeMeta."""
    key = (show_id, season, ep)
    cached = settings.tmdb_episode_cache.get(key)
    if isinstance(cached, EpisodeMeta):
        return cached
    try:
        logger.info("[TMDB] 🔄 Fetching episode S%02dE%02d for show ID %s", season, ep, show_id)
        raw = tmdb_get(f"/tv/{show_id}/season/{season}/episode/{ep}", {})

        meta = EpisodeMeta(
            air_date=raw.get("air_date", ""),
            crew=raw.get("crew", []),
            episode_number=raw.get("episode_number", 0),
            guest_stars=raw.get("guest_stars", []),
            name=raw.get("name", ""),
            overview=raw.get("overview", ""),
            id=raw.get("id", 0),
            production_code=raw.get("production_code", ""),
            runtime=raw.get("runtime"),
            season_number=raw.get("season_number", season),
            still_path=raw.get("still_path"),
            vote_average=raw.get("vote_average", 0.0),
            vote_count=raw.get("vote_count", 0),
            raw=raw,
        )
        settings.tmdb_episode_cache[key] = meta
        return meta
    except Exception as e:
        logger.warning("[TMDB] ⚠️ Episode lookup failed: %s", e)
        settings.tmdb_episode_cache[key] = None
        return None