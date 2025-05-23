# strmgen/core/logger.py

import sys
import json
import logging
import asyncio
from logging import Handler

# ─── Custom Formatter ────────────────────────────────────────────────────────
class CategoryFormatter(logging.Formatter):
    def format(self, record):
        if not hasattr(record, "category"):
            record.category = record.name.upper()
        return super().format(record)

# shared formatter for queue & (optionally) console
formatter = CategoryFormatter(
    fmt="%(asctime)s %(levelname)-8s [%(category)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)

# ─── In‑memory queues ─────────────────────────────────────────────────────────
# lines for real‑time logs
log_queue: asyncio.Queue[str] = asyncio.Queue(maxsize=1000)
# queues for progress events
progress_listeners: list[asyncio.Queue[str]] = []

# ─── Queue‐based handler ────────────────────────────────────────────────────
class AsyncQueueHandler(Handler):
    """Push formatted log records into an asyncio.Queue."""
    def emit(self, record: logging.LogRecord) -> None:
        msg = self.format(record)
        try:
            log_queue.put_nowait(msg)
        except asyncio.QueueFull:
            # drop on overflow
            pass

# ─── Public API ───────────────────────────────────────────────────────────────
def setup_logging(level=logging.INFO, enable_console=True):
    root_logger = logging.getLogger()
    root_logger.setLevel(level)

    if not any(isinstance(h, AsyncQueueHandler) for h in root_logger.handlers):
        q_handler = AsyncQueueHandler()
        q_handler.setFormatter(formatter)
        root_logger.addHandler(q_handler)

    if enable_console and not any(isinstance(h, logging.StreamHandler) for h in root_logger.handlers):
        console = logging.StreamHandler(sys.stdout)
        console.setFormatter(formatter)
        root_logger.addHandler(console)



def notify_progress(media_type, group, current, total):
    """
    Broadcast progress updates to all connected /status SSE clients.
    """
    payload = json.dumps({
        "type": "progress",
        "media_type": media_type.value,
        "group": group,
        "current": current,
        "total": total
    })
    for q in progress_listeners:
        try:
            q.put_nowait(payload)
        except asyncio.QueueFull:
            # drop if listener is slow
            pass