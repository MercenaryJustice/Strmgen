# strmgen/services/tv.py

import asyncio
import logging
from pathlib import Path
from typing import Dict, Optional

from ..core.state import mark_skipped, is_skipped, SkippedStream, set_reprocess
from ..core.config import settings
from ..core.models import DispatcharrStream
from .tmdb import TVShow, EpisodeMeta, lookup_show, get_season_meta, get_episode_meta, download_if_missing
from .subtitles import download_episode_subtitles
from ..core.utils import (
    filter_by_threshold,
    target_folder,
    write_if,
    write_tvshow_nfo,
    write_episode_nfo,
    clean_name
)
from .streams import write_strm_file, fetch_streams
from ..core.auth import get_auth_headers

logger = logging.getLogger(__name__)
RE_EPISODE_TAG = settings.TV_SERIES_EPIDOSE_RE
log_tag = "[TV] 🖼️"

# Track which show‐NFOs we've already written this run
_written_show_nfos: set[str] = set()


class Paths:
    @staticmethod
    def show_nfo(folder: Path, show: str) -> Path:
        return folder / f"{show}.nfo"

    @staticmethod
    def show_image(folder: Path, filename: str) -> Path:
        return folder / filename

    @staticmethod
    def season_folder(root: Path, group: str, show: str, season: int) -> Path:
        return target_folder(root, "TV Shows", group, show) / f"Season {season:02d}"

    @staticmethod
    def season_poster(dest_folder: Path, season: int) -> Path:
        return dest_folder / f"Season {season:02d}.tbn"

    @staticmethod
    def episode_strm(dest_folder: Path, show: str, season: int, ep: int) -> Path:
        base = f"{show} - S{season:02d}E{ep:02d}"
        return dest_folder / f"{base}.strm"

    @staticmethod
    def episode_nfo(dest_folder: Path, show: str, season: int, ep: int) -> Path:
        base = f"{show} - S{season:02d}E{ep:02d}"
        return dest_folder / f"{base}.nfo"

    @staticmethod
    def episode_image(dest_folder: Path, show: str, season: int, ep: int) -> Path:
        base = f"{show} - S{season:02d}E{ep:02d}"
        return dest_folder / f"{base}.jpg"


async def write_assets(
    stream: DispatcharrStream,
    show: str,
    season: int,
    ep: int,
    show_folder: Path,
    season_folder: Path,
    strm_path: Path,
    mshow: Optional[TVShow],
    episode_meta: EpisodeMeta,
    headers: Dict[str, str]
) -> bool:
    """
    Async write of .strm, NFOs, and images for a TV episode.
    """
    global _written_show_nfos

    # 1) Show‐level NFO & images
    if mshow and settings.write_nfo:
        if show not in _written_show_nfos:
            # write_tvshow_nfo is sync; run in thread
            await asyncio.to_thread(write_tvshow_nfo, mshow.raw, Paths.show_nfo(show_folder, mshow.name))
            _written_show_nfos.add(show)
            if settings.update_tv_series_nfo:
                return True

        # download poster & backdrop
        await download_if_missing(log_tag, f"{mshow.name} poster", mshow.poster_path,
                                  Paths.show_image(show_folder, "poster.jpg"))
        await download_if_missing(log_tag, f"{mshow.name} backdrop", mshow.backdrop_path,
                                  Paths.show_image(show_folder, "fanart.jpg"))

    # 2) Season‐level poster
    if mshow:
        season_meta = await get_season_meta(mshow.id, season)
        poster_path = season_meta.poster_path if season_meta else None
        await download_if_missing(log_tag,
                                  f"{mshow.name} Season {season:02d} poster",
                                  poster_path,
                                  Paths.season_poster(season_folder, season))

    # 3) Write .strm file
    ok = await write_strm_file(strm_path, headers, stream)
    if not ok:
        logger.warning("[TV] ❌ Failed writing .strm for: %s", strm_path)
        return False

    # 4) Episode NFO & still image
    if settings.write_nfo:
        ep_nfo = Paths.episode_nfo(season_folder,
                                   mshow.name if mshow else show,
                                   season,
                                   ep)
        await asyncio.to_thread(write_if,
                                settings.write_nfo_only_if_not_exists,
                                ep_nfo,
                                write_episode_nfo,
                                episode_meta.raw)
        await download_if_missing(log_tag,
                                  f"{mshow.name if mshow else show} S{season:02d}E{ep:02d} still",
                                  episode_meta.still_path,
                                  Paths.episode_image(season_folder,
                                                      mshow.name if mshow else show,
                                                      season,
                                                      ep))
    return True


async def download_subtitles_if_enabled(
    show: str,
    season: int,
    ep: int,
    season_folder: Path,
    mshow: Optional[TVShow],
) -> None:
    """
    Async download of episode subtitles if enabled.
    """
    if settings.opensubtitles_download:
        logger.info("[SUB] 🔽 Downloading subtitles for: %s S%02dE%02d", show, season, ep)
        tmdb_id = (mshow.external_ids.get("imdb_id")
                   if mshow and mshow.external_ids else None)
        await download_episode_subtitles(
            show,
            season,
            ep,
            season_folder,
            tmdb_id=tmdb_id or (str(mshow.id) if mshow else None)
        )


async def process_tv(
    stream: DispatcharrStream,
    root: Path,
    group: str,
    headers: Dict[str, str]
) -> None:
    """
    Async processing for a single TV episode:
      1) Parse SxxExx
      2) Lookup and cache show metadata
      3) Filter by threshold
      4) Write assets & subtitles
    """
    match = RE_EPISODE_TAG.match(stream.name)
    if not match:
        logger.info("[TV] ❌ No SxxExx pattern in: %s", stream.name)
        return

    show = clean_name(match.group(1))
    season = int(match.group(2))
    ep = int(match.group(3))
    logger.info("[TV] 📺 Episode: %s S%02dE%02d", show, season, ep)

    # lookup show metadata
    mshow = await lookup_show(show)
    if not mshow:
        return
    if await asyncio.to_thread(is_skipped, "TV", mshow.id):
        logger.info("[TV] ⏭️ Skipped show: %s", show)
        return
    if not await asyncio.to_thread(filter_by_threshold, stream.name, mshow.raw if mshow else None):
        await asyncio.to_thread(mark_skipped, "TV", group, mshow, stream)
        logger.info("[TV] 🚫 Threshold filter failed for: %s", show)
        return
    if settings.update_tv_series_nfo and show in _written_show_nfos:
        return

    # prepare paths
    show_folder = target_folder(root, "TV Shows", group, show)
    season_folder = Paths.season_folder(root, group, show, season)
    strm_path = Paths.episode_strm(season_folder, show, season, ep)

    # fetch episode metadata
    episode_meta = await get_episode_meta(mshow.id, season, ep)
    if not episode_meta:
        logger.warning("[TV] ❌ No metadata for episode: %s S%02dE%02d", show, season, ep)
        return

    # write assets and subtitles
    if await write_assets(stream, show, season, ep, show_folder, season_folder, strm_path, mshow, episode_meta, headers):
        await download_subtitles_if_enabled(show, season, ep, season_folder, mshow)


async def reprocess_tv(skipped: SkippedStream) -> bool:
    """
    Async reprocess of a skipped TV show.
    """
    headers = await get_auth_headers()
    try:
        streams = await fetch_streams(skipped["group"], skipped["stream_type"], headers=headers)
        if not streams:
            logger.error("Cannot reprocess TV %s: no streams", skipped["name"])
            return False

        root = Path(settings.output_root)
        for stream in streams:
            await process_tv(stream, root, skipped["group"], headers)

        await asyncio.to_thread(set_reprocess, skipped["tmdb_id"], False)
        logger.info("✅ Reprocessed TV show %s", skipped["name"])
        return True
    except Exception as e:
        logger.error("Error reprocessing TV %s: %s", skipped["name"], e, exc_info=True)
        return False