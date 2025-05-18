# strmgen/services/service_24_7.py

import re
import logging

from typing import List

from .streams import write_strm_file
from strmgen.core.string_utils import clean_name
from strmgen.core.models.dispatcharr import DispatcharrStream

logger = logging.getLogger(__name__)
RE_24_7_CLEAN = re.compile(r"(?i)\b24[/-]7\b[\s\-:]*")
_skipped_247: set[str] = set()

async def process_24_7(
    streams: List[DispatcharrStream],
    group: str
) -> None:
    """
    Async processing for 24/7 streams:
      - Clean title
      - Optional TMDb lookup & threshold filter
      - Write .strm file
      - Write .nfo if enabled
    """
    # settings = get_settings()

    for stream in streams:
        try:
            # 1) Clean the title
            title = clean_name(RE_24_7_CLEAN.sub("", stream.name))
            if title in _skipped_247:
                return

            try:
                wrote = await write_strm_file(stream)
            except Exception:
                logger.exception("Error writing .strm for '%s'", title)
                return

            if not wrote:
                return
        except Exception as e:
            logger.error("Error processing stream %s: %s", stream.name, e)
            continue
    logger.info("Completed processing 24/7 streams for group: %s", group)
