# strmgen/web_ui/routes.py

import json
from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import RedirectResponse, HTMLResponse
from fastapi.templating import Jinja2Templates
from typing import Any
from starlette.status import HTTP_303_SEE_OTHER

from ..core.config import CONFIG_PATH, reload_settings

router = APIRouter()
BASE_DIR = Path(__file__).resolve().parent
TEMPLATE_DIR = BASE_DIR / "templates"
templates = Jinja2Templates(directory=str(TEMPLATE_DIR))


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


@router.get("/settings", include_in_schema=False, response_class=HTMLResponse)
async def settings_page(request: Request):
    # Load existing settings
    from typing import Any

    cfg: dict[str, Any] = {}
    if CONFIG_PATH.exists():
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            cfg = json.load(f)
    return templates.TemplateResponse("settings.html", {"request": request, "config": cfg})


@router.post("/settings")
async def save_settings(request: Request):
    form = await request.form()
    # Load current config
    cfg: dict[str, Any] = {}
    if CONFIG_PATH.exists():
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            cfg = json.load(f)
    original: dict[str, Any] = cfg.copy()

    # Apply updates from form
    for key, val in form.items():
        if key.endswith("_raw"):
            # comma-separated lists
            new_key = key[:-4]
            cfg[new_key] = [s.strip() for s in str(val).split(",") if s.strip()]
        elif key in original and isinstance(original[key], bool):
            # checkbox present => true
            cfg[key] = True
        else:
            # Attempt numeric conversion (int or float)
            try:
                if isinstance(val, str) and "." in val:
                    num = float(val)
                else:
                    num = int(val)
            except (ValueError, TypeError):
                cfg[key] = val
            else:
                cfg[key] = num

    # Unchecked booleans => false
    for key, val in original.items():
        if isinstance(val, bool) and key not in form:
            cfg[key] = False

    # Persist back to config.json
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2)

    reload_settings()

    return RedirectResponse(request.url_for("settings_page"), status_code=HTTP_303_SEE_OTHER)



@router.get("/skipped", include_in_schema=False, response_class=HTMLResponse)
async def skipped_page(request: Request):
    return templates.TemplateResponse("skipped.html", {"request": request})



