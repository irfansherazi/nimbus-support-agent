"""Domain models shared across the store, tools, agent and API layers."""

from datetime import date, datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel

Tier = Literal["free", "pro", "enterprise"]
ChunkTier = Literal["all", "free", "pro", "enterprise"]
ContractStatus = Literal["active", "expired", "past_due"]
Channel = Literal["chat", "voice"]
Role = Literal["user", "assistant"]
Priority = Literal["low", "normal", "high"]


class Customer(BaseModel):
    """A mock CRM customer. The PIN is deliberately not part of this model."""

    id: str
    name: str
    tier: Tier
    contract_status: ContractStatus
    email: str
    phone: str
    billing_contact: str
    chaos_flags: dict[str, str] = {}


class Invoice(BaseModel):
    id: str
    customer_id: str
    amount_cents: int
    issued_at: date
    description: str


class PolicyLimit(BaseModel):
    tier: Tier
    max_refund_cents: int
    window_days: int


class RefundRow(BaseModel):
    id: int
    invoice_id: str
    customer_id: str
    amount_cents: int
    reason: str
    idempotency_key: str
    created_at: datetime


class Escalation(BaseModel):
    ticket_id: str
    reason: str


class SessionRow(BaseModel):
    id: UUID
    customer_id: str | None
    verify_failures: int
    escalation: Escalation | None


class Message(BaseModel):
    id: int
    session_id: UUID
    turn_id: str
    channel: Channel
    role: Role
    content: str
    interrupted: bool
    created_at: datetime


class Ticket(BaseModel):
    id: str
    session_id: UUID
    customer_id: str | None
    summary: str
    category: str
    priority: Priority
    reason: str
    turns: list[dict[str, Any]]
    created_at: datetime
