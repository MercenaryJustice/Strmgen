# strmgen/core/control.py

import asyncio
from typing import Optional

# Holds the currently‐running pipeline task
_processor_task: Optional[asyncio.Task] = None

def set_processor_task(task: asyncio.Task) -> None:
    """Called by runner.start_background_run() to register the task."""
    global _processor_task
    _processor_task = task

def is_running() -> bool:
    """True if there’s a live pipeline task that hasn’t finished or been cancelled."""
    return bool(_processor_task and not _processor_task.done())