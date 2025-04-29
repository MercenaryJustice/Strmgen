# strmgen/state.py

import sqlite3
import json
from pathlib import Path
from typing import Optional, Any
from dataclasses import is_dataclass, asdict

from .config import CONFIG_PATH
from .log import setup_logger

logger = setup_logger(__name__)


# ——————————————————————————————————————————————————————————————————————
# Database setup
# ——————————————————————————————————————————————————————————————————————

# Place the SQLite file alongside config.json
DB_PATH = CONFIG_PATH.parent / "state.db"

# We use a single connection for the life of the app
_conn = sqlite3.connect(DB_PATH, check_same_thread=False)
_conn.row_factory = sqlite3.Row


def _init_db() -> None:
    """Create the skipped_streams table if it doesn't exist."""
    _conn.execute(
        """
        CREATE TABLE IF NOT EXISTS skipped_streams (
          tmdb_id     INTEGER PRIMARY KEY,
          stream_type TEXT    NOT NULL,
          group_name  TEXT    NOT NULL,
          name        TEXT    NOT NULL,
          data        TEXT    NOT NULL,
          reprocess   INTEGER NOT NULL   -- 0 = keep skipping, 1 = allow next run
        );
        """
    )
    _conn.commit()

# initialize on import
_init_db()


# ——————————————————————————————————————————————————————————————————————
# State-management API
# ——————————————————————————————————————————————————————————————————————

def is_skipped(stream_type: str, tmdb_id: int) -> bool:
    """
    Return True if the given TMDb ID exists in our table with reprocess=0.
    """
    row = _conn.execute(
        "SELECT 1 FROM skipped_streams WHERE stream_type=? AND tmdb_id=? AND reprocess=0",
        (stream_type, tmdb_id),
    ).fetchone()
    return bool(row)


def mark_skipped(stream_type: str, group: str, mshow: Any) -> bool:
    """
    Insert a row into skipped_streams for the given stream_type and group.
    Supports dataclass Movie/TVShow, objects with a .raw attr, or plain objects.
    """
    # 1) Serialization
    if is_dataclass(mshow):
        data_dict = asdict(mshow)
    elif hasattr(mshow, "raw"):
        data_dict = mshow.raw
    else:
        data_dict = getattr(mshow, "__dict__", {})

    # 2) Pick an ID field
    tmdb_id = None
    for key in ("id", "tmdb_id", "movie_id", "show_id"):
        if key in data_dict and data_dict[key] is not None:
            tmdb_id = data_dict[key]
            break
    if tmdb_id is None:
        tmdb_id = getattr(mshow, "id", None) or getattr(mshow, "tmdb_id", None)

    # 3) Pick a human‐readable name/title
    name = None
    for key in ("name", "title", "original_name"):
        if key in data_dict and data_dict[key]:
            name = data_dict[key]
            break
    if name is None:
        name = getattr(mshow, "name", None) or getattr(mshow, "title", None)

    # 4) If we still don’t have both, warn & bail
    if tmdb_id is None or not name:
        logger.warning("Skipped insert: could not determine tmdb_id or name from %r", mshow)
        return


    try:
        # 5) Finally insert (ignore if already exists)
        cursor = _conn.execute(
            """
            INSERT OR IGNORE INTO skipped_streams
            (tmdb_id, stream_type, group_name, name, data, reprocess)
            VALUES (?,      ?,           ?,          ?,    ?,       ?)
            """,
            (tmdb_id, stream_type, group, name, json.dumps(data_dict), 0)
        )
        _conn.commit()
    except Exception as e:
        logger.error("Failed to insert skipped stream for %s: %s", name, e)
        return False

    if cursor.rowcount == 1:
        logger.info("✅ mark_skipped: inserted %s (%s)", name, tmdb_id)
        return True
    else:
        logger.debug("⏭️ mark_skipped: record already exists %s (%s)", name, tmdb_id)
        return False

def list_skipped(stream_type: Optional[str] = None) -> list[dict]:
    """
    Return a list of all rows in skipped_streams as dicts:
    [{ "tmdb_id": ..., "stream_type": ..., "group": ..., "name": ..., "data": ..., "reprocess": ... }, ...]
    """
    if stream_type is None:
        rows = _conn.execute(
            "SELECT tmdb_id, stream_type, group_name, name, data, reprocess FROM skipped_streams"
        ).fetchall()
    else:
        rows = _conn.execute(
            "SELECT tmdb_id, stream_type, group_name, name, data, reprocess FROM skipped_streams WHERE stream_type=?",
            (stream_type,),
        ).fetchall()
    out = []
    for r in rows:
        out.append({
            "tmdb_id":     r["tmdb_id"],
            "stream_type": r["stream_type"],
            "group":       r["group_name"],
            "name":        r["name"],
            "data":        json.loads(r["data"]),
            "reprocess":   bool(r["reprocess"]),
        })
    return out


def set_reprocess(tmdb_id: int, allow: bool) -> None:
    """
    Toggle whether this show should be reprocessed on the next run.
    `allow=True` sets reprocess=1, `allow=False` sets reprocess=0.
    """
    _conn.execute(
        "UPDATE skipped_streams SET reprocess=? WHERE tmdb_id=?",
        (1 if allow else 0, tmdb_id)
    )
    _conn.commit()


def update_skipped_reprocess(tmdb_id: int, stream_type: str, reprocess: bool) -> None:
    """
    Toggle the `reprocess` flag for a skipped_stream.
    """
    _conn.execute(
        "UPDATE skipped_streams SET reprocess = ? WHERE tmdb_id = ? AND stream_type = ?",
        (1 if reprocess else 0, tmdb_id, stream_type),
    )
    _conn.commit()