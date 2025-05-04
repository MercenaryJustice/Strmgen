
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from typing import Optional, Dict, List, Any, NamedTuple
from enum import Enum
from pathlib import Path
from pydantic import BaseModel, root_validator

from ..core.config import settings
from ..core.fs_utils import clean_name, fix_url_string

TITLE_YEAR_RE = re.compile(
    r"""
    ^\s*                                 # leading whitespace   
    (?P<title>.+?)                       # minimally grab the title  
    [\s\.\-_]*                           # optional separators  
    (?:\(|\[)?                           # optional opening ( or [
    (?P<year>(?:19|20)\d{2})             # capture a 4‑digit year 1900–2099
    (?:\)|\])?                           # optional closing ) or ]
    \s*$                                 # trailing whitespace to end
    """,
    re.VERBOSE,
)
RE_EPISODE_TAG = settings.TV_SERIES_EPIDOSE_RE

class MediaType(Enum):
    MOVIE = "Movies"
    TV   = "TV Shows"
    _24_7   = "24-7"

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



@dataclass
class Movie:
    id: int
    title: str
    original_title: str
    overview: str
    poster_path: Optional[str]
    backdrop_path: Optional[str]
    release_date: str
    adult: bool
    original_language: str
    genre_ids: Dict[str, Any]
    popularity: float
    video: bool
    vote_average: float
    vote_count: int
    alternative_titles: Dict[str, Any]
    changes: Dict[str, Any]
    credits: Dict[str, Any]
    external_ids: Dict[str, Any]
    images: Dict[str, Any]
    keywords: Dict[str, Any]
    lists: Dict[str, Any]
    recommendations: Dict[str, Any]
    release_dates: Dict[str, Any]
    reviews: Dict[str, Any]
    similar: Dict[str, Any]
    translations: Dict[str, Any]
    videos: Dict[str, Any]
    watch_providers: Dict[str, Any]
    raw: Dict[str, Any]

    @property
    def year(self) -> Optional[int]:
        if not self.release_date or len(self.release_date) < 4:
            return None
        try:
            return int(self.release_date[:4])
        except ValueError:
            return None

@dataclass
class TVShow:
    # — your routing/group context —
    channel_group_name: str                # e.g. "Action", "Premium"

    # — the TMDb fields you already have —
    id: int
    name: str
    original_name: str
    overview: str
    poster_path: Optional[str]
    backdrop_path: Optional[str]
    media_type: str
    adult: bool
    original_language: str
    genre_ids: List[int]
    popularity: float
    first_air_date: str
    vote_average: float
    vote_count: int
    origin_country: List[str]
    external_ids: Dict[str, Any]
    raw: Dict[str, Any]
    genre_names: List[str] = field(default_factory=list)

    # — computed paths (init=False so you don’t pass them in) —
    show_folder:         Path = field(init=False, repr=False)
    show_nfo_path:       Path = field(init=False, repr=False)
    poster_local_path:   Path = field(init=False, repr=False)
    backdrop_local_path: Path = field(init=False, repr=False)

    def __post_init__(self):
        # pack into a minimal StreamInfo
        info = StreamInfo(
            group   = self.channel_group_name,
            title   = self.name,
            # movies use .year, tv doesn’t need it
            year    = None,
            season  = None,
            episode = None,
        )

        # 1) ensure the base show folder exists
        #    …/TV Shows/<group>/<show>/
        self.show_folder = MediaPaths._base_folder(
            MediaType.TV,
            info.group,
            info.title,
            None
        )

        # 2) path to the show‐level .nfo
        #    …/TV Shows/<group>/<show>/<show>.nfo
        self.show_nfo_path = MediaPaths.show_nfo(
            info
        )

        # 3) local filenames for poster & fanart
        #    …/TV Shows/<group>/<show>/poster.jpg
        #    …/TV Shows/<group>/<show>/fanart.jpg
        self.poster_local_path   = MediaPaths.show_image(
            info, "poster.jpg"
        )
        self.backdrop_local_path = MediaPaths.show_image(
            info, "fanart.jpg"
        )

    def _recompute_paths(self) -> None:
        # same logic again
        self.__post_init__()

@dataclass
class SeasonMeta:
    # — routing / grouping context —
    channel_group_name: str                # e.g. "Action", "Premium"
    show:               str                # cleaned‐up show title, e.g. "The Great Show"

    # — TMDb season fields —
    id:               int
    name:             str
    overview:         str
    air_date:         str
    episodes:         List[Dict[str, Any]]
    poster_path:      Optional[str]
    season_number:    int
    vote_average:     float
    raw:              Dict[str, Any]

    # — computed folders & files —
    show_folder:       Path = field(init=False, repr=False)
    season_folder:     Path = field(init=False, repr=False)
    poster_local_path: Path = field(init=False, repr=False)

    def __post_init__(self):
        # pack into StreamInfo
        info = StreamInfo(
            group   = self.channel_group_name,
            title   = self.show,
            year    = None,
            season  = self.season_number,
            episode = None,
        )

        # ensure …/TV Shows/<group>/<show>/ exists
        self.show_folder = MediaPaths._base_folder(
            MediaType.TV,
            self.channel_group_name,
            self.show,
            None
        )

        # ensure …/TV Shows/<group>/<show>/Season XX/ exists
        self.season_folder = MediaPaths.season_folder(info)

        # local path where the season poster (Season XX.tbn) should live
        self.poster_local_path = MediaPaths.season_poster(info)

    def _recompute_paths(self) -> None:
        # rerun same logic
        self.__post_init__()

@dataclass
class EpisodeMeta:
    #––– identity & context –––
    group:               str                # e.g. “Action”, “Premium”
    show:                str                # cleaned‐up show title, e.g. “The Great Show”

    #––– TMDb fields –––
    air_date:            str
    crew:                List[Dict[str, Any]]
    episode_number:      int
    guest_stars:         List[Dict[str, Any]]
    name:                str                # episode title
    overview:            str
    id:                  int
    production_code:     str
    runtime:             Optional[int]
    season_number:       int
    still_path:          Optional[str]
    vote_average:        float
    vote_count:          int
    raw:                 Dict[str, Any]

    #––– computed paths (init=False so you don’t pass them in) –––
    show_folder:         Path               = field(init=False, repr=False)
    season_folder:       Path               = field(init=False, repr=False)
    strm_path:           Path               = field(init=False, repr=False)
    nfo_path:            Path               = field(init=False, repr=False)
    image_path:          Path               = field(init=False, repr=False)

    def __post_init__(self):
        # build a StreamInfo for this episode
        info = StreamInfo(
            group   = self.group,
            title   = self.show,
            year    = None,
            season  = self.season_number,
            episode = self.episode_number,
        )

        # 1) base show folder …/TV Shows/<group>/<show>/
        self.show_folder = MediaPaths._base_folder(
            MediaType.TV,
            info.group,
            info.title,
            None
        )

        # 2) season folder …/TV Shows/<group>/<show>/Season XX/
        self.season_folder = MediaPaths.season_folder(info)

        # 3) episode paths under that season
        self.strm_path   = MediaPaths.episode_strm(info)
        self.nfo_path    = MediaPaths.episode_nfo(info)
        self.image_path  = MediaPaths.episode_image(info)

    def _recompute_paths(self) -> None:
        # just re‑run the same logic
        self.__post_init__()



class StreamInfo(NamedTuple):
    group: str
    title: str
    year: Optional[int] = None
    season: Optional[int] = None
    episode: Optional[int] = None

class MediaPaths:
    ROOT = Path(settings.output_root)

    @classmethod
    def _ensure(cls, p: Path) -> Path:
        p.mkdir(parents=True, exist_ok=True)
        return p

    @classmethod
    def _base_folder(
        cls,
        media_type: MediaType,
        group: str,
        title: str,
        year: Optional[int] = None
    ) -> Path:
        """
        e.g. …/<media_type>/<group>/<title> (YYYY)   (for movies)
             …/<media_type>/<group>/<show>            (for TV)
        """
        if media_type is MediaType.MOVIE:
            folder_name = f"{title} ({year})" if year else title
        else:
            folder_name = title

        return cls.ROOT / media_type.value / group / folder_name
        # return cls._ensure(folder)

    @classmethod
    def _file_path(
        cls,
        media_type: MediaType,
        group: str,
        title: str,
        year: Optional[int],
        filename: str
    ) -> Path:
        base = cls._base_folder(media_type, group, title, year)
        return base / filename

    # ── Movie helpers ────────────────────────────────────────────────────────────

    @classmethod
    def movie_strm(cls, stream: StreamInfo) -> Path:
        fn = f"{stream.title}.strm"
        return cls._file_path(MediaType.MOVIE, stream.group, stream.title, stream.year, fn)

    @classmethod
    def movie_nfo(cls, stream: StreamInfo) -> Path:
        fn = f"{stream.title}.nfo"
        return cls._file_path(MediaType.MOVIE, stream.group, stream.title, stream.year, fn)

    @classmethod
    def movie_poster(cls, stream: StreamInfo) -> Path:
        return cls._file_path(MediaType.MOVIE, stream.group, stream.title, stream.year, "poster.jpg")

    @classmethod
    def movie_backdrop(cls, stream: StreamInfo) -> Path:
        return cls._file_path(MediaType.MOVIE, stream.group, stream.title, stream.year, "fanart.jpg")

    # ── TV‑show helpers ───────────────────────────────────────────────────────────

    @classmethod
    def show_nfo(cls, stream: StreamInfo) -> Path:
        fn = f"{stream.title}.nfo"
        return cls._file_path(MediaType.TV, stream.group, stream.title, None, fn)

    @classmethod
    def show_image(cls, stream: StreamInfo, filename: str) -> Path:
        return cls._file_path(MediaType.TV, stream.group, stream.title, None, filename)

    @classmethod
    def season_folder(cls, stream: StreamInfo) -> Path:
        assert stream.season is not None, "season required"
        base = cls._base_folder(MediaType.TV, stream.group, stream.title, None)
        return base / f"Season {stream.season:02d}"
        # return cls._ensure(sf)

    @classmethod
    def season_poster(cls, stream: StreamInfo) -> Path:
        sf = cls.season_folder(stream)
        return sf / f"Season {stream.season:02d}.tbn"

    @classmethod
    def episode_strm(cls, stream: StreamInfo) -> Path:
        assert stream.season is not None and stream.episode is not None
        sf = cls.season_folder(stream)
        base = f"{stream.title} - S{stream.season:02d}E{stream.episode:02d}"
        return sf / f"{base}.strm"

    @classmethod
    def episode_nfo(cls, stream: StreamInfo) -> Path:
        sf = cls.season_folder(stream)
        base = f"{stream.title} - S{stream.season:02d}E{stream.episode:02d}"
        return sf / f"{base}.nfo"

    @classmethod
    def episode_image(cls, stream: StreamInfo) -> Path:
        sf = cls.season_folder(stream)
        base = f"{stream.title} - S{stream.season:02d}E{stream.episode:02d}"
        return sf / f"{base}.jpg"    
    