from collections.abc import AsyncIterator

import httpx
import pytest

import app.db  # noqa: F401  (sets the Windows selector event-loop policy before any loop exists)
from app.config import Settings
from app.main import create_app


def make_settings(**overrides: object) -> Settings:
    base: dict[str, object] = {"frontend_origin": "http://localhost:3000"}
    base.update(overrides)
    return Settings(_env_file=None, **base)  # type: ignore[call-arg]


@pytest.fixture
async def client() -> AsyncIterator[httpx.AsyncClient]:
    app = create_app(make_settings())
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


# ---------------------------------------------------------------- database
from pathlib import Path  # noqa: E402

BACKEND_DIR = Path(__file__).resolve().parents[1]
MUTABLE_TABLES = "sessions, messages, refunds, tickets, traces, spend"


@pytest.fixture(scope="session")
async def _migrated_pool():
    from app.db import create_pool, migrate, run_sql_file

    settings = make_settings()
    pool = await create_pool(settings.test_database_url)
    await migrate(pool, BACKEND_DIR / "migrations")
    await run_sql_file(pool, BACKEND_DIR / "seed" / "seed.sql")
    yield pool
    await pool.close()


@pytest.fixture
async def pool(_migrated_pool):
    from app.db import run_sql_file

    async with _migrated_pool.connection() as conn:
        await conn.execute(f"TRUNCATE {MUTABLE_TABLES} RESTART IDENTITY CASCADE")
        await conn.execute("ALTER SEQUENCE ticket_seq RESTART WITH 100")
    await run_sql_file(_migrated_pool, BACKEND_DIR / "seed" / "seed.sql")
    return _migrated_pool
