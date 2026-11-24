"""OpenAI Realtime plumbing: create a WebRTC call from the browser's offer, and the server-side event socket."""

import json
import logging
from collections.abc import AsyncIterator
from typing import Any, Protocol

import httpx
import websockets

from app.config import Settings

log = logging.getLogger(__name__)
API = "https://api.openai.com/v1/realtime"
SIDEBAND = "wss://api.openai.com/v1/realtime"


class CallCreateError(RuntimeError):
    pass


class RealtimeTransport(Protocol):
    async def connect(self) -> None: ...

    async def send(self, event: dict[str, Any]) -> None: ...

    def __aiter__(self) -> AsyncIterator[dict[str, Any]]: ...

    async def close(self) -> None: ...

    async def hangup(self) -> None: ...


async def create_call(settings: Settings, offer_sdp: str, session: dict[str, Any]) -> tuple[str, str]:
    """Relay the browser's SDP offer with our key and session config. Returns (answer_sdp, call_id)."""
    async with httpx.AsyncClient(timeout=20) as client:
        r = await client.post(
            f"{API}/calls",
            headers={"Authorization": f"Bearer {settings.openai_api_key}"},
            files={"sdp": (None, offer_sdp), "session": (None, json.dumps(session))},
        )
    if r.status_code >= 300:
        raise CallCreateError(f"realtime call rejected ({r.status_code}): {r.text[:300]}")
    call_id = (r.headers.get("location") or "").rstrip("/").split("/")[-1]
    if not call_id:
        raise CallCreateError("realtime call created without a call id")
    return r.text, call_id


class OpenAIRealtimeTransport:
    """The server's own connection to a live call ("sideband"): receives every event, can send any event."""

    def __init__(self, settings: Settings, call_id: str) -> None:
        self._key = settings.openai_api_key
        self.call_id = call_id
        self._ws: Any = None

    @property
    def url(self) -> str:
        return f"{SIDEBAND}?call_id={self.call_id}"

    async def connect(self) -> None:
        self._ws = await websockets.connect(self.url, additional_headers={"Authorization": f"Bearer {self._key}"})

    async def send(self, event: dict[str, Any]) -> None:
        await self._ws.send(json.dumps(event))

    async def __aiter__(self) -> AsyncIterator[dict[str, Any]]:
        try:
            async for raw in self._ws:
                yield json.loads(raw)
        except websockets.ConnectionClosed:
            return

    async def close(self) -> None:
        if self._ws is not None:
            await self._ws.close()

    async def hangup(self) -> None:
        """Best effort: end the call for the browser too (the UI also closes its side on VOICE_LIMIT)."""
        try:
            async with httpx.AsyncClient(timeout=5) as client:
                await client.post(
                    f"{API}/calls/{self.call_id}/hangup", headers={"Authorization": f"Bearer {self._key}"}
                )
        except httpx.HTTPError:
            log.info("hangup for %s failed; the browser will close its side", self.call_id)


def openai_transport(settings: Settings, call_id: str) -> OpenAIRealtimeTransport:
    return OpenAIRealtimeTransport(settings, call_id)
