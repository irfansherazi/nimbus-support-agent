"""Connection pool and a minimal ordered-SQL-file migrator."""

import asyncio
import sys
from pathlib import Path

from pgvector.psycopg import register_vector_async
from psycopg import AsyncConnection, AsyncCursor
from psycopg.rows import DictRow, dict_row
from psycopg_pool import AsyncConnectionPool

if sys.platform == "win32":  # psycopg's async driver needs the selector loop on Windows (local dev only)
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())  # type: ignore[attr-defined]


Conn = AsyncConnection[DictRow]
Pool = AsyncConnectionPool[Conn]


async def one(cur: AsyncCursor[DictRow]) -> DictRow:
    """fetchone() for statements that always return a row (INSERT ... RETURNING, aggregates)."""
    row = await cur.fetchone()
    if row is None:
        raise LookupError("expected a row, got none")
    return row


async def _configure(conn: Conn) -> None:
    await register_vector_async(conn)


async def create_pool(url: str, min_size: int = 1, max_size: int = 10) -> Pool:
    pool: Pool = AsyncConnectionPool(
        url,
        min_size=min_size,
        max_size=max_size,
        kwargs={"row_factory": dict_row, "autocommit": True},
        configure=_configure,
        open=False,
    )
    await pool.open(wait=True)
    return pool


async def run_sql_file(pool: Pool, path: Path) -> None:
    async with pool.connection() as conn:
        await conn.execute(path.read_text(encoding="utf-8"))  # type: ignore[arg-type]


async def migrate(pool: Pool, migrations_dir: Path) -> list[str]:
    """Apply every *.sql file in name order that is not yet recorded. Returns the names applied."""
    applied: list[str] = []
    async with pool.connection() as conn:
        await conn.execute(
            "CREATE TABLE IF NOT EXISTS schema_migrations (name text PRIMARY KEY, applied_at timestamptz DEFAULT now())"
        )
        done = {r["name"] for r in await (await conn.execute("SELECT name FROM schema_migrations")).fetchall()}
        for path in sorted(migrations_dir.glob("*.sql")):
            if path.name in done:
                continue
            async with conn.transaction():
                await conn.execute(path.read_text(encoding="utf-8"))  # type: ignore[arg-type]
                await conn.execute("INSERT INTO schema_migrations (name) VALUES (%s)", (path.name,))
            applied.append(path.name)
    return applied
