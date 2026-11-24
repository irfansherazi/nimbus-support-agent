"""Per-turn traces for the observability drawer."""

from typing import Any
from uuid import UUID

from psycopg.types.json import Jsonb

from app.db import Conn


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
    await conn.execute(
        """INSERT INTO traces (turn_id, session_id, channel, status, spans, usage, latency)
           VALUES (%s, %s, %s, %s, %s, %s, %s)
           ON CONFLICT (turn_id) DO UPDATE SET status = EXCLUDED.status, spans = EXCLUDED.spans,
               usage = EXCLUDED.usage, latency = EXCLUDED.latency""",
        (turn_id, session_id, channel, status, Jsonb(spans), Jsonb(usage), Jsonb(latency)),
    )


async def merge_latency(conn: Conn, turn_id: str, latency: dict[str, Any]) -> None:
    await conn.execute("UPDATE traces SET latency = latency || %s WHERE turn_id = %s", (Jsonb(latency), turn_id))


async def append_spans(conn: Conn, turn_id: str, spans: list[dict[str, Any]]) -> None:
    await conn.execute("UPDATE traces SET spans = spans || %s WHERE turn_id = %s", (Jsonb(spans), turn_id))


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
