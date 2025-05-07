# strmgen/core/auth.py

import asyncio
import httpx
from typing import Dict, Callable, Awaitable, AsyncIterator

from .config import settings
from .logger import setup_logger

logger = setup_logger(__name__)

_token_lock = asyncio.Lock()
_cached_token: str = ""
_token_expires_at: float = 0.0  # UNIX timestamp when token expires

async def _fetch_new_token() -> str:
    """
    Fetch a new bearer token from the auth endpoint and update the expiry.
    """
    url = f"{settings.api_base.rstrip('/')}{settings.token_url}"
    logger.debug(f"[AUTH] Fetching new token from {url} with username={settings.username!r}")
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.post(
            url,
            json={"username": settings.username, "password": settings.password},
        )
    logger.debug(f"[AUTH] Token endpoint returned {resp.status_code}: {resp.text}")
    resp.raise_for_status()
    data = resp.json()
    token = data.get("access") or data.get("token")
    expires_in = data.get("expires_in", 3600)
    loop = asyncio.get_event_loop()
    global _token_expires_at
    _token_expires_at = loop.time() + expires_in - 60
    logger.info(f"[AUTH] Retrieved new token; expires in {expires_in}s")
    return token

async def get_auth_headers(expired: bool = False) -> Dict[str, str]:
    """
    Return Bearer token header, refreshing and caching under a lock.
    """
    global _cached_token, _token_expires_at
    async with _token_lock:
        now = asyncio.get_event_loop().time()
        if not _cached_token or now >= _token_expires_at or expired:
            try:
                _cached_token = await _fetch_new_token()
            except Exception:
                logger.exception("[AUTH] Failed to refresh token")
                raise
    return {"Authorization": f"Bearer {_cached_token}"}

async def get_access_token() -> str:
    """
    Get the raw bearer token string from cache (refreshing if needed).
    """
    headers = await get_auth_headers()
    auth_header = headers.get("Authorization", "")
    parts = auth_header.split(" ", 1)
    return parts[1] if len(parts) > 1 else ""

class TokenAuth(httpx.Auth):
    """
    HTTPX Auth plugin that injects Bearer tokens and auto-refreshes once on 401.
    """
    def __init__(
        self,
        token_getter: Callable[[], str],
        token_refresher: Callable[[], Awaitable[None]]
    ):
        self._get_token = token_getter
        self._refresh_token = token_refresher

    async def auth_flow(self, request: httpx.Request) -> AsyncIterator[httpx.Request]:
        # Attach current token
        request.headers["Authorization"] = f"Bearer {self._get_token()}"
        response = yield request

        # On 401, refresh and retry once
        if response.status_code == 401:
            logger.info("[AUTH] 🔄 Token expired, refreshing & retrying")
            await self._refresh_token()
            request.headers["Authorization"] = f"Bearer {self._get_token()}"
            yield request


def _get_token() -> str:
    """
    Return the currently cached token.
    """
    return _cached_token

async def _refresh_token() -> None:
    """
    Force-refresh the cached token by calling the header getter with expired flag.
    """
    await get_auth_headers(expired=True)
