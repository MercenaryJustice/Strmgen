# strmgen/core/config.py
import json
import re
from datetime import datetime
from functools import lru_cache
from pathlib import Path
from typing import List, Optional

from fastapi import FastAPI
from fastapi_utils.tasks import repeat_every
from pydantic import BaseModel, Field, field_validator

# ─── 1) Locate your JSON file ─────────────────────────────────────────────────
# Assumes this file lives at:  strmgen/core/config.py
# and your JSON lives at:        strmgen/core/config/config.json

BASE_DIR    = Path(__file__).parent           # .../strmgen/core
CONFIG_PATH = BASE_DIR / "config.json"


if not CONFIG_PATH.exists():
    raise FileNotFoundError(f"Cannot find config.json at {CONFIG_PATH!r}")

# ─── 2) Define your validated settings model ──────────────────────────────────
class Settings(BaseModel):
    # Authentication & API
    api_base:        str
    token_url:       str
    username:        str
    password:        str
    stream_base_url: str

    enable_testcontainers: bool = Field(
        False,
        description="Whether to use a PostgreSQL Docker container for testing",
    )
    database_url: str = "postgresql://strmgen:secret@192.168.86.33:5432/strmgen"
    db_user: str = "strmgen"
    db_pass: str = "secret"
    db_name: str = "strmgen"
    postgres_dsn: str = "postgresql://strmgen:secret@192.168.86.33:5432/strmgen"

    # Runtime tokens (populated later)
    access:  Optional[str]
    refresh: Optional[str]

    # Output & directories
    clean_output_dir: bool
    output_root:      str

    # Filtering
    process_movies_groups:    bool
    movies_groups:            List[str]
    movie_year_regex: str = Field(
        r"^(?P<title>.+?)[\s._-]*\((?P<year>\d{4})\)$",
        description="Regex to extract title and year from a filename",
    )    
    process_tv_series_groups: bool
    tv_series_episode_regex: str = Field(
        r"^(?P<title>.+?)[\s._-]*\((?P<year>\d{4})\)$",
        description="Regex to extract tv series season and episode from a filename",
    )    
    tv_series_groups:         List[str]
    process_groups_24_7:      bool
    groups_24_7:              List[str]
    remove_strings:           List[str]
    skip_stream_check:        bool
    update_stream_link:       bool
    only_updated_streams:     bool
    last_modified_days: int = 0

    # TMDb
    tmdb_api_key:         Optional[str]
    tmdb_language:        str
    tmdb_download_images: bool
    tmdb_image_size:      str
    tmdb_create_not_found: bool
    check_tmdb_thresholds: bool

    batch_size: int                = 20
    batch_delay_seconds: float     = 2.0
    concurrent_requests: int       = 5
    tmdb_rate_limit: int           = 40

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
    
    # Emby
    emby_api_url: Optional[str]
    emby_api_key:  Optional[str]
    emby_movie_library_id:   Optional[int]


    # ─── coerce blank-last_run into None ──────────────────────────────────────
    @field_validator("last_run", mode="before")
    @classmethod
    def _none_if_blank_last_run(cls, v: Optional[str]) -> Optional[str]:
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

    @property
    def MOVIE_TITLE_YEAR_RE(self) -> re.Pattern[str]:
        return re.compile(self.movie_year_regex)

    @property
    def TV_SERIES_EPIDOSE_RE(self) -> re.Pattern[str]:
        return re.compile(self.tv_series_episode_regex)

# ─── 3) Cached loader for settings ───────────────────────────────────────────
@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """
    Load and return the Settings instance from config.json, cached in-memory.
    Calling get_settings again returns the same object without re-reading disk.
    """
    with CONFIG_PATH.open(encoding="utf-8") as f:
        data = json.load(f)
    return Settings(**data)


def reload_settings() -> None:
    """
    Clear the cached Settings so that next get_settings() re-reads config.json.
    """
    get_settings.cache_clear()


def save_settings(cfg: Settings) -> None:
    """
    Persist the given Settings back to disk (config.json), then clear cache.
    """
    data = cfg.model_dump(mode="json")
    with CONFIG_PATH.open("w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
    get_settings.cache_clear()


def register_startup(app: FastAPI) -> None:
    # 1) Fetch tokens once at startup
    @app.on_event("startup")
    async def _initial_fetch() -> None:
        from strmgen.core.auth import get_access_token
        await get_access_token()
        
    # 2) Then refresh every 15 minutes, auto-cancelled on shutdown
    @app.on_event("startup")
    @repeat_every(seconds=15 * 60, raise_exceptions=True)
    async def _periodic_refresh() -> None:
        from strmgen.core.auth import get_access_token
        await get_access_token()
