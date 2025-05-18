# strmgen/core/db.py
"""Database-access layer: connection pool, skipped_streams table, etc."""

import asyncpg
import asyncio
import logging

from typing import TypedDict, Optional, Any, List
from dataclasses import is_dataclass, asdict

from strmgen.core.config import get_settings
from strmgen.core.models.dispatcharr import DispatcharrStream

logger = logging.getLogger(__name__)

_pool: asyncpg.Pool | None = None
_pool_lock = asyncio.Lock()

# ─────────────────────────────────────────────────────────────────────────────
# Connection Pool Access
# ─────────────────────────────────────────────────────────────────────────────
async def get_pg_pool() -> asyncpg.Pool:
    global _pool
    if _pool is None:
        async with _pool_lock:
            if _pool is None:
                settings = get_settings()
                _pool = await asyncpg.create_pool(dsn=settings.postgres_dsn)
    return _pool

async def init_pg_pool() -> None:
    """Explicit init (optional). Usually prefer get_pg_pool()."""
    await get_pg_pool()

async def close_pg_pool() -> None:
    """Close the asyncpg connection pool."""
    global _pool
    if _pool is not None:
        await _pool.close()
        _pool = None

# ─────────────────────────────────────────────────────────────────────────────
# State-management API
# ─────────────────────────────────────────────────────────────────────────────
async def is_skipped(stream_type: str, dispatcharr_id: int) -> bool:
    """Check if a stream is marked skipped in the DB."""
    pool = await get_pg_pool()
    row = await pool.fetchrow(
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
    """Upsert a skipped_streams record for a given stream."""
    if is_dataclass(mshow):
        data_dict = asdict(mshow) if not isinstance(mshow, type) else {}
    elif hasattr(mshow, "raw"):
        data_dict = mshow.raw
    else:
        data_dict = getattr(mshow, "__dict__", {})

    dispatcharr_id = stream.id
    tmdb_id = None
    for key in ("id", "tmdb_id", "movie_id", "show_id"):
        if key in data_dict and data_dict[key] is not None:
            tmdb_id = data_dict[key]
            break
    if tmdb_id is None:
        tmdb_id = getattr(mshow, "id", None) or getattr(mshow, "tmdb_id", None)

    name = None
    for key in ("name", "title", "original_name"):
        if key in data_dict and data_dict[key]:
            name = data_dict[key]
            break
    if name is None:
        name = getattr(mshow, "name", None) or getattr(mshow, "title", None)

    if tmdb_id is None or not name:
        logger.warning("Skipped insert: missing tmdb_id or name for %r", mshow)
        return False

    pool = await get_pg_pool()
    await pool.execute(
        """
        INSERT INTO skipped_streams
        (tmdb_id, dispatcharr_id, stream_type, group_name, name, reprocess)
        VALUES ($1, $2, $3, $4, $5, FALSE)
        ON CONFLICT (tmdb_id)
        DO UPDATE SET
            dispatcharr_id=EXCLUDED.dispatcharr_id,
            stream_type=EXCLUDED.stream_type,
            group_name=EXCLUDED.group_name,
            name=EXCLUDED.name,
            reprocess=EXCLUDED.reprocess;
        """,
        tmdb_id, dispatcharr_id, stream_type, group, name
    )
    return True

class SkippedStream(TypedDict):
    tmdb_id: int
    dispatcharr_id: int
    stream_type: str
    group: str
    name: str
    reprocess: bool

async def list_skipped(
    stream_type: Optional[str] = None,
    tmdb_id: Optional[int] = None
) -> List[SkippedStream]:
    """List skipped streams, optionally filtering by type or tmdb_id."""
    clauses: list[str] = []
    params: list[Any] = []
    if stream_type is not None:
        clauses.append(f"stream_type = ${len(params)+1}")
        params.append(stream_type)
    if tmdb_id is not None:
        clauses.append(f"tmdb_id = ${len(params)+1}")
        params.append(tmdb_id)
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    sql = (
        "SELECT tmdb_id, dispatcharr_id, stream_type, group_name AS group, "
        "name, reprocess FROM skipped_streams " + where
    )
    pool = await get_pg_pool()
    rows = await pool.fetch(sql, *params)
    return [dict(r) for r in rows]

async def set_reprocess(tmdb_id: int, allow: bool) -> None:
    """Set reprocess flag for a skipped stream."""
    pool = await get_pg_pool()
    await pool.execute(
        "UPDATE skipped_streams SET reprocess = $1 WHERE tmdb_id = $2",
        allow, tmdb_id
    )

async def update_skipped_reprocess(tmdb_id: int, stream_type: str, reprocess: bool) -> None:
    """Update reprocess for a specific tmdb_id and stream_type."""
    pool = await get_pg_pool()
    await pool.execute(
        """
        UPDATE skipped_streams
           SET reprocess = $1
         WHERE tmdb_id = $2
           AND stream_type = $3
        """,
        reprocess, tmdb_id, stream_type
    )