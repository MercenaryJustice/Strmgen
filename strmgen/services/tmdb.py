# strmgen/services/tmdb.py

import asyncio
import random
from difflib import SequenceMatcher
from typing import Optional, Dict, List, Any, TypeVar
from pathlib import Path
from datetime import datetime

import aiofiles
import httpx
from httpx import PoolTimeout, HTTPError

from strmgen.core.config import get_settings
from strmgen.core.utils import setup_logger, safe_mkdir
from strmgen.core.string_utils import clean_name
from strmgen.core.httpclient import tmdb_client, tmdb_image_client, tmdb_limiter
from strmgen.core.models.dispatcharr import DispatcharrStream
from strmgen.core.models.tv import TVShow, EpisodeMeta, SeasonMeta
from strmgen.core.models.movie import Movie


logger = setup_logger(__name__)


async def _get(endpoint: str, params: Dict[str, Any]) -> Any:
    """
    Internal TMDb GET with retry/backoff and rate-limit handling.
    """
    backoff = 1
    settings = get_settings()
    for attempt in range(3):
        try:
            async with tmdb_limiter:
                resp = await tmdb_client.get(
                    endpoint,
                    params={**params, "api_key": settings.tmdb_api_key}
                )
            if resp.status_code == 429:
                logger.warning("[TMDB] 429 for %s, backing off %ds", endpoint, backoff)
                await asyncio.sleep(backoff + random.random())
                backoff = min(backoff * 2, 8)
                continue
            resp.raise_for_status()
            return resp.json()
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 429:
                logger.warning("[TMDB] Rate-limit on attempt %d for %s", attempt+1, endpoint)
                await asyncio.sleep(backoff + random.random())
                backoff = min(backoff * 2, 8)
                continue
            raise
        except httpx.RequestError as exc:
            logger.error("[TMDB] Request error for %s: %s", endpoint, exc)
            await asyncio.sleep(backoff + random.random())
            backoff = min(backoff * 2, 8)
    logger.error("[TMDB] Giving up on %s after retries", endpoint)
    return None

async def search_any_tmdb(title: str) -> Optional[Dict[str, Any]]:
    settings = get_settings()
    if not settings.tmdb_api_key:
        return None
    try:
        data = await _get("/search/multi", {"query": title})
        results = data.get("results", []) if data else []
        return results[0] if results else None
    except Exception as e:
        logger.error("[TMDB] multi-search failed for '%s': %s", title, e)
        return None

async def fetch_movie_details(
    title: Optional[str] = None,
    year: Optional[int] = None,
    tmdb_id: Optional[int] = None
) -> Optional[Movie]:
    settings = get_settings()
    if not settings.tmdb_api_key:
        return None
    append_sections = [
        "alternative_titles","changes","credits","external_ids",
        "images","keywords","lists","recommendations",
        "release_dates","reviews","similar","translations",
        "videos","watch/providers",
    ]
    append_to = {"append_to_response": ",".join(append_sections)}
    try:
        if tmdb_id:
            detail = await _get(f"/movie/{tmdb_id}", append_to)
        else:
            logger.info("[TMDB] Searching movie: %s (%s)", title, year)
            params: Dict[str, Any] = {"query": title or ""}
            if year:
                params["year"] = year
            search_data = await _get("/search/movie", params)
            results = search_data.get("results", []) if search_data else []
            if not results:
                return None

            candidates: List[Movie] = []
            for r in results:
                mid = r.get("id")
                if not mid:
                    continue

                # fetch full details
                det = await _get(f"/movie/{mid}", append_to)
                rel_date = det.get("release_date", "")
                if rel_date:
                    try:
                        dt = datetime.fromisoformat(rel_date)       # e.g. "2022-05-13"
                        rel_year = dt.year
                    except ValueError:
                        rel_year = None
                else:
                    rel_year = None

                # skip if we asked for a year and it doesn't match
                if year is not None and rel_year is not None and rel_year != year:
                    logger.debug("[TMDB] Skipping %s (%s) — year mismatch", det.get("title"), rel_year)
                    continue

                candidates.append(Movie(
                    id=det.get("id", 0),
                    title=det.get("title", ""),
                    original_title=det.get("original_title", ""),
                    overview=det.get("overview", ""),
                    poster_path=det.get("poster_path"),
                    backdrop_path=det.get("backdrop_path"),
                    release_date=rel_date,
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

            # scoring / fallback
            target = clean_name(title or "")
            def score(m: Movie) -> float:
                sim = SequenceMatcher(None, clean_name(m.title), target).ratio()
                year_score = 1.0  # since we’ve already filtered mismatches
                return 0.7 * sim + 0.3 * year_score

            best: Movie = await asyncio.to_thread(max, candidates, key=score)
            detail = best.raw

        if not detail:
            return None

        # final construction
        return Movie(
            id=detail.get("id", 0),
            title=detail.get("title", ""),
            original_title=detail.get("original_title", ""),
            overview=detail.get("overview", ""),
            poster_path=detail.get("poster_path", None),
            backdrop_path=detail.get("backdrop_path", None),
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
        logger.error("[TMDB] movie details failed: %s", e)
        return None
    


async def fetch_tv_details(
    group: str,
    query: Optional[str] = None,
    tv_id: Optional[int] = None
) -> Optional[TVShow]:
    settings = get_settings()
    if not settings.tmdb_api_key:
        return None
    try:
        # if not _tv_genre_map:
        #     await init_tv_genre_map()

        append = {"append_to_response": "credits"}

        if tv_id:
            detail = await _get(f"/tv/{tv_id}", append)
        else:
            if not query:
                return None

            logger.info("[TMDB] Searching TV: %s", query)
            data = await _get("/search/tv", {"query": query})
            results = data.get("results", []) if data else []

            # → FIX: use .ratio() on the SequenceMatcher
            if results:
                best = max(
                    results,
                    key=lambda r: SequenceMatcher(
                        None,
                        query.lower(),
                        r.get("name", "").lower()
                    ).ratio()
                )
            else:
                best = None

            if not best or not best.get("id"):
                return None

            tv_id = best["id"]
            detail = await _get(f"/tv/{tv_id}", append)

        if not detail:
            return None

        return TVShow(
            id=detail.get("id", 0),
            channel_group_name=group,
            name=clean_name(detail.get("name", query or "")),
            original_name=detail.get("original_name", ""),
            overview=detail.get("overview", ""),
            poster_path=detail.get("poster_path"),
            backdrop_path=detail.get("backdrop_path", None),
            media_type=detail.get("media_type", ""),
            adult=detail.get("adult", False),
            original_language=detail.get("original_language", ""),
            genre_ids=detail.get("genres", []),
            popularity=detail.get("popularity", 0.0),
            first_air_date=detail.get("first_air_date", ""),
            vote_average=detail.get("vote_average", 0.0),
            vote_count=detail.get("vote_count", 0),
            origin_country=detail.get("origin_country", []),
            external_ids=detail.get("external_ids", {}),
            raw=detail,
        )

    except Exception as e:
        logger.error("[TMDB] fetch_tv_details failed: %s", e)
        return None

async def _download_image(path_val: str, dest: Path) -> None:
    settings = get_settings()
    safe_mkdir(dest.parent)
    url = f"/{settings.tmdb_image_size}{path_val}"
    retries = 3
    for attempt in range(1, retries+1):
        try:
            resp = await tmdb_image_client.get(url)
            resp.raise_for_status()
            async with aiofiles.open(dest, "wb") as f:
                await f.write(resp.content)
            logger.info("[TMDB] Downloaded image: %s", dest)
            return
        except PoolTimeout:
            if attempt < retries:
                wait = attempt
                logger.warning("[TMDB] PoolTimeout, retry %d/%d", attempt, retries)
                await asyncio.sleep(wait)
                continue
            else:
                logger.error("[TMDB] PoolTimeout giving up on %s", url)
        except HTTPError as exc:
            logger.warning("[TMDB] HTTP error on %s: %s", url, exc)
            return
    logger.error("[TMDB] Failed to download image after retries: %s", url)

T = TypeVar("T", Movie, TVShow, SeasonMeta, EpisodeMeta)
_download_semaphore = asyncio.Semaphore(30)

async def download_if_missing(
    log_tag: str,
    stream: DispatcharrStream,
    tmdb: T,
) -> bool:
    if isinstance(tmdb, EpisodeMeta):
        poster_url = tmdb.still_path
        backdrop_url = None
    else:
        poster_url = getattr(tmdb, "poster_path", None)
        backdrop_url = getattr(tmdb, "backdrop_path", None)
    poster_path = stream.poster_path
    fanart_path = stream.backdrop_path
    async with _download_semaphore:
        if poster_url and not await asyncio.to_thread(poster_path.exists):
            logger.info(f"{log_tag} Downloading poster %s", poster_url)
            await _download_image(poster_url, poster_path)
        if backdrop_url and not await asyncio.to_thread(fanart_path.exists):
            logger.info(f"{log_tag} Downloading backdrop %s", backdrop_url)
            await _download_image(backdrop_url, fanart_path)
    return True

async def get_season_meta(
    stream: DispatcharrStream,
    mshow: TVShow
) -> Optional[SeasonMeta]:
    show_id = mshow.id
    season = stream.season

    try:
        data = await _get(f"/tv/{show_id}/season/{season}", {})
        meta = SeasonMeta(
            channel_group_name=stream.channel_group_name,
            show=stream.name,
            id=data.get("id", 0),
            name=data.get("name", ""),
            overview=data.get("overview", ""),
            air_date=data.get("air_date", ""),
            raw_episodes=data.get("episodes", []),
            poster_path=data.get("poster_path"),
            season_number=data.get("season_number", season),
            vote_average=data.get("vote_average", 0.0),
            raw=data,
        )
        return meta
    except Exception as e:
        logger.warning("[TMDB] Season lookup failed: %s", e)
        return None

async def get_episode_meta(
    stream: DispatcharrStream,
    mshow: TVShow
) -> Optional[EpisodeMeta]:
    show_id = mshow.id
    season = stream.season
    ep = stream.episode

    try:
        data = await _get(f"/tv/{show_id}/season/{season}/episode/{ep}", {})
        meta = EpisodeMeta(
            id=data.get("id", 0),
            name=data.get("name", ""),
            overview=data.get("overview", ""),
            air_date=data.get("air_date", ""),
            crew=data.get("crew", []),
            guest_stars=data.get("guest_stars", []),
            season_number=stream.season,
            episode_number=data.get("episode_number", 0),
            production_code=data.get("production_code", ""),
            runtime=data.get("runtime"),
            still_path=data.get("still_path"),
            vote_average=data.get("vote_average", 0.0),
            vote_count=data.get("vote_count", 0),
            raw=data,
            group=stream.channel_group_name,
            show=stream.name,
        )
        return meta
    except Exception as e:
        logger.warning("[TMDB] Episode lookup failed: %s", e)
        return None