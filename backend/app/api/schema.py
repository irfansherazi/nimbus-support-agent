"""Exists so the AgentEvent union reaches the OpenAPI schema, from which the frontend's types are generated."""

from fastapi import APIRouter, Response

from app.events import AgentEvent

router = APIRouter(prefix="/api/schema", tags=["schema"])


@router.get("/events", status_code=204, responses={200: {"model": AgentEvent, "description": "Event union"}})
async def event_schema() -> Response:
    return Response(status_code=204)
