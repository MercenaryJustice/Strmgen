# strmgen/services/subtitles.py

import shutil
import asyncio
from typing import Optional, Any
from pathlib import Path

from opensubtitlescom import OpenSubtitles

from ..core.config import settings
from ..core.utils import setup_logger
from ..core.fs_utils import clean_name, safe_mkdir
from ..services.tmdb import Movie
from ..core.models import DispatcharrStream

logger = setup_logger(__name__)

_download_limit_reached = False
sub_client: Optional[OpenSubtitles] = None

# Initialize the OpenSubtitles client at import time (if configured)
if (
    settings.opensubtitles_download
    and settings.opensubtitles_app_name
    and settings.opensubtitles_username
    and settings.opensubtitles_password
):
    try:
        sub_client = OpenSubtitles(settings.opensubtitles_app_name, settings.opensubtitles_api_key)
        sub_client.login(settings.opensubtitles_username, settings.opensubtitles_password)
    except Exception as e:
        logger.warning(f"[SUB] OpenSubtitles login failed: {e}")
        sub_client = None


async def _download_and_write(params: dict[str, Any], filename: str, folder: Path) -> None:
    """
    Blocking subtitle search & download logic, run in a thread.
    """
    global _download_limit_reached

    def _blocking():
        nonlocal params, filename, folder
        safe_mkdir(folder)
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
            logger.warning("[SUB] ❌ Best subtitle result missing 'id'; skipping download.")
            return

        logger.info(f"[SUB] Downloading subtitle ID: {sub_id} ({count} downloads)")
        sub_path = sub_client.download_and_save(best)
        if not Path(sub_path).exists():
            logger.error(f"[SUB] ❌ Downloaded subtitle not found at: {sub_path}")
            return

        output_path = folder / filename
        shutil.copy(sub_path, output_path)
        Path(sub_path).unlink(missing_ok=True)
        logger.info(f"[SUB] ✅ Subtitle saved as: {output_path}")

    if _download_limit_reached:
        logger.info("[SUB] ⏭️ Skipping subtitle download: daily limit reached.")
        return
    if not sub_client:
        logger.warning("[SUB] OpenSubtitles client is not initialized.")
        return

    try:
        await asyncio.to_thread(_blocking)
    except Exception as e:
        msg = str(e)
        if "Download limit reached" in msg or "406" in msg:
            _download_limit_reached = True
            logger.warning("[SUB] ❌ Subtitle download blocked (quota or bad format); skipping further attempts.")
        else:
            logger.exception(f"[SUB] ⚠️ Failed to download/save subtitles: {e}")


async def download_movie_subtitles(
    meta: Movie,
    stream: DispatcharrStream,
    tmdb_id: Optional[str] = None
) -> None:
    """
    Async entrypoint to download movie subtitles.
    """
    if not settings.opensubtitles_download or not meta:
        return

    filename = f"{clean_name(meta.title)}.en.srt"
    filepath = stream.base_path / filename
    if await asyncio.to_thread(filepath.exists):
        logger.info(f"[SUB] Skipping download, subtitle already exists: {filepath}")
        return

    params: dict[str, Any] = {"languages": "en"}
    if tmdb_id:
        params["tmdb_id"] = tmdb_id
    else:
        params.update({
            "query": meta.title,
            "year": meta.release_date[:4]
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
    if not settings.opensubtitles_download or not show:
        return

    filename = f"{clean_name(show)} - S{season:02}E{ep:02}.en.srt"
    filepath = folder / filename
    if await asyncio.to_thread(filepath.exists):
        logger.info(f"[SUB] Skipping download, subtitle already exists: {filepath}")
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