# strmgen/core/logger.py
import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path
from logging import LoggerAdapter

# ─── Log Path ────────────────────────────────────────────────────────────────
LOG_DIR = Path(__file__).parent.parent / "logs"
LOG_DIR.mkdir(parents=True, exist_ok=True)
LOG_PATH = LOG_DIR / "strmgen.log"

# ─── Rotation Settings ───────────────────────────────────────────────────────
MAX_BYTES    = 10 * 1024 * 1024   # 10 MB
BACKUP_COUNT = 5                  # keep 5 archives

# ─── Custom Formatter ────────────────────────────────────────────────────────
class CategoryFormatter(logging.Formatter):
    def format(self, record):
        if not hasattr(record, "category"):
            record.category = record.name.upper()
        return super().format(record)

formatter = CategoryFormatter(
    fmt="%(asctime)s %(levelname)-8s [%(category)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)

# ─── File Handler with Rotation ───────────────────────────────────────────────
file_handler = RotatingFileHandler(
    filename=str(LOG_PATH),
    maxBytes=MAX_BYTES,
    backupCount=BACKUP_COUNT,
    encoding="utf-8"
)
file_handler.setFormatter(formatter)

# ─── Base Logger Setup ────────────────────────────────────────────────────────
_base_logger = logging.getLogger("strmgen")
_base_logger.setLevel(logging.INFO)
_base_logger.addHandler(file_handler)
_base_logger.propagate = False

# ─── Public API ───────────────────────────────────────────────────────────────
def setup_logger(category: str) -> LoggerAdapter:
    """
    Get a logger that tags every record with a CATEGORY.
    Usage in your routers or modules:
        from strmgen.core.logger import LOG_PATH, setup_logger

        logger = setup_logger("CIRCULATION")
        logger.info("Circulation task started")
    """
    return LoggerAdapter(_base_logger, {"category": category.upper()})


