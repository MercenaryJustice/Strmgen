
import requests

from pathlib import Path
from typing import List, Dict, Optional, Any
from urllib.parse import quote_plus
from ..core.config import settings
from ..core.utils import safe_mkdir
from ..core.utils import setup_logger
from ..core.auth import get_access_token, refresh_access_token_if_needed
from ..core.models import Stream, DispatcharrStream
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
            body: Dict[str, Any] = {}
        if body.get("code") == "token_not_valid":
            logger.info("[AUTH] 🔄 Token expired, refreshing & retrying")
            new_token = get_access_token()
            headers["Authorization"] = f"Bearer {new_token}"
            r = func(url, headers=headers, **kwargs)
    return r

def fetch_streams_by_group_name(
    group_name: str,
    headers: Dict[str, str]
) -> List[Stream]:
    """
    Fetch all streams for a given channel group, with automatic token refresh,
    and return as a list of Stream models.
    """
    out: List[Stream] = []
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
        results = data.get("results", [])

        # parse each dict into our Pydantic model
        for item in results:
            try:
                stream = Stream(**item)
            except Exception as e:
                logger.error("Failed to parse Stream for %s: %s", item, e)
                continue
            out.append(stream)

        # no more pages?
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
    headers: Dict[str, str],
    stream: DispatcharrStream,
    timeout: int = 10
) -> bool:
    """
    Fetch stream metadata, verify reachability via is_stream_alive, write a .strm file,
    and update the stream's metadata with the local file path.
    """
    if not settings.update_stream_link and path.exists():
        return True
    info = get_stream_by_id(stream.id, headers, timeout)
    if not info:
        logger.warning("[STRM] ⚠️ Stream #%d metadata unavailable, skipping", stream.id)
        return False

    if not stream.url:
        logger.warning("[STRM] ⚠️ Stream #%d has no URL, skipping", stream.id)
        return False

    if not is_stream_alive(stream.id, headers, timeout):
        logger.warning("[STRM] ⚠️ Stream #%d unreachable, skipping", stream.id)
        return False

    safe_mkdir(path.parent)

    # If file exists, compare its contents with the current URL
    if path.exists():
        existing_url = path.read_text(encoding="utf-8").strip()
        if existing_url == stream.url.strip():
            logger.info("[STRM] ⚠️ .strm already exists and is up-to-date: %s", path)
            return True
        else:
            logger.info("[STRM] 🔄 Updating existing .strm file (URL changed): %s", path)

    # Write new or updated URL to the .strm file
    path.write_text(stream.url, encoding="utf-8")
    logger.info("[STRM] ✅ Wrote .strm: %s", path)


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
) -> Optional[Stream]:
    """
    Fetch a single channel stream's metadata via GET, with token refresh,
    and return as a Stream model.
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

        data: Dict[str, Any] = r.json()
        logger.info("[STRM] ✅ Fetched stream #%d", stream_id)

        try:
            # Parse into our Pydantic model
            return Stream(**data)
        except Exception as ve:
            logger.error(
                "[STRM] ❌ Validation error for stream #%d: %s",
                stream_id,
                ve
            )
            return None

    except Exception as e:
        logger.error(
            "[STRM] ❌ Exception fetching stream #%d: %s",
            stream_id,
            e
        )
        return None

def fetch_groups() -> List[str]:
    """
    Return the list of channel‐group names from the STRMGen API.
    """
    token = refresh_access_token_if_needed()
    headers = {"Authorization": f"Bearer {token}"}
    url = f"{settings.api_base}/api/channels/streams/groups/"
    resp = requests.get(url, headers=headers, timeout=10)
    resp.raise_for_status()
    return resp.json()