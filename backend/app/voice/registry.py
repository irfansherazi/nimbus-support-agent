"""Active voice calls, at most one per session."""

import asyncio
import logging
from collections.abc import Awaitable, Callable
from typing import Any
from uuid import UUID

from app.bus import SessionBus
from app.config import Settings
from app.db import Pool
from app.store.sessions import recent_messages
from app.voice.bridge import DriftLLM, TurnRunnerLike, VoiceBridge
from app.voice.openai_realtime import RealtimeTransport, create_call, openai_transport
from app.voice.session_config import build_session_config

log = logging.getLogger(__name__)

CallFactory = Callable[[Settings, str, dict[str, Any]], Awaitable[tuple[str, str]]]
TransportFactory = Callable[[Settings, str], RealtimeTransport]


class VoiceBusy(RuntimeError):
    """This session already has a live voice call."""


class VoiceRegistry:
    def __init__(
        self,
        *,
        pool: Pool,
        bus: SessionBus,
        runner: TurnRunnerLike,
        llm: DriftLLM,
        settings: Settings,
        budget: Any = None,
        call_factory: CallFactory = create_call,
        transport_factory: TransportFactory = openai_transport,
    ) -> None:
        self.pool, self.bus, self.runner, self.llm = pool, bus, runner, llm
        self.settings, self.budget = settings, budget
        self.call_factory, self.transport_factory = call_factory, transport_factory
        self._calls: dict[UUID, tuple[VoiceBridge, asyncio.Task[None]]] = {}

    def active(self, session_id: UUID) -> bool:
        return session_id in self._calls

    async def start(self, session_id: UUID, offer_sdp: str) -> str:
        """Create the Realtime call from the browser's offer; returns the SDP answer for the browser."""
        if self.active(session_id):
            raise VoiceBusy(str(session_id))
        async with self.pool.connection() as conn:
            history = await recent_messages(conn, session_id, self.settings.voice_history_turns)
        answer_sdp, call_id = await self.call_factory(self.settings, offer_sdp, build_session_config(self.settings))
        bridge = VoiceBridge(
            session_id=session_id,
            transport=self.transport_factory(self.settings, call_id),
            runner=self.runner,
            pool=self.pool,
            bus=self.bus,
            llm=self.llm,
            settings=self.settings,
            budget=self.budget,
        )
        task = asyncio.create_task(self._run(session_id, bridge, history))
        self._calls[session_id] = (bridge, task)
        return answer_sdp

    async def _run(self, session_id: UUID, bridge: VoiceBridge, history: list[Any]) -> None:
        try:
            await bridge.run(history)
        except Exception:
            log.exception("voice bridge for %s crashed", session_id)
            # Don't leave the browser talking to a call nobody is handling.
            try:
                await bridge.stop("VOICE_DROPPED", "Voice connection dropped. You can keep chatting.")
            except Exception:
                log.exception("could not end the call for %s", session_id)
        finally:
            self._calls.pop(session_id, None)

    async def end(self, session_id: UUID) -> None:
        call = self._calls.get(session_id)
        if call is not None:
            await call[0].stop()

    async def shutdown(self) -> None:
        for bridge, task in list(self._calls.values()):
            await bridge.stop()
            task.cancel()
        await asyncio.gather(*(t for _, t in self._calls.values()), return_exceptions=True)
