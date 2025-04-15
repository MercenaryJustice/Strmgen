import logging
import re
from pathlib import Path
from typing import Dict, Optional

from config import settings
from tmdb_helpers import TVShow, SeasonMeta, EpisodeMeta, lookup_show, get_season_meta, get_episode_meta, download_if_missing
from subtitles import download_episode_subtitles
from utils import (
    filter_by_threshold,
    target_folder,
    write_if,
    write_tvshow_nfo,
    write_episode_nfo,
    clean_name
)
from streams import write_strm_file

logger = logging.getLogger(__name__)
RE_EPISODE_TAG = re.compile(r"(.+?)[ ._-][sS](\d{2})[eE](\d{2})")
_skipped_shows = set()

log_tag = "[TV] 🖼️"


class Paths:
    @staticmethod
    def show_nfo(folder: Path, show: str) -> Path:
        return folder / f"{show}.nfo"

    @staticmethod
    def show_image(folder: Path, filename: str) -> Path:
        return folder / filename

    @staticmethod
    def season_folder(root: Path, group: str, show: str, season: int) -> Path:
        season_dir = target_folder(root, "TV Shows", group, show) / f"Season {season:02}"
        # season_dir.mkdir(parents=True, exist_ok=True)
        return season_dir

    @staticmethod
    def season_poster(dest_folder: Path, season: int) -> Path:
        return dest_folder / f"Season {season:02}.tbn"

    @staticmethod
    def episode_strm(dest_folder: Path, show: str, season: int, ep: int) -> Path:
        base = f"{show} - S{season:02}E{ep:02}"
        return dest_folder / f"{base}.strm"

    @staticmethod
    def episode_nfo(dest_folder: Path, show: str, season: int, ep: int) -> Path:
        base = f"{show} - S{season:02}E{ep:02}"
        return dest_folder / f"{base}.nfo"

    @staticmethod
    def episode_image(dest_folder: Path, show: str, season: int, ep: int) -> Path:
        base = f"{show} - S{season:02}E{ep:02}"
        return dest_folder / f"{base}.jpg"


def write_assets(
    show: str,
    season: int,
    ep: int,
    show_folder: Path,
    season_folder: Path,
    strm_path: Path,
    mshow: Optional[TVShow],
    episode_meta: EpisodeMeta,
    sid: int,
    headers: Dict[str, str],
    url: str,
) -> bool:
    """Write .strm file, NFOs, and download images."""
    # Show-level NFO and images
    if mshow and settings.write_nfo:
        # Write the show NFO
        write_if(True, Paths.show_nfo(show_folder, mshow.name), write_tvshow_nfo, mshow.raw)

        # Download poster and backdrop (if missing)
        download_if_missing(
            log_tag,
            f"{mshow.name} poster",
            mshow.poster_path,
            Paths.show_image(show_folder, "poster.jpg"),
        )
        download_if_missing(
            log_tag,
            f"{mshow.name} backdrop",
            mshow.backdrop_path,
            Paths.show_image(show_folder, "fanart.jpg"),
        )

    # Season poster
    if mshow:
        season_meta = get_season_meta(mshow.id, season)
        download_if_missing(
            log_tag,
            f"{mshow.name} Season {season:02} poster",
            season_meta.poster_path if season_meta else None,
            Paths.season_poster(season_folder, season),
        )

    # Write .strm file
    if not write_strm_file(strm_path, sid, headers, url):
        logger.warning("[TV] ❌ Failed writing .strm for: %s", strm_path)
        return False

    # Episode NFO and still image
    if settings.write_nfo:
        ep_nfo = Paths.episode_nfo(season_folder, mshow.name if mshow else show, season, ep)
        write_if(True, ep_nfo, write_episode_nfo, episode_meta.raw)
        download_if_missing(
            log_tag,
            f"{mshow.name if mshow else show} S{season:02}E{ep:02} still",
            episode_meta.still_path,
            Paths.episode_image(season_folder, mshow.name if mshow else show, season, ep),
        )

    return True


def download_subtitles_if_enabled(
    show: str,
    season: int,
    ep: int,
    season_folder: Path,
    mshow: Optional[TVShow],
) -> None:
    """Download subtitles if the feature is enabled."""
    if settings.opensubtitles_download:
        logger.info("[SUB] 🔽 Downloading subtitles for: %s S%02dE%02d", show, season, ep)
        tmdb_id = (
            mshow.external_ids.get("imdb_id")
            if mshow and mshow.external_ids
            else None
        )
        download_episode_subtitles(
            show,
            season,
            ep,
            season_folder,
            tmdb_id=tmdb_id or (str(mshow.id) if mshow else None),
        )


def process_tv(
    name: str,
    sid: int,
    root: Path,
    group: str,
    headers: Dict[str, str],
    url: str,
) -> None:
    """
    Process a single TV episode entry:
      1. Parse SxxExx tag
      2. Lookup & cache TMDb metadata
      3. Filter by thresholds
      4. Write .strm, NFOs, images, and subtitles
    """
    match = RE_EPISODE_TAG.match(name)
    if not match:
        logger.info("[TV] ❌ No SxxExx pattern matched in: %s", name)
        return

    show = clean_name(match.group(1))
    season = int(match.group(2))
    ep = int(match.group(3))
    logger.info("[TV] 📺 Detected TV episode: %s S%02dE%02d", show, season, ep)

    if show in _skipped_shows:
        logger.info("[TV] ⏭️ Skipped show (cached): %s", show)
        return

    # Ensure metadata
    mshow = lookup_show(show)
    if not filter_by_threshold(_skipped_shows, name, mshow.raw if mshow else None):
        logger.info("[TV] 🚫 Show '%s' failed threshold filters", show)
        return

    # Prepare folders and paths
    show_folder = target_folder(root, "TV Shows", group, show)
    season_folder = Paths.season_folder(root, group, show, season)
    strm_path = Paths.episode_strm(season_folder, show, season, ep)

    # Fetch episode metadata
    episode_meta = None
    if mshow:
        episode_meta = get_episode_meta(mshow.id, season, ep)
    if not episode_meta:
        logger.warning("[TV] ❌ No metadata for episode: %s S%02dE%02d", show, season, ep)
        return

    if mshow.name.casefold() != show.casefold():
        mshow.name = show

    # Write assets and subtitles
    if write_assets(
        show,
        season,
        ep,
        show_folder,
        season_folder,
        strm_path,
        mshow,
        episode_meta,
        sid,
        headers,
        url,
    ):
        download_subtitles_if_enabled(show, season, ep, season_folder, mshow)
