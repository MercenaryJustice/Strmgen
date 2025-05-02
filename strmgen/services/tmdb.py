
import requests
from dataclasses import dataclass
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from difflib import SequenceMatcher
from typing import Optional, Dict, List, Any
from ..core.http import session as TMDB_SESSION
from ..core.config import settings
from ..core.utils import clean_name
from ..core.logger import setup_logger
logger = setup_logger(__name__)

# cache of { genre_id → genre_name }
_tv_genre_map: dict[int, str] = {}

@dataclass
class Movie:
    # Core movie fields
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

    # Appended sub-resources
    alternative_titles: Dict[str, Any]
    changes: Dict[str, Any]
    credits: Dict[str, Any]
    external_ids: Dict[str, Any]
    images: Dict[str, Any]
    keywords: Dict[str, Any]
    lists: Dict[str, Any]
    recommendations: Dict[str, Any]
    release_dates: Dict[str, Any]
    reviews: Dict[str, Any]
    similar: Dict[str, Any]
    translations: Dict[str, Any]
    videos: Dict[str, Any]
    watch_providers: Dict[str, Any]

    # Raw JSON payload
    raw: Dict[str, Any]

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
    genre_names: List[str]
    popularity: float
    first_air_date: str
    vote_average: float
    vote_count: int
    origin_country: List[str]
    external_ids: Dict[str, str]
    raw: Dict[str, Any]

@dataclass
class SeasonMeta:
    id: int
    name: str
    overview: str
    air_date: str
    episodes: List[Dict[str, Any]]
    poster_path: Optional[str]
    season_number: int
    vote_average: float
    raw: Dict[str, Any]

@dataclass
class EpisodeMeta:
    air_date: str
    crew: List[Dict[str, Any]]
    episode_number: int
    guest_stars: List[Dict[str, Any]]
    name: str
    overview: str
    id: int
    production_code: str
    runtime: Optional[int]
    season_number: int
    still_path: Optional[str]
    vote_average: float
    vote_count: int
    raw: Dict[str, Any]


DOWNLOAD_EXECUTOR = ThreadPoolExecutor(max_workers=8)
TMDB_BASE = "https://api.themoviedb.org/3"
TMDB_IMG_BASE = "https://image.tmdb.org/t/p"

_tmdb_show_cache = {}

def tmdb_get(endpoint: str, params: Dict[str, Any]) -> Dict[str, Any]:
    params.update({"api_key": settings.tmdb_api_key, "language": settings.tmdb_language})
    r = TMDB_SESSION.get(f"{TMDB_BASE}{endpoint}", params=params, timeout=10)
    r.raise_for_status()
    return r.json()


def search_any_tmdb(title: str) -> Optional[Dict[str, Any]]:
    if not settings.tmdb_api_key:
        return None
    try:
        data = tmdb_get("/search/multi", {"query": title})
        results = data.get("results") or []
        for r in results:
            name = r.get("title") or r.get("name")
            if name and str(name).strip().lower() == str(title).strip().lower():
                return r
        return results[0] if results else None
    except requests.RequestException as e:
        logger.error("[TMDB] ❌ TMDb multi-search failed for '%s': %s", title, e)
        return None



def get_movie(title: str, year: Optional[int]) -> Optional[Movie]:
    """
    Search TMDb for a movie by title (and optional year), fetch full details
    (including all append_to_response sub‐resources), score by title similarity
    and year proximity, cache, and return the single best match.
    Returns None if no suitable movie is found or on error.
    """
    # 2) Require API key to proceed
    if not settings.tmdb_api_key:
        return None

    logger.info("[TMDB] 🔍 Searching for movie: %s (%s)", title, year)
    # 3) Search endpoint
    params = {"query": title}
    if year:
        params["year"] = str(year)

    try:
        data = tmdb_get("/search/movie", params)
        results = data.get("results") or []
        if not results:
            return None

        # 4) Fetch full details for each candidate
        candidates: List[Movie] = []
        append_items = [
            "alternative_titles", "changes", "credits", "external_ids",
            "images", "keywords", "lists", "recommendations",
            "release_dates", "reviews", "similar", "translations",
            "videos", "watch/providers",
        ]
        for r in results:
            tmdb_id = r.get("id")
            if not tmdb_id:
                continue

            url = f"{TMDB_BASE}/movie/{tmdb_id}"
            fetch_params: Dict[str, str] = {
                "api_key": settings.tmdb_api_key or "",
                "language": settings.tmdb_language,
                "append_to_response": ",".join(append_items),
            }
            resp = TMDB_SESSION.get(url, params=fetch_params, timeout=10)
            resp.raise_for_status()
            raw = resp.json()

            movie = Movie(
                id=raw.get("id", 0),
                title=raw.get("title", ""),
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

                alternative_titles=raw.get("alternative_titles", {}),
                changes=raw.get("changes", {}),
                credits=raw.get("credits", {}),
                external_ids=raw.get("external_ids", {}),
                images=raw.get("images", {}),
                keywords=raw.get("keywords", {}),
                lists=raw.get("lists", {}),
                recommendations=raw.get("recommendations", {}),
                release_dates=raw.get("release_dates", {}),
                reviews=raw.get("reviews", {}),
                similar=raw.get("similar", {}),
                translations=raw.get("translations", {}),
                videos=raw.get("videos", {}),
                watch_providers=raw.get("watch/providers", {}),

                raw=raw,
            )
            candidates.append(movie)

        if not candidates:
            return None

        # 5) Score candidates by title similarity (70%) and year proximity (30%)
        target = clean_name(title)
        def score(m: Movie) -> float:
            sim = SequenceMatcher(None, clean_name(m.title), target).ratio()
            if m.year and year:
                diff = abs(m.year - year)
                year_score = max(0.0, 1.0 - (diff * 0.1))
            else:
                year_score = 0.5
            return sim * 0.7 + year_score * 0.3

        best = max(candidates, key=score)
        logger.info(
            "[TMDB] ✅ Best match: %s (%s) score=%.2f",
            best.title, best.year, score(best)
        )

        # 6) Cache and return
        settings.tmdb_movie_cache[title] = best
        return best

    except Exception as e:
        logger.error(
            "[TMDB] ❌ get_movie failed for '%s' (year=%s): %s",
            title, year, e
        )
        return None


def fetch_movie_details(tmdb_id: int) -> Optional[Movie]:
    """
    Fetch full movie details plus ALL appendable sub-resources in one request.
    Returns a Movie dataclass or None on network/HTTP failure.
    """
    url = f"{TMDB_BASE}/movie/{tmdb_id}"
    append_items = [
        "alternative_titles",
        "changes",
        "credits",
        "external_ids",
        "images",
        "keywords",
        "lists",
        "recommendations",
        "release_dates",
        "reviews",
        "similar",
        "translations",
        "videos",
        "watch/providers",
    ]
    params: Dict[str, str] = {
        "api_key": settings.tmdb_api_key or "",
        "language": settings.tmdb_language,
        "append_to_response": ",".join(append_items),
    }

    try:
        resp = TMDB_SESSION.get(url, params=params, timeout=10)
        resp.raise_for_status()
        raw = resp.json()

        # Build Movie — use empty dicts/lists as defaults if a key is missing
        movie = Movie(
            id=raw.get("id", 0),
            title=raw.get("title", ""),
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

            # appended sub-resources:
            alternative_titles=raw.get("alternative_titles", {}),
            changes=raw.get("changes", {}),
            credits=raw.get("credits", {}),
            external_ids=raw.get("external_ids", {}),
            images=raw.get("images", {}),
            keywords=raw.get("keywords", {}),
            lists=raw.get("lists", {}),
            recommendations=raw.get("recommendations", {}),
            release_dates=raw.get("release_dates", {}),
            reviews=raw.get("reviews", {}),
            similar=raw.get("similar", {}),
            translations=raw.get("translations", {}),
            videos=raw.get("videos", {}),
            watch_providers=raw.get("watch/providers", {}),

            # always keep the full payload around
            raw=raw,
        )

        return movie

    except requests.RequestException as e:
        logger.warning("[TMDB] ⚠️ Movie lookup failed for %s: %s", tmdb_id, e)
        return None

def _get_best_match_tv(results: List[Dict[str, Any]], search_term: str) -> Optional[Dict[str, Any]]:
    """
    Pick the result whose 'name' is most similar to the search_term.
    """
    best = None
    highest_ratio = 0.0
    for r in results:
        name = r.get("name", "")
        ratio = SequenceMatcher(None, search_term.lower(), name.lower()).ratio()
        if ratio > highest_ratio:
            highest_ratio = ratio
            best = r
    return best

def fetch_tv_details(query: str) -> Optional[TVShow]:
    """
    Search TMDb for the TV show whose name best matches `query`, then
    fetch its full details (with credits) and return a TVShow instance.
    """
    # 1) Search for shows matching the query
    search_url = f"{TMDB_BASE}/search/tv"
    search_params: Dict[str, str] = {
        "api_key":        settings.tmdb_api_key or "",
        "language":       settings.tmdb_language,
        "query":          query,
    }
    try:
        sr = TMDB_SESSION.get(search_url, params=search_params, timeout=10)
        sr.raise_for_status()
        results = sr.json().get("results", [])
        if not results:
            return None

        best = _get_best_match_tv(results, query)
        if not best or "id" not in best:
            return None

        tv_id = best["id"]

        # 2) Fetch full details including credits
        detail_url = f"{TMDB_BASE}/tv/{tv_id}"
        detail_params: Dict[str, str] = {
            "api_key":            settings.tmdb_api_key or "",
            "language":           settings.tmdb_language,
            "append_to_response": "credits",
        }
        dr = TMDB_SESSION.get(detail_url, params=detail_params, timeout=10)
        dr.raise_for_status()
        data = dr.json()

        # 3) Parse into your TVShow model
        return TVShow(
            id=data.get("id", 0),
            name=data.get("name", ""),
            original_name=data.get("original_name", ""),
            overview=data.get("overview", ""),
            poster_path=data.get("poster_path"),
            backdrop_path=data.get("backdrop_path"),
            media_type=data.get("media_type", ""),
            adult=data.get("adult", False),
            original_language=data.get("original_language", ""),
            genre_ids=data.get("genre_ids", []),
            genre_names=[],  # Populate this if necessary
            popularity=data.get("popularity", 0.0),
            first_air_date=data.get("first_air_date", ""),
            vote_average=data.get("vote_average", 0.0),
            vote_count=data.get("vote_count", 0),
            origin_country=data.get("origin_country", []),
            external_ids=data.get("external_ids", {}),
            raw=data,
        )

    except Exception:
        # you might want to log the exception here
        return None

def _download_image(path: str, dest: Path):
    if settings.write_nfo_only_if_not_exists and dest.exists():
        logger.info("[TMDB] ⚠️ Skipped image (exists): %s", dest)
        return
    url = f"{TMDB_IMG_BASE}/{settings.tmdb_image_size}{path}"
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
    if not dest.exists():
    #     logger.info(f"{log_tag} Skipping %s (exists): %s", label, dest)
    # else:
        logger.info(f"{log_tag} Downloading %s: %s", label, dest)
        download_image(path_val, dest)


def download_image(path: str, dest: Path) -> bool:
    try:
        DOWNLOAD_EXECUTOR.submit(_download_image, path, dest)
        return True
    except Exception as e:
        logger.error("[TMDB] ❌ Failed to submit image download task: %s", e)
        return False

def tmdb_lookup_tv_show(show: str) -> Optional[Dict[str, Any]]:
    """
    Look up a TV show in TMDb, returning the result whose name best matches the query.
    Caches by the original query string.
    """
    if show in _tmdb_show_cache:
        return _tmdb_show_cache[show]

    data = tmdb_get("/search/multi", {"query": show})
    results: List[Dict[str, Any]] = data.get("results", []) or []

    # Prefer TV media_type; if none, fall back to any result
    candidates: List[Dict[str, Any]] = [r for r in results if r.get("media_type") == "tv"]
    if not candidates:
        candidates = results

    def similarity(item: Dict[str, Any]) -> float:
        name = item.get("name") or item.get("title") or ""
        return SequenceMatcher(None, show.lower(), name.lower()).ratio()

    best_match = max(candidates, key=similarity) if candidates else None
    _tmdb_show_cache[show] = best_match
    return best_match



def lookup_show(show_name: str) -> Optional[TVShow]:
    """Fetch and cache TMDb show metadata, returning a typed TVShow."""
    # 1) check the cache first
    cached = settings.tmdb_show_cache.get(show_name)
    if isinstance(cached, TVShow):
        return cached

    # 2) only hit TMDb if the key is present
    if not settings.tmdb_api_key:
        return None

    logger.info("[TMDB] 🔍 Looking up show: %s", show_name)
    raw = tmdb_lookup_tv_show(show_name)
    if not raw:
        return None

    # 3) build our genre_names from the global _tv_genre_map cache
    genre_ids = raw.get("genre_ids", [])
    genre_names = [
        _tv_genre_map[gid]
        for gid in genre_ids
        if gid in _tv_genre_map
    ]

    # 4) inject genre_names back into raw, so templates or other code can see them
    raw["genre_names"] = genre_names

    # 5) construct our TVShow dataclass
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
        genre_ids=genre_ids,
        genre_names=genre_names,
        popularity=raw.get("popularity", 0.0),
        first_air_date=raw.get("first_air_date", ""),
        vote_average=raw.get("vote_average", 0.0),
        vote_count=raw.get("vote_count", 0),
        origin_country=raw.get("origin_country", []),
        external_ids=raw.get("external_ids", {}),
        raw=raw,
    )

    # cache and return
    settings.tmdb_show_cache[show_name] = tv
    return tv

def _load_tv_genres() -> None:
    """
    Populate the _tv_genre_map cache by calling /genre/tv/list.
    """
    global _tv_genre_map
    if _tv_genre_map:
        return

    url = f"{TMDB_BASE}/genre/tv/list"
    params = {
        "language": settings.tmdb_language,
        "api_key": settings.tmdb_api_key
    }
    resp = TMDB_SESSION.get(url, params=params, timeout=10)
    resp.raise_for_status()
    for g in resp.json().get("genres", []):
        _tv_genre_map[g["id"]] = g["name"]



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
