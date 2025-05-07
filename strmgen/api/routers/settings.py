# strmgen/api/routers/settings.py

import json
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from strmgen.core.config import settings, CONFIG_PATH
from strmgen.core.auth import get_access_token

router = APIRouter(tags=["Settings"])

# --- Pydantic models for I/O ----------------------------------------------

class SettingsOut(BaseModel):
    api_base: str
    token_url: str
    access: Optional[str] = None
    refresh: Optional[str] = None

    username: str
    password: str

    stream_base_url: str
    skip_stream_check: bool
    only_updated_streams: bool
    last_modified_days: int
    update_stream_link: bool

    output_root: str
    clean_output_dir: bool

    process_movies_groups: bool
    movies_groups: list[str]
    process_tv_series_groups: bool
    tv_series_groups: list[str]
    process_groups_24_7: bool
    groups_24_7: list[str]
    remove_strings: list[str]

    batch_size: int 
    batch_delay_seconds: float
    concurrent_requests: int
    tmdb_rate_limit: int 

    movie_year_regex: str
    tv_series_episode_regex: str

    tmdb_api_key: Optional[str] = None
    tmdb_language: str
    tmdb_download_images: bool
    tmdb_image_size: str
    tmdb_create_not_found: bool
    minimum_year: int
    check_tmdb_thresholds: bool
    minimum_tmdb_rating: float
    minimum_tmdb_votes: int
    minimum_tmdb_popularity: float

    write_nfo: bool
    write_nfo_only_if_not_exists: bool
    update_tv_series_nfo: bool

    opensubtitles_download: bool
    opensubtitles_app_name: Optional[str] = None
    opensubtitles_api_key: Optional[str] = None
    opensubtitles_username: Optional[str] = None
    opensubtitles_password: Optional[str] = None

    enable_scheduled_task: bool
    scheduled_hour: int
    scheduled_minute: int


class SettingsIn(BaseModel):
    api_base: str
    token_url: str
    access: Optional[str] = None
    refresh: Optional[str] = None

    username: str
    password: str

    stream_base_url: str
    skip_stream_check: bool
    only_updated_streams: bool
    last_modified_days: int
    update_stream_link: bool

    output_root: str
    clean_output_dir: bool

    process_movies_groups: bool
    movies_groups: list[str]
    process_tv_series_groups: bool
    tv_series_groups: list[str]
    process_groups_24_7: bool
    groups_24_7: list[str]
    remove_strings: list[str]

    batch_size: int 
    batch_delay_seconds: float
    concurrent_requests: int
    tmdb_rate_limit: int 

    movie_year_regex: str
    tv_series_episode_regex: str

    tmdb_api_key: Optional[str] = None
    tmdb_language: str
    tmdb_download_images: bool
    tmdb_image_size: str
    tmdb_create_not_found: bool
    minimum_year: int
    check_tmdb_thresholds: bool
    minimum_tmdb_rating: float
    minimum_tmdb_votes: int
    minimum_tmdb_popularity: float

    write_nfo: bool
    write_nfo_only_if_not_exists: bool
    update_tv_series_nfo: bool

    opensubtitles_download: bool
    opensubtitles_app_name: Optional[str] = None
    opensubtitles_api_key: Optional[str] = None
    opensubtitles_username: Optional[str] = None
    opensubtitles_password: Optional[str] = None

    enable_scheduled_task: bool
    scheduled_hour: int
    scheduled_minute: int


class SettingsPatch(BaseModel):
    api_base: Optional[str]
    token_url: Optional[str]
    access: Optional[str]
    refresh: Optional[str]

    username: Optional[str]
    password: Optional[str]

    stream_base_url: Optional[str]
    skip_stream_check: Optional[bool]
    only_updated_streams: Optional[bool]
    last_modified_days: Optional[int]
    update_stream_link: Optional[bool]

    output_root: Optional[str]
    clean_output_dir: Optional[bool]

    process_movies_groups: Optional[bool]
    movies_groups: Optional[list[str]]
    process_tv_series_groups: Optional[bool]
    tv_series_groups: Optional[list[str]]
    process_groups_24_7: Optional[bool]
    groups_24_7: Optional[list[str]]
    remove_strings: Optional[list[str]]

    batch_size: Optional[int]
    batch_delay_seconds: Optional[float]
    concurrent_requests: Optional[int]
    tmdb_rate_limit: Optional[int ]

    movie_year_regex: Optional[str]
    tv_series_episode_regex: Optional[str]

    tmdb_api_key: Optional[str]
    tmdb_language: Optional[str]
    tmdb_download_images: Optional[bool]
    tmdb_image_size: Optional[str]
    tmdb_create_not_found: Optional[bool]
    minimum_year: Optional[int]
    check_tmdb_thresholds: Optional[bool]
    minimum_tmdb_rating: Optional[float]
    minimum_tmdb_votes: Optional[int]
    minimum_tmdb_popularity: Optional[float]

    write_nfo: Optional[bool]
    write_nfo_only_if_not_exists: Optional[bool]
    update_tv_series_nfo: Optional[bool]

    opensubtitles_download: Optional[bool]
    opensubtitles_app_name: Optional[str]
    opensubtitles_api_key: Optional[str]
    opensubtitles_username: Optional[str]
    opensubtitles_password: Optional[str]

    enable_scheduled_task: Optional[bool]
    scheduled_hour: Optional[int]
    scheduled_minute: Optional[int]


# --- Helpers ---------------------------------------------------------------

def _read_config_file() -> dict:
    try:
        return json.loads(Path(CONFIG_PATH).read_text())
    except Exception as e:
        raise HTTPException(500, f"Failed to load config.json: {e}")

def _write_config_file(data: dict) -> None:
    try:
        Path(CONFIG_PATH).write_text(json.dumps(data, indent=2))
    except Exception as e:
        raise HTTPException(500, f"Failed to write config.json: {e}")

def _sync_in_memory(cfg: dict):
    # update the BaseSettings instance so rest of app sees new values
    for key, val in cfg.items():
        if hasattr(settings, key):
            setattr(settings, key, val)


# --- Routes ---------------------------------------------------------------

@router.get("", response_model=SettingsOut, summary="Fetch current settings")
async def read_settings():
    cfg = _read_config_file()
    return cfg


@router.put("", response_model=SettingsOut, summary="Replace all settings")
async def replace_settings(new: SettingsIn):
    cfg = new.dict()
    _write_config_file(cfg)
    _sync_in_memory(cfg)
    return cfg


@router.patch("", response_model=SettingsOut, summary="Update one or more settings")
async def update_settings(changes: SettingsPatch):
    cfg = _read_config_file()
    updates = changes.dict(exclude_unset=True)
    cfg.update(updates)
    _write_config_file(cfg)
    _sync_in_memory(cfg)
    return cfg


@router.post("/refresh", summary="Refresh access & refresh tokens")
async def refresh_tokens():
    token = await get_access_token()
    if not token:
        raise HTTPException(502, "Unable to refresh token")
    return {"access": settings.access}


@router.get("/token-status", summary="Get current token status")
async def token_status():
    return {
        "access": bool(settings.access),
        "refresh": bool(settings.refresh),
    }