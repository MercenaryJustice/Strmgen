# strmgen/core/string_utils.py

import re
from urllib.parse import urlsplit, urlunsplit, quote, parse_qsl, urlencode

from strmgen.core.config import get_settings

# ─── Filename Utilities ───────────────────────────────────────────────────────

def clean_name(name: str) -> str:
    """Sanitize and strip optional tokens from a name, then trim surrounding spaces."""
    settings = get_settings()
    if settings.remove_strings:
        for token in settings.remove_strings:
            name = name.replace(token, "")
    # remove illegal filesystem characters
    name = re.sub(r'[<>:"/\\|?*]', "", name)
    # strip spaces before and after
    return name.strip()


def remove_prefixes(title: str) -> str:
    """Remove configured prefixes from a title and strip whitespace."""
    settings = get_settings()
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
