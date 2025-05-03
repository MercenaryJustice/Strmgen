# strmgen/core/auth.py

import asyncio
from typing import Dict
from .http import async_client
from .config import settings
from .logger import setup_logger

logger = setup_logger(__name__)

_token_lock = asyncio.Lock()
_cached_token: str = ""
_token_expires_at: float = 0.0  # UNIX timestamp

async def _fetch_new_token() -> str:
    """
    Actually call your token endpoint (settings.token_url) with
    username/password, parse the JSON, and return the raw token string.
    """
    url = f"{settings.api_base.rstrip('/')}{settings.token_url}"
    logger.debug(f"[AUTH] Fetching new token from {url} with username={settings.username!r}")
    payload = {
        "username": settings.username,
        "password": settings.password,
    }
    # reuse the single shared AsyncClient
    resp = await async_client.post(url, json=payload, timeout=10)
    logger.debug(f"[AUTH] Token endpoint returned {resp.status_code}: {resp.text}")
    resp.raise_for_status()
    data = resp.json()
    # adjust the key here to whatever your API returns
    token = data.get("access") or data.get("token")
    expires_in = data.get("expires_in", 3600)
    # schedule expiration 60s earlier for safety
    loop = asyncio.get_event_loop()
    global _token_expires_at
    _token_expires_at = loop.time() + expires_in - 60
    logger.info("[AUTH] Retrieved new token; expires in %ds", expires_in)
    return token

async def get_auth_headers() -> Dict[str, str]:
    """
    Return a fresh Bearer token header, caching it until just before expiry.
    """
    global _cached_token, _token_expires_at
    async with _token_lock:
        now = asyncio.get_event_loop().time()
        if not _cached_token or now >= _token_expires_at:
            try:
                _cached_token = await _fetch_new_token()
            except Exception:
                logger.exception("[AUTH] Failed to refresh token")
                raise
    return {"Authorization": f"Bearer {_cached_token}"}

async def get_access_token() -> str:
    """
    Async helper to retrieve the raw bearer token string.
    """
    headers = await get_auth_headers()
    auth = headers.get("Authorization", "")
    parts = auth.split(" ", 1)
    return parts[1] if len(parts) > 1 else ""