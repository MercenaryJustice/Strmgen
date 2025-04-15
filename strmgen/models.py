
from dataclasses import dataclass
from datetime import datetime, timezone, timedelta
from typing import Optional, Dict, List
from pathlib import Path

@dataclass
class DispatcharrStream:
    id: int
    name: str
    url: str
    m3u_account: int
    logo_url: str
    tvg_id: str
    local_file: Optional[Path]
    current_viewers: int
    updated_at: datetime
    stream_profile_id: Optional[int]
    is_custom: bool
    channel_group: int
    stream_hash: str

    @property
    def was_updated_today(self) -> bool:
        """
        Returns True if updated_at falls on “today” in UTC.
        """
        if not self.updated_at:
            return False
        # use timezone‐aware now()
        today_utc = datetime.now(timezone.utc).date() - timedelta(days=1)
        return self.updated_at.date() >= today_utc
    
    @classmethod
    def from_dict(cls, data: dict) -> "DispatcharrStream":
        """
        Create a Stream instance from a raw dict, converting
        types for `local_file` and `updated_at`.
        """
        # Convert local_file to Path if present
        lf = data.get("local_file")
        local_file = Path(lf) if lf else None

        # parse ISO8601 with Z suffix
        ts = data.get("updated_at")
        updated_at = None
        if ts:
            try:
                # try with microseconds
                updated_at = datetime.strptime(ts, "%Y-%m-%dT%H:%M:%S.%fZ")
            except ValueError:
                # fallback without microseconds
                updated_at = datetime.strptime(ts, "%Y-%m-%dT%H:%M:%SZ")

        return cls(
            id=data["id"],
            name=data["name"],
            url=data["url"],
            m3u_account=data["m3u_account"],
            logo_url=data["logo_url"],
            tvg_id=data.get("tvg_id", ""),
            local_file=local_file,
            current_viewers=data.get("current_viewers", 0),
            updated_at=updated_at,
            stream_profile_id=data.get("stream_profile_id"),
            is_custom=data.get("is_custom", False),
            channel_group=data.get("channel_group", 0),
            stream_hash=data["stream_hash"],
        )
