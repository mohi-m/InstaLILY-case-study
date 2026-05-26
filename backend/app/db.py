from pathlib import Path

import asyncpg
from pgvector.asyncpg import register_vector

from app.config import get_settings

_pool: asyncpg.Pool | None = None

MIGRATIONS_DIR = Path(__file__).resolve().parent.parent / "migrations"


async def _init_connection(conn: asyncpg.Connection) -> None:
    # pgvector codec must be registered per-connection so vector params bind.
    await register_vector(conn)


async def init_pool() -> asyncpg.Pool:
    """Create the pool (if needed) and apply migrations idempotently."""
    global _pool
    if _pool is None:
        settings = get_settings()
        _pool = await asyncpg.create_pool(
            dsn=settings.database_url,
            min_size=1,
            max_size=10,
            init=_init_connection,
        )
        await apply_migrations(_pool)
    return _pool


async def apply_migrations(pool: asyncpg.Pool) -> None:
    for sql_file in sorted(MIGRATIONS_DIR.glob("*.sql")):
        sql = sql_file.read_text()
        async with pool.acquire() as conn:
            await conn.execute(sql)


def get_pool() -> asyncpg.Pool:
    if _pool is None:
        raise RuntimeError("DB pool not initialised; call init_pool() first")
    return _pool


async def close_pool() -> None:
    global _pool
    if _pool is not None:
        await _pool.close()
        _pool = None
