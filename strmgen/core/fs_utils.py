import re
from pathlib import Path

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