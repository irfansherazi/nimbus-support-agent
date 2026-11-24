"""The public demo shares one mock CRM between all visitors, so it is reset on a schedule (and on every deploy):
refunds are cleared and the seeded customers and invoices are restored. Conversations and tickets are kept."""

import asyncio
import logging
from pathlib import Path

from app.db import Pool, run_sql_file
from app.tools import identity

log = logging.getLogger(__name__)
SEED = Path(__file__).resolve().parents[1] / "seed" / "seed.sql"


async def reset_demo_data(pool: Pool) -> None:
    async with pool.connection() as conn:
        await conn.execute("DELETE FROM refunds")
    await run_sql_file(pool, SEED)
    identity.ACCOUNT_FAILURES.clear()


async def reset_periodically(pool: Pool, minutes: int) -> None:
    while True:
        await asyncio.sleep(minutes * 60)
        try:
            await reset_demo_data(pool)
            log.info("demo data reset")
        except Exception:
            log.exception("demo data reset failed")
