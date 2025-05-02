# strmgen/main.py

from pathlib import Path
from fastapi import FastAPI, APIRouter
from contextlib import asynccontextmanager
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from strmgen.api.routers import logs, process, schedule, streams, tmdb
from strmgen.api.routers import settings
from strmgen.web_ui.routes import router as ui_router
from strmgen.core.auth import get_access_token
from strmgen.core.pipeline import schedule_on_startup
from strmgen.core.config import register_startup
from strmgen.core.logger import setup_logger

# ─── FastAPI & lifespan ─────────────────────────────────────────────────────
app = FastAPI(title="STRMGen API & UI", debug=True)

# Web UI routes
app.include_router(ui_router)


register_startup(app)

# 1) Prime the logger for the “APP” category immediately on import
logger = setup_logger("APP")
logger.info("Logger initialized, starting application…")

# API v1 domain routers
api_v1 = APIRouter(prefix="/api/v1", tags=["API"])
api_v1.include_router(process.router,  prefix="/process")
api_v1.include_router(schedule.router, prefix="/schedule")
api_v1.include_router(streams.router,  prefix="/streams")
api_v1.include_router(logs.router,     prefix="/logs")
api_v1.include_router(tmdb.router,     prefix="/tmdb")
api_v1.include_router(settings.router, prefix="/settings")
app.include_router(api_v1)


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
