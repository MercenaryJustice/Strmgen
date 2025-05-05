# strmgen/services/streams.py
import asyncio
import httpx
from pathlib import Path
from typing import List, Dict, Optional, Any
from urllib.parse import quote_plus

from ..core.config import settings
from ..core.auth import get_auth_headers
from ..core.utils import setup_logger
from ..core.fs_utils import safe_mkdir
from ..core.models import Stream, DispatcharrStream, MediaType

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
        response = await client.request(method, url, headers=headers, **kwargs)

    if response.status_code == 401:
        # Check if token is expired
        logger.info("[AUTH] 🔄 Token expired, refreshing & retrying")
        headers = await get_auth_headers(True)
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.request(method, url, headers=headers, **kwargs)

    return response


async def fetch_streams_by_group_name(
    group_name: str,
    headers: Dict[str, str],
    stream_type: MediaType,
    updated_only: bool = False,
) -> List[DispatcharrStream]:
    """
    Async fetch all Stream entries for a given channel group,
    with automatic token refresh, returning DispatcharrStream.
    """
    out: List[DispatcharrStream] = []
    page = 1
    enc = quote_plus(group_name)

    while True:
        url = (
            f"{settings.api_base}/api/channels/streams/"
            f"?page={page}&page_size=250&ordering=name&channel_group={enc}"
        )
        resp = await _request_with_refresh("GET", url, headers)

        if not resp.is_success:
            logger.error(
                "[STRM] ❌ Error fetching streams for group '%s': %d %s",
                group_name, resp.status_code, await resp.aread()
            )
            break

        data = resp.json()
        for item in data.get("results", []):
            try:
                ds = DispatcharrStream.from_dict(
                    item,
                    channel_group_name=group_name,
                    stream_type=stream_type,
                )
                if not ds:
                    continue

                if updated_only:
                    if ds.stream_updated is None or ds.stream_updated:
                        out.append(ds)
                else:
                    out.append(ds)
            except Exception as e:
                logger.error("Failed to parse DispatcharrStream for %s: %s", item, e)

        if not data.get("next"):
            break
        page += 1

    return out


async def is_stream_alive(
    stream_url: str,
    timeout: float = 5.0,
) -> bool:
    """
    Check reachability of the stream URL; skip if configured to always trust.
    """
    if settings.skip_stream_check:
        return True

    try:
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
        resp = await _request_with_refresh("GET", url, headers)
        if not resp.is_success:
            logger.error(
                "[STRM] ❌ Error fetching stream #%d: %d %s",
                stream_id, resp.status_code, resp.text
            )
            return None

        data = resp.json()
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
    Async fetch of a single DispatcharrStream by ID, with token refresh.
    """
    url = f"{settings.api_base}/api/channels/streams/{stream_id}/"
    try:
        resp = await _request_with_refresh("GET", url, headers)
        if not resp.is_success:
            logger.error(
                "[STRM] ❌ Error fetching stream #%d: %d %s",
                stream_id, resp.status_code, resp.text
            )
            return None

        data = resp.json()
        logger.info("[STRM] ✅ Fetched stream #%d", stream_id)
        return DispatcharrStream.from_dict(data)
    except Exception as e:
        logger.error("[STRM] ❌ Exception fetching stream #%d: %s", stream_id, e)
        return None


async def write_strm_file(
    stream: DispatcharrStream,
    timeout: float = API_TIMEOUT
) -> bool:
    # unchanged
    if not settings.update_stream_link and await asyncio.to_thread(stream.strm_path.exists):
        return True

    if not stream.url or not stream.proxy_url:
        logger.warning("[STRM] ⚠️ Stream #%d has no URL, skipping", stream.id)
        return False

    if not await is_stream_alive(stream.url, timeout):
        logger.warning("[STRM] ⚠️ Stream #%d unreachable, skipping", stream.id)
        return False

    await asyncio.to_thread(safe_mkdir, stream.strm_path.parent)

    if await is_strm_up_to_date(stream):
        logger.info("[STRM] ⚠️ .strm up-to-date: %s", stream.strm_path)
        return True

    await asyncio.to_thread(stream.strm_path.write_text, stream.proxy_url.strip(), "utf-8")
    logger.info("[STRM] ✅ Wrote .strm: %s", stream.strm_path)
    return True


async def is_strm_up_to_date(stream: DispatcharrStream, encoding: str = "utf-8") -> bool:
    # unchanged
    path: Path = stream.strm_path
    if not await asyncio.to_thread(path.exists):
        return False
    existing = await asyncio.to_thread(path.read_text, encoding)
    return existing.strip() == stream.proxy_url.strip()


async def fetch_groups() -> List[str]:
    """
    Async fetch of all channel-group names.
    """
    headers = await get_auth_headers()
    url = f"{settings.api_base}/api/channels/streams/groups/"
    resp = await _request_with_refresh("GET", url, headers)
    resp.raise_for_status()
    return resp.json()


async def fetch_streams(
    group: str,
    stream_type: str,
    headers: Optional[Dict[str, str]] = None,
    timeout: float = API_TIMEOUT,
) -> List[DispatcharrStream]:
    """
    Async fetch of DispatcharrStream entries matching a group and type.
    """
    out: List[DispatcharrStream] = []
    hdrs = headers or await get_auth_headers()
    hdrs["accept"] = "application/json"
    url = f"{settings.api_base.rstrip('/')}\
/api/channels/streams/"
    page = 1

    while True:
        params = {
            "search":      group,
            "stream_type": stream_type,
            "ordering":    "name",
        }
        resp = await _request_with_refresh("GET", url, hdrs, timeout=timeout, params=params)
        resp.raise_for_status()
        body: Any = resp.json()

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
