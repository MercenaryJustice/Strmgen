# strmgen/main.py

# import logging

from pathlib import Path
from fastapi import FastAPI, APIRouter
from testcontainers.postgres import PostgresContainer
from contextlib import asynccontextmanager
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from strmgen.api.routers import logs, process, schedule, streams, tmdb, skipped
from strmgen.api.routers import settings as settings_router
from strmgen.web_ui.routes import router as ui_router
from strmgen.core.auth import get_access_token
from strmgen.core.pipeline import schedule_on_startup
from strmgen.core.config import register_startup, settings
from strmgen.core.state import close_pg_pool, init_pg_pool
from strmgen.core.logger import setup_logger
from strmgen.core.logger_sse import setup_sse_logging
from strmgen.services.tmdb import init_tv_genre_map
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

postgres_container: PostgresContainer


# Static files for the UI
STATIC_DIR = Path(__file__).parent / "web_ui" / "static"
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

@app.get("/favicon.ico")
def favicon():
    return FileResponse(STATIC_DIR / "img" / "strmgen_icon.png")

# Lifespan: start scheduler + auth, shutdown scheduler cleanly
@asynccontextmanager
async def lifespan(app: FastAPI):
    global postgres_container
    # 1) Launch a PostgreSQL Docker container
    postgres_container = PostgresContainer(
        image="postgres:15",
        username=settings.db_user,
        password=settings.db_pass,
        dbname=settings.db_name,
    )


    postgres_container.start()

    # 2) Inject its DSN into your settings so your pool uses it
    # Normalize DSN for asyncpg (must start with "postgresql://" or "postgres://")
    raw_dsn = postgres_container.get_connection_url()
    if raw_dsn.startswith("postgresql+psycopg2://"):
        raw_dsn = "postgresql://" + raw_dsn.split("://", 1)[1]
    settings.postgres_dsn = raw_dsn


    # 3) Now create your asyncpg pool
    await init_pg_pool()

    # 3) Ensure your table & index exist
    import asyncpg
    # import the module‑level pool, not the function
    from strmgen.core.state import _pool as pg_pool
    async with pg_pool.acquire() as conn:
        # run your DDL
        await conn.execute("""
        CREATE TABLE IF NOT EXISTS skipped_streams (
          tmdb_id        BIGINT   PRIMARY KEY,
          dispatcharr_id BIGINT   NOT NULL,
          stream_type    TEXT     NOT NULL,
          group_name     TEXT     NOT NULL,
          name           TEXT     NOT NULL,
          reprocess      BOOLEAN  NOT NULL DEFAULT FALSE
        );
        """)
        await conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_skipped_dispatcharr
          ON skipped_streams(dispatcharr_id);
        """)

    schedule_on_startup()
    setup_sse_logging()
    await get_access_token()
    await init_tv_genre_map()
    try:
        yield
    finally:
        from strmgen.core.pipeline import scheduler
        from strmgen.services.tmdb import _tmdb_client, _tmdb_image_client

        # 1) Close your pool
        await close_pg_pool()

        # 2) Stop & remove the container
        postgres_container.stop()

        # stop background jobs
        scheduler.shutdown(wait=False)

        # close all HTTPX clients
        await API_CLIENT.aclose()
        await _tmdb_client.aclose()
        await _tmdb_image_client.aclose()

app.router.lifespan_context = lifespan


