import json
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional, Dict, Any


from pydantic import BaseModel, Field, field_validator


# ─── 1) Locate your JSON file ─────────────────────────────────────────────────
# Assumes this file lives at:  strmgen/strmgen/config.py
# and your JSON lives at:        strmgen/strmgen/config/config.json

BASE_DIR    = Path(__file__).parent           # .../strmgen/strmgen
CONFIG_PATH = BASE_DIR / "config" / "config.json"

if not CONFIG_PATH.exists():
    raise FileNotFoundError(f"Cannot find config.json at {CONFIG_PATH!r}")

# ─── 2) Load JSON once ─────────────────────────────────────────────────────────
with CONFIG_PATH.open(encoding="utf-8") as f:
    _json_cfg = json.load(f)


# ─── 3) Define your validated settings model ──────────────────────────────────
class Settings(BaseModel):
    # Authentication & API
    api_base:        str
    token_url:       str
    username:        str
    password:        str
    stream_base_url: str

    # Output & directories
    clean_output_dir: bool
    output_root:      Path

    # Filtering
    process_movies_groups:    bool
    movies_groups:            List[str]
    process_tv_series_groups: bool
    tv_series_groups:         List[str]
    process_groups_24_7:      bool
    groups_24_7:              List[str]
    remove_strings:           List[str]
    skip_stream_check:        bool
    update_stream_link:       bool
    only_updated_streams:     bool

    # Runtime tokens (populated later)
    access:  Optional[str]
    refresh: Optional[str]

    # TMDb
    tmdb_api_key:         Optional[str]
    tmdb_language:        str
    tmdb_download_images: bool
    tmdb_image_size:      str
    tmdb_create_not_found: bool
    check_tmdb_thresholds: bool

    minimum_year:           int
    minimum_tmdb_rating:    float
    minimum_tmdb_votes:     int
    minimum_tmdb_popularity: float

    # NFO options
    write_nfo:                    bool
    write_nfo_only_if_not_exists: bool
    update_tv_series_nfo:       bool
    
    # Subtitles
    opensubtitles_download: bool
    opensubtitles_app_name:  Optional[str]
    opensubtitles_api_key:   Optional[str]
    opensubtitles_username:  Optional[str]
    opensubtitles_password:  Optional[str]


    # ─── In-memory caches ───────────────────────────────────────────────────────
    tmdb_show_cache:    Dict[str, Any] = Field(default_factory=dict)
    tmdb_season_cache:  Dict[str, Any] = Field(default_factory=dict)
    tmdb_episode_cache: Dict[str, Any] = Field(default_factory=dict)
    tmdb_movie_cache:   Dict[str, Any] = Field(default_factory=dict)

    # ─── coerce blank-last_run into None ──────────────────────────────────────
    @field_validator("last_run", mode="before")
    @classmethod
    def _none_if_blank_last_run(cls, v):
        if isinstance(v, str) and not v.strip():
            return None
        return v
    
    # ─── Scheduled Task Settings ───────────────────────────────────────────────
    enable_scheduled_task: bool = Field(
        True,
        description="Whether the daily scheduled run is enabled",
    )
    scheduled_hour:        int  = Field(
        2,
        ge=0, le=23,
        description="Hour of day (0–23) to trigger the scheduled run",
    )
    scheduled_minute:      int  = Field(
        0,
        ge=0, le=59,
        description="Minute of hour (0–59) to trigger the scheduled run",
    )
    last_run: Optional[datetime] = Field(
        None,
        description="ISO timestamp of the last run (UTC)",
    )


# ─── 4) Instantiate from your JSON ────────────────────────────────────────────
settings = Settings(**_json_cfg)