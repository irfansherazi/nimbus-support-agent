"""Per-turn traces for the observability drawer.

A turn's trace can be written by several parties: the agent run, and (in voice) the Realtime bridge adding audio
usage, latency and drift checks as they happen. So every write MERGES into the row: spans and usage are appended,
latency keys are merged, and the row is created by whichever write comes first.
"""

from typing import Any
from uuid import UUID

from psycopg.types.json import Jsonb

from app.db import Conn

_UPSERT = """INSERT INTO traces (turn_id, session_id, channel, status, spans, usage, latency)
             VALUES (%s, %s, %s, %s, %s, %s, %s)
             ON CONFLICT (turn_id) DO UPDATE SET
                 status = COALESCE(NULLIF(EXCLUDED.status, ''), traces.status),
                 spans = traces.spans || EXCLUDED.spans,
                 usage = traces.usage || EXCLUDED.usage,
                 latency = traces.latency || EXCLUDED.latency"""


async def save_trace(
    conn: Conn,
    turn_id: str,
    session_id: UUID,
    channel: str,
    status: str,
    spans: list[dict[str, Any]],
    usage: list[dict[str, Any]],
    latency: dict[str, Any],
) -> None:
    await conn.execute(_UPSERT, (turn_id, session_id, channel, status, Jsonb(spans), Jsonb(usage), Jsonb(latency)))


async def append_trace(
    conn: Conn,
    turn_id: str,
    session_id: UUID,
    channel: str,
    *,
    spans: list[dict[str, Any]] | None = None,
    usage: list[dict[str, Any]] | None = None,
) -> None:
    """Add spans/usage to a turn's trace without touching its status (creates the row as 'ok' if needed)."""
    await conn.execute(_UPSERT, (turn_id, session_id, channel, "", Jsonb(spans or []), Jsonb(usage or []), Jsonb({})))
    await conn.execute("UPDATE traces SET status = 'ok' WHERE turn_id = %s AND status = ''", (turn_id,))


async def merge_latency(
    conn: Conn, turn_id: str, latency: dict[str, Any], session_id: UUID | None = None, channel: str = "voice"
) -> None:
    if session_id is None:
        await conn.execute("UPDATE traces SET latency = latency || %s WHERE turn_id = %s", (Jsonb(latency), turn_id))
        return
    await conn.execute(_UPSERT, (turn_id, session_id, channel, "", Jsonb([]), Jsonb([]), Jsonb(latency)))
    await conn.execute("UPDATE traces SET status = 'ok' WHERE turn_id = %s AND status = ''", (turn_id,))


async def get_trace(conn: Conn, turn_id: str) -> dict[str, Any] | None:
    cur = await conn.execute(
        "SELECT turn_id, session_id, channel, status, spans, usage, latency, created_at FROM traces WHERE turn_id = %s",
        (turn_id,),
    )
    return await cur.fetchone()


async def session_cost_usd(conn: Conn, session_id: UUID) -> float:
    cur = await conn.execute(
        """SELECT COALESCE(SUM((u ->> 'cost_usd')::float), 0) AS total
           FROM traces, jsonb_array_elements(usage) u WHERE session_id = %s""",
        (session_id,),
    )
    row = await cur.fetchone()
    return float(row["total"]) if row else 0.0


async def list_traces(conn: Conn, session_id: UUID) -> list[dict[str, Any]]:
    cur = await conn.execute(
        "SELECT turn_id, channel, status, spans, usage, latency, created_at FROM traces "
        "WHERE session_id = %s ORDER BY created_at",
        (session_id,),
    )
    return list(await cur.fetchall())


async def latest_trace_turn(conn: Conn, session_id: UUID, channel: str) -> str | None:
    cur = await conn.execute(
        "SELECT turn_id FROM traces WHERE session_id = %s AND channel = %s ORDER BY created_at DESC LIMIT 1",
        (session_id, channel),
    )
    row = await cur.fetchone()
    return row["turn_id"] if row else None
