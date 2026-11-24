"""Tool plumbing: the environment a tool runs in, its spec, and the structured error every precondition raises.

Preconditions live inside each tool function, not in the prompt, so the model cannot talk its way past them.
"""

from collections import defaultdict
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any, Literal

from pydantic import BaseModel

from app.context import TurnContext
from app.db import Pool
from app.models import Customer, SessionRow
from app.rag.embedder import Embedder
from app.store.customers import get_customer
from app.store.sessions import get_session

ToolErrorCode = Literal[
    "NOT_VERIFIED",
    "VERIFICATION_LOCKED",
    "INVALID_CREDENTIALS",
    "CUSTOMER_NOT_FOUND",
    "CONTRACT_NOT_ACTIVE",
    "INVOICE_NOT_FOUND",
    "REFUND_NOT_ELIGIBLE",
    "OUTSIDE_REFUND_WINDOW",
    "AMOUNT_EXCEEDS_LIMIT",
    "AMOUNT_NOT_CONFIRMED",
    "INVALID_AMOUNT",
    "FIELD_NOT_ALLOWED",
    "INVALID_VALUE",
    "TOOL_FAILED",
]


class ToolError(Exception):
    def __init__(self, code: ToolErrorCode, message: str, retryable: bool = False, hint: str | None = None) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message
        self.retryable = retryable
        self.hint = hint

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {"error": self.code, "message": self.message, "retryable": self.retryable}
        if self.hint:
            out["hint"] = self.hint
        return out


@dataclass
class ToolEnv:
    """Per-turn tool environment. `customer` is set only by verify_customer."""

    ctx: TurnContext
    pool: Pool
    session: SessionRow
    customer: Customer | None
    embedder: Embedder
    failures: dict[str, int] = field(default_factory=lambda: defaultdict(int))
    last_retrieval: dict[str, Any] | None = None
    escalation_reason: str = "agent_requested"
    recent_turns: list[dict[str, Any]] = field(default_factory=list)
    customer_said: list[str] = field(default_factory=list)  # the customer's messages, oldest first, incl. this turn
    last_assistant: str = ""  # what the assistant said last, for "yes" to an offered amount

    @classmethod
    async def load(cls, ctx: TurnContext, embedder: Embedder) -> "ToolEnv":
        assert ctx.pool is not None, "tools need a database pool"
        async with ctx.pool.connection() as conn:
            session = await get_session(conn, ctx.session_id)
            if session is None:
                raise LookupError(f"unknown session {ctx.session_id}")
            customer = await get_customer(conn, session.customer_id) if session.customer_id else None
        return cls(ctx=ctx, pool=ctx.pool, session=session, customer=customer, embedder=embedder)

    def require_customer(self) -> Customer:
        if self.customer is None:
            raise ToolError("NOT_VERIFIED", "Verify the customer first.", hint="ask for account ID and PIN")
        return self.customer


ToolFn = Callable[[ToolEnv, Any], Awaitable[dict[str, Any]]]


@dataclass(frozen=True)
class ToolSpec:
    name: str
    label: str
    description: str
    args_model: type[BaseModel]
    fn: ToolFn


@dataclass(frozen=True)
class ToolOutcome:
    ok: bool
    data: dict[str, Any] | None = None
    error: ToolError | None = None

    def for_model(self) -> dict[str, Any]:
        """What the agent LLM sees as the tool result."""
        if self.ok:
            return self.data or {}
        assert self.error is not None
        return self.error.to_dict()
