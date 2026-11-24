"""The per-session SSE stream: every agent event, chat and voice, with Last-Event-ID resume."""

from collections.abc import AsyncIterator
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Request
from sse_starlette.sse import EventSourceResponse

from app.api.deps import Services, get_services
from app.bus import SessionBus

router = APIRouter(prefix="/api/sessions", tags=["events"])

SSE_HEADERS = {"Cache-Control": "no-cache, no-transform", "X-Accel-Buffering": "no"}


def _parse_seq(value: str | None) -> int | None:
    try:
        return int(value) if value not in (None, "") else None
    except ValueError:
        return None


async def sse_events(
    bus: SessionBus, session_id: UUID, last_seq: int | None, request: Request
) -> AsyncIterator[dict[str, Any]]:
    async for event in bus.subscribe(session_id, last_seq):
        if await request.is_disconnected():
            return
        # No `event:` field: an event named "error" would collide with EventSource's own error event. The type is in
        # the JSON payload, and the client uses onmessage.
        yield {"id": str(event.seq), "data": event.model_dump_json()}


@router.get("/{session_id}/events")
async def events(
    session_id: UUID,
    request: Request,
    services: Annotated[Services, Depends(get_services)],
    last_event_id: str | None = None,
    last_event_id_header: Annotated[str | None, Header(alias="Last-Event-ID")] = None,
) -> EventSourceResponse:
    """Header wins (browser reconnects send it); the query param covers the first connect after hydration."""
    last_seq = _parse_seq(last_event_id_header) if last_event_id_header is not None else _parse_seq(last_event_id)
    return EventSourceResponse(sse_events(services.bus, session_id, last_seq, request), ping=15, headers=SSE_HEADERS)
