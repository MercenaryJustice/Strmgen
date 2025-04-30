# strmgen/main.py

from pathlib import Path
from fastapi import FastAPI
from contextlib import asynccontextmanager
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from strmgen.api.routes import router as api_router
from strmgen.web_ui.routes import router as ui_router

from strmgen.core.pipeline import schedule_on_startup

# ─── FastAPI & lifespan ─────────────────────────────────────────────────────
app = FastAPI(title="STRMGen API & UI", debug=True)

app.include_router(api_router, prefix="/api")

# ─── Static / UI ─────────────────────────────────────────────────────────────
BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR / "web_ui" / "static"
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

@app.get("/favicon.ico", include_in_schema=False)
async def favicon():
    return FileResponse(STATIC_DIR / "img" / "strmgen_icon.png")

app.include_router(api_router)
app.include_router(ui_router)

@asynccontextmanager
async def lifespan(app: FastAPI):
    # start the scheduler and schedule the job
    schedule_on_startup()
    try:
        yield
    finally:
        from strmgen.core.pipeline import scheduler
        scheduler.shutdown(wait=False)

app.router.lifespan_context = lifespan

# ─── Schedule endpoints ─────────────────────────────────────────────────────
class ScheduleUpdate(BaseModel):
    hour: int
    minute: int

