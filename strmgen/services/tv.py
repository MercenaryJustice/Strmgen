# strmgen/services/tv.py

import asyncio
import shutil

from collections import defaultdict
from pathlib import Path
from typing import Dict, Optional, List
from more_itertools import chunked

from strmgen.core.db import mark_skipped, is_skipped, SkippedStream
from strmgen.core.config import get_settings
from strmgen.core.logger import setup_logger
from strmgen.services.tmdb import TVShow, fetch_tv_details, get_season_meta, download_if_missing
from strmgen.services.subtitles import download_episode_subtitles
from strmgen.core.utils import filter_by_threshold, write_tvshow_nfo, write_episode_nfo, safe_remove
from strmgen.services.streams import fetch_streams
from strmgen.core.auth import get_auth_headers
from strmgen.core.control import is_running
from strmgen.core.models.dispatcharr import DispatcharrStream
from strmgen.core.models.tv import SeasonMeta

logger = setup_logger(__name__)
TAG = "[TV] 🖼️"
_skipped: set[str] = set()

# Cached settings at module level (in-memory)
settings = get_settings()

async def download_subtitles_if_enabled(
    show: str,
    season: int,
    ep: int,
    season_folder: Path,
    mshow: Optional[TVShow],
) -> None:
    if not is_running():
        return

    settings = get_settings()
    if settings.opensubtitles_download:
        logger.info(f"{TAG} 🔽 Downloading subtitles for: {show} S{season:02d}E{ep:02d}")
        tmdb_id = mshow.external_ids.get("imdb_id") if mshow and mshow.external_ids else None
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
    reprocess: bool = False
) -> None:
    settings = get_settings()
    # 1) Filter out streams missing season/episode
    streams = [s for s in streams if s.season is not None and s.episode is not None]

    # 2) Group streams by show→season
    shows: Dict[str, Dict[int, List[DispatcharrStream]]] = defaultdict(lambda: defaultdict(list))
    for s in streams:
        shows[s.name][s.season].append(s)

    # 3) Chunk into show‑batches
    show_items = list(shows.items())
    show_batches = list(chunked(show_items, settings.batch_size))

    async def run_show_batch(batch_idx: int, batch: List):
        if not is_running():
            return

        logger.info(
            f"{TAG} 🔷 Starting show‑batch {batch_idx}/{len(show_batches)}: "
            f"{[name for name,_ in batch]}"
        )
        sem_show = asyncio.Semaphore(settings.concurrent_requests)

        async def _process_one_show(item):
            show_name, seasons = item
            if not is_running() or show_name in _skipped:
                return

            async with sem_show:
                logger.info(f"{TAG} ▶️ Processing show {show_name!r}")

                # a) Lookup & cache show metadata
                sample = next(iter(next(iter(seasons.values()))))
                mshow: Optional[TVShow] = await fetch_tv_details(group, show_name)
                if not is_running() or not mshow:
                    _skipped.add(show_name)
                    return

                # b) Threshold check
                passed = await asyncio.to_thread(filter_by_threshold, show_name, mshow)
                if not is_running() or not passed:
                    try:
                        await mark_skipped("TV", group, mshow, sample)
                        _skipped.add(show_name)
                        await asyncio.to_thread(shutil.rmtree, mshow.show_folder)
                        logger.info(f"{TAG} 🚫 Threshold filter failed for: {show_name}")
                        if mshow.show_folder.exists():
                            await asyncio.to_thread(safe_remove, mshow.show_folder)
                            logger.info(f"{TAG} ✂️ Removed path: {mshow.show_folder}")
                    except Exception as e:
                        logger.info(f"{TAG} Exception occurred: {e}")

                    return

                # c) Write show‑level NFO & artwork
                if settings.write_nfo:
                    await asyncio.to_thread(write_tvshow_nfo, sample, mshow)
                    asyncio.create_task(download_if_missing(TAG, sample, mshow))
                    if settings.update_tv_series_nfo:
                        return

                # d) Seasons & episode batches
                for season_num, eps in seasons.items():
                    if not is_running():
                        return
                    logger.info(
                        f"{TAG} 📅 Fetch season {show_name!r} "
                        f"S{season_num:02d} ({len(eps)} eps)"
                    )
                    season_meta: Optional[SeasonMeta] = await get_season_meta(eps[0], mshow)
                    if not is_running() or not season_meta:
                        logger.warning(f"{TAG} ❌ No metadata for {show_name!r} S{season_num:02d}")
                        continue

                    asyncio.create_task(download_if_missing(TAG, eps[0], season_meta))

                    ep_batches = list(chunked(eps, settings.batch_size))
                    for ep_idx, ep_batch in enumerate(ep_batches, start=1):
                        if not is_running():
                            return
                        logger.info(
                            f"{TAG} 🔸 Episode batch {ep_idx}/{len(ep_batches)} "
                            f"for {show_name!r} S{season_num:02d}"
                        )
                        sem_ep = asyncio.Semaphore(settings.concurrent_requests)

                        async def _process_one_ep(stream: DispatcharrStream):
                            if not is_running():
                                return
                            async with sem_ep:
                                if not is_running():
                                    return
                                if not reprocess and await is_skipped(stream.stream_type.name, stream.id):
                                    _skipped.add(stream.name)
                                    return

                                # write .strm
                                ep_meta = season_meta.episode_map.get(stream.episode)  # type: ignore
                                if not ep_meta:
                                    return
                                ep_meta.strm_path.parent.mkdir(parents=True, exist_ok=True)
                                ep_meta.strm_path.write_text(stream.proxy_url, encoding="utf-8")

                                # per‑episode NFO & artwork
                                if settings.write_nfo:
                                    await asyncio.to_thread(write_episode_nfo, stream, ep_meta)
                                    if ep_meta.still_path:
                                        asyncio.create_task(
                                            download_if_missing(TAG, stream, ep_meta)
                                        )

                                # subtitles
                                await download_subtitles_if_enabled(
                                    show_name,
                                    season_num,
                                    stream.episode,
                                    season_meta.season_folder,
                                    mshow,
                                )

                        await asyncio.gather(*(_process_one_ep(s) for s in ep_batch))
                        if not is_running():
                            return
                        await asyncio.sleep(settings.batch_delay_seconds)

                logger.info(f"{TAG} ✅ Finished show {show_name!r}")

        # launch this batch of shows
        await asyncio.gather(*(_process_one_show(item) for item in batch))
        if not is_running():
            return
        await asyncio.sleep(settings.batch_delay_seconds)

    # 4) Kick off all show‑batches in parallel
    await asyncio.gather(*(
        run_show_batch(idx, batch)
        for idx, batch in enumerate(show_batches, start=1)
    ))


async def reprocess_tv(skipped: SkippedStream) -> bool:
    try:
        streams = await fetch_streams(skipped["group"], skipped["stream_type"])
        if not is_running() or not streams:
            logger.error("Cannot reprocess TV %s: no streams", skipped["name"])
            return False

        await process_tv(streams, skipped["group"], True)
        logger.info("✅ Reprocessed TV show %s", skipped["name"])
        return True
    except Exception as e:
        logger.error("Error reprocessing TV %s: %s", skipped["name"], e, exc_info=True)
        return False
