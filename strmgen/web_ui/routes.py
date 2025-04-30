# strmgen/web_ui/routes.py

import json
from pathlib import Path

from fastapi import FastAPI, APIRouter, Request, Form, HTTPException, Query, Body
from fastapi.responses import RedirectResponse, HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from pydantic import ValidationError, BaseModel
from types import SimpleNamespace

from ..core.state import set_reprocess, list_skipped, update_skipped_reprocess
from ..core.config import settings, CONFIG_PATH, _json_cfg
from ..services.tmdb import fetch_movie_details, fetch_tv_details

router = APIRouter()
BASE_DIR = Path(__file__).resolve().parent
TEMPLATE_DIR = BASE_DIR / "templates"
templates = Jinja2Templates(directory=str(TEMPLATE_DIR))

app = FastAPI()

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
        "movie_year_regex":        posted["movie_year_regex"],
        "movies_groups":            [s.strip() for s in posted["movies_groups_raw"].split(",") if s.strip()],
        "process_tv_series_groups": "process_tv_series_groups" in posted,
        "tv_series_groups":         [s.strip() for s in posted["tv_series_groups_raw"].split(",") if s.strip()],
        "tv_series_episode_regex":        posted["tv_series_episode_regex"],
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



@router.get("/skipped", response_class=HTMLResponse)
async def skipped_page(request: Request):
    return templates.TemplateResponse("skipped.html", {"request": request})


@app.get("/api/skipped-streams")
async def api_list_skipped(stream_type: str | None = Query(None)):
    """
    List all skipped streams, optionally filtered by stream_type.
    """
    rows = list_skipped(stream_type) if stream_type else list_skipped(None)
    return {"skipped": rows}

@app.post("/api/skipped-streams/{stream_type}/{tmdb_id}/reprocess")
async def api_set_reprocess(
    stream_type: str,
    tmdb_id: int,
    payload: dict = Body(...),
):
    """
    Update the `reprocess` flag for a given skipped stream.
    """
    if "reprocess" not in payload:
        raise HTTPException(400, "Missing 'reprocess' in body")
    update_skipped_reprocess(tmdb_id, stream_type, bool(payload["reprocess"]))
    return {"status": "ok"}

@app.get("/api/tmdb/info/{stream_type}/{tmdb_id}")
async def api_tmdb_info(stream_type: str, tmdb_id: int):
    """
    Fetch TMDb metadata for a movie or TV show and return as JSON.
    """
    if stream_type.lower() == "movie":
        info = fetch_movie_details(tmdb_id)
    else:
        info = fetch_tv_details(tmdb_id)

    if not info:
        # no data found
        raise HTTPException(404, f"No TMDb info for {stream_type} {tmdb_id}")

    # ensure JSON-serializable dict
    return JSONResponse(content=info)

class ReprocessToggle(BaseModel):
    tmdb_id: int
    allow:   bool

@router.post("/api/skipped_streams")
async def toggle_reprocess(toggle: ReprocessToggle):
    set_reprocess(toggle.tmdb_id, toggle.allow)
    return {"status": "ok"}