# strmgen/core/models/movie.py
from dataclasses import dataclass
from typing import Optional, Dict, Any
from datetime import datetime


@dataclass
class Movie:
    id: int
    title: str
    original_title: str
    overview: str
    poster_path: Optional[str]
    backdrop_path: Optional[str]
    release_date: str
    adult: bool
    original_language: str
    genre_ids: Dict[str, Any]
    popularity: float
    video: bool
    vote_average: float
    vote_count: int
    alternative_titles: Dict[str, Any]
    changes: Dict[str, Any]
    credits: Dict[str, Any]
    external_ids: Dict[str, Any]
    images: Dict[str, Any]
    keywords: Dict[str, Any]
    lists: Dict[str, Any]
    recommendations: Dict[str, Any]
    release_dates: Dict[str, Any]
    reviews: Dict[str, Any]
    similar: Dict[str, Any]
    translations: Dict[str, Any]
    videos: Dict[str, Any]
    watch_providers: Dict[str, Any]
    raw: Dict[str, Any]

    @property
    def year(self) -> Optional[int]:
        try:
            # datetime.fromisoformat handles “YYYY-MM-DD”
            dt = datetime.fromisoformat(self.release_date)
            return dt.year
        except (ValueError, TypeError):
            return None