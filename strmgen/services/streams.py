# strmgen/services/streams.py

import asyncio
import httpx
from pathlib import Path
from typing import List, Dict, Optional, Any
from urllib.parse import quote_plus

from ..core.config import settings
from ..core.auth import get_auth_headers
from ..core.utils import safe_mkdir, setup_logger
from ..core.models import Stream, DispatcharrStream

logger = setup_logger(__name__)
API_TIMEOUT = 10.0


async def _request_with_refresh(
    method: str,
    url: str,
    headers: Dict[str, str],
    timeout: float = API_TIMEOUT,
    **kwargs: Any
) -> httpx.Response:
    """
    Async HTTP request with a single retry on 401/token_not_valid.
    """
    async with httpx.AsyncClient(timeout=timeout) as client:
        r = await client.request(method, url, headers=headers, **kwargs)

    if r.status_code == 401:
        # Attempt to parse body for token expiration
        try:
            body = r.json()
        except ValueError:
            body = {}
        if body.get("code") == "token_not_valid":
            logger.info("[AUTH] 🔄 Token expired, refreshing & retrying")
            headers = await get_auth_headers()
            async with httpx.AsyncClient(timeout=timeout) as client:
                r = await client.request(method, url, headers=headers, **kwargs)

    return r


async def fetch_streams_by_group_name(
    group_name: str,
    headers: Dict[str, str]
) -> List[Stream]:
    """
    Async fetch all Stream entries for a given channel group,
    with automatic token refresh, and return as Pydantic models.
    """
    out: List[Stream] = []
    page = 1
    enc = quote_plus(group_name)

    while True:
        url = (
            f"{settings.api_base}/api/channels/streams/"
            f"?page={page}&page_size=250&ordering=name&channel_group={enc}"
        )
        r = await _request_with_refresh("GET", url, headers, timeout=API_TIMEOUT)
        if not r.is_success:
            logger.error(
                "[STRM] ❌ Error fetching streams for group '%s': %d %s",
                group_name, r.status_code, r.text
            )
            break

        data = r.json()
        results = data.get("results", [])

        for item in results:
            try:
                out.append(Stream(**item))
            except Exception as e:
                logger.error("Failed to parse Stream for %s: %s", item, e)

        if not data.get("next"):
            break
        page += 1

    return out


async def is_stream_alive(
    stream_id: int,
    headers: Dict[str, str],
    timeout: float = 5.0
) -> bool:
    """
    Check reachability of the stream URL; skip if configured to always trust.
    """
    if settings.skip_stream_check:
        return True

    url = f"{settings.api_base}/api/channels/streams/{stream_id}/"
    try:
        r = await _request_with_refresh("GET", url, headers, timeout=timeout)
        r.raise_for_status()
        stream_url = r.json().get("url")
        if not stream_url:
            return False

        async with httpx.AsyncClient(timeout=timeout) as client:
            head = await client.head(stream_url)
        return head.is_success
    except Exception:
        return False


async def get_stream_by_id(
    stream_id: int,
    headers: Dict[str, str],
    timeout: float = API_TIMEOUT
) -> Optional[Stream]:
    """
    Async fetch of a single Stream by ID, with token refresh.
    """
    url = f"{settings.api_base}/api/channels/streams/{stream_id}/"
    try:
        r = await _request_with_refresh("GET", url, headers, timeout=timeout)
        if not r.is_success:
            logger.error(
                "[STRM] ❌ Error fetching stream #%d: %d %s",
                stream_id, r.status_code, r.text
            )
            return None

        data = r.json()
        logger.info("[STRM] ✅ Fetched stream #%d", stream_id)
        return Stream(**data)
    except Exception as e:
        logger.error("[STRM] ❌ Exception fetching stream #%d: %s", stream_id, e)
        return None

async def get_dispatcharr_stream_by_id(
    stream_id: int,
    headers: Dict[str, str],
    timeout: float = API_TIMEOUT
) -> Optional[DispatcharrStream]:
    """
    Async fetch of a single Stream by ID, with token refresh.
    """
    url = f"{settings.api_base}/api/channels/streams/{stream_id}/"
    try:
        r = await _request_with_refresh("GET", url, headers, timeout=timeout)
        if not r.is_success:
            logger.error(
                "[STRM] ❌ Error fetching stream #%d: %d %s",
                stream_id, r.status_code, r.text
            )
            return None

        data = r.json()
        logger.info("[STRM] ✅ Fetched stream #%d", stream_id)
        return DispatcharrStream.from_dict(data)
    except Exception as e:
        logger.error("[STRM] ❌ Exception fetching stream #%d: %s", stream_id, e)
        return None

async def write_strm_file(
    path: Path,
    headers: Dict[str, str],
    stream: DispatcharrStream,
    timeout: float = API_TIMEOUT
) -> bool:
    """
    Async wrapper to:
    - Fetch latest metadata
    - Verify stream is alive
    - Write or update the .strm file atomically
    """
    # Skip if update_stream_link disabled and file exists
    if not settings.update_stream_link and await asyncio.to_thread(path.exists):
        return True

    info = await get_stream_by_id(stream.id, headers, timeout)
    if not info:
        logger.warning("[STRM] ⚠️ Stream #%d metadata unavailable, skipping", stream.id)
        return False

    if not stream.url:
        logger.warning("[STRM] ⚠️ Stream #%d has no URL, skipping", stream.id)
        return False

    if not await is_stream_alive(stream.id, headers, timeout):
        logger.warning("[STRM] ⚠️ Stream #%d unreachable, skipping", stream.id)
        return False

    # Ensure directory exists
    await asyncio.to_thread(safe_mkdir, path.parent)

    # Check existing file content
    if await asyncio.to_thread(path.exists):
        existing = await asyncio.to_thread(path.read_text, encoding="utf-8")
        if existing.strip() == stream.url.strip():
            logger.info("[STRM] ⚠️ .strm up-to-date: %s", path)
            return True
        else:
            logger.info("[STRM] 🔄 Updating .strm (URL changed): %s", path)

    # Write new .strm
    await asyncio.to_thread(path.write_text, stream.url, "utf-8")
    logger.info("[STRM] ✅ Wrote .strm: %s", path)
    return True


async def fetch_groups() -> List[str]:
    """
    Async fetch of all channel-group names.
    """
    headers = await get_auth_headers()
    url = f"{settings.api_base}/api/channels/streams/groups/"
    r = await _request_with_refresh("GET", url, headers, timeout=API_TIMEOUT)
    r.raise_for_status()
    return r.json()


async def fetch_streams(
    group: str,
    stream_type: str,
    headers: Optional[Dict[str, str]] = None,
    timeout: float = API_TIMEOUT,
    # page: int = 1,
    # page_size: int = 1000,
) -> List[DispatcharrStream]:
    """
    Async fetch of DispatcharrStream entries matching a group and type.
    """
    out: List[DispatcharrStream] = []
    hdrs = headers or get_auth_headers()
    hdrs["accept"] = "application/json"
    url = f"{settings.api_base.rstrip('/')}/api/channels/streams/"

    while True:
        params = {
            "search":      group,
            "stream_type": stream_type,
            "ordering":    "name",
            # "page":        page,
            # "page_size":   page_size,
        }
        r = await _request_with_refresh("GET", url, hdrs, timeout=timeout, params=params)
        r.raise_for_status()
        body: Any = r.json()

        items = body.get("results", body if isinstance(body, list) else [])
        for entry in items:
            try:
                out.append(DispatcharrStream.from_dict(entry))
            except Exception as e:
                logger.warning("Skipping invalid stream entry: %s — %s", entry, e)

        if not body.get("next"):
            break
        page += 1

    return out