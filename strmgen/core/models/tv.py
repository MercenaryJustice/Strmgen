# strmgen/core/models/tv.py
from dataclasses import dataclass, field
from typing import Optional, Dict, List, Any
from pathlib import Path

from strmgen.core.string_utils import clean_name
from strmgen.core.models.paths import MediaPaths
from strmgen.core.models.models import StreamInfo
from strmgen.core.models.enums import MediaType

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
            title   = clean_name(self.name),
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



@dataclass
class SeasonMeta:
    # — routing / grouping context —
    channel_group_name: str
    show:               str

    # — raw TMDb season fields —
    id:               int
    name:             str
    overview:         str
    air_date:         str
    raw_episodes:     List[Dict[str, Any]]
    poster_path:      Optional[str]
    season_number:    int
    vote_average:     float
    raw:              Dict[str, Any]

    # — computed folders & files —
    show_folder:       Path               = field(init=False, repr=False)
    season_folder:     Path               = field(init=False, repr=False)
    poster_local_path: Path               = field(init=False, repr=False)

    # ── NEW: map ep# → EpisodeMeta ──
    episode_map:       Dict[int, EpisodeMeta] = field(init=False, repr=False)

    def __post_init__(self):
        # build your existing folders
        info = StreamInfo(
            group   = self.channel_group_name,
            title   = self.show,
            year    = None,
            season  = self.season_number,
            episode = None,
        )
        self.show_folder       = MediaPaths._base_folder(
            MediaType.TV,
            self.channel_group_name,
            self.show,
            None
        )
        self.season_folder     = MediaPaths.season_folder(info)
        self.poster_local_path = MediaPaths.season_poster(info)

        # ── now build the episode_map from raw_episodes ──
        self.episode_map = {}
        for e in self.raw_episodes:
            ep_num = e.get("episode_number")
            # instantiate an EpisodeMeta for each raw dict
            self.episode_map[ep_num] = EpisodeMeta(
                group           = self.channel_group_name,
                show            = self.show,
                air_date        = e.get("air_date", ""),
                crew            = e.get("crew", []),
                episode_number  = ep_num,
                guest_stars     = e.get("guest_stars", []),
                name            = e.get("name", ""),
                overview        = e.get("overview", ""),
                id              = e.get("id", 0),
                production_code = e.get("production_code", ""),
                runtime         = e.get("runtime"),
                season_number   = self.season_number,
                still_path      = e.get("still_path"),
                vote_average    = e.get("vote_average", 0.0),
                vote_count      = e.get("vote_count", 0),
                raw             = e,
            )

    def _recompute_paths(self) -> None:
        # rerun same logic
        self.__post_init__()
