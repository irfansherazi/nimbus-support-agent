import uuid

import psycopg

from app.db import create_pool
from tests.conftest import make_settings


async def test_pool_works_on_a_fresh_database_without_the_vector_extension():
    # CI and a new Railway Postgres start empty: the pool must not need the extension before migrations run.
    base = make_settings().test_database_url
    name = f"nimbus_fresh_{uuid.uuid4().hex[:8]}"
    admin = await psycopg.AsyncConnection.connect(base, autocommit=True)
    await admin.execute(f'CREATE DATABASE "{name}"')
    try:
        pool = await create_pool(base.rsplit("/", 1)[0] + "/" + name)
        async with pool.connection() as conn:
            row = await (await conn.execute("SELECT '[1,2,3]'::vector AS v")).fetchone()
        await pool.close()
        assert row["v"].to_list() == [1, 2, 3]
    finally:
        await admin.execute(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')
        await admin.close()
