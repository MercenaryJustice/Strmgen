# strmgen/services/tmdb.py

import asyncio
from difflib import SequenceMatcher
from typing import Optional, Dict, List, Any, Tuple
from pathlib import Path

import aiofiles
import httpx

from ..core.config import settings
from ..core.utils import clean_name, safe_mkdir, setup_logger
from ..core.models import Movie, TVShow, SeasonMeta, EpisodeMeta

logger = setup_logger(__name__)

# Constants
TMDB_BASE = "https://api.themoviedb.org/3"
TMDB_IMG_BASE = "https://image.tmdb.org/t/p"

# Caches
_tv_genre_map: Dict[int, str] = {}
_tmdb_show_cache: Dict[str, Any] = {}




# ─── Internal HTTP helper ─────────────────────────────────────────────────────
async def _get(endpoint: str, params: Dict[str, Any]) -> Dict[str, Any]:
    params = {**params, "api_key": settings.tmdb_api_key, "language": settings.tmdb_language}
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.get(f"{TMDB_BASE}{endpoint}", params=params)
        resp.raise_for_status()
        return resp.json()


# ─── TMDb search / details ───────────────────────────────────────────────────
async def search_any_tmdb(title: str) -> Optional[Dict[str, Any]]:
    if not settings.tmdb_api_key:
        return None
    try:
        data = await _get("/search/multi", {"query": title})
        results = data.get("results", [])
        return results[0] if results else None
    except Exception as e:
        logger.error("[TMDB] ❌ multi-search failed for '%s': %s", title, e)
        return None

async def get_movie(title: str, year: Optional[int]) -> Optional[Movie]:
    if not settings.tmdb_api_key:
        return None
    logger.info("[TMDB] 🔍 Searching movie: %s (%s)", title, year)
    params: Dict[str, Any] = {"query": title}
    if year:
        params["year"] = year
    try:
        search_data = await _get("/search/movie", params)
        results = search_data.get("results", [])
        if not results:
            return None

        append = [
            "alternative_titles","changes","credits","external_ids",
            "images","keywords","lists","recommendations",
            "release_dates","reviews","similar","translations",
            "videos","watch/providers",
        ]
        candidates: List[Movie] = []
        for r in results:
            tmdb_id = r.get("id")
            if not tmdb_id:
                continue
            detail = await _get(f"/movie/{tmdb_id}", {"append_to_response": ",".join(append)})
            movie = Movie(
                id=detail.get("id", 0),
                title=detail.get("title", ""),
                original_title=detail.get("original_title", ""),
                overview=detail.get("overview", ""),
                poster_path=detail.get("poster_path"),
                backdrop_path=detail.get("backdrop_path"),
                release_date=detail.get("release_date", ""),
                adult=detail.get("adult", False),
                original_language=detail.get("original_language", ""),
                genre_ids=detail.get("genre_ids", []),
                popularity=detail.get("popularity", 0.0),
                video=detail.get("video", False),
                vote_average=detail.get("vote_average", 0.0),
                vote_count=detail.get("vote_count", 0),
                alternative_titles=detail.get("alternative_titles", {}),
                changes=detail.get("changes", {}),
                credits=detail.get("credits", {}),
                external_ids=detail.get("external_ids", {}),
                images=detail.get("images", {}),
                keywords=detail.get("keywords", {}),
                lists=detail.get("lists", {}),
                recommendations=detail.get("recommendations", {}),
                release_dates=detail.get("release_dates", {}),
                reviews=detail.get("reviews", {}),
                similar=detail.get("similar", {}),
                translations=detail.get("translations", {}),
                videos=detail.get("videos", {}),
                watch_providers=detail.get("watch/providers", {}),
                raw=detail,
            )
            candidates.append(movie)

        if not candidates:
            return None

        target = clean_name(title)
        def score(m: Movie) -> float:
            sim = SequenceMatcher(None, clean_name(m.title), target).ratio()
            year_score = 0.5
            if m.year and year:
                diff = abs(m.year - year)
                year_score = max(0.0, 1.0 - diff * 0.1)
            return 0.7 * sim + 0.3 * year_score

        best = await asyncio.to_thread(max, candidates, key=score)
        logger.info("[TMDB] ✅ Best match: %s (%s) score=%.2f", best.title, best.year, score(best))
        return best
    except Exception as e:
        logger.error("[TMDB] ❌ get_movie failed for '%s': %s", title, e)
        return None

async def fetch_movie_details(tmdb_id: int) -> Optional[Movie]:
    try:
        detail = await _get(f"/movie/{tmdb_id}", {"append_to_response": "".join([])})
        return Movie(
            id=detail.get("id", 0),
            title=detail.get("title", ""),
            original_title=detail.get("original_title", ""),
            overview=detail.get("overview", ""),
            poster_path=detail.get("poster_path"),
            backdrop_path=detail.get("backdrop_path"),
            release_date=detail.get("release_date", ""),
            adult=detail.get("adult", False),
            original_language=detail.get("original_language", ""),
            genre_ids=detail.get("genre_ids", []),
            popularity=detail.get("popularity", 0.0),
            video=detail.get("video", False),
            vote_average=detail.get("vote_average", 0.0),
            vote_count=detail.get("vote_count", 0),
            alternative_titles=detail.get("alternative_titles", {}),
            changes=detail.get("changes", {}),
            credits=detail.get("credits", {}),
            external_ids=detail.get("external_ids", {}),
            images=detail.get("images", {}),
            keywords=detail.get("keywords", {}),
            lists=detail.get("lists", {}),
            recommendations=detail.get("recommendations", {}),
            release_dates=detail.get("release_dates", {}),
            reviews=detail.get("reviews", {}),
            similar=detail.get("similar", {}),
            translations=detail.get("translations", {}),
            videos=detail.get("videos", {}),
            watch_providers=detail.get("watch/providers", {}),
            raw=detail,
        )
    except Exception as e:
        logger.error("[TMDB] ❌ fetch_movie_details failed for ID %s: %s", tmdb_id, e)
        return None

# ─── TV Helpers ──────────────────────────────────────────────────────────────
def _get_best_match_tv(results: List[Dict[str, Any]], search_term: str) -> Optional[Dict[str, Any]]:
    best, highest = None, 0.0
    for r in results:
        name = r.get("name", "")
        ratio = SequenceMatcher(None, search_term.lower(), name.lower()).ratio()
        if ratio > highest:
            highest, best = ratio, r
    return best

async def fetch_tv_details(query: str) -> Optional[TVShow]:
    try:
        data = await _get("/search/tv", {"query": query})
        results = data.get("results", [])
        best = _get_best_match_tv(results, query)
        if not best or not best.get("id"):
            return None
        tv_id = best["id"]
        detail = await _get(f"/tv/{tv_id}", {"append_to_response": "credits"})
        genres = detail.get("genre_ids", [])
        names = [ _tv_genre_map.get(gid, "") for gid in genres ]
        return TVShow(
            id=detail.get("id", 0),
            name=detail.get("name", ""),
            original_name=detail.get("original_name", ""),
            overview=detail.get("overview", ""),
            poster_path=detail.get("poster_path"),
            backdrop_path=detail.get("backdrop_path"),
            media_type=detail.get("media_type", ""),
            adult=detail.get("adult", False),
            original_language=detail.get("original_language", ""),
            genre_ids=genres,
            genre_names=names,
            popularity=detail.get("popularity", 0.0),
            first_air_date=detail.get("first_air_date", ""),
            vote_average=detail.get("vote_average", 0.0),
            vote_count=detail.get("vote_count", 0),
            origin_country=detail.get("origin_country", []),
            external_ids=detail.get("external_ids", {}),
            raw=detail,
        )
    except Exception:
        return None

async def _download_image(path_val: str, dest: Path) -> None:
    safe_mkdir(dest.parent)
    url = f"{TMDB_IMG_BASE}/{settings.tmdb_image_size}{path_val}"
    async with httpx.AsyncClient(timeout=10.0) as client:
        r = await client.get(url)
        r.raise_for_status()
        data = r.content
    async with aiofiles.open(dest, "wb") as f:
        await f.write(data)
    logger.info("[TMDB] 🖼️ Downloaded image: %s", dest)

async def download_if_missing(
    log_tag: str,
    label: str,
    path_val: Optional[str],
    dest: Path
) -> bool:
    if not path_val or await asyncio.to_thread(dest.exists):
        return False
    logger.info(f"{log_tag} Downloading %s: %s", label, dest)
    await _download_image(path_val, dest)
    return True

async def tmdb_lookup_tv_show(show: str) -> Optional[Dict[str, Any]]:
    if show in _tmdb_show_cache:
        return _tmdb_show_cache[show]
    data = await search_any_tmdb(show)
    results = data.get("results", []) if data else []
    candidates = [r for r in results if r.get("media_type") == "tv"] or results
    best = max(candidates, key=lambda i: SequenceMatcher(None, show.lower(), (i.get("name") or i.get("title", "")).lower()).ratio()) if candidates else None
    _tmdb_show_cache[show] = best
    return best

async def lookup_show(show_name: str) -> Optional[TVShow]:
    cached = settings.tmdb_show_cache.get(show_name)
    if isinstance(cached, TVShow):
        return cached
    if not settings.tmdb_api_key:
        return None
    raw = await tmdb_lookup_tv_show(show_name)
    if not raw:
        return None
    # populate genres if not loaded
    global _tv_genre_map
    if not _tv_genre_map:
        genre_data = await _get("/genre/tv/list", {})
        for g in genre_data.get("genres", []):
            _tv_genre_map[g["id"]] = g["name"]
    genres = raw.get("genre_ids", [])
    names = [_tv_genre_map.get(g, "") for g in genres]
    tv = TVShow(
        id=raw.get("id", 0),
        name=raw.get("name", show_name),
        original_name=raw.get("original_name", ""),
        overview=raw.get("overview", ""),
        poster_path=raw.get("poster_path"),
        backdrop_path=raw.get("backdrop_path"),
        media_type=raw.get("media_type", ""),
        adult=raw.get("adult", False),
        original_language=raw.get("original_language", ""),
        genre_ids=genres,
        genre_names=names,
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

async def get_season_meta(show_id: int, season: int) -> Optional[SeasonMeta]:
    key = (show_id, season)
    cached = settings.tmdb_season_cache.get(key)
    if isinstance(cached, SeasonMeta):
        return cached
    try:
        data = await _get(f"/tv/{show_id}/season/{season}", {})
        meta = SeasonMeta(
            id=data.get("id", 0),
            name=data.get("name", ""),
            overview=data.get("overview", ""),
            air_date=data.get("air_date", ""),
            episodes=data.get("episodes", []),
            poster_path=data.get("poster_path"),
            season_number=data.get("season_number", season),
            vote_average=data.get("vote_average", 0.0),
            raw=data,
        )
        settings.tmdb_season_cache[key] = meta
        return meta
    except Exception as e:
        logger.warning("[TMDB] ⚠️ Season lookup failed: %s", e)
        settings.tmdb_season_cache[key] = None
        return None

async def get_episode_meta(show_id: int, season: int, ep: int) -> Optional[EpisodeMeta]:
    key = (show_id, season, ep)
    cached = settings.tmdb_episode_cache.get(key)
    if isinstance(cached, EpisodeMeta):
        return cached
    try:
        data = await _get(f"/tv/{show_id}/season/{season}/episode/{ep}", {})
        meta = EpisodeMeta(
            air_date=data.get("air_date", ""),
            crew=data.get("crew", []),
            episode_number=data.get("episode_number", 0),
            guest_stars=data.get("guest_stars", []),
            name=data.get("name", ""),
            overview=data.get("overview", ""),
            id=data.get("id", 0),
            production_code=data.get("production_code", ""),
            runtime=data.get("runtime"),
            season_number=data.get("season_number", season),
            still_path=data.get("still_path"),
            vote_average=data.get("vote_average", 0.0),
            vote_count=data.get("vote_count", 0),
            raw=data,
        )
        settings.tmdb_episode_cache[key] = meta
        return meta
    except Exception as e:
        logger.warning("[TMDB] ⚠️ Episode lookup failed: %s", e)
        settings.tmdb_episode_cache[key] = None
        return None
