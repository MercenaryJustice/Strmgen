import os
from celery.app.base import Celery as CeleryApp
from celery.schedules import crontab

CELERY_BROKER_URL    = os.getenv("CELERY_BROKER_URL", "redis://localhost:6379/0")
CELERY_RESULT_BACKEND = os.getenv("CELERY_RESULT_BACKEND", "redis://localhost:6379/1")

# annotate celery_app as the BaseCelery type
celery_app: CeleryApp = CeleryApp(
    "strmgen",
    broker=CELERY_BROKER_URL,
    backend=CELERY_RESULT_BACKEND,
)

# schedule nightly run at 02:00
celery_app.conf.beat_schedule = {
     "run-nightly-pipeline": {
         "task": "strmgen.core.pipeline.run_pipeline",
         "schedule": crontab(hour=2, minute=0),    # ← use crontab
     },
 }

# auto‑discover any @shared_task in your code
celery_app.autodiscover_tasks(["strmgen.core.pipeline"])