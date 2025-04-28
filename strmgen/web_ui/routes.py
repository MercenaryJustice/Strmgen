# strmgen/web_ui/routes.py

import json
from pathlib import Path

from fastapi import APIRouter, Request, Form, HTTPException
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from pydantic import ValidationError
from types import SimpleNamespace

from ..config import settings, CONFIG_PATH, _json_cfg

router = APIRouter()
BASE_DIR = Path(__file__).resolve().parent
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))


@router.get("/", include_in_schema=False)
def home_page(request: Request):
    """
    Render the dashboard home page.
    """
    return templates.TemplateResponse(
        "home.html",
        {"request": request},
    )


@router.get("/logs", include_in_schema=False)
def logs_page(request: Request):
    """
    Render the application logs page.
    """
    return templates.TemplateResponse(
        "logs.html",
        {"request": request},
    )


@router.get("/settings", include_in_schema=False)
def settings_page(request: Request):
    try:
        disk_cfg = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        disk_ns = SimpleNamespace(**disk_cfg)
    except FileNotFoundError:
        disk_cfg = _json_cfg.copy()
    return templates.TemplateResponse(
        "settings.html",
        {"request": request, "config": disk_ns, "title": "Settings"},
    )


@router.post("/settings", include_in_schema=False)
async def save_settings(
    request: Request,
):
    """
    Validate and persist settings updates (including scheduling fields),
    then redirect back to GET /settings.
    """
    posted = await request.form()
    # Build the flat settings dict
    data = {
        "api_base":          posted["api_base"],
        "token_url":         posted["token_url"],
        "username":          posted["username"],
        "password":          posted["password"],
        "stream_base_url":   posted["stream_base_url"],

        "clean_output_dir":      "clean_output_dir"      in posted,
        "output_root":           posted["output_root"],

        "process_movies_groups":    "process_movies_groups"    in posted,
        "movies_groups":            [s.strip() for s in posted["movies_groups_raw"].split(",") if s.strip()],
        "process_tv_series_groups": "process_tv_series_groups" in posted,
        "tv_series_groups":         [s.strip() for s in posted["tv_series_groups_raw"].split(",") if s.strip()],
        "process_groups_24_7":      "process_groups_24_7"      in posted,
        "groups_24_7":              [s.strip() for s in posted["groups_24_7_raw"].split(",") if s.strip()],
        "remove_strings":           [s.strip() for s in posted["remove_strings_raw"].split(",") if s.strip()],

        "skip_stream_check":        "skip_stream_check"   in posted,
        "update_stream_link":       "update_stream_link"  in posted,
        "only_updated_streams":     "only_updated_streams"in posted,

        # TMDb
        "tmdb_api_key":         posted.get("tmdb_api_key","") or None,
        "tmdb_language":        posted["tmdb_language"],
        "tmdb_download_images": "tmdb_download_images" in posted,
        "tmdb_image_size":      posted["tmdb_image_size"],
        "tmdb_create_not_found":"tmdb_create_not_found" in posted,
        "check_tmdb_thresholds":"check_tmdb_thresholds" in posted,
        "minimum_year":           int(posted["minimum_year"]),
        "minimum_tmdb_rating":    float(posted["minimum_tmdb_rating"]),
        "minimum_tmdb_votes":     int(posted["minimum_tmdb_votes"]),
        "minimum_tmdb_popularity":float(posted["minimum_tmdb_popularity"]),

        # NFO
        "write_nfo":                    "write_nfo" in posted,
        "write_nfo_only_if_not_exists": "write_nfo_only_if_not_exists" in posted,
        "update_tv_series_nfo":         "update_tv_series_nfo" in posted,

        # Subtitles
        "opensubtitles_download": "opensubtitles_download" in posted,
        "opensubtitles_app_name":  posted.get("opensubtitles_app_name") or None,
        "opensubtitles_api_key":   posted.get("opensubtitles_api_key") or None,
        "opensubtitles_username":  posted.get("opensubtitles_username") or None,
        "opensubtitles_password":  posted.get("opensubtitles_password") or None,
    }

    data["access"]               = settings.access               # whatever the current runtime value is
    data["refresh"]              = settings.refresh

    # Validate against the Pydantic Settings model
    try:
        settings.__class__(**data)
    except ValidationError as exc:
        # If validation fails, re-render the form with errors
        print(exc)
        default_cfg = settings.model_dump()
        current_cfg = {**_json_cfg, **data}
        # Format last_run nicely
        lr = default_cfg.get("last_run")
        current_cfg["last_run"] = lr.isoformat() if lr else ""
        merged = {**default_cfg, **current_cfg}
        return templates.TemplateResponse(
            "settings.html",
            {
                "request": request,
                "config": merged,
                "errors": exc.errors(),
            },
        )

    # Persist into the shared JSON dict and to disk
    _json_cfg.update(data)
    try:
        CONFIG_PATH.write_text(json.dumps(_json_cfg, indent=2), encoding="utf-8")

        settings.__init__(**_json_cfg)
    except Exception:
        raise HTTPException(500, "Failed to write config.json")

    # Redirect GET→POST→GET
    return RedirectResponse(request.url_for("settings_page"), status_code=303)