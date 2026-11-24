"""Conversation sessions and their message history (shared by chat and voice)."""

from typing import Any
from uuid import UUID

from psycopg.types.json import Jsonb

from app.db import Conn, one
from app.models import Channel, Escalation, Message, Role, SessionRow


def _session(row: dict[str, Any]) -> SessionRow:
    esc = row["escalation"]
    return SessionRow(
        id=row["id"],
        customer_id=row["customer_id"],
        verify_failures=row["verify_failures"],
        escalation=Escalation(**esc) if esc else None,
    )


async def create_session(conn: Conn) -> SessionRow:
    cur = await conn.execute("INSERT INTO sessions DEFAULT VALUES RETURNING *")
    return _session(await one(cur))


async def get_session(conn: Conn, session_id: UUID) -> SessionRow | None:
    cur = await conn.execute("SELECT * FROM sessions WHERE id = %s", (session_id,))
    row = await cur.fetchone()
    return _session(row) if row else None


async def set_customer(conn: Conn, session_id: UUID, customer_id: str) -> None:
    await conn.execute("UPDATE sessions SET customer_id = %s WHERE id = %s", (customer_id, session_id))


async def incr_verify_failures(conn: Conn, session_id: UUID) -> int:
    cur = await conn.execute(
        "UPDATE sessions SET verify_failures = verify_failures + 1 WHERE id = %s RETURNING verify_failures",
        (session_id,),
    )
    return int((await one(cur))["verify_failures"])


async def set_escalation(conn: Conn, session_id: UUID, escalation: Escalation) -> None:
    await conn.execute(
        "UPDATE sessions SET escalation = %s WHERE id = %s", (Jsonb(escalation.model_dump()), session_id)
    )


async def get_chaos(conn: Conn, session_id: UUID) -> dict[str, Any]:
    cur = await conn.execute("SELECT chaos FROM sessions WHERE id = %s", (session_id,))
    row = await cur.fetchone()
    return dict(row["chaos"]) if row else {}


async def set_chaos(conn: Conn, session_id: UUID, chaos: dict[str, Any]) -> None:
    await conn.execute("UPDATE sessions SET chaos = %s WHERE id = %s", (Jsonb(chaos), session_id))


async def add_message(
    conn: Conn,
    *,
    session_id: UUID,
    turn_id: str,
    channel: Channel,
    role: Role,
    content: str,
    interrupted: bool = False,
) -> Message:
    cur = await conn.execute(
        """INSERT INTO messages (session_id, turn_id, channel, role, content, interrupted)
           VALUES (%s, %s, %s, %s, %s, %s) RETURNING *""",
        (session_id, turn_id, channel, role, content, interrupted),
    )
    return Message(**(await one(cur)))


async def recent_messages(conn: Conn, session_id: UUID, n: int) -> list[Message]:
    """The last n messages, oldest first."""
    cur = await conn.execute(
        """SELECT * FROM (SELECT * FROM messages WHERE session_id = %s ORDER BY id DESC LIMIT %s) t
           ORDER BY id ASC""",
        (session_id, n),
    )
    return [Message(**r) for r in await cur.fetchall()]
