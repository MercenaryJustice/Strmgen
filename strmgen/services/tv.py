# strmgen/services/tv.py

import asyncio
import logging
from collections import defaultdict
from pathlib import Path
from typing import Dict, Optional, List

from ..core.state import mark_skipped, is_skipped, SkippedStream
from ..core.config import settings
from ..core.models import DispatcharrStream, SeasonMeta
from .tmdb import TVShow, EpisodeMeta, lookup_show, get_season_meta, download_if_missing
from .subtitles import download_episode_subtitles
from ..core.utils import (
    filter_by_threshold,
    write_if,
    write_tvshow_nfo,
    write_episode_nfo
)
from .streams import write_strm_file, fetch_streams
from ..core.auth import get_auth_headers

logger = logging.getLogger(__name__)
RE_EPISODE_TAG = settings.TV_SERIES_EPIDOSE_RE
log_tag = "[TV] 🖼️"

# Track which show‐NFOs we've already written this run
_skipped: set[str] = set()




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
    streams: List[DispatcharrStream],
    group: str,
    headers: Dict[str, str],
    reprocess: bool = False
) -> None:
    TAG = "[TV]"

    # 1) Drop any streams missing season/episode
    streams = [s for s in streams if s.season is not None and s.episode is not None]

    # 2) Build show→season→[streams] map
    shows: Dict[str, Dict[int, List[DispatcharrStream]]] = defaultdict(lambda: defaultdict(list))
    for s in streams:
        shows[s.name][s.season].append(s)

    # 3) Iterate each show
    for show_name, seasons in shows.items():
        if show_name in _skipped:
            continue

        logger.info(f"{TAG} ▶️ Processing show {show_name!r}")

        # 3a) Lookup & cache show metadata
        sample_stream = next(iter(next(iter(seasons.values()))))
        mshow: Optional[TVShow] = await lookup_show(sample_stream)
        if not mshow:
            _skipped.add(show_name)
            continue

        # 3b) Threshold check once per show
        passed = await asyncio.to_thread(filter_by_threshold, show_name, mshow.raw)
        if not passed:
            await asyncio.to_thread(mark_skipped, "TV", group, mshow, sample_stream)
            _skipped.add(show_name)
            logger.info(f"{TAG} 🚫 Threshold filter failed for: {show_name}")
            continue

        # 3c) Write show‐level .nfo & schedule show images
        if settings.write_nfo and show_name:
            await asyncio.to_thread(write_tvshow_nfo, sample_stream, mshow)
            asyncio.create_task(download_if_missing(TAG, sample_stream, mshow))
            if settings.update_tv_series_nfo:
                # if only updating series‐level NFO, skip episodes
                continue

        # 4) Iterate each season
        for season_num, eps in seasons.items():
            logger.info(f"{TAG} 📅 Fetch season {show_name!r} S{season_num:02d} ({len(eps)} eps)")

            season_meta: Optional[SeasonMeta] = await get_season_meta(eps[0], mshow)
            if not season_meta:
                logger.warning(f"{TAG} ❌ No metadata for {show_name!r} S{season_num:02d}")
                continue

            # schedule season poster download
            asyncio.create_task(download_if_missing(TAG, eps[0], season_meta))

            # 5) Process each episode
            for stream in eps:
                try:
                    # per‐episode skip checks
                    if stream.name in _skipped:
                        continue
                    if not reprocess and await asyncio.to_thread(is_skipped, stream.stream_type, stream.id):
                        logger.info(f"{TAG} ⏭️ Skipped episode: {stream.name}")
                        _skipped.add(stream.name)
                        continue

                    logger.info(
                        f"{TAG} 📺 Episode: {show_name} S{season_num:02d}E{stream.episode:02d}"
                    )

                    # grab the pre‑built EpisodeMeta
                    ep_num = stream.episode  # type: ignore[assignment]
                    episode_meta = season_meta.episode_map.get(ep_num)
                    if not episode_meta:
                        logger.warning(
                            f"{TAG} ❌ Missing ep {ep_num:02d} in {show_name!r} S{season_num:02d}"
                        )
                        continue

                    # — Write .strm file —
                    episode_meta.strm_path.parent.mkdir(parents=True, exist_ok=True)
                    episode_meta.strm_path.write_text(stream.proxy_url, encoding="utf-8")

                    # — Episode .nfo & still image —
                    if settings.write_nfo:
                        await asyncio.to_thread(write_episode_nfo, stream, episode_meta)
                        if episode_meta.still_path:
                            asyncio.create_task(download_if_missing(TAG, stream, episode_meta))

                except Exception as e:
                    logger.error(f"{TAG} ❌ Error processing {stream.name}: {e}", exc_info=True)
                    continue

        logger.info(f"{TAG} ✅ Finished show {show_name!r}")

    logger.info(f"{TAG} Completed processing TV streams for group: {group}")



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

        await process_tv(streams, skipped["group"], headers, True)

        #await asyncio.to_thread(set_reprocess, skipped["tmdb_id"], False)
        logger.info("✅ Reprocessed TV show %s", skipped["name"])
        return True
    except Exception as e:
        logger.error("Error reprocessing TV %s: %s", skipped["name"], e, exc_info=True)
        return False