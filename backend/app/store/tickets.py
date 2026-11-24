"""Structured escalation tickets."""

from typing import Any
from uuid import UUID

from psycopg.types.json import Jsonb

from app.db import Conn, one
from app.models import Priority, Ticket


async def create_ticket(
    conn: Conn,
    *,
    session_id: UUID,
    customer_id: str | None,
    summary: str,
    category: str,
    priority: Priority,
    reason: str,
    turns: list[dict[str, Any]],
) -> Ticket:
    cur = await conn.execute(
        """INSERT INTO tickets (id, session_id, customer_id, summary, category, priority, reason, turns)
           VALUES ('T-' || nextval('ticket_seq'), %s, %s, %s, %s, %s, %s, %s) RETURNING *""",
        (session_id, customer_id, summary, category, priority, reason, Jsonb(turns)),
    )
    return Ticket(**(await one(cur)))


async def append_to_ticket(conn: Conn, ticket_id: str, note: str, turns: list[dict[str, Any]]) -> None:
    await conn.execute(
        "UPDATE tickets SET summary = summary || E'\\n\\n' || %s, turns = turns || %s WHERE id = %s",
        (note, Jsonb(turns), ticket_id),
    )


async def list_tickets(conn: Conn, session_id: UUID) -> list[Ticket]:
    cur = await conn.execute("SELECT * FROM tickets WHERE session_id = %s ORDER BY created_at, id", (session_id,))
    return [Ticket(**r) for r in await cur.fetchall()]
