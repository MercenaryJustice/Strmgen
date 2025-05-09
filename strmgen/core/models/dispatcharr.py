# strmgen/core/models/dispatcharr.py
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from typing import Optional, Dict, Any
from pathlib import Path

from strmgen.core.config import settings
from strmgen.core.string_utils import clean_name, fix_url_string
from strmgen.core.models.paths import MediaPaths
from strmgen.core.models.models import StreamInfo
from strmgen.core.models.enums import MediaType
from strmgen.core.models.regex import TITLE_YEAR_RE, RE_EPISODE_TAG

@dataclass
class DispatcharrStream:
    # ── Raw API fields ─────────────────────────────────────────────────────────
    id: int
    name: str                   # cleaned title/show (no trailing metadata)
    year: Optional[int]         # only for movies
    url: str
    m3u_account: int
    logo_url: str
    tvg_id: str
    local_file: Optional[Path]
    current_viewers: int
    updated_at: Optional[datetime]
    stream_profile_id: Optional[int]
    is_custom: bool
    channel_group: int
    channel_group_name: str
    stream_hash: str

    # ── Populated in from_dict ────────────────────────────────────────────────
    stream_type: MediaType            = field(repr=False)        # "movie" or "tv"
    season:  Optional[int]      = field(default=None, repr=False)
    episode: Optional[int]      = field(default=None, repr=False)

    # ── Computed paths ─────────────────────────────────────────────────────────
    base_path:     Path         = field(init=False, repr=False)
    strm_path:     Path         = field(init=False, repr=False)
    nfo_path:      Path         = field(init=False, repr=False)
    poster_path:   Path         = field(init=False, repr=False)
    backdrop_path: Path         = field(init=False, repr=False)

    def __post_init__(self):
        # pack into StreamInfo for easy reuse
        info = StreamInfo(
            group   = self.channel_group_name,
            title   = self.name,
            year    = self.year,
            season  = self.season,
            episode = self.episode,
        )

        if self.stream_type is MediaType.TV:
            # ── full‑episode if season+ep present
            if info.season is not None and info.episode is not None:
                self.base_path     = MediaPaths.season_folder(info)
                self.strm_path     = MediaPaths.episode_strm(info)
                self.nfo_path      = MediaPaths.episode_nfo(info)
                self.poster_path   = MediaPaths.episode_image(info)
                self.backdrop_path = MediaPaths.season_poster(info)

            # ── show‑level fallback (no per‑episode data)
            else:
                # logger.warning("[TV] missing SxxExx for: %s", info.title)
                self.base_path     = MediaPaths._base_folder(
                                        MediaType.TV,
                                        info.group,
                                        info.title,
                                        None
                                     )
                self.strm_path     = Path()
                self.nfo_path      = MediaPaths.show_nfo(info)
                self.poster_path   = MediaPaths.show_image(info, "poster.jpg")
                self.backdrop_path = MediaPaths.show_image(info, "fanart.jpg")

        else:
            # ── movie
            self.base_path     = MediaPaths._base_folder(
                                    MediaType.MOVIE,
                                    info.group,
                                    info.title,
                                    info.year
                                 )
            self.strm_path     = MediaPaths.movie_strm(info)
            self.nfo_path      = MediaPaths.movie_nfo(info)
            self.poster_path   = MediaPaths.movie_poster(info)
            self.backdrop_path = MediaPaths.movie_backdrop(info)

    def _recompute_paths(self):
        # re‑run exactly the same logic
        self.__post_init__()

    @property
    def proxy_url(self) -> str:
        # fall back to raw url if no hash
        if not self.stream_hash:
            return self.url
        url = f"{settings.api_base}/{settings.stream_base_url}/{self.stream_hash}"
        return fix_url_string(url)

    @property
    def stream_updated(self) -> bool:
        """
        Returns True if:
         - updated_at is set, AND
         - either:
           • settings.last_modified_days > 0 and updated_at is within that many days
           • settings.last_modified_days <= 0 and updated_at is today (UTC)
        """
        if not self.updated_at:
            return False

        now = datetime.now(timezone.utc)
        days = settings.last_modified_days

        if days and days > 0:
            # Within the last `days` days
            return (now - self.updated_at) <= timedelta(days=days)

        # Fallback to “today” if no positive window set
        return self.updated_at.date() == now.date()

    @classmethod
    def from_dict(
        cls,
        data: Dict[str, Any],
        channel_group_name: str,
        stream_type: MediaType
    ) -> Optional["DispatcharrStream"]:
        raw_name = str(data.get("name") or "")

        # ── parse movie title + year ──────────────────────────────────
        if stream_type is MediaType.MOVIE:
            m = TITLE_YEAR_RE.match(raw_name)
            if m:
                title = clean_name(m.group("title"))
                year  = int(m.group("year"))
            else:
                title = clean_name(raw_name)
                year  = None

            season = episode = None

        # ── parse TV show + SxxExx ────────────────────────────────────
        else:
            match = RE_EPISODE_TAG.match(raw_name)
            if not match:
                # logger.info("[TV] ❌ No SxxExx tag in '%s'", raw_name)
                return None

            raw_show, ss, ee = match.groups()
            title   = clean_name(raw_show)
            year    = None
            season  = int(ss)
            episode = int(ee)

        # ── common fields ──────────────────────────────────────────────
        url             = str(data.get("url") or "")
        m3u_account     = int(data.get("m3u_account") or 0)
        logo_url        = str(data.get("logo_url") or "")
        tvg_id          = str(data.get("tvg_id") or "")
        channel_group   = int(data.get("channel_group") or 0)
        stream_hash     = str(data.get("stream_hash") or "")
        local_file_val  = data.get("local_file")
        local_file      = Path(str(local_file_val)) if local_file_val else None

        ts = data.get("updated_at")
        updated_at = None
        if ts:
            for fmt in ("%Y-%m-%dT%H:%M:%S.%fZ", "%Y-%m-%dT%H:%M:%SZ"):
                try:
                    updated_at = datetime.strptime(str(ts), fmt)\
                                     .replace(tzinfo=timezone.utc)
                    break
                except ValueError:
                    continue

        return cls(
            id                  = int(data["id"]),
            name                = title,
            year                = year,
            url                 = url,
            m3u_account         = m3u_account,
            logo_url            = logo_url,
            tvg_id              = tvg_id,
            local_file          = local_file,
            current_viewers     = int(data.get("current_viewers") or 0),
            updated_at          = updated_at,
            stream_profile_id   = data.get("stream_profile_id"),
            is_custom           = bool(data.get("is_custom", False)),
            channel_group       = channel_group,
            channel_group_name  = channel_group_name,
            stream_hash         = stream_hash,
            stream_type         = stream_type,
            season              = season,
            episode             = episode,
        )

