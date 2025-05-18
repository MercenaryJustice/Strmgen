# strmgen/services/dispatcharr.py

import asyncio
import httpx
from pathlib import Path
from typing import List, Optional, Any
from urllib.parse import quote_plus
from fastapi import HTTPException

from strmgen.core.config import get_settings
from strmgen.core.auth import get_auth_headers
from strmgen.core.utils import setup_logger, safe_mkdir
from strmgen.core.models.dispatcharr import DispatcharrStream, MediaType
from strmgen.core.clients import async_client

logger = setup_logger(__name__)
API_TIMEOUT = 10.0

tag = "[STRM]"

async def fetch_streams_by_group_name(
    group_name: str,
    stream_type: MediaType,
    updated_only: bool = False,
) -> List[DispatcharrStream]:
    """
    Async fetch all Stream entries for a given channel group,
    with automatic token refresh, returning DispatcharrStream.
    """
    settings = get_settings()
    out: List[DispatcharrStream] = []
    page = 1
    enc = quote_plus(group_name)
    page_size = 1000
    while True:
        logger.info(
            "%s Fetching streams for group '%s': page: %d...",
            tag, group_name, page
        )
        url = (
            f"{settings.api_base}/api/channels/streams/"
            f"?page={page}&page_size={page_size}&ordering=name&channel_group={enc}"
        )
        resp = await _request("GET", url)
        # stream_count = data.get("count", 0)


        if not resp.is_success:
            logger.error(
                "%s ❌ Error fetching streams for group '%s': %d %s",
                tag, group_name, resp.status_code, await resp.aread()
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
    settings = get_settings()
    if settings.skip_stream_check:
        return True

    try:
        head = await async_client.head(stream_url, timeout=timeout)
        return head.is_success
    except Exception:
        return False


async def get_dispatcharr_stream_by_id(
    stream_id: int
) -> Optional[DispatcharrStream]:
    """
    Async fetch of a single DispatcharrStream by ID, with token refresh.
    """
    url = f"{get_settings().api_base}/api/channels/streams/{stream_id}/"
    try:
        resp = await _request("GET", url)
        if not resp.is_success:
            logger.error(
                "%s ❌ Error fetching stream #%d: %d %s",
                tag, stream_id, resp.status_code, resp.text
            )
            return None

        data = resp.json()
        logger.info("%s ✅ Fetched stream #%d", tag, stream_id)
        return DispatcharrStream.from_dict(data)
    except Exception as e:
        logger.error("[STRM] ❌ Exception fetching stream #%d: %s", stream_id, e)
        return None


async def write_strm_file(
    stream: DispatcharrStream,
    timeout: float = API_TIMEOUT
) -> bool:
    settings = get_settings()

    if not stream.url or not stream.proxy_url:
        logger.warning("%s ⚠️ Stream #%d has no URL, skipping", tag, stream.id)
        return False

    if not await is_stream_alive(stream.url, timeout):
        logger.warning("%s ⚠️ Stream #%d unreachable, skipping", tag, stream.id)
        return False

    if not settings.update_stream_link and await asyncio.to_thread(stream.strm_path.exists):
        return True

    # Ensure target directory exists
    await asyncio.to_thread(stream.strm_path.parent.mkdir, parents=True, exist_ok=True)

    if await is_strm_up_to_date(stream):
        logger.info("%s ⚠️ .strm up-to-date: %s", tag, stream.strm_path)
        return True

    # Write the file
    await asyncio.to_thread(stream.strm_path.write_text, stream.proxy_url.strip(), "utf-8")
    logger.info("%s ✅ Wrote .strm: %s", tag, stream.strm_path)
    return True


async def is_strm_up_to_date(stream: DispatcharrStream, encoding: str = "utf-8") -> bool:
    path: Path = stream.strm_path
    if not await asyncio.to_thread(path.exists):
        return False
    existing = await asyncio.to_thread(path.read_text, encoding)
    return existing.strip() == stream.proxy_url.strip()


async def fetch_groups() -> List[str]:
    settings = get_settings()
    url = f"{settings.api_base}/api/channels/streams/groups/"
    resp = await _request("GET", url)
    resp.raise_for_status()
    payload = resp.json()

    # Unwrap if it’s a dict with "results"
    if isinstance(payload, dict) and "results" in payload:
        raw = payload["results"]
    elif isinstance(payload, list):
        raw = payload
    else:
        raise HTTPException(502, detail="Unexpected /groups/ response format")

    groups: list[str] = []
    for item in raw:
        # If it's already a string
        if isinstance(item, str):
            groups.append(item)
        # If it’s an object, try to pull a "name" or "group" field
        elif isinstance(item, dict):
            name = item.get("name") or item.get("group")
            if isinstance(name, str):
                groups.append(name)
    return groups


async def fetch_streams(
    group: str,
    stream_type: str,
    timeout: float = API_TIMEOUT,
) -> List[DispatcharrStream]:
    out: List[DispatcharrStream] = []
    settings = get_settings()
    url = f"{settings.api_base.rstrip('/')}\
/ api/channels/streams/"
    page = 1

    while True:
        params = {
            "search":      group,
            "stream_type": stream_type,
            "ordering":    "name",
        }
        resp = await _request("GET", url, timeout=timeout, params=params)
        resp.raise_for_status()
        body: Any = resp.json()

        items = body.get("results", body if isinstance(body, list) else [])
        for entry in items:
            try:
                out.append(DispatcharrStream.from_dict(entry))
            except Exception as e:
                logger.warning("%s Skipping invalid stream entry: %s — %s", tag, entry, e)

        if not body.get("next"):
            break
        page += 1

    return out


async def _request(
    method: str, url: str, timeout: float = API_TIMEOUT, **kwargs
) -> httpx.Response:
    # 1) grab a fresh header
    headers = await get_auth_headers()
    resp = await async_client.request(method, url, headers=headers, timeout=timeout, **kwargs)

    # 2) if we got kicked back, force-refresh & retry once
    if resp.status_code == 401:
        logger.info("[AUTH] 🔄 Token expired, refreshing & retrying")
        headers = await get_auth_headers(expired=True)
        resp = await async_client.request(method, url, headers=headers, timeout=timeout, **kwargs)

    return resp
