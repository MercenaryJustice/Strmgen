import shutil

from typing import Optional
from pathlib import Path

from opensubtitlescom import OpenSubtitles
from ..core.config import settings
from .tmdb import Movie
from ..core.utils import clean_name, safe_mkdir
from ..core.utils import setup_logger
logger = setup_logger(__name__)

_download_limit_reached = False  # global flag

sub_client: Optional[OpenSubtitles] = None
if (
    settings.opensubtitles_download
    and settings.opensubtitles_app_name
    and settings.opensubtitles_username
    and settings.opensubtitles_password
):
    sub_client = OpenSubtitles(settings.opensubtitles_app_name, settings.opensubtitles_api_key)
    try:
        sub_client.login(settings.opensubtitles_username, settings.opensubtitles_password)
    except Exception as e:
        logger.warning(f"[SUB] OpenSubtitles login failed: {e}")
        sub_client = None

def _download_and_write(params: dict, filename: str, folder: Path) -> None:
    global _download_limit_reached

    if _download_limit_reached:
        logger.info("[SUB] ⏭️ Skipping subtitle download: daily limit already reached.")
        return

    if not sub_client:
        logger.warning("[SUB] OpenSubtitles client is not initialized.")
        return

    safe_mkdir(folder)

    try:
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

        output_path = folder / filename
        logger.info(f"[SUB] Downloading subtitle ID: {sub_id} with {count} downloads")

        # Download subtitle to temp file
        sub_path = sub_client.download_and_save(best)

        if not Path(sub_path).exists():
            logger.error(f"[SUB] ❌ Downloaded subtitle not found at: {sub_path}")
            return

        # Move to desired filename and delete original
        shutil.copy(sub_path, output_path)
        Path(sub_path).unlink(missing_ok=True)

        logger.info(f"[SUB] ✅ Subtitle saved as: {output_path}")

    except Exception as e:
        if "Download limit reached" in str(e) or "406" in str(e):
            _download_limit_reached = True
            logger.warning("[SUB] ❌ Subtitle download blocked (quota or bad format). Skipping further attempts this run.")
        else:
            logger.exception(f"[SUB] ⚠️ Failed to download/save subtitles: {e}")


def download_movie_subtitles(meta: Movie, folder: Path, tmdb_id: Optional[str] = None) -> None:
    if not settings.opensubtitles_download or not meta:
        return
    filename = f"{clean_name(meta.title)}.en.srt"
    filepath = folder / filename
    if filepath.exists():
        logger.info(f"[SUB] Skipping download, subtitle already exists: {filepath}")
        return

    params = {"languages": "en"}
    if tmdb_id:
        params["tmdb_id"] = tmdb_id
    else:
        params.update({
            "query": meta.title,
            "year": meta.release_date[:4]
        })

    _download_and_write(params, filename, folder)


def download_episode_subtitles(show: str, season: int, ep: int, folder: Path, tmdb_id: Optional[str] = None) -> None:
    if not settings.opensubtitles_download or not show:
        return
    filename = f"{clean_name(show)} - S{season:02}E{ep:02}.en.srt"
    filepath = folder / filename
    if filepath.exists():
        logger.info(f"[SUB] Skipping download, subtitle already exists: {filepath}")
        return

    params: dict[str, str | int] = {
        "season_number": season,
        "episode_number": ep,
        "languages": "en"
    }
    if tmdb_id:
        params["tmdb_id"] = tmdb_id
    else:
        params["query"] = show

    _download_and_write(params, filename, folder)