"""Per-session fault injection, driven from the UI's "Simulate failure" menu.

One-shot flags are consumed atomically by the first call they affect, so a flag never leaks into a second call
or another session. `tool_slow` is sticky until turned off.
"""

from typing import Any
from uuid import UUID

from psycopg.types.json import Jsonb
from pydantic import BaseModel

from app.db import Pool


class ChaosState(BaseModel):
    llm_timeout_next: bool = False  # primary model times out on every attempt of the next call -> fallback serves it
    llm_429_next: bool = False  # first attempt of the next call is rate-limited -> retry succeeds
    llm_outage_next: bool = False  # primary and fallback both fail on the next call -> error + Retry in the UI
    tool_fail_next: str | None = None  # the next call to this tool fails (retryable)
    tool_slow: str | None = None  # this tool takes +5 s on every call


class MemoryChaosStore:
    def __init__(self, flags: dict[str, Any] | None = None) -> None:
        self._flags: dict[str, Any] = dict(flags or {})

    async def get(self) -> dict[str, Any]:
        return dict(self._flags)

    async def set(self, flags: dict[str, Any]) -> None:
        self._flags = dict(flags)

    async def consume(self, flag: str) -> bool:
        return bool(self._flags.pop(flag, False))

    async def consume_tool_fail(self, tool: str) -> bool:
        if self._flags.get("tool_fail_next") == tool:
            self._flags.pop("tool_fail_next")
            return True
        return False

    async def tool_slow(self) -> str | None:
        return self._flags.get("tool_slow")


class PgChaosStore:
    """Flags live on sessions.chaos; read-and-clear is a single UPDATE ... RETURNING, so it is atomic."""

    def __init__(self, pool: Pool, session_id: UUID) -> None:
        self._pool = pool
        self._sid = session_id

    async def get(self) -> dict[str, Any]:
        async with self._pool.connection() as conn:
            cur = await conn.execute("SELECT chaos FROM sessions WHERE id = %s", (self._sid,))
            row = await cur.fetchone()
        return dict(row["chaos"]) if row else {}

    async def set(self, flags: dict[str, Any]) -> None:
        async with self._pool.connection() as conn:
            await conn.execute("UPDATE sessions SET chaos = %s WHERE id = %s", (Jsonb(flags), self._sid))

    async def consume(self, flag: str) -> bool:
        async with self._pool.connection() as conn:
            cur = await conn.execute(
                """UPDATE sessions SET chaos = chaos - %s
                   WHERE id = %s AND chaos ->> %s = 'true' RETURNING id""",
                (flag, self._sid, flag),
            )
            return await cur.fetchone() is not None

    async def consume_tool_fail(self, tool: str) -> bool:
        async with self._pool.connection() as conn:
            cur = await conn.execute(
                """UPDATE sessions SET chaos = chaos - 'tool_fail_next'
                   WHERE id = %s AND chaos ->> 'tool_fail_next' = %s RETURNING id""",
                (self._sid, tool),
            )
            return await cur.fetchone() is not None

    async def tool_slow(self) -> str | None:
        value = (await self.get()).get("tool_slow")
        return str(value) if value else None
