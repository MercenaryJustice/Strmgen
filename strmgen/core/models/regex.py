# strmgen/core/models/regex.py
import re

from strmgen.core.config import get_settings

# Regex to extract movie title and year (1900–2099)
TITLE_YEAR_RE = re.compile(
    r"""
    ^\s*                                 # leading whitespace   
    (?P<title>.+?)                       # minimally grab the title  
    [\s\.\-_]*                        # optional separators  
    (?:\(|\[)?                         # optional opening ( or [
    (?P<year>(?:19|20)\d{2})            # capture a 4‑digit year 1900–2099
    (?:\)|\])?                         # optional closing ) or ]
    \s*$                                 # trailing whitespace to end
    """,
    re.VERBOSE,
)

# Regex for TV series SxxExx tags, pulled from in-memory settings
RE_EPISODE_TAG = get_settings().TV_SERIES_EPIDOSE_RE
