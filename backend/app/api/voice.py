"""Voice call routes. The browser's SDP offer comes here; our server creates the Realtime call with its own key."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status

from app.api.deps import Services, get_services
from app.ratelimit import client_ip
from app.store.sessions import get_session
from app.voice.openai_realtime import CallCreateError
from app.voice.registry import VoiceBusy, VoiceRegistry

router = APIRouter(prefix="/api/voice", tags=["voice"])
ServicesDep = Annotated[Services, Depends(get_services)]


def _registry(services: Services) -> VoiceRegistry:
    return services.extras["voice"]  # type: ignore[no-any-return]


def _error(code: int, name: str, message: str) -> HTTPException:
    return HTTPException(code, detail={"code": name, "message": message})


@router.post(
    "/calls",
    status_code=status.HTTP_201_CREATED,
    response_class=Response,
    responses={201: {"content": {"application/sdp": {}}, "description": "SDP answer"}},
)
async def start_call(session_id: UUID, request: Request, services: ServicesDep) -> Response:
    async with services.pool.connection() as conn:
        if await get_session(conn, session_id) is None:
            raise _error(404, "SESSION_NOT_FOUND", "Unknown session.")
    if await services.budget.exceeded():
        raise _error(503, "BUDGET_EXCEEDED", "The demo has reached today's usage limit.")
    if _registry(services).active(session_id):
        raise _error(409, "VOICE_BUSY", "A voice call is already active for this conversation.")
    if not services.voice_ip_limiter.hit(client_ip(request.headers, request.client and request.client.host)):
        raise _error(429, "RATE_LIMITED", "Too many voice calls. Try again later, or keep chatting.")
    offer = (await request.body()).decode()
    try:
        answer = await _registry(services).start(session_id, offer)
    except VoiceBusy as exc:
        raise _error(409, "VOICE_BUSY", "A voice call is already active for this conversation.") from exc
    except CallCreateError as exc:
        raise _error(502, "VOICE_UNAVAILABLE", "Voice is unavailable right now. You can keep chatting.") from exc
    return Response(content=answer, media_type="application/sdp", status_code=status.HTTP_201_CREATED)


@router.delete("/calls/{session_id}", status_code=status.HTTP_204_NO_CONTENT)
async def end_call(session_id: UUID, services: ServicesDep) -> Response:
    await _registry(services).end(session_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
