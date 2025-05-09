# strmgen/core/models/models.py
from typing import Optional, NamedTuple

class StreamInfo(NamedTuple):
    group: str
    title: str
    year: Optional[int] = None
    season: Optional[int] = None
    episode: Optional[int] = None
