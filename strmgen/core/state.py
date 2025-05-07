# strmgen/state.py

import threading
import asyncpg
from typing import TypedDict, Optional, List, Any
from dataclasses import is_dataclass, asdict

from .config import CONFIG_PATH, settings
from .utils import setup_logger
from strmgen.core.models import DispatcharrStream, MediaType

logger = setup_logger(__name__)

_pool: asyncpg.Pool

# ——————————————————————————————————————————————————————————————————————
# State-management API
# ——————————————————————————————————————————————————————————————————————

async def is_skipped(stream_type: str, dispatcharr_id: int) -> bool:
    row = await _pool.fetchrow(
        """
        SELECT 1
          FROM skipped_streams
         WHERE stream_type = $1
           AND dispatcharr_id = $2
           AND reprocess = FALSE
        """,
        stream_type, dispatcharr_id
    )
    return row is not None


async def mark_skipped(stream_type: str, group: str, mshow: Any, stream: DispatcharrStream) -> bool:
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
    await _pool.execute(
        """
        INSERT INTO skipped_streams
        (tmdb_id, dispatcharr_id, stream_type, group_name, name, reprocess)
        VALUES ($1, $2, $3, $4, $5, FALSE)
        ON CONFLICT (tmdb_id)
        DO UPDATE SET dispatcharr_id=EXCLUDED.dispatcharr_id,
                    stream_type=EXCLUDED.stream_type,
                    group_name=EXCLUDED.group_name,
                    name=EXCLUDED.name,
                    reprocess=EXCLUDED.reprocess;
        """,
        tmdb_id, dispatcharr_id, stream_type, group, name
    )

    # if cursor.rowcount == 1:
    #     logger.info("✅ mark_skipped: inserted %s (%s)", name, tmdb_id)
    return True
    # else:
    #     logger.debug("⏭️ mark_skipped: record already exists %s (%s)", name, tmdb_id)
    #     return False

class SkippedStream(TypedDict):
    tmdb_id: int
    dispatcharr_id: int
    stream_type: str
    group: str
    name: str
    reprocess: bool

async def list_skipped(
    stream_type: Optional[str] = None,
    tmdb_id: Optional[int]  = None
) -> list[SkippedStream]:
    clauses = []
    params = []
    if stream_type is not None:
        clauses.append("stream_type = $%d" % (len(params) + 1))
        params.append(stream_type)
    if tmdb_id is not None:
        clauses.append("tmdb_id = $%d" % (len(params) + 1))
        params.append(tmdb_id)
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    sql = (
        "SELECT tmdb_id, dispatcharr_id, stream_type, group_name AS group, "
        "name, reprocess "
        "FROM skipped_streams "
        f"{where}"
    )
    rows = await _pool.fetch(sql, *params)
    return [dict(r) for r in rows]


async def set_reprocess(tmdb_id: int, allow: bool):
    await _pool.execute(
        "UPDATE skipped_streams SET reprocess = $1 WHERE tmdb_id = $2",
        allow, tmdb_id
    )

async def update_skipped_reprocess(tmdb_id: int, stream_type: str, reprocess: bool):
    await _pool.execute(
        """
        UPDATE skipped_streams
           SET reprocess = $1
         WHERE tmdb_id = $2
           AND stream_type = $3
        """,
        reprocess, tmdb_id, stream_type
    )


async def init_pg_pool():
    global _pool
    _pool = await asyncpg.create_pool(dsn=settings.postgres_dsn)

async def close_pg_pool():
    await _pool.close()        