from pathlib import Path

import asyncpg
from pgvector.asyncpg import register_vector

from app.config import get_settings

_pool: asyncpg.Pool | None = None

MIGRATIONS_DIR = Path(__file__).resolve().parent.parent / "migrations"


async def _init_connection(conn: asyncpg.Connection) -> None:
    # pgvector codec must be registered per-connection so vector params bind.
    await register_vector(conn)
    # Decode numeric/decimal as float so tool results stay JSON-serializable.
    # Without this, asyncpg returns Decimal, which LangChain's ToolNode can't
    # json.dumps — it falls back to a Python repr string and the rich UI cards
    # (which carry prices) degrade to an unrenderable {"text": ...} blob.
    await conn.set_type_codec(
        "numeric",
        encoder=str,
        decoder=float,
        schema="pg_catalog",
        format="text",
    )


async def init_pool() -> asyncpg.Pool:
    """Create the pool (if needed) and apply migrations idempotently."""
    global _pool
    if _pool is None:
        settings = get_settings()
        # Run migrations on a plain connection first so that
        # CREATE EXTENSION IF NOT EXISTS vector exists before the pool
        # tries to register the vector codec on every connection.
        raw = await asyncpg.connect(dsn=settings.database_url)
        try:
            await _apply_migrations_conn(raw)
        finally:
            await raw.close()
        _pool = await asyncpg.create_pool(
            dsn=settings.database_url,
            min_size=1,
            max_size=10,
            init=_init_connection,
        )
    return _pool


async def _apply_migrations_conn(conn: asyncpg.Connection) -> None:
    for sql_file in sorted(MIGRATIONS_DIR.glob("*.sql")):
        sql = sql_file.read_text()
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
