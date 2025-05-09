# strmgen/core/models/paths.py
from typing import Optional
from pathlib import Path

from strmgen.core.config import settings
from strmgen.core.models.models import StreamInfo
from strmgen.core.models.enums import MediaType

class MediaPaths:
    ROOT = Path(settings.output_root)

    @classmethod
    def _ensure(cls, p: Path) -> Path:
        p.mkdir(parents=True, exist_ok=True)
        return p

    @classmethod
    def _base_folder(
        cls,
        media_type: MediaType,
        group: str,
        title: str,
        year: Optional[int] = None
    ) -> Path:
        """
        e.g. …/<media_type>/<group>/<title> (YYYY)   (for movies)
             …/<media_type>/<group>/<show>            (for TV)
        """
        if media_type is MediaType.MOVIE:
            folder_name = f"{title} ({year})" if year else title
        else:
            folder_name = title

        return cls.ROOT / media_type.value / group / folder_name
        # return cls._ensure(folder)

    @classmethod
    def _file_path(
        cls,
        media_type: MediaType,
        group: str,
        title: str,
        year: Optional[int],
        filename: str
    ) -> Path:
        base = cls._base_folder(media_type, group, title, year)
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
        return base / f"Season {stream.season:02d}"
        # return cls._ensure(sf)

    @classmethod
    def season_poster(cls, stream: StreamInfo) -> Path:
        sf = cls.season_folder(stream)
        return sf / f"Season {stream.season:02d}.tbn"

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
    