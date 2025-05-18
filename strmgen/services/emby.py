# strmgen/services/emby.py
import asyncio
import httpx
import urllib.parse
from typing import Any

from strmgen.core.clients import emby_client
from strmgen.core.config import get_settings
from strmgen.core.logger import logging

settings = get_settings()

def normalize_title(title: str) -> str:
    return title.lower().replace("’", "'").strip()


from strmgen.core.models.enums import MediaType


MEDIA_TYPE_MAP = {0: "Movie", 1: "Series"}

from strmgen.core.config import get_settings

async def search_emby_library(title: str, media_type: str | int | MediaType) -> dict[str, Any] | None:
    """Search Emby for a given title (movie/show)."""
    try:
        settings = get_settings()

        # Normalize media_type to string
        if isinstance(media_type, MediaType):
            media_type = media_type.value
        elif isinstance(media_type, int):
            media_type = MEDIA_TYPE_MAP.get(media_type)
            if not media_type:
                raise ValueError(f"{media_type} is not a valid MediaType")
        elif isinstance(media_type, str):
            media_type = media_type.capitalize()
        else:
            raise ValueError(f"Unsupported media_type: {media_type}")

        encoded = urllib.parse.quote(title)
        query = f"/Items?SearchTerm={encoded}&IncludeItemTypes={media_type}&Recursive=true"

        # Restrict to specific library if configured
        if media_type == "Movie" and settings.emby_movie_library_id:
            query += f"&ParentId={settings.emby_movie_library_id}"

        logging.debug("[Emby] Searching library: %s", query)
        resp = await emby_client.get(query)
        resp.raise_for_status()
        data = resp.json()

        for item in data.get("Items", []):
            if normalize_title(item.get("Name", "")) == normalize_title(title):
                return item
    except httpx.HTTPError as e:
        logging.warning("[Emby] Search failed: %s", e)
    except Exception as e:
        logging.warning("[Emby] Unexpected error: %s", e)

    return None


async def trigger_emby_rescan(item_id: str) -> None:
    """Tell Emby to refresh metadata for a given item."""
    try:
        url = f"/Items/{item_id}/Refresh?metadataRefreshMode=Default&imageRefreshMode=Default&replaceAllMetadata=false"
        logging.debug("[Emby] Triggering metadata refresh: %s", url)
        resp = await emby_client.post(url)
        resp.raise_for_status()
        logging.info("[Emby] Triggered refresh for item ID: %s", item_id)
    except httpx.HTTPError as e:
        logging.warning("[Emby] Failed to trigger refresh: %s", e)