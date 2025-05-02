# strmgen/api/schemas.py

from pydantic import BaseModel
from typing import List, Optional

class LogsResponse(BaseModel):
    total: int
    logs: List[str]

class ClearResponse(BaseModel):
    status: str

class StatusResponse(BaseModel):
    running: bool
    task_id: str | None = None

class ScheduleResponse(BaseModel):
    enabled:   bool
    hour:      int
    minute:    int
    next_run:  Optional[str]
    last_run:  Optional[str]

class ScheduleUpdate(BaseModel):
    hour:   int  # 0–23
    minute: int  # 0–59