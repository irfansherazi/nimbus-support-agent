"""Daily spend kill switch for the public demo."""

from app.config import Settings
from app.db import Pool
from app.store.spend import add_spend, today_spend


class BudgetGuard:
    def __init__(self, pool: Pool, settings: Settings) -> None:
        self._pool = pool
        self._cap = settings.daily_budget_usd

    async def charge(self, usd: float) -> None:
        if usd <= 0:
            return
        async with self._pool.connection() as conn:
            await add_spend(conn, usd)

    async def exceeded(self) -> bool:
        async with self._pool.connection() as conn:
            return await today_spend(conn) >= self._cap
