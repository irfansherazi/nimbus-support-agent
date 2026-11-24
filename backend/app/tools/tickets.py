from typing import Any, Literal

from pydantic import BaseModel, Field

from app.models import Escalation
from app.store.sessions import set_escalation
from app.store.tickets import append_to_ticket, create_ticket
from app.tools.base import ToolEnv


class CreateEscalationTicketArgs(BaseModel):
    summary: str = Field(description="One or two sentences a human specialist can act on")
    category: Literal["policy", "billing", "technical", "account", "other"]
    priority: Literal["low", "normal", "high"] = "normal"


async def create_escalation_ticket(env: ToolEnv, args: CreateEscalationTicketArgs) -> dict[str, Any]:
    """Open a ticket, or add to the session's open one, and put the session into the escalated state."""
    async with env.pool.connection() as conn:
        if env.session.escalation is not None:
            ticket_id = env.session.escalation.ticket_id
            await append_to_ticket(conn, ticket_id, args.summary, env.recent_turns)
            return {"ticket_id": ticket_id, "appended": True}
        ticket = await create_ticket(
            conn,
            session_id=env.session.id,
            customer_id=env.customer.id if env.customer else None,
            summary=args.summary,
            category=args.category,
            priority=args.priority,
            reason=env.escalation_reason,
            turns=env.recent_turns,
        )
        escalation = Escalation(ticket_id=ticket.id, reason=env.escalation_reason)
        await set_escalation(conn, env.session.id, escalation)
    env.session.escalation = escalation
    return {"ticket_id": ticket.id, "appended": False}
