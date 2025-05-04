# strmgen/services/_24_7.py

import re
import asyncio
from pathlib import Path
from typing import Dict, Optional, List

from ..core.config import settings
from .streams import write_strm_file
from .tmdb import search_any_tmdb
from ..core.fs_utils import clean_name
from ..core.utils import write_if, write_movie_nfo, filter_by_threshold
from ..core.logger import setup_logger
from ..core.models import DispatcharrStream

logger = setup_logger(__name__)

RE_24_7_CLEAN = re.compile(r"(?i)\b24[/-]7\b[\s\-:]*")
_skipped_247: set[str] = set()


async def process_24_7(
    streams: List[DispatcharrStream],
    group: str,
    headers: Dict[str, str]
) -> None:
    """
    Async processing for 24/7 streams:
      - Clean title
      - Optional TMDb lookup & threshold filter
      - Write .strm file
      - Write .nfo if enabled
    """
    for stream in streams:
        try:
            # 1) Clean the title
            title = clean_name(RE_24_7_CLEAN.sub("", stream.name))
            if title in _skipped_247:
                return

            # 2) Fetch metadata from TMDb if configured
            metadata: Optional[dict] = None
            if settings.tmdb_api_key:
                try:
                    metadata = await search_any_tmdb(title)
                except Exception:
                    logger.exception("Error fetching TMDb data for '%s'", title)

            # 3) Apply threshold filter (offload if heavy)
            try:
                ok = await asyncio.to_thread(filter_by_threshold, stream.name, metadata)
            except Exception:
                logger.exception("Error in threshold filter for '%s'", title)
                return

            if not ok:
                return

            # 5) Write the .strm file
            try:
                wrote = await write_strm_file(stream)
            except Exception:
                logger.exception("Error writing .strm for '%s'", title)
                return

            if not wrote:
                return

            # 6) Write NFO if enabled and we have metadata
            if settings.write_nfo and metadata:
                try:
                    # Use to_thread for the write_if helper
                    await asyncio.to_thread(
                        write_if,
                        True,
                        stream,
                        write_movie_nfo,
                        metadata
                    )
                except Exception:
                    logger.exception("Error writing .nfo for '%s'", title)
        except Exception as e:  # Catch all exceptions to avoid crashing the loop
            logger.error("Error processing stream %s: %s", stream.name, e)
            continue
    logger.info("Completed processing 24/7 streams for group: %s", group)
