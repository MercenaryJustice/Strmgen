
from dataclasses import dataclass
from datetime import datetime, timezone, timedelta
from typing import Optional, Dict, List, Any
from pathlib import Path
from pydantic import BaseModel

@dataclass
class DispatcharrStream:
    id: int
    name: str
    url: str
    m3u_account: int
    logo_url: str
    tvg_id: str
    local_file: Optional[Path]
    current_viewers: int
    updated_at: datetime
    stream_profile_id: Optional[int]
    is_custom: bool
    channel_group: int
    stream_hash: str

    @property
    def was_updated_today(self) -> bool:
        """
        Returns True if updated_at falls on “today” in UTC.
        """
        if not self.updated_at:
            return False
        # use timezone‐aware now()
        today_utc = datetime.now(timezone.utc).date() - timedelta(days=1)
        return self.updated_at.date() >= today_utc
    
    @classmethod
    def from_dict(cls, data: Dict[str, Optional[object]]) -> "DispatcharrStream":
        """
        Create a Stream instance from a raw dict, converting
        types for `local_file` and `updated_at`.
        """
        # Convert local_file to Path if present
        lf = data.get("local_file")
        local_file = Path(str(lf)) if lf else None

        # parse ISO8601 with Z suffix
        ts = data.get("updated_at")
        updated_at = None
        if ts:
            try:
                # try with microseconds
                updated_at = datetime.strptime(str(ts), "%Y-%m-%dT%H:%M:%S.%fZ")
            except ValueError:
                # fallback without microseconds
                updated_at = datetime.strptime(str(ts), "%Y-%m-%dT%H:%M:%SZ")

        return cls(
            id=data["id"],
            name=data["name"],
            url=data["url"],
            m3u_account=data["m3u_account"],
            logo_url=data["logo_url"],
            tvg_id=data.get("tvg_id", ""),
            local_file=local_file,
            current_viewers=data.get("current_viewers", 0),
            updated_at=updated_at,
            stream_profile_id=data.get("stream_profile_id"),
            is_custom=data.get("is_custom", False),
            channel_group=data.get("channel_group", 0),
            stream_hash=data["stream_hash"],
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
    genre_names: List[str]
    popularity: float
    first_air_date: str
    vote_average: float
    vote_count: int
    origin_country: List[str]
    external_ids: Dict[str, Any]
    raw: Dict[str, Any]

@dataclass
class SeasonMeta:
    id: int
    name: str
    overview: str
    air_date: str
    episodes: List[Dict[str, Any]]
    poster_path: Optional[str]
    season_number: int
    vote_average: float
    raw: Dict[str, Any]

@dataclass
class EpisodeMeta:
    air_date: str
    crew: List[Dict[str, Any]]
    episode_number: int
    guest_stars: List[Dict[str, Any]]
    name: str
    overview: str
    id: int
    production_code: str
    runtime: Optional[int]
    season_number: int
    still_path: Optional[str]
    vote_average: float
    vote_count: int
    raw: Dict[str, Any]    