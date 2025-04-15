
import requests

from pathlib import Path
from typing import List, Dict, Optional, Any
from urllib.parse import quote_plus
from config import settings
from utils import safe_mkdir
from utils import setup_logger
from auth import get_access_token
logger = setup_logger(__name__)

API_SESSION = requests.Session()

def _request_with_refresh(
    method: str,
    url: str,
    headers: Dict[str, str],
    **kwargs: Any
) -> requests.Response:
    """
    Perform the HTTP request and refresh the access token once on a 401 token_not_valid.
    """
    func = getattr(API_SESSION, method)
    r = func(url, headers=headers, **kwargs)
    if r.status_code == 401:
        # Attempt to parse body for token expiration
        try:
            body = r.json()
        except ValueError:
            body = {}
        if body.get("code") == "token_not_valid":
            logger.info("[AUTH] 🔄 Token expired, refreshing & retrying")
            new_token = get_access_token()
            headers["Authorization"] = f"Bearer {new_token}"
            r = func(url, headers=headers, **kwargs)
    return r


def fetch_streams_by_group_name(
    group_name: str,
    headers: Dict[str, str]
) -> List[Dict[str, Any]]:
    """
    Fetch all streams for a given channel group, with automatic token refresh.
    """
    out: List[Dict[str, Any]] = []
    page = 1
    enc = quote_plus(group_name)
    while True:
        url = (
            f"{settings.api_base}/api/channels/streams/"
            f"?page={page}&page_size=250&ordering=name&channel_group={enc}"
        )
        r = _request_with_refresh("get", url, headers, timeout=10)
        if not r.ok:
            logger.error(
                "[STRM] ❌ Error fetching streams for group '%s': %d %s",
                group_name,
                r.status_code,
                r.text
            )
            break
        data = r.json()
        out.extend(data.get("results", []))
        if not data.get("next"):
            break
        page += 1
    return out


def is_stream_alive(
    stream_id: int,
    headers: Dict[str, str],
    timeout: int = 5
) -> bool:
    if settings.skip_stream_check:
        return True
    try:
        url = f"{settings.api_base}/api/channels/streams/{stream_id}/"
        r = _request_with_refresh("get", url, headers, timeout=timeout)
        r.raise_for_status()
        stream_url = r.json().get("url")
        return bool(stream_url and API_SESSION.head(stream_url, timeout=timeout).ok)
    except Exception:
        return False



def write_strm_file(
    path: Path,
    stream_id: int,
    headers: Dict[str, str],
    dispatcharr_url: str = "",
    timeout: int = 10
) -> bool:
    """
    Fetch stream metadata, verify reachability via is_stream_alive, write a .strm file,
    and update the stream's metadata with the local file path.
    """
    if not settings.update_stream_link and path.exists():
        return True
    info = get_stream_by_id(stream_id, headers, timeout)
    if not info:
        logger.warning("[STRM] ⚠️ Stream #%d metadata unavailable, skipping", stream_id)
        return False

    #current_url = info.get("url")
    current_url = dispatcharr_url
    if not current_url:
        logger.warning("[STRM] ⚠️ Stream #%d has no URL, skipping", stream_id)
        return False

    if not is_stream_alive(current_url, timeout):
        logger.warning("[STRM] ⚠️ Stream #%d unreachable, skipping", stream_id)
        return False

    safe_mkdir(path.parent)

    # If file exists, compare its contents with the current URL
    if path.exists():
        existing_url = path.read_text(encoding="utf-8").strip()
        if existing_url == current_url.strip():
            logger.info("[STRM] ⚠️ .strm already exists and is up-to-date: %s", path)
            return True
        else:
            logger.info("[STRM] 🔄 Updating existing .strm file (URL changed): %s", path)

    # Write new or updated URL to the .strm file
    path.write_text(current_url, encoding="utf-8")
    logger.info("[STRM] ✅ Wrote .strm: %s → %s", path, current_url)


    # # local_file update currently not supported by Dispatcharr
    # # Merge existing metadata, exclude read-only fields, and update local_file
    # payload = {k: v for k, v in info.items() if k not in ('id', 'updated_at')}
    # payload["local_file"] = str(path)
    # try:
    #     response = update_stream_metadata(stream_id, payload, headers)
    #     if response is not None:
    #         logger.info("[STRM] 📌 Updated metadata local_file for stream #%d", stream_id)
    # except Exception as e:
    #     logger.warning("[STRM] ⚠️ Failed to update metadata for stream #%d: %s", stream_id, e)

    return True


def get_stream_by_id(
    stream_id: int,
    headers: Dict[str, str],
    timeout: int = 10
) -> Optional[Dict[str, Any]]:
    """
    Fetch a single channel stream's metadata via GET, with token refresh.
    """
    url = f"{settings.api_base}/api/channels/streams/{stream_id}/"
    try:
        r = _request_with_refresh("get", url, headers, timeout=timeout)
        if not r.ok:
            logger.error(
                "[STRM] ❌ Error fetching stream #%d: %d %s",
                stream_id,
                r.status_code,
                r.text
            )
            return None
        logger.info("[STRM] ✅ Fetched stream #%d", stream_id)
        return r.json()
    except Exception as e:
        logger.error(
            "[STRM] ❌ Exception fetching stream #%d: %s",
            stream_id,
            e
        )
        return None


def update_stream_metadata(
    stream_id: int,
    data: Dict[str, Any],
    headers: Dict[str, str],
    timeout: int = 10
) -> Optional[Dict[str, Any]]:
    """
    Update a channel stream's metadata via PUT, with token refresh.
    """
    url = f"{settings.api_base}/api/channels/streams/{stream_id}/"
    # Exclude read-only fields
    clean_data = {k: v for k, v in data.items() if k not in ('id', 'updated_at')}
    try:
        files = None
        headers_for_call = headers.copy()
        if 'local_file' in clean_data:
            local_path = clean_data.pop('local_file')
            try:
                files = {'local_file': open(local_path, 'rb')}
            except Exception as fe:
                logger.error(
                    "[STRM] ❌ Could not open local_file '%s': %s",
                    local_path,
                    fe
                )
                return None
            # Remove JSON header to allow multipart
            headers_for_call.pop('Content-Type', None)
            r = _request_with_refresh(
                "put",
                url,
                headers_for_call,
                data=clean_data,
                files=files,
                timeout=timeout
            )
            for f in files.values():
                f.close()
        else:
            r = _request_with_refresh(
                "put",
                url,
                {**headers, 'Content-Type': 'application/json'},
                json=clean_data,
                timeout=timeout
            )
        if not r.ok:
            logger.error(
                "[STRM] ❌ Error updating stream #%d: %d %s",
                stream_id,
                r.status_code,
                r.text
            )
            return None
        logger.info("[STRM] ✅ Updated stream #%d", stream_id)
        return r.json()
    except Exception as e:
        logger.error(
            "[STRM] ❌ Exception updating stream #%d: %s",
            stream_id,
            e
        )
        return None
