# strmgen/services/tmdb.py

import asyncio
from difflib import SequenceMatcher
from typing import Optional, Dict, List, Any, TypeVar
from pathlib import Path

import aiofiles
import httpx

from ..core.config import settings
from ..core.utils import setup_logger
from ..core.fs_utils import clean_name, safe_mkdir
from ..core.models import Movie, TVShow, SeasonMeta, EpisodeMeta, DispatcharrStream

logger = setup_logger(__name__)

# Constants
TMDB_BASE = "https://api.themoviedb.org/3"
TMDB_IMG_BASE = "https://image.tmdb.org/t/p"

# Caches
_tv_genre_map: Dict[int, str] = {}
_tmdb_show_cache: Dict[str, Any] = {}


async def init_tv_genre_map() -> None:
    """
    Populate the global _tv_genre_map by calling the TMDb
    /genre/tv/list endpoint and extracting {id: name}.
    """
    # 1) fetch the raw payload (which looks like {"genres":[{"id":10759,"name":"Action"},{"id":16,"name":"Animation"}, …]})
    payload: Dict[str, Any] = await _get("/genre/tv/list", {})

    # 2) extract & remap into Dict[int,str]
    genres = payload.get("genres", [])
    for g in genres:
        # ensure we have both an int id and a string name
        gid  = int(g.get("id", 0))
        name = str(g.get("name", ""))
        _tv_genre_map[gid] = name

       


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

async def fetch_movie_details(
    title: Optional[str] = None,
    year:  Optional[int] = None,
    tmdb_id: Optional[int] = None
) -> Optional[Movie]:
    """
    Single entry point:
      • If tmdb_id is provided, fetch detail directly (with all append sections).
      • Otherwise, search by title/year, pick best candidate, then fetch detail.
    """
    if not settings.tmdb_api_key:
        return None

    # define once: which extra sections to include on detail fetch
    append_sections = [
        "alternative_titles","changes","credits","external_ids",
        "images","keywords","lists","recommendations",
        "release_dates","reviews","similar","translations",
        "videos","watch/providers",
    ]
    append_to = {"append_to_response": ",".join(append_sections)}

    try:
        # 1) Direct lookup path
        if tmdb_id:
            detail = await _get(f"/movie/{tmdb_id}", append_to)

        # 2) Search + scoring path
        else:
            logger.info("[TMDB] 🔍 Searching movie: %s (%s)", title, year)
            params: Dict[str, Any] = {"query": title or ""}
            if year:
                params["year"] = year

            search_data = await _get("/search/movie", params)
            results = search_data.get("results", [])
            if not results:
                return None

            # build Movie candidates with detail fetch
            candidates: List[Movie] = []
            for r in results:
                mid = r.get("id")
                if not mid:
                    continue
                det = await _get(f"/movie/{mid}", append_to)
                candidates.append(Movie(
                    id=det.get("id", 0),
                    title=det.get("title", ""),
                    original_title=det.get("original_title", ""),
                    overview=det.get("overview", ""),
                    poster_path=det.get("poster_path"),
                    backdrop_path=det.get("backdrop_path"),
                    release_date=det.get("release_date", ""),
                    adult=det.get("adult", False),
                    original_language=det.get("original_language", ""),
                    genre_ids=det.get("genres", []),
                    popularity=det.get("popularity", 0.0),
                    video=det.get("video", False),
                    vote_average=det.get("vote_average", 0.0),
                    vote_count=det.get("vote_count", 0),
                    alternative_titles=det.get("alternative_titles", {}),
                    changes=det.get("changes", {}),
                    credits=det.get("credits", {}),
                    external_ids=det.get("external_ids", {}),
                    images=det.get("images", {}),
                    keywords=det.get("keywords", {}),
                    lists=det.get("lists", {}),
                    recommendations=det.get("recommendations", {}),
                    release_dates=det.get("release_dates", {}),
                    reviews=det.get("reviews", {}),
                    similar=det.get("similar", {}),
                    translations=det.get("translations", {}),
                    videos=det.get("videos", {}),
                    watch_providers=det.get("watch/providers", {}),
                    raw=det,
                ))

            if not candidates:
                return None

            # scoring: name similarity + year proximity
            target = clean_name(title or "")
            def score(m: Movie) -> float:
                sim = SequenceMatcher(None, clean_name(m.title), target).ratio()
                year_score = 0.5
                if m.year and year:
                    diff = abs(m.year - year)
                    year_score = max(0.0, 1.0 - diff * 0.1)
                return 0.7 * sim + 0.3 * year_score

            best: Movie = await asyncio.to_thread(max, candidates, key=score)
            detail = best.raw  # use its raw dict for final mapping

        # 3) Final Movie construction from `detail`
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
            genre_ids=detail.get("genres", []),
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
        logger.error("[TMDB] ❌ get_movie failed for title=%r, id=%r: %s", title, tmdb_id, e)
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

async def fetch_tv_details(
    query: Optional[str]  = None,
    tv_id: Optional[int]  = None
) -> Optional[TVShow]:
    """
    Fetch a TV show by tmdb_id (if provided), otherwise
    search on `query` and pick the best match.
    """
    if not settings.tmdb_api_key:
        return None

    try:
        # Always append credits
        append = {"append_to_response": "credits"}

        # 1) Direct lookup if tv_id given
        if tv_id:
            detail = await _get(f"/tv/{tv_id}", append)

        # 2) Search + best-match otherwise
        else:
            if not query:
                return None

            logger.info("[TMDB] 🔍 Searching TV: %s", query)
            data = await _get("/search/tv", {"query": query})
            results: List[Dict[str, Any]] = data.get("results", [])
            if not results:
                return None

            # pick best by whatever logic you already have
            best = _get_best_match_tv(results, query)
            if not best or not best.get("id"):
                return None

            tv_id = best["id"]
            detail = await _get(f"/tv/{tv_id}", append)

        # 3) Map to your TVShow model
        return TVShow(
            id=detail.get("id", 0),
            channel_group_name="",
            name=detail.get("name", ""),
            original_name=detail.get("original_name", ""),
            overview=detail.get("overview", ""),
            poster_path=detail.get("poster_path"),
            backdrop_path=detail.get("backdrop_path"),
            media_type=detail.get("media_type", ""),
            adult=detail.get("adult", False),
            original_language=detail.get("original_language", ""),
            genre_ids=detail.get("genre_ids", []),
            genre_names=[_tv_genre_map.get(g, "") for g in detail.get("genre_ids", [])],
            popularity=detail.get("popularity", 0.0),
            first_air_date=detail.get("first_air_date", ""),
            vote_average=detail.get("vote_average", 0.0),
            vote_count=detail.get("vote_count", 0),
            origin_country=detail.get("origin_country", []),
            external_ids=detail.get("external_ids", {}),
            raw=detail,
        )
    except Exception as e:
        logger.error("[TMDB] ❌ fetch_tv_details failed for query=%r, tv_id=%r: %s", query, tv_id, e)
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

T = TypeVar("T", Movie, TVShow, SeasonMeta, EpisodeMeta)


async def download_if_missing(
    log_tag: str,
    stream: DispatcharrStream,
    tmdb: T,
) -> bool:
    # 1) pick the correct remote‐URL field
    if isinstance(tmdb, EpisodeMeta):
        poster_url   = tmdb.still_path      # episodes use `still_path`
        backdrop_url = None
    else:
        # Movie, TVShow, SeasonMeta all have `poster_path` & `backdrop_path`
        poster_url   = getattr(tmdb, "poster_path", None)
        backdrop_url = getattr(tmdb, "backdrop_path", None)

    # 2) your DispatcharrStream already knows where these belong on disk:
    poster_path = stream.poster_path
    fanart_path = stream.backdrop_path

    # 3) download if URL exists and file is missing
    if poster_url and not await asyncio.to_thread(poster_path.exists):
        logger.info(f"{log_tag} Downloading poster %s", poster_url)
        await _download_image(poster_url, poster_path)

    if backdrop_url and not await asyncio.to_thread(fanart_path.exists):
        logger.info(f"{log_tag} Downloading backdrop %s", backdrop_url)
        await _download_image(backdrop_url, fanart_path)

    return True



async def tmdb_lookup_tv_show(show: str) -> Optional[Dict[str, Any]]:
    """
    Look up a TV show in TMDb, returning the best-matching result.
    Handles both:
      - search_any_tmdb returning a dict with "results": [...]
      - search_any_tmdb returning a single dict (one result)
    """
    # return cached if present
    if show in _tmdb_show_cache:
        return _tmdb_show_cache[show]

    data = await search_any_tmdb(show)
    # normalize into a list of candidates
    if isinstance(data, dict) and "results" in data:
        candidates = data["results"] or []
    elif isinstance(data, list):
        candidates = data
    elif isinstance(data, dict):
        # single-object response
        candidates = [data]
    else:
        candidates = []

    # prefer TV entries
    tvs = [r for r in candidates if r.get("media_type") == "tv"]
    candidates = tvs or candidates

    if not candidates:
        _tmdb_show_cache[show] = None
        return None

    def similarity(item: Dict[str, Any]) -> float:
        title = (item.get("name") or item.get("title") or "").lower()
        return SequenceMatcher(None, show.lower(), title).ratio()

    best = max(candidates, key=similarity)
    _tmdb_show_cache[show] = best
    return best

async def lookup_show(show: DispatcharrStream) -> Optional[TVShow]:
    show_name = show.name
    cached = settings.tmdb_show_cache.get(show_name)
    if isinstance(cached, TVShow):
        return cached
    if not settings.tmdb_api_key:
        return None
    raw = await tmdb_lookup_tv_show(show_name)
    if not raw:
        return None
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
        channel_group_name=show.channel_group_name,
    )
    settings.tmdb_show_cache[show_name] = tv
    return tv

async def get_season_meta(
    stream: DispatcharrStream,
    mshow: TVShow
) -> Optional[SeasonMeta]:
    show_id = mshow.id
    season  = stream.season
    key     = (show_id, season)

    cached = settings.tmdb_season_cache.get(key)
    if isinstance(cached, SeasonMeta):
        return cached

    try:
        data = await _get(f"/tv/{show_id}/season/{season}", {})
        meta = SeasonMeta(
            channel_group_name = stream.channel_group_name,
            show               = stream.name,
            id                 = data.get("id", 0),
            name               = data.get("name", ""),
            overview           = data.get("overview", ""),
            air_date           = data.get("air_date", ""),
            raw_episodes       = data.get("episodes", []),   # ← here!
            poster_path        = data.get("poster_path"),
            season_number      = data.get("season_number", season),
            vote_average       = data.get("vote_average", 0.0),
            raw                = data,
        )
        settings.tmdb_season_cache[key] = meta
        return meta

    except Exception as e:
        logger.warning("[TMDB] ⚠️ Season lookup failed: %s", e)
        settings.tmdb_season_cache[key] = None
        return None

async def get_episode_meta(stream: DispatcharrStream, mshow: TVShow) -> Optional[EpisodeMeta]:
    show_id = mshow.id
    season = stream.season
    ep = stream.episode

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
            group=stream.channel_group_name,
            show=stream.name,
        )
        settings.tmdb_episode_cache[key] = meta
        return meta
    except Exception as e:
        logger.warning("[TMDB] ⚠️ Episode lookup failed: %s", e)
        settings.tmdb_episode_cache[key] = None
        return None
