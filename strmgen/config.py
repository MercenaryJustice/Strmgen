import os
import json
from pathlib import Path
from typing import List, Optional, Dict, Any
from pydantic_settings import BaseSettings
from pydantic import Field

# Load environment variables from .env (python-dotenv)
from dotenv import load_dotenv


# ─── 1) Load .env early ───────────────────────────────────────────────────────
BASE_DIR = Path(__file__).parent
DOTENV_PATH = BASE_DIR / ".env"
if DOTENV_PATH.exists():
    load_dotenv(DOTENV_PATH, override=True)

# ─── 2) Load JSON defaults ───────────────────────────────────────────────────
def load_json_settings(path: Path) -> Dict[str, Any]:
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    return {}

_json_cfg = load_json_settings(BASE_DIR / "config.json")


# ─── 3) Define Settings (env-only) ────────────────────────────────────────────
class Settings(BaseSettings):
    # Authentication & API
    api_base:        str
    token_url:       str
    username:        str
    password:        str
    stream_base_url: str

    # Output & directories
    clean_output_dir: bool = False
    output_root:      Path

    # Filtering
    process_movies_groups:    bool = False
    movies_groups:       List[str] = []
    process_tv_series_groups:    bool = False
    tv_series_groups:       List[str] = []
    process_groups_24_7:    bool = False
    groups_24_7:       List[str] = []
    remove_strings:       List[str] = []
    skip_stream_check:    bool = False
    update_stream_link:   bool = False
    only_updated_streams:   bool = False

    # Runtime tokens (populated later)
    access:  Optional[str] = None
    refresh: Optional[str] = None

    # TMDb
    tmdb_api_key:         Optional[str] = None
    tmdb_language:        str = "en-US"
    tmdb_download_images: bool = True
    tmdb_image_size:      str = "original"
    tmdb_create_not_found: bool = False
    check_tmdb_thresholds: bool = True

    minimum_year:         int   = 0
    minimum_tmdb_rating:  float = 0.0
    minimum_tmdb_votes:   int   = 0
    minimum_tmdb_popularity: float = 0.0

    # NFO options
    write_nfo:                  bool = True
    write_nfo_only_if_not_exists: bool = False

    # Subtitles
    opensubtitles_download: bool = False
    opensubtitles_app_name: Optional[str] = None
    opensubtitles_api_key:  Optional[str] = None
    opensubtitles_username: Optional[str] = None
    opensubtitles_password: Optional[str] = None

    # Internal caches
    tmdb_show_cache:    Dict = {}
    tmdb_season_cache:  Dict = {}
    tmdb_episode_cache: Dict = {}
    tmdb_movie_cache:   Dict = {}

# ─── 4) Instantiate from ENV ─────────────────────────────────────────────────
# This will pull values from os.environ (populated by load_dotenv above).
settings = Settings()

# ─── 5) Overlay JSON defaults where ENV didn’t set anything ──────────────────
_valid_fields = set(Settings.model_fields.keys())

for key, val in _json_cfg.items():
    if key not in _valid_fields:
        # skip any JSON setting that isn’t declared in Settings
        continue

    # only apply JSON default if the env didn’t already set it
    if getattr(settings, key, None) is None:
        setattr(settings, key, val)