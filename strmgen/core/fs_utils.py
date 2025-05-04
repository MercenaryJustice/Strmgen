import re
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit, quote, parse_qsl, urlencode


from .logger import setup_logger
from .config import settings


logger = setup_logger(__name__)

# ─── Filesystem Helpers ───────────────────────────────────────────────────────

def safe_mkdir(path: Path) -> None:
    """Safely create a directory tree if not exists."""
    try:
        path.mkdir(parents=True, exist_ok=True)
        logger.debug("Created directory: %s", path)
    except Exception as e:
        logger.error("Failed to create directory %s: %s", path, e)

# ─── Filename Utilities ───────────────────────────────────────────────────────

def clean_name(name: str) -> str:
    """Sanitize and strip optional tokens from a name."""
    if settings.remove_strings:
        for token in settings.remove_strings:
            name = name.replace(token, "")
    return re.sub(r'[<>:"/\\|?*]', "", name)

def remove_prefixes(title: str) -> str:
    for bad in settings.remove_strings:
        title = title.replace(bad, "").strip()
    return title        



def fix_url_string(raw_url: str) -> str:
    """
    1. Splits into (scheme, netloc, path, query, fragment).
    2. Collapses multiple slashes in the *path* only.
    3. Percent‑encodes the path and query.
    4. Re‑assembles with urlunsplit, preserving 'http://' or 'https://'.
    """
    scheme, netloc, path, query, fragment = urlsplit(raw_url)

    # collapse runs of '/' in the *path* to a single '/'
    normalized_path = re.sub(r'/{2,}', '/', path)

    # percent‑encode remaining unsafe characters
    safe_path = quote(normalized_path, safe="/")

    # re‑encode query parameters
    query_params = parse_qsl(query, keep_blank_values=True)
    safe_query = urlencode(query_params, doseq=True)

    return urlunsplit((scheme, netloc, safe_path, safe_query, fragment))