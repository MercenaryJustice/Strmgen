
import re
from pathlib import Path
from typing import Optional

from .config import settings
from .subtitles import download_movie_subtitles, download_episode_subtitles
from .streams import write_strm_file
from .tmdb_helpers import search_any_tmdb
from .utils import clean_name, target_folder, write_if, write_movie_nfo, filter_by_threshold
from .log import setup_logger
logger = setup_logger(__name__)

RE_24_7_CLEAN  = re.compile(r"(?i)\b24[/-]7\b[\s\-:]*")

_skipped_247 = set()

def meets_thresholds(meta: dict) -> bool:
    lang = settings.tmdb_language.split("-")[0].casefold()
    if (not meta.get("original_language", "").casefold() == lang):
        return False
    if settings.check_tmdb_thresholds:
        return (
            meta.get("vote_average", 0) >= settings.minimum_tmdb_rating and
            meta.get("vote_count", 0) >= settings.minimum_tmdb_votes and
            meta.get("popularity", 0) >= settings.minimum_tmdb_popularity
        )
    return True



def process_24_7(name: str, sid: int, root: Path, group: str, headers: dict, url: str):
    title = clean_name(RE_24_7_CLEAN.sub("", name))
    if title in _skipped_247:
        return
    res = search_any_tmdb(title) if settings.tmdb_api_key else None
    if not filter_by_threshold(_skipped_247, name, res):
        return
    fld = target_folder(root, "24-7", group, title)
    if not write_strm_file(fld / f"{title}.strm", sid, headers, url):
        return
    if settings.write_nfo and res:
        write_if(True, fld / f"{title}.nfo", write_movie_nfo, res)


