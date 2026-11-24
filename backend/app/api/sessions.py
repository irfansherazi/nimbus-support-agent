"""Session REST API: create/read sessions, send chat messages, traces, tickets, chaos controls, client metrics."""

from datetime import datetime
from typing import Annotated, Any, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel, StringConstraints

from app.api.deps import Services, get_services
from app.chaos import ChaosState, PgChaosStore
from app.models import ContractStatus, Escalation, Message, Ticket, Tier
from app.observability.trace import Latency, LLMUsage, Span
from app.ratelimit import client_ip
from app.store.customers import get_customer
from app.store.sessions import create_session, get_session, recent_messages
from app.store.tickets import list_tickets
from app.store.traces import latest_trace_turn, list_traces, merge_latency

router = APIRouter(prefix="/api/sessions", tags=["sessions"])

ServicesDep = Annotated[Services, Depends(get_services)]
MessageText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=2000)]


class CreatedSession(BaseModel):
    session_id: UUID


class CustomerView(BaseModel):
    name: str
    tier: Tier
    contract_status: ContractStatus


class SessionView(BaseModel):
    session_id: UUID
    customer: CustomerView | None
    escalation: Escalation | None
    messages: list[Message]
    last_event_seq: int  # pass as ?last_event_id= when opening the event stream, so nothing is missed


class SendMessage(BaseModel):
    text: MessageText


class TurnAccepted(BaseModel):
    turn_id: str


class TraceView(BaseModel):
    turn_id: str
    channel: str
    status: str
    spans: list[Span]
    usage: list[LLMUsage]
    latency: Latency
    created_at: datetime


class Metric(BaseModel):
    kind: Literal["voice_e2e_ms"]
    value: int
    turn_id: str | None = None


def _rate_limited() -> HTTPException:
    return HTTPException(
        status.HTTP_429_TOO_MANY_REQUESTS,
        detail={"code": "RATE_LIMITED", "message": "You're sending messages too quickly — try again in a minute."},
    )


async def _require_session(services: Services, session_id: UUID) -> None:
    async with services.pool.connection() as conn:
        if await get_session(conn, session_id) is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, detail={"code": "SESSION_NOT_FOUND"})


@router.post("", status_code=status.HTTP_201_CREATED)
async def create(request: Request, services: ServicesDep) -> CreatedSession:
    if not services.session_create_limiter.hit(client_ip(request.headers, request.client and request.client.host)):
        raise _rate_limited()
    async with services.pool.connection() as conn:
        session = await create_session(conn)
    return CreatedSession(session_id=session.id)


@router.get("/{session_id}")
async def read(session_id: UUID, services: ServicesDep) -> SessionView:
    async with services.pool.connection() as conn:
        session = await get_session(conn, session_id)
        if session is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, detail={"code": "SESSION_NOT_FOUND"})
        customer = await get_customer(conn, session.customer_id) if session.customer_id else None
        messages = await recent_messages(conn, session_id, 200)
    return SessionView(
        session_id=session_id,
        customer=CustomerView(**customer.model_dump()) if customer else None,
        escalation=session.escalation,
        messages=messages,
        last_event_seq=services.bus.last_seq(session_id),
    )


@router.post("/{session_id}/messages", status_code=status.HTTP_202_ACCEPTED)
async def send(session_id: UUID, body: SendMessage, request: Request, services: ServicesDep) -> TurnAccepted:
    await _require_session(services, session_id)
    ip = client_ip(request.headers, request.client and request.client.host)
    if not services.chat_session_limiter.hit(str(session_id)) or not services.chat_ip_limiter.hit(ip):
        raise _rate_limited()
    return TurnAccepted(turn_id=services.runner.start_turn(session_id, body.text, "chat"))


@router.get("/{session_id}/traces")
async def traces(session_id: UUID, services: ServicesDep) -> list[TraceView]:
    async with services.pool.connection() as conn:
        rows = await list_traces(conn, session_id)
    return [TraceView(**r) for r in rows]


@router.get("/{session_id}/tickets")
async def tickets(session_id: UUID, services: ServicesDep) -> list[Ticket]:
    async with services.pool.connection() as conn:
        return await list_tickets(conn, session_id)


@router.put("/{session_id}/chaos")
async def set_chaos(session_id: UUID, body: ChaosState, services: ServicesDep) -> ChaosState:
    await _require_session(services, session_id)
    store = PgChaosStore(services.pool, session_id)
    await store.set(body.model_dump(exclude_defaults=True))
    return ChaosState(**await store.get())


@router.post("/{session_id}/metrics", status_code=status.HTTP_204_NO_CONTENT)
async def metric(session_id: UUID, body: Metric, services: ServicesDep) -> Response:
    async with services.pool.connection() as conn:
        turn_id = body.turn_id or await latest_trace_turn(conn, session_id, "voice")
        if turn_id is not None:
            await merge_latency(conn, turn_id, {"voice_e2e_ms": body.value})
    return Response(status_code=status.HTTP_204_NO_CONTENT)


def register(app: Any) -> None:
    app.include_router(router)
