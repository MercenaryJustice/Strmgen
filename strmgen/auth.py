
import requests
from typing import Optional
from config import settings
from utils import setup_logger
logger = setup_logger(__name__)

API_SESSION = requests.Session()

def get_access_token() -> Optional[str]:
    if not settings.token_url:
        raise ValueError("Missing 'token_url'")
    url = f"{settings.api_base}/{settings.token_url.lstrip('/')}"
    if not settings.username or not settings.password:
        raise ValueError("Missing username/password in config")
    try:
        r = API_SESSION.post(
            url,
            json={"username": settings.username, "password": settings.password},
            timeout=10
        )
        r.raise_for_status()
        tokens = r.json()
        settings.access = tokens.get("access")
        settings.refresh = tokens.get("refresh")
        return settings.access
    except requests.RequestException:
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
    except requests.RequestException:
        return get_access_token()

