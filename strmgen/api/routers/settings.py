# strmgen/api/routers/settings.py

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional, List

from strmgen.core.config import get_settings, save_settings, reload_settings
from strmgen.core.config import Settings as SettingsModel

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
    movies_groups: List[str]
    process_tv_series_groups: bool
    tv_series_groups: List[str]
    process_groups_24_7: bool
    groups_24_7: List[str]
    remove_strings: List[str]

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

    # ——— Emby integration ———
    emby_api_url: Optional[str] = None
    emby_api_key: Optional[str] = None
    emby_movie_library_id: Optional[int] = None


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
    movies_groups: List[str]
    process_tv_series_groups: bool
    tv_series_groups: List[str]
    process_groups_24_7: bool
    groups_24_7: List[str]
    remove_strings: List[str]

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

    # ——— Emby integration ———
    emby_api_url: Optional[str] = None
    emby_api_key: Optional[str] = None
    emby_movie_library_id: Optional[int] = None

class SettingsPatch(BaseModel):
    api_base:                Optional[str]   = None
    token_url:               Optional[str]   = None
    access:                  Optional[str]   = None
    refresh:                 Optional[str]   = None
    username:                Optional[str]   = None
    password:                Optional[str]   = None

    stream_base_url:         Optional[str]   = None
    skip_stream_check:       Optional[bool]  = None
    only_updated_streams:    Optional[bool]  = None
    last_modified_days:      Optional[int]   = None
    update_stream_link:      Optional[bool]  = None

    output_root:             Optional[str]   = None
    clean_output_dir:        Optional[bool]  = None

    process_movies_groups:         Optional[bool]  = None
    movies_groups:                 Optional[List[str]] = None
    process_tv_series_groups:      Optional[bool]  = None
    tv_series_groups:              Optional[List[str]] = None
    process_groups_24_7:           Optional[bool]  = None
    groups_24_7:                   Optional[List[str]] = None
    remove_strings:                Optional[List[str]] = None

    batch_size:                   Optional[int]   = None
    batch_delay_seconds:          Optional[int]   = None
    concurrent_requests:          Optional[int]   = None
    tmdb_rate_limit:              Optional[int]   = None

    movie_year_regex:             Optional[str]   = None
    tv_series_episode_regex:      Optional[str]   = None

    tmdb_api_key:                 Optional[str]   = None
    tmdb_language:                Optional[str]   = None
    tmdb_download_images:         Optional[bool]  = None
    tmdb_image_size:              Optional[str]   = None
    tmdb_create_not_found:        Optional[bool]  = None
    minimum_year:                 Optional[int]   = None
    check_tmdb_thresholds:        Optional[bool]  = None
    minimum_tmdb_rating:          Optional[int]   = None
    minimum_tmdb_votes:           Optional[int]   = None
    minimum_tmdb_popularity:      Optional[int]   = None

    write_nfo:                    Optional[bool]  = None
    write_nfo_only_if_not_exists: Optional[bool]  = None
    update_tv_series_nfo:         Optional[bool]  = None

    opensubtitles_download:       Optional[bool]  = None
    opensubtitles_app_name:       Optional[str]   = None
    opensubtitles_api_key:        Optional[str]   = None
    opensubtitles_username:       Optional[str]   = None
    opensubtitles_password:       Optional[str]   = None

    enable_scheduled_task:        Optional[bool]  = None
    scheduled_hour:               Optional[int]   = None
    scheduled_minute:             Optional[int]   = None

    # ——— Emby integration ———
    emby_api_url:                       Optional[str] = None
    emby_api_key: Optional[str] = None
    emby_movie_library_id: Optional[int] = None

# --- Routes ---------------------------------------------------------------

@router.get("", response_model=SettingsOut, summary="Fetch current settings", name="settings.get_settings")
def read_settings():
    """Return in-memory settings without disk I/O."""
    return get_settings()

@router.put("", response_model=SettingsOut, summary="Replace all settings")
def replace_settings(new: SettingsIn):
    """
    Replace entire config, persist to disk, reload in-memory cache.
    """
    try:
        settings_model = SettingsModel(**new.dict())
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))
    save_settings(settings_model)
    reload_settings()
    return settings_model

@router.patch("", response_model=SettingsOut, summary="Update one or more settings")
def update_settings(changes: SettingsPatch):
    """
    Apply partial changes, persist, reload cache.
    """
    current = get_settings()
    updates = changes.dict(exclude_unset=True)

    # dump to JSON‑ready dict (this will use your json_encoders for Path → str)
    data = current.model_dump(mode="json")
    data.update(updates)

    try:
        settings_model = SettingsModel(**data)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

    save_settings(settings_model)
    reload_settings()

    # <<< return the dict, not the BaseModel instance >>>
    return SettingsOut(**data)

@router.post("/refresh", summary="Refresh access & refresh tokens")
async def refresh_tokens():
    from strmgen.core.auth import get_access_token
    token = await get_access_token()
    if not token:
        raise HTTPException(502, "Unable to refresh token")
    return {"access": get_settings().access}

@router.get("/token-status", summary="Get current token status")
def token_status():
    s = get_settings()
    return {"access": bool(s.access), "refresh": bool(s.refresh)}
