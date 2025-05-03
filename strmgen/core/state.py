# strmgen/state.py

import sqlite3
import json
from typing import TypedDict, Optional, List, Any
from dataclasses import is_dataclass, asdict

from .config import CONFIG_PATH
from .utils import setup_logger
from strmgen.core.models import DispatcharrStream

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


    # ——————————————————————————————
    # 2) Ensure our version‐tracking table exists
    # ——————————————————————————————
    _conn.execute("""
      CREATE TABLE IF NOT EXISTS schema_version (
        version INTEGER NOT NULL
      );
    """)
    # If it’s brand new, insert version 0
    cur = _conn.execute("SELECT COUNT(*) FROM schema_version").fetchone()
    if cur[0] == 0:
        _conn.execute("INSERT INTO schema_version (version) VALUES (0)")
    _conn.commit()

    # ——————————————————————————————
    # 3) Fetch the current version
    # ——————————————————————————————
    cur = _conn.execute("SELECT version FROM schema_version").fetchone()
    current_version = cur["version"] if isinstance(cur, sqlite3.Row) else cur[0]

    # ——————————————————————————————
    # 4) List out migrations in order
    # ——————————————————————————————
    migrations = [
        (1, """
            ALTER TABLE skipped_streams
            ADD COLUMN dispatcharr_id INTEGER NOT NULL DEFAULT 0
        """),
        (2, """
            CREATE INDEX IF NOT EXISTS idx_skipped_dispatcharr
              ON skipped_streams(dispatcharr_id)
        """),
        # future migrations: (3, "... DDL or data changes ..."),
    ]

    # ——————————————————————————————
    # 5) Apply any pending migrations
    # ——————————————————————————————
    for target_version, sql in migrations:
        if current_version < target_version:
            try:
                # apply the migration
                _conn.execute(sql)
                _conn.execute(
                    "UPDATE schema_version SET version = ?", (target_version,)
                )
                _conn.commit()
                current_version = target_version
                logger.info("Migrated DB schema to version %d", target_version)
            except Exception as e:
                # Log the error *and* the SQL that failed
                logger.warning(
                    "Skipping migration %d due to error: %s\nSQL:\n%s",
                    target_version,
                    e,
                    sql
                )
                _conn.rollback()
                continue

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


def mark_skipped(stream_type: str, group: str, mshow: Any, stream: DispatcharrStream) -> bool:
    """
    Insert a row into skipped_streams for the given stream_type and group.
    Supports dataclass Movie/TVShow, objects with a .raw attr, or plain objects.
    """
    # 1) Serialization
    if is_dataclass(mshow):
        data_dict = asdict(mshow) if not isinstance(mshow, type) else {}
    elif hasattr(mshow, "raw"):
        data_dict = mshow.raw
    else:
        data_dict = getattr(mshow, "__dict__", {})

    dispatcharr_id = stream.id

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
        return False


    # 5) Upsert (insert new or update existing)
    sql = """
        INSERT INTO skipped_streams
          (tmdb_id, dispatcharr_id, stream_type, group_name, name, data, reprocess)
        VALUES (?,      ?,              ?,           ?,          ?,    ?,       ?)
        ON CONFLICT(tmdb_id) DO UPDATE SET
          dispatcharr_id = excluded.dispatcharr_id,
          stream_type    = excluded.stream_type,
          group_name     = excluded.group_name,
          name           = excluded.name,
          data           = excluded.data,
          reprocess      = excluded.reprocess
    """
    try:
        cursor = _conn.execute(
            sql,
            (
                tmdb_id,
                dispatcharr_id,
                stream_type,
                group,
                name,
                json.dumps(data_dict),
                0,  # always reset reprocess to “skip next runs”
            ),
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

class SkippedStream(TypedDict):
    tmdb_id: int
    dispatcharr_id: int
    stream_type: str
    group: str
    name: str
    data: dict[str, Any]
    reprocess: bool

def list_skipped(stream_type: Optional[str] = None, tmdb_id: Optional[int] = None) -> List[SkippedStream]:
    """
    Return a list of all rows in skipped_streams as dicts:
    [{ "tmdb_id": ..., "dispatcharr_id": ..., "stream_type": ..., "group": ..., "name": ..., "data": ..., "reprocess": ... }, ...]
    """
    if stream_type is None:
        rows = _conn.execute(
            "SELECT tmdb_id, dispatcharr_id, stream_type, group_name, name, data, reprocess FROM skipped_streams"
        ).fetchall()
    elif tmdb_id is not None:
        rows = _conn.execute(
            "SELECT tmdb_id, dispatcharr_id, stream_type, group_name, name, data, reprocess FROM skipped_streams WHERE stream_type=? AND tmdb_id=?",
            (stream_type, tmdb_id),
        ).fetchall()
    else:
        rows = _conn.execute(
            "SELECT tmdb_id, dispatcharr_id, stream_type, group_name, name, data, reprocess FROM skipped_streams WHERE stream_type=?",
            (stream_type,),
        ).fetchall()
    out: List[SkippedStream] = []
    for r in rows:
        out.append({
            "tmdb_id":     r["tmdb_id"],
            "dispatcharr_id":     r["dispatcharr_id"],
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