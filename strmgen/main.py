# strmgen/main.py

from pathlib import Path
from fastapi import FastAPI
from contextlib import asynccontextmanager
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from strmgen.api.routers import logs, process, schedule, streams, tmdb
from strmgen.web_ui.routes import router as ui_router
from strmgen.core.auth import get_access_token
from strmgen.core.pipeline import schedule_on_startup

# ─── FastAPI & lifespan ─────────────────────────────────────────────────────
app = FastAPI(title="STRMGen API & UI", debug=True)

# Web UI routes
app.include_router(ui_router)

# API v1 domain routers
app.include_router(streams.router, prefix="/api/v1")
app.include_router(schedule.router, prefix="/api/v1")
app.include_router(logs.router, prefix="/api/v1")
app.include_router(process.router, prefix="/api/v1")
app.include_router(tmdb.router, prefix="/api/v1")

# ─── Static / UI ─────────────────────────────────────────────────────────────
BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR / "web_ui" / "static"
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

@app.get("/favicon.ico", include_in_schema=False)
async def favicon():
    return FileResponse(STATIC_DIR / "img" / "strmgen_icon.png")


@asynccontextmanager
async def lifespan(app: FastAPI):
    # start the scheduler and schedule the job
    schedule_on_startup()
    get_access_token()
    try:
        yield
    finally:
        from strmgen.core.pipeline import scheduler
        scheduler.shutdown(wait=False)

app.router.lifespan_context = lifespan
