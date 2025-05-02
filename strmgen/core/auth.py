
import requests
import json
from pathlib import Path
from typing import Optional, Dict, Any
from strmgen.core.config import settings, BASE_DIR
from strmgen.core.utils import setup_logger
from requests import RequestException

from strmgen.core.http import session as API_SESSION

logger = setup_logger(__name__)

CONFIG_PATH: Path = BASE_DIR / "config.json"

def get_access_token() -> Optional[str]:
    """
    Fetches a fresh access token (and refresh token) from the API,
    updates `settings.access` and `settings.refresh`, and
    writes those back into config.json.
    """
    if not settings.token_url:
        raise ValueError("Missing 'token_url' in settings")

    # assemble URL (avoid double slashes)
    url = f"{settings.api_base.rstrip('/')}/{settings.token_url.lstrip('/')}"
    if not settings.username or not settings.password:
        raise ValueError("Missing username/password in settings")

    try:
        response = API_SESSION.post(
            url,
            json={"username": settings.username, "password": settings.password},
            timeout=10,
        )
        response.raise_for_status()
        tokens: Dict[str, Any] = response.json()

        # update in-memory settings
        access_token = tokens.get("access")
        refresh_token = tokens.get("refresh")
        settings.access = access_token
        settings.refresh = refresh_token

        # persist back to config.json
        try:
            # load existing JSON (or start with empty dict)
            if CONFIG_PATH.exists():
                cfg: Dict[str, Any] = json.loads(
                    CONFIG_PATH.read_text(encoding="utf-8")
                )
            else:
                cfg = {}

            # overwrite/add our tokens
            cfg["access"] = access_token
            cfg["refresh"] = refresh_token

            # write back (pretty‐printed)
            CONFIG_PATH.write_text(
                json.dumps(cfg, indent=4, ensure_ascii=False),
                encoding="utf-8",
            )
        except Exception as e:
            # if you have a logger, you could log this warning instead
            print(f"⚠️ Warning: failed to write tokens to {CONFIG_PATH}: {e}")

        return access_token

    except RequestException as exc:
        # you could log the exception here as well
        return None

def refresh_access_token_if_needed() -> Optional[str]:
    access = settings.access
    if not access:
        return get_access_token()
    headers = {"Authorization": f"Bearer {access}"}
    try:
        r = API_SESSION.get(f"{settings.api_base}/api/core/settings/", headers=headers, timeout=10)
        if r.status_code == 401:
            return get_access_token()
        return access
    except RequestException:
        return get_access_token()
