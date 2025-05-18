# strmgen/main.py

from pathlib import Path
from typing import Optional
from fastapi import FastAPI, APIRouter
from testcontainers.postgres import PostgresContainer
from contextlib import asynccontextmanager
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from strmgen.api.routers import logs, process, schedule, streams, tmdb, skipped
from strmgen.api.routers import settings as settings_router
from strmgen.web_ui.routes import router as ui_router
from strmgen.core.auth import get_access_token
from strmgen.pipeline.runner import schedule_on_startup
from strmgen.core.config import register_startup, get_settings
from strmgen.core.db import close_pg_pool, init_pg_pool
from strmgen.core.logger import setup_logger
# from strmgen.services.tmdb import init_tv_genre_map
from strmgen.core.clients import async_client, tmdb_client, tmdb_image_client, emby_client

app = FastAPI(title="STRMGen API & UI", debug=True)

# Web UI
app.include_router(ui_router)
register_startup(app)

# Prime the app logger
logger = setup_logger(__name__)
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

# Global container reference
postgres_container: Optional[PostgresContainer] = None

@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    global postgres_container

    # 1) Optionally launch a PostgreSQL Docker container
    if settings.enable_testcontainers:
        try:
            postgres_container = PostgresContainer(
                image=settings.testcontainers_image,
                username=settings.db_user,
                password=settings.db_pass,
                dbname=settings.db_name,
            )
            postgres_container.start()
            raw_dsn = postgres_container.get_connection_url()
            if raw_dsn.startswith("postgresql+psycopg2://"):
                raw_dsn = "postgresql://" + raw_dsn.split("//", 1)[1]
            settings.postgres_dsn = raw_dsn
            logger.info("Started test Postgres container: %s", raw_dsn)
        except Exception as e:
            logger.warning(
                "Testcontainers unavailable (%s); falling back to DATABASE_URL", e
            )
            settings.postgres_dsn = settings.database_url
    else:
        # Use the configured database URL
        settings.postgres_dsn = settings.database_url

    # 2) Initialize asyncpg pool
    await init_pg_pool()

    # 3) Ensure skipped_streams table exists
    from strmgen.core.db import _pool as pg_pool
    async with pg_pool.acquire() as conn:
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

        # 3.a) Grant all the necessary rights to your configured DB user
        db_user = settings.db_user
        db_name = settings.db_name

        # allow connecting
        await conn.execute(f"GRANT CONNECT ON DATABASE {db_name} TO {db_user};")
        # allow usage of the public schema
        await conn.execute(f"GRANT USAGE ON SCHEMA public TO {db_user};")
        # full control over existing tables
        await conn.execute(f"GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA public TO {db_user};")
        # full control over sequences (if you ever add serial/identity columns)
        await conn.execute(f"GRANT ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA public TO {db_user};")
        # optional—if you want to auto-grant privileges on future tables/sequences:
        await conn.execute(f"ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL ON TABLES TO {db_user};")
        await conn.execute(f"ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL ON SEQUENCES TO {db_user};")





    # 4) Start scheduler, auth, and TMDb genre map
    schedule_on_startup()
    await get_access_token()
    # await init_tv_genre_map()

    try:
        yield
    finally:
        # Shutdown: close DB pool, HTTP clients, scheduler, and test container
        await close_pg_pool()
        if postgres_container:
            try:
                postgres_container.stop()
                logger.info("Stopped test Postgres container")
            except Exception:
                logger.exception("Error stopping test Postgres container")

        # Stop background jobs and close HTTP clients
        from strmgen.pipeline.runner import scheduler
        scheduler.shutdown(wait=False)
        await tmdb_client.aclose()
        await tmdb_image_client.aclose()
        await async_client.aclose()
        await emby_client.aclose()


# Attach the lifespan to the app
app.router.lifespan_context = lifespan