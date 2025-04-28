# strmgen/log.py

import logging
import os
from logging.handlers import RotatingFileHandler
from pathlib import Path

# ─── New log folder under the strmgen package ───────────────────────────────
# e.g. /path/to/Strmgen/strmgen/logs/app.log
LOG_PATH = Path(__file__).resolve().parent / "logs" / "app.log"

# Read handler preference from LOG_HANDLERS env var (default "both")
# Valid values: "console", "file", "both" (comma-sep also ok: "console,file")
raw = os.getenv("LOG_HANDLERS", "file").lower()
handler_flags = {h.strip() for h in raw.split(",")}
WRITE_CONSOLE = "console" in handler_flags or "both" in handler_flags
WRITE_FILE    = "file"    in handler_flags or "both" in handler_flags

def setup_logger(name: str) -> logging.Logger:
    """
    Configure and return a named logger that writes to both console
    and a rotating file in strmgen/logs/app.log.
    """
    logger = logging.getLogger(name)
    logger.setLevel(logging.DEBUG)

    # Prevent double-logging if setup_logger called multiple times
    if logger.handlers:
        return logger

    # Formatter for console
    fmt_console = logging.Formatter(
        "%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    # Formatter for file (with module name)
    fmt_file = logging.Formatter(
        "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    # Console handler
    if WRITE_CONSOLE:
        ch = logging.StreamHandler()
        ch.setLevel(logging.DEBUG)
        ch.setFormatter(fmt_console)
        logger.addHandler(ch)

    # File handler (rotate at 5MB, keep 3 backups)
    if WRITE_FILE:
        # ensure directory exists
        LOG_PATH.parent.mkdir(parents=True, exist_ok=True)

        fh = RotatingFileHandler(
            filename=str(LOG_PATH),
            maxBytes=5 * 1024 * 1024,
            backupCount=3,
            encoding="utf-8",
        )
        fh.setLevel(logging.INFO)
        fh.setFormatter(fmt_file)
        logger.addHandler(fh)

    return logger