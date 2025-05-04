
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from ..core.config import settings
from typing import Optional, Dict, List, Any
from pathlib import Path
from pydantic import BaseModel, root_validator
from ..core.fs_utils import clean_name

TITLE_YEAR_RE = re.compile(r"^(.*)\s+\((\d{4})\)$")

@dataclass
class DispatcharrStream:
    id: int
    name: str                # cleaned title (no trailing year)
    year: Optional[int]      # parsed from raw name, if present
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
    stream_hash: str
    channel_group_name: str
    stream_type: Optional[str] = field(default=None, repr=False)

    proxy_url: Optional[str] = field(default=None, repr=False)
    
    # ← new, computed paths (no need to pass these in)
    base_path: Path     = field(init=False, repr=False)
    strm_path: Path     = field(init=False, repr=False)
    nfo_path: Path      = field(init=False, repr=False)
    poster_path: Path   = field(init=False, repr=False)
    backdrop_path: Path = field(init=False, repr=False)

    def __post_init__(self):
        # 1) ensure the movie folder exists & get its Path
        self.base_path = MoviePaths.base_folder(
            self.channel_group_name,
            self.name,
            self.year,
        )

        # 2) assign all the common file paths
        self.strm_path     = MoviePaths.strm_path(self.channel_group_name, self.name, self.year)
        self.nfo_path      = MoviePaths.nfo_path(self.channel_group_name, self.name, self.year)
        self.poster_path   = MoviePaths.poster_path(self)   # tmdb arg unused in your implementation
        self.backdrop_path = MoviePaths.backdrop_path(self) # same here

    def _recompute_paths(self):
        self.base_path     = MoviePaths.base_folder(self.channel_group_name, self.name, self.year)
        self.strm_path     = MoviePaths.strm_path(self.channel_group_name, self.name, self.year)
        self.nfo_path      = MoviePaths.nfo_path(self.channel_group_name, self.name, self.year)
        self.poster_path   = MoviePaths.poster_path(self)
        self.backdrop_path = MoviePaths.backdrop_path(self)

    @property
    def proxy_url1(self) -> str:
        if not self.stream_hash:
            return self.url
        return f"{settings.api_base}{settings.stream_base_url}{self.stream_hash}"

    @property
    def was_updated_today(self) -> bool:
        if not self.updated_at:
            return False
        return self.updated_at.date() == datetime.now(timezone.utc).date()

    @classmethod
    def from_dict(cls, data: Dict[str, Any], channel_group_name: str) -> "DispatcharrStream":
        # 1) coerce to str so raw_name is really a str
        raw_name = str(data.get("name") or "")
        m = TITLE_YEAR_RE.match(raw_name)
        if m:
            raw_title, raw_year = m.groups()
            title = clean_name(raw_title)
            year  = int(raw_year)
        else:
            title = clean_name(raw_name)
            year  = None

        # 2) coerce all the other fields up front
        url                  = str(data.get("url") or "")
        m3u_account          = int(data.get("m3u_account") or 0)
        logo_url             = str(data.get("logo_url") or "")
        tvg_id               = str(data.get("tvg_id") or "")
        channel_group        = int(data.get("channel_group") or 0)
        stream_hash          = str(data.get("stream_hash") or "")
        stream_type          = (str(data.get("stream_type"))
                                if data.get("stream_type") is not None
                                else None)
        local_file_val       = data.get("local_file")
        local_file           = Path(str(local_file_val)) if local_file_val else None

        # parse updated_at…
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

        # build the proxy_url
        proxy_url = (
            f"{settings.api_base}{settings.stream_base_url}{stream_hash}"
            if stream_hash else None
        )

        return cls(
            id                 = int(data["id"]),
            name               = title,
            year               = year,
            url                = url,
            m3u_account        = m3u_account,
            logo_url           = logo_url,
            tvg_id             = tvg_id,
            local_file         = local_file,
            current_viewers    = int(data.get("current_viewers") or 0),
            updated_at         = updated_at,
            stream_profile_id  = data.get("stream_profile_id"),
            is_custom          = bool(data.get("is_custom", False)),
            channel_group      = channel_group,
            channel_group_name = channel_group_name,
            stream_hash        = stream_hash,
            stream_type        = stream_type,
            proxy_url          = proxy_url,
        )






class Stream(BaseModel):
    id: int
    name: str
    url: str
    m3u_account: int
    logo_url: Optional[str]
    tvg_id: Optional[str]
    local_file: Optional[str]
    current_viewers: int
    updated_at: datetime
    stream_profile_id: Optional[int]
    is_custom: bool
    channel_group: int
    stream_hash: str

    proxy_url: Optional[str]

    @root_validator(pre=True)
    def compute_proxy_url(cls, values):
        # grab the raw hash (or empty string)
        sh = values.get("stream_hash") or ""
        if sh:
            api = settings.api_base.rstrip("/")
            path = settings.stream_base_url.lstrip("/")
            values["proxy_url"] = f"{api}/{path}/{sh}"
        else:
            # fall back to the original URL
            values["proxy_url"] = values.get("url", "")
        return values

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
    genre_ids: List[int]
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
    genre_names: List[str] = field(default_factory=list)

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
    channel_group_name: str                  # e.g. "Action", "Premium"
    
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
    show_folder: Path             = field(init=False, repr=False)
    show_nfo_path: Path           = field(init=False, repr=False)
    poster_local_path: Path       = field(init=False, repr=False)
    backdrop_local_path: Path     = field(init=False, repr=False)

    def __post_init__(self):
        # 1) ensure the base show folder exists
        self.show_folder = TVPaths.show_folder(self.channel_group_name, self.name)

        # 2) path to the show-level .nfo
        self.show_nfo_path = TVPaths.show_nfo(self.channel_group_name, self.name)

        # 3) local filenames for poster & fanart
        #    (download into these)
        self.poster_local_path   = TVPaths.show_image(self.channel_group_name, self.name, "poster.jpg")
        self.backdrop_local_path = TVPaths.show_image(self.channel_group_name, self.name, "fanart.jpg")

    def _recompute_paths(self) -> None:
        # 1) ensure the base show folder exists
        self.show_folder = TVPaths.show_folder(self.channel_group_name, self.name)
        # 2) path to the show-level .nfo
        self.show_nfo_path = TVPaths.show_nfo(self.channel_group_name, self.name)
        # 3) local filenames for poster & fanart
        self.poster_local_path   = TVPaths.show_image(self.channel_group_name, self.name, "poster.jpg")
        self.backdrop_local_path = TVPaths.show_image(self.channel_group_name, self.name, "fanart.jpg")

@dataclass
class SeasonMeta:
    # — routing / grouping context —
    channel_group_name: str                   # e.g. "Action", "Premium"
    show: str                    # cleaned‐up show title, e.g. "The Great Show"

    # — TMDb season fields —
    id: int
    name: str
    overview: str
    air_date: str
    episodes: List[Dict[str, Any]]
    poster_path: Optional[str]
    season_number: int
    vote_average: float
    raw: Dict[str, Any]

    # — computed folders & files —
    show_folder: Path           = field(init=False, repr=False)
    season_folder: Path         = field(init=False, repr=False)
    poster_local_path: Path     = field(init=False, repr=False)

    def __post_init__(self):
        # ensure …/TV Shows/<group>/<show>/ exists
        self.show_folder = TVPaths.show_folder(self.channel_group_name, self.show)

        # ensure …/TV Shows/<group>/<show>/Season XX/ exists
        self.season_folder = TVPaths.season_folder(
            self.channel_group_name,
            self.show,
            self.season_number
        )

        # local path where the season poster (Season XX.tbn) should live
        self.poster_local_path = TVPaths.season_poster(
            self.season_folder,
            self.season_number
        )

    def _recompute_paths(self) -> None:
        # show folder …/TV Shows/<group>/<show>/
        self.show_folder = TVPaths.show_folder(self.channel_group_name, self.show)
        # season folder …/TV Shows/<group>/<show>/Season XX/
        self.season_folder = TVPaths.season_folder(
            self.channel_group_name,
            self.show,
            self.season_number
        )
        # poster …/Season XX/Season XX.tbn
        self.poster_local_path = TVPaths.season_poster(
            self.season_folder,
            self.season_number
        )

@dataclass
class EpisodeMeta:
    #––– identity & context –––
    group: str                   # e.g. “Action”, “Premium”
    show: str                    # cleaned‐up show title, e.g. “The Great Show”

    #––– TMDb fields –––
    air_date: str
    crew: List[Dict[str, Any]]
    episode_number: int
    guest_stars: List[Dict[str, Any]]
    name: str                    # episode title
    overview: str
    id: int
    production_code: str
    runtime: Optional[int]
    season_number: int
    still_path: Optional[str]
    vote_average: float
    vote_count: int
    raw: Dict[str, Any]

    #––– computed paths (init=False so you don’t pass them in) –––
    show_folder: Path     = field(init=False, repr=False)
    season_folder: Path   = field(init=False, repr=False)
    strm_path: Path       = field(init=False, repr=False)
    nfo_path: Path        = field(init=False, repr=False)
    image_path: Path      = field(init=False, repr=False)

    def __post_init__(self):
        # 1) base show folder …/TV Shows/<group>/<show>/
        self.show_folder = TVPaths.show_folder(self.group, self.show)

        # 2) season folder …/TV Shows/<group>/<show>/Season XX/
        self.season_folder = TVPaths.season_folder(
            self.group,
            self.show,
            self.season_number
        )

        # 3) paths inside that season
        self.strm_path  = TVPaths.episode_strm(
            self.season_folder,
            self.show,
            self.season_number,
            self.episode_number
        )
        self.nfo_path   = TVPaths.episode_nfo(
            self.season_folder,
            self.show,
            self.season_number,
            self.episode_number
        )
        self.image_path = TVPaths.episode_image(
            self.season_folder,
            self.show,
            self.season_number,
            self.episode_number
        ) 
    def _recompute_paths(self) -> None:
        # …/TV Shows/<group>/<show>/
        self.show_folder = TVPaths.show_folder(self.group, self.show)

        # …/TV Shows/<group>/<show>/Season XX/
        self.season_folder = TVPaths.season_folder(
            self.group,
            self.show,
            self.season_number
        )

        # episode paths under that season
        self.strm_path  = TVPaths.episode_strm(
            self.season_folder,
            self.show,
            self.season_number,
            self.episode_number
        )
        self.nfo_path   = TVPaths.episode_nfo(
            self.season_folder,
            self.show,
            self.season_number,
            self.episode_number
        )
        self.image_path = TVPaths.episode_image(
            self.season_folder,
            self.show,
            self.season_number,
            self.episode_number
        )

class MoviePaths:
    # Base root for all movie content
    BASE_ROOT = Path(settings.output_root) / "Movies"

    @staticmethod
    def _ensure(path: Path) -> Path:
        path.mkdir(parents=True, exist_ok=True)
        return path

    @classmethod
    def base_folder(cls, group: str, title: str, year: Optional[int]) -> Path:
        """
        e.g. …/Movies/<group>/<title> (YYYY)/
        """
        folder_name = f"{title} ({year})" if year is not None else title
        folder = cls.BASE_ROOT / group / folder_name
        return folder

    @classmethod
    def strm_path(cls, group: str, title: str, year: Optional[int]) -> Path:
        """
        e.g. …/Movies/<group>/<folder_name>/<title>.strm
        """
        folder = cls.base_folder(group, title, year)
        return folder / f"{title}.strm"

    @classmethod
    def nfo_path(cls, group: str, title: str, year: Optional[int]) -> Path:
        """
        e.g. …/Movies/<group>/<folder_name>/<title>.nfo
        """
        folder = cls.base_folder(group, title, year)
        return folder / f"{title}.nfo"

    @classmethod
    def poster_path(cls, stream: DispatcharrStream) -> Path:
        """
        e.g. …/Movies/<group>/<folder_name>/poster.jpg
        """
        folder = cls.base_folder(stream.channel_group_name, stream.name, stream.year)
        return folder / "poster.jpg"

    @classmethod
    def backdrop_path(cls, stream: DispatcharrStream) -> Path:
        """
        e.g. …/Movies/<group>/<folder_name>/fanart.jpg
        """
        folder = cls.base_folder(stream.channel_group_name, stream.name, stream.year)
        return folder / "fanart.jpg"
    

class TVPaths:
    # Base root for all TV content
    BASE_ROOT = Path(settings.output_root) / "TV Shows"

    @staticmethod
    def _ensure(path: Path) -> Path:
        path.mkdir(parents=True, exist_ok=True)
        return path

    @classmethod
    def show_folder(cls, group: str, show: str) -> Path:
        """
        e.g. …/TV Shows/<group>/<show>/
        """
        folder = cls.BASE_ROOT / group / show
        return cls._ensure(folder)

    @classmethod
    def show_nfo(cls, group: str, show: str) -> Path:
        """
        e.g. …/TV Shows/<group>/<show>/<show>.nfo
        """
        folder = cls.show_folder(group, show)
        return folder / f"{show}.nfo"

    @classmethod
    def show_image(cls, group: str, show: str, filename: str) -> Path:
        """
        e.g. …/TV Shows/<group>/<show>/<filename>
        """
        return cls.show_folder(group, show) / filename

    @classmethod
    def season_folder(cls, group: str, show: str, season: int) -> Path:
        """
        e.g. …/TV Shows/<group>/<show>/Season 01/
        """
        folder = cls.show_folder(group, show) / f"Season {season:02d}"
        return cls._ensure(folder)

    @staticmethod
    def season_poster(season_folder: Path, season: int) -> Path:
        """
        e.g. …/Season 01/Season 01.tbn
        """
        return season_folder / f"Season {season:02d}.tbn"

    @staticmethod
    def episode_strm(season_folder: Path, show: str, season: int, ep: int) -> Path:
        """
        e.g. …/Season 01/<Show> - S01E01.strm
        """
        base = f"{show} - S{season:02d}E{ep:02d}"
        return season_folder / f"{base}.strm"

    @staticmethod
    def episode_nfo(season_folder: Path, show: str, season: int, ep: int) -> Path:
        """
        e.g. …/Season 01/<Show> - S01E01.nfo
        """
        base = f"{show} - S{season:02d}E{ep:02d}"
        return season_folder / f"{base}.nfo"

    @staticmethod
    def episode_image(season_folder: Path, show: str, season: int, ep: int) -> Path:
        """
        e.g. …/Season 01/<Show> - S01E01.jpg
        """
        base = f"{show} - S{season:02d}E{ep:02d}"
        return season_folder / f"{base}.jpg"   
    
    