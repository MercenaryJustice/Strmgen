# strmgen/main.py

# import logging

from pathlib import Path
from fastapi import FastAPI, APIRouter
from contextlib import asynccontextmanager
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from strmgen.api.routers import logs, process, schedule, streams, tmdb, skipped
from strmgen.api.routers import settings as settings_router
from strmgen.web_ui.routes import router as ui_router
from strmgen.core.auth import get_access_token
from strmgen.core.pipeline import schedule_on_startup
from strmgen.core.config import register_startup
from strmgen.core.logger import setup_logger
from strmgen.core.logger_sse import setup_sse_logging
from strmgen.services.tmdb import init_tv_genre_map, init_movie_genre_map
from .core.http import async_client as API_CLIENT

# # Configure logging first thing
# logging.basicConfig(
#     level=logging.DEBUG,
#     format="%(asctime)s %(levelname)s %(name)s: %(message)s"
# )
# ─── FastAPI & Lifespan ────────────────────────────────────────────────────
app = FastAPI(title="STRMGen API & UI", debug=True)

# Web UI
app.include_router(ui_router)
register_startup(app)

# Prime the app logger
logger = setup_logger("APP")
logger.info("Logger initialized, starting application…")

# API v1 routers
api_v1 = APIRouter(prefix="/api/v1", tags=["API"])
api_v1.include_router(process.router,  prefix="/process")
api_v1.include_router(schedule.router, prefix="/schedule")
api_v1.include_router(streams.router,  prefix="/streams")
api_v1.include_router(logs.router,     prefix="/logs")
api_v1.include_router(tmdb.router,     prefix="/tmdb")
api_v1.include_router(skipped.router,  prefix="/skipped")
api_v1.include_router(settings_router.router, prefix="/settings")

app.include_router(api_v1)

# Static files for the UI
STATIC_DIR = Path(__file__).parent / "web_ui" / "static"
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

@app.get("/favicon.ico")
def favicon():
    return FileResponse(STATIC_DIR / "img" / "strmgen_icon.png")

# Lifespan: start scheduler + auth, shutdown scheduler cleanly
@asynccontextmanager
async def lifespan(app: FastAPI):
    schedule_on_startup()
    setup_sse_logging()
    await get_access_token()
    await init_tv_genre_map()
    await init_movie_genre_map()
    try:
        yield
    finally:
        from strmgen.core.pipeline import scheduler
        scheduler.shutdown(wait=False)
        await API_CLIENT.aclose()

app.router.lifespan_context = lifespan


