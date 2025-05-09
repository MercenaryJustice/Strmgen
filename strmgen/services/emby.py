# strmgen/services/emby.py
import urllib.parse
import httpx
import requests
import logging

logger = logging.getLogger(__name__)
from strmgen.core.config import get_settings

settings = get_settings()
_client: httpx.AsyncClient | None = None


def get_client() -> httpx.AsyncClient:
    global _client
    if _client is None:
        _client = httpx.AsyncClient(base_url=settings.emby_api_url, headers={"X-Emby-Token": settings.emby_api_key})
    return _client

async def emby_movie_exists(title: str, year: int | None = None) -> bool:
    """
    Returns True if a movie with the given title (and optional year)
    already exists in the Emby library.
    """
    client = get_client()
    params = {
        "IncludeItemTypes": "Movie",
        "Recursive": "true",
        "SearchTerm": title,
        "ParentId": settings.emby_movie_library_id,
        "Limit": 50,
        "Fields": "ProductionYear"
    }
    resp = await client.get(f"/Items?{urllib.parse.urlencode(params)}")
    resp.raise_for_status()
    items = resp.json().get("Items", [])
    for item in items:
        if item["Name"].lower() == title.lower() and (year is None or item.get("ProductionYear") == year):
            return True
    return False

def trigger_emby_scan(folder: str) -> None:
    """
    Tell Emby to scan a specific folder for new or changed media.

    :param folder: Absolute path to the folder containing .strm files
    :param emby_url: Base Emby API URL (including /emby)
    :param api_key:  Your Emby API key/token
    :raises HTTPError: if the Emby API returns a bad status
    """
    # URL-encode the folder parameter
    encoded_path = urllib.parse.quote(folder, safe='')
    url = f"{settings.emby_api_url}/Library/Media/Updated?api_key={settings.emby_api_key}&Path={encoded_path}"

    logger.debug("Triggering Emby scan: %s", url)
    resp = requests.get(url)
    resp.raise_for_status()
    logger.info("Triggered Emby scan for folder: %s", folder)