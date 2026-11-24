"""LangGraph state for one agent turn. Live objects (TurnContext, ToolEnv, deps) travel in the run config."""

from typing import Annotated, Any, Literal, TypedDict

from langchain_core.messages import BaseMessage
from langgraph.graph.message import add_messages

from app.agent.guardrails import Intent
from app.models import Channel

TurnStatus = Literal["ok", "escalated", "failed"]


class AgentState(TypedDict, total=False):
    session_id: str
    channel: Channel
    user_text: str
    messages: Annotated[list[BaseMessage], add_messages]  # history + this turn's agent/tool messages
    intent: Intent | None
    retrieval: dict[str, Any] | None  # {query, tier_filter, top_score, chunks, band}
    searched_this_turn: bool
    iterations: int
    escalate_reason: str | None
    escalation: dict[str, Any] | None  # {ticket_id, reason} once a ticket exists this turn
    answer: str | None
    verify: dict[str, Any] | None
    status: TurnStatus
