
import re
from pathlib import Path

from ..core.config import settings
from .streams import write_strm_file
from .tmdb import search_any_tmdb
from ..core.utils import clean_name, target_folder, write_if, write_movie_nfo, filter_by_threshold
from ..core.logger import setup_logger
from ..core.models import DispatcharrStream

logger = setup_logger(__name__)

RE_24_7_CLEAN  = re.compile(r"(?i)\b24[/-]7\b[\s\-:]*")

_skipped_247 = set()



from typing import Dict

def process_24_7(stream: DispatcharrStream, root: Path, group: str, headers: Dict[str, str], url: str):
    title = clean_name(RE_24_7_CLEAN.sub("", stream.name))
    if title in _skipped_247:
        return
    res = search_any_tmdb(title) if settings.tmdb_api_key else None
    if not filter_by_threshold(_skipped_247, stream.name, res):
        return
    fld = target_folder(root, "24-7", group, title)
    if not write_strm_file(fld / f"{title}.strm", headers, stream):
        return
    if settings.write_nfo and res:
        write_if(True, fld / f"{title}.nfo", write_movie_nfo, res)


