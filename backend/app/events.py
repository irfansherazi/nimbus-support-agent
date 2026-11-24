"""The session event protocol. Every agent event in either mode goes onto one per-session SSE stream.

These Pydantic models are the single source of truth: the frontend's TypeScript types are generated from
the OpenAPI schema they produce (see GET /api/schema/events).
"""

import time
from typing import Annotated, Literal

from pydantic import BaseModel, Field

from app.models import Channel, Role
from app.observability.trace import Latency, LLMUsage, Span

ErrorCode = Literal[
    "LLM_TIMEOUT",
    "RATE_LIMITED",
    "LLM_UNAVAILABLE",
    "TOOL_FAILED",
    "BUDGET_EXCEEDED",
    "VOICE_LIMIT",
    "VOICE_DROPPED",
    "INTERNAL",
]
Band = Literal["high", "grey", "low", "skipped"]


class _Event(BaseModel):
    turn_id: str | None = None
    seq: int = 0
    ts: float = Field(default_factory=time.time)


class TurnStartedEvent(_Event):
    type: Literal["turn_started"] = "turn_started"
    channel: Channel


class TokenEvent(_Event):
    type: Literal["token"] = "token"
    text: str


class StepEvent(_Event):
    type: Literal["step_started", "step_completed", "step_failed"] = "step_started"
    step_id: str
    tool: str
    label: str
    kind: Literal["tool", "system"] = "tool"
    duration_ms: int | None = None
    error: str | None = None


class GuardrailEvent(_Event):
    type: Literal["guardrail"] = "guardrail"
    band: Band
    top_score: float | None
    verify: Literal["supported", "unsupported", "not_run"] = "not_run"


class EscalationEvent(_Event):
    type: Literal["escalation"] = "escalation"
    ticket_id: str
    reason: str


class AnswerRetractedEvent(_Event):
    type: Literal["answer_retracted"] = "answer_retracted"
    reason: str


class TranscriptEvent(_Event):
    type: Literal["transcript"] = "transcript"
    role: Role
    text: str
    final: bool = True
    interrupted: bool = False
    channel: Channel = "voice"


class TraceEvent(_Event):
    type: Literal["trace"] = "trace"
    spans: list[Span]


class UsageEvent(_Event):
    type: Literal["usage"] = "usage"
    calls: list[LLMUsage]
    turn_cost_usd: float
    session_cost_usd: float
    latency: Latency


class ErrorEvent(_Event):
    type: Literal["error"] = "error"
    code: ErrorCode
    retryable: bool
    message: str


class TurnCompletedEvent(_Event):
    type: Literal["turn_completed"] = "turn_completed"
    status: Literal["ok", "escalated", "failed"]


AgentEvent = Annotated[
    TurnStartedEvent
    | TokenEvent
    | StepEvent
    | GuardrailEvent
    | EscalationEvent
    | AnswerRetractedEvent
    | TranscriptEvent
    | TraceEvent
    | UsageEvent
    | ErrorEvent
    | TurnCompletedEvent,
    Field(discriminator="type"),
]
