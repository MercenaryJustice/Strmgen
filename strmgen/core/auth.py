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
    Internal: request a new access token and update the expiry cache.
    """
    payload = {
        "grant_type": "password",
        "username": settings.username,
        "password": settings.password,
    }
    token_url = f"{settings.api_base}{settings.token_url}"
    resp = await async_client.post(token_url, data=payload, timeout=10.0)
    resp.raise_for_status()
    body = resp.json()
    token = body.get("access_token")
    # schedule refresh a minute before expiry
    global _token_expires_at
    expires_in = body.get("expires_in", 3600)
    _token_expires_at = asyncio.get_event_loop().time() + expires_in - 60
    logger.info("[AUTH] ✅ Fetched new token, expires at %s", _token_expires_at)
    return token

async def get_auth_headers() -> Dict[str, str]:
    """
    Async getter for fresh authorization headers.
    Caches the token until shortly before expiration.
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