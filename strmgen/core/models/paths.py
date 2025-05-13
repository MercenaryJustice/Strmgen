# strmgen/core/models/paths.py
from typing import Optional
from pathlib import Path

from strmgen.core.config import get_settings
from strmgen.core.models.models import StreamInfo
from strmgen.core.models.enums import MediaType

class MediaPaths:
    """
    Utility for constructing media file paths based on in-memory settings.
    """

    @classmethod
    def _root(cls) -> Path:
        """Get the configured output root directory from settings."""
        return Path(get_settings().output_root)

    @classmethod
    def _base_folder(
        cls,
        media_type: MediaType,
        group: str,
        title: str,
        year: Optional[int] = None
    ) -> Path:
        """
        Construct the base folder for the given media type, group, title, and optional year.
        """
        root = cls._root()
        if media_type is MediaType.MOVIE:
            folder_name = f"{title} ({year})" if year else title
        else:
            folder_name = title
        return root / media_type.value / group / folder_name

    @classmethod
    def _file_path(
        cls,
        media_type: MediaType,
        group: str,
        title: str,
        year: Optional[int],
        filename: str
    ) -> Path:
        """
        Build the full file path under the base folder and ensure directories exist.
        """
        base = cls._base_folder(media_type, group, title, year)
        # base.mkdir(parents=True, exist_ok=True)
        return base / filename

    # ── Movie helpers ────────────────────────────────────────────────────────────

    @classmethod
    def movie_strm(cls, stream: StreamInfo) -> Path:
        fn = f"{stream.title}.strm"
        return cls._file_path(MediaType.MOVIE, stream.group, stream.title, stream.year, fn)

    @classmethod
    def movie_nfo(cls, stream: StreamInfo) -> Path:
        fn = f"{stream.title}.nfo"
        return cls._file_path(MediaType.MOVIE, stream.group, stream.title, stream.year, fn)

    @classmethod
    def movie_poster(cls, stream: StreamInfo) -> Path:
        return cls._file_path(MediaType.MOVIE, stream.group, stream.title, stream.year, "poster.jpg")

    @classmethod
    def movie_backdrop(cls, stream: StreamInfo) -> Path:
        return cls._file_path(MediaType.MOVIE, stream.group, stream.title, stream.year, "fanart.jpg")

    # ── TV‑show helpers ───────────────────────────────────────────────────────────

    @classmethod
    def show_nfo(cls, stream: StreamInfo) -> Path:
        fn = f"{stream.title}.nfo"
        return cls._file_path(MediaType.TV, stream.group, stream.title, None, fn)

    @classmethod
    def show_image(cls, stream: StreamInfo, filename: str) -> Path:
        return cls._file_path(MediaType.TV, stream.group, stream.title, None, filename)

    @classmethod
    def season_folder(cls, stream: StreamInfo) -> Path:
        assert stream.season is not None, "season required"
        base = cls._base_folder(MediaType.TV, stream.group, stream.title, None)
        season_folder = base / f"Season {stream.season:02d}"
        season_folder.mkdir(parents=True, exist_ok=True)
        return season_folder

    @classmethod
    def season_poster(cls, stream: StreamInfo) -> Path:
        sf = cls.season_folder(stream)
        fn = f"Season {stream.season:02d}.tbn"
        return sf / fn

    @classmethod
    def episode_strm(cls, stream: StreamInfo) -> Path:
        assert stream.season is not None and stream.episode is not None
        sf = cls.season_folder(stream)
        base = f"{stream.title} - S{stream.season:02d}E{stream.episode:02d}"
        return sf / f"{base}.strm"

    @classmethod
    def episode_nfo(cls, stream: StreamInfo) -> Path:
        sf = cls.season_folder(stream)
        base = f"{stream.title} - S{stream.season:02d}E{stream.episode:02d}"
        return sf / f"{base}.nfo"

    @classmethod
    def episode_image(cls, stream: StreamInfo) -> Path:
        sf = cls.season_folder(stream)
        base = f"{stream.title} - S{stream.season:02d}E{stream.episode:02d}"
        return sf / f"{base}.jpg"
