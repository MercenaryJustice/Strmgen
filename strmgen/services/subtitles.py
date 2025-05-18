# strmgen/services/subtitles.py

import shutil
import asyncio
import logging

from typing import Optional, Any
from pathlib import Path

from opensubtitlescom import OpenSubtitles

from strmgen.core.config import get_settings
from strmgen.core.utils import safe_mkdir
from strmgen.core.string_utils import clean_name
from strmgen.services.tmdb import Movie
from strmgen.core.models.dispatcharr import DispatcharrStream

logger = logging.getLogger(__name__)
_settings = get_settings()
_download_limit_reached = False
sub_client: Optional[OpenSubtitles] = None

# Initialize the OpenSubtitles client if configured
def _init_sub_client():
    global sub_client
    s = get_settings()
    if (
        s.opensubtitles_download
        and s.opensubtitles_app_name
        and s.opensubtitles_username
        and s.opensubtitles_password
    ):
        try:
            client = OpenSubtitles(s.opensubtitles_app_name, s.opensubtitles_api_key)
            client.login(s.opensubtitles_username, s.opensubtitles_password)
            sub_client = client
        except Exception as e:
            logger.warning(f"[SUB] OpenSubtitles login failed: {e}")
            sub_client = None

# Call client initialization at import
_init_sub_client()

async def _download_and_write(params: dict[str, Any], filename: str, folder: Path) -> None:
    """
    Blocking subtitle search & download logic, run in a thread.
    """
    global _download_limit_reached
    def _blocking():
        nonlocal params, filename, folder
        safe_mkdir(folder)
        if not sub_client:
            logger.warning("[SUB] OpenSubtitles client not initialized.")
            return
        logger.info(f"[SUB] Searching for subtitles with: {params}")
        resp = sub_client.search(**params)
        results = getattr(resp, "data", None)
        if not results:
            logger.info("[SUB] No subtitle results found.")
            return

        best = max(results, key=lambda s: getattr(s, "download_count", 0))
        sub_id = getattr(best, "id", None)
        count = getattr(best, "download_count", 0)

        if not sub_id:
            logger.warning("[SUB] Best subtitle missing 'id'; skipping.")
            return

        logger.info(f"[SUB] Downloading subtitle ID: {sub_id} ({count} downloads)")
        sub_path = sub_client.download_and_save(best)
        if not Path(sub_path).exists():
            logger.error(f"[SUB] Downloaded subtitle not found: {sub_path}")
            return

        output_path = folder / filename
        shutil.copy(sub_path, output_path)
        Path(sub_path).unlink(missing_ok=True)
        logger.info(f"[SUB] Subtitle saved as: {output_path}")

    if _download_limit_reached:
        logger.info("[SUB] Skipping subtitle download: limit reached.")
        return

    try:
        await asyncio.to_thread(_blocking)
    except Exception as e:
        msg = str(e)
        if "Download limit reached" in msg or "406" in msg:
            _download_limit_reached = True
            logger.warning("[SUB] Subtitle download blocked; skipping further attempts.")
        else:
            logger.exception(f"[SUB] Failed to download/save subtitles: {e}")

async def download_movie_subtitles(
    meta: Movie,
    stream: DispatcharrStream,
    tmdb_id: Optional[str] = None
) -> None:
    """
    Async entrypoint to download movie subtitles.
    """
    s = get_settings()
    if not s.opensubtitles_download or not meta:
        return

    filename = f"{clean_name(meta.title)}.en.srt"
    filepath = stream.base_path / filename
    if await asyncio.to_thread(filepath.exists):
        logger.info(f"[SUB] Subtitle exists: {filepath}")
        return

    params: dict[str, Any] = {"languages": "en"}
    if tmdb_id:
        params["tmdb_id"] = tmdb_id
    else:
        params.update({
            "query": meta.title,
            "year": meta.release_date[:4] if meta.release_date else None
        })

    await _download_and_write(params, filename, stream.base_path)

async def download_episode_subtitles(
    show: str,
    season: int,
    ep: int,
    folder: Path,
    tmdb_id: Optional[str] = None
) -> None:
    """
    Async entrypoint to download episode subtitles.
    """
    s = get_settings()
    if not s.opensubtitles_download or not show:
        return

    filename = f"{clean_name(show)} - S{season:02d}E{ep:02d}.en.srt"
    filepath = folder / filename
    if await asyncio.to_thread(filepath.exists):
        logger.info(f"[SUB] Subtitle exists: {filepath}")
        return

    params: dict[str, Any] = {
        "season_number": season,
        "episode_number": ep,
        "languages": "en"
    }
    if tmdb_id:
        params["tmdb_id"] = tmdb_id
    else:
        params["query"] = show

    await _download_and_write(params, filename, folder)