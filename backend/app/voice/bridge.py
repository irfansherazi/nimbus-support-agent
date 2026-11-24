"""One live voice call: Realtime events in, the shared agent and the session store on the other side.

The Realtime model is only the voice ("one brain", spec §4.3): anything substantive arrives as a consult_agent call,
which runs the SAME LangGraph turn as chat, so tools, guardrails, step events and traces are identical in both modes.
"""

import asyncio
import logging
import time
from typing import Any, Protocol
from uuid import UUID

from langchain_core.messages import HumanMessage, SystemMessage

from app.agent.nodes import AgentLLM
from app.agent.runner import TurnResult
from app.bus import SessionBus
from app.chaos import MemoryChaosStore
from app.config import Settings
from app.context import TurnContext
from app.db import Pool
from app.events import ErrorEvent, TranscriptEvent
from app.llm.errors import LLMError
from app.llm.pricing import cost_usd
from app.models import Channel, Message
from app.observability.trace import LLMUsage, TraceRecorder
from app.store.sessions import add_message
from app.store.traces import append_trace, merge_latency
from app.voice.drift import CLAIM_SYSTEM, DRIFT_SYSTEM, DriftResult
from app.voice.handler import (
    Effect,
    RealtimeError,
    RealtimeEventHandler,
    RecordRealtimeUsage,
    RecordVoiceLatency,
    RunConsult,
    SpeakHoldingLine,
    StoreAssistantTranscript,
    StoreUserTranscript,
)
from app.voice.openai_realtime import RealtimeTransport
from app.voice.session_config import history_items

log = logging.getLogger(__name__)

TRANSCRIPT_WAIT_S = 3.0
CONSULT_FAILED = "I'm having trouble reaching our systems right now. Please try again in a moment."
IDLE_MESSAGE = "Voice session ended after a minute of silence. You can keep chatting, or start a new call."
MAX_MESSAGE = "Voice sessions are limited to 10 minutes. You can keep chatting, or start a new call."
HOLDING_LINE_REQUEST = {
    "type": "response.create",
    "response": {
        "instructions": 'Say only this, briefly and warmly: "One moment while I check that for you."',
        "tool_choice": "none",
        "metadata": {"purpose": "holding"},
    },
}
ACTIVITY_EVENTS = {
    "input_audio_buffer.speech_started",
    "input_audio_buffer.speech_stopped",
    "output_audio_buffer.started",
    "output_audio_buffer.stopped",
    "response.function_call_arguments.done",
}


class TurnRunnerLike(Protocol):
    async def run_turn(
        self,
        session_id: UUID,
        text: str,
        channel: Channel,
        *,
        turn_id: str | None = None,
        persist_user: bool = True,
        persist_answer: bool = True,
    ) -> TurnResult: ...

    async def publish_trace(self, session_id: UUID, turn_id: str) -> None: ...


DriftLLM = AgentLLM


def realtime_usage(kind: str, usage: dict[str, Any], settings: Settings) -> LLMUsage:
    """Convert a Realtime/transcription usage block into our LLMUsage with an audio-aware cost estimate."""
    itd = usage.get("input_token_details") or {}
    otd = usage.get("output_token_details") or {}
    audio_in = int(itd.get("audio_tokens", 0) or 0)
    text_in = int(itd.get("text_tokens", 0) or 0) if itd else int(usage.get("input_tokens", 0) or 0)
    audio_out = int(otd.get("audio_tokens", 0) or 0)
    out = int(usage.get("output_tokens", 0) or 0)
    text_out = int(otd.get("text_tokens", out) or 0) if otd else out
    cached = min(int(itd.get("cached_tokens", 0) or 0), text_in)
    model = settings.realtime_model if kind == "realtime" else settings.transcription_model
    return LLMUsage(
        model=model,
        purpose="voice" if kind == "realtime" else "transcription",
        input_tokens=text_in + audio_in,
        output_tokens=text_out + audio_out,
        cached_input_tokens=cached,
        audio_input_tokens=audio_in,
        audio_output_tokens=audio_out,
        cost_usd=cost_usd(model, text_in, text_out, cached, audio_in, audio_out),
    )


class VoiceBridge:
    def __init__(
        self,
        *,
        session_id: UUID,
        transport: RealtimeTransport,
        runner: TurnRunnerLike,
        pool: Pool,
        bus: SessionBus,
        llm: DriftLLM,
        settings: Settings,
        budget: Any = None,
        watchdog_interval_s: float = 0.5,
        transcript_wait_s: float = TRANSCRIPT_WAIT_S,
    ) -> None:
        self.session_id = session_id
        self.transport = transport
        self.runner = runner
        self.pool = pool
        self.bus = bus
        self.llm = llm
        self.settings = settings
        self.budget = budget
        self.handler = RealtimeEventHandler()
        self.agent_answers: dict[str, str] = {}
        self._tasks: set[asyncio.Task[Any]] = set()
        self._consults_running = 0
        self._watchdog_interval = watchdog_interval_s
        self._started = self._last_activity = time.monotonic()
        self._ended = False
        self._transcript_wait_s = transcript_wait_s
        self._transcribed: dict[str, asyncio.Event] = {}  # turn -> the customer's transcript is stored
        # Realtime allows one active response at a time: track them so the answer waits for a holding line.
        self._active_responses = 0
        self._requested_responses = 0
        self._no_active_response = asyncio.Event()
        self._no_active_response.set()

    # ---------------------------------------------------------------- lifecycle

    async def run(self, history: list[Message]) -> None:
        await self.transport.connect()
        watchdog = asyncio.create_task(self._watchdog())
        try:
            for item in history_items(history):
                await self.transport.send(item)
            async for event in self.transport:
                if event.get("type") in ACTIVITY_EVENTS:
                    self._last_activity = time.monotonic()
                for effect in self.handler.handle(event, now_ms=int(time.time() * 1000)):
                    await self._apply(effect)
                # After the effects: a holding line requested on this response.done keeps the line busy, so a
                # waiting answer can't slip in between.
                self._track_responses(event.get("type", ""))
        finally:
            watchdog.cancel()
            if self._tasks:
                await asyncio.gather(*self._tasks, return_exceptions=True)

    async def stop(self, code: str | None = None, message: str = "") -> None:
        """End the call. With a code, the UI is told why (VOICE_LIMIT); a user hang-up passes none."""
        if self._ended:
            return
        self._ended = True
        if code:
            self.bus.publish(self.session_id, ErrorEvent(code=code, retryable=False, message=message))  # type: ignore[arg-type]
        await self.transport.hangup()
        await self.transport.close()

    async def _watchdog(self) -> None:
        while not self._ended:
            await asyncio.sleep(self._watchdog_interval)
            now = time.monotonic()
            if now - self._started > self.settings.voice_max_seconds:
                await self.stop("VOICE_LIMIT", MAX_MESSAGE)
            elif self._consults_running == 0 and now - self._last_activity > self.settings.voice_idle_seconds:
                await self.stop("VOICE_LIMIT", IDLE_MESSAGE)

    def _track_responses(self, event_type: str) -> None:
        if event_type == "response.created":
            if self._requested_responses > 0:
                self._requested_responses -= 1  # already counted when we asked for it
            else:
                self._active_responses += 1
        elif event_type == "response.done":
            self._active_responses = max(0, self._active_responses - 1)
        elif event_type == "error" and self._requested_responses > 0:
            # Most likely one of our response.create requests was rejected: it will never be created or done.
            self._requested_responses -= 1
            self._active_responses = max(0, self._active_responses - 1)
        if self._active_responses == 0:
            self._no_active_response.set()
        else:
            self._no_active_response.clear()

    async def _request_response(self, request: dict[str, Any]) -> None:
        self._requested_responses += 1
        self._active_responses += 1
        self._no_active_response.clear()
        await self.transport.send(request)

    def _emit(self, event: Any) -> None:
        self.bus.publish(self.session_id, event)

    def _spawn(self, coro: Any) -> None:
        task = asyncio.create_task(coro)
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    # ---------------------------------------------------------------- effects

    async def _apply(self, effect: Effect) -> None:
        if isinstance(effect, StoreUserTranscript):
            await self._store(effect.turn_id, "user", effect.text, interrupted=False)
            self._transcript_event(effect.turn_id).set()
        elif isinstance(effect, StoreAssistantTranscript):
            await self._store(effect.turn_id, "assistant", effect.text, interrupted=effect.interrupted)
            # Consulted answers are compared with the agent's; replies the voice gave on its own are checked for
            # unsourced policy or account claims (spec §8.2a).
            self._spawn(self._check_drift(effect.turn_id, effect.text))
        elif isinstance(effect, SpeakHoldingLine):
            await self._request_response(HOLDING_LINE_REQUEST)
        elif isinstance(effect, RunConsult):
            self._consults_running += 1
            self._spawn(self._consult(effect))
        elif isinstance(effect, RecordRealtimeUsage):
            usage = realtime_usage(effect.kind, effect.usage, self.settings)
            async with self.pool.connection() as conn:
                await append_trace(conn, effect.turn_id, self.session_id, "voice", usage=[usage.model_dump()])
            if self.budget is not None:
                await self.budget.charge(usage.cost_usd)
            await self.runner.publish_trace(self.session_id, effect.turn_id)
        elif isinstance(effect, RecordVoiceLatency):
            async with self.pool.connection() as conn:
                await merge_latency(conn, effect.turn_id, {"voice_e2e_ms": effect.ms}, self.session_id, "voice")
            await self.runner.publish_trace(self.session_id, effect.turn_id)
        elif isinstance(effect, RealtimeError):
            log.warning("realtime error on %s: %s", self.session_id, effect.message)

    async def _store(self, turn_id: str, role: str, text: str, interrupted: bool) -> None:
        async with self.pool.connection() as conn:
            await add_message(
                conn,
                session_id=self.session_id,
                turn_id=turn_id,
                channel="voice",
                role=role,  # type: ignore[arg-type]
                content=text,
                interrupted=interrupted,
            )
        self.bus.publish(
            self.session_id,
            TranscriptEvent(turn_id=turn_id, role=role, text=text, interrupted=interrupted, channel="voice"),  # type: ignore[arg-type]
        )

    def _transcript_event(self, turn_id: str) -> asyncio.Event:
        return self._transcribed.setdefault(turn_id, asyncio.Event())

    async def _consult(self, effect: RunConsult) -> None:
        # The transcript can arrive after the tool call; the agent needs the customer's own words in history.
        try:
            await asyncio.wait_for(self._transcript_event(effect.turn_id).wait(), self._transcript_wait_s)
        except TimeoutError:
            log.info("no transcript for %s yet; running the agent without it", effect.turn_id)
        try:
            result = await self.runner.run_turn(
                self.session_id,
                effect.user_request or "(the customer's request was unclear)",
                "voice",
                turn_id=effect.turn_id,
                persist_user=False,
                persist_answer=False,
            )
            answer = result.answer if result.status != "failed" and result.answer else CONSULT_FAILED
        except Exception:
            log.exception("consult_agent failed for %s", effect.turn_id)
            answer = CONSULT_FAILED
        finally:
            self._consults_running -= 1
            self._last_activity = time.monotonic()
        self.agent_answers[effect.turn_id] = answer
        try:
            await self.transport.send(
                {
                    "type": "conversation.item.create",
                    "item": {"type": "function_call_output", "call_id": effect.call_id, "output": answer},
                }
            )
            # Wait for a holding line still being spoken: overlapping responses are rejected by the API.
            try:
                await asyncio.wait_for(self._no_active_response.wait(), 15)
            except TimeoutError:
                log.info("speaking the answer for %s without waiting any longer", effect.turn_id)
            # tool_choice none: the voice must speak this answer, not call consult_agent again.
            await self._request_response({"type": "response.create", "response": {"tool_choice": "none"}})
        except Exception:
            log.info("call ended before the agent's answer could be spoken (%s)", effect.turn_id)

    async def _check_drift(self, turn_id: str, spoken: str) -> None:
        agent = self.agent_answers.get(turn_id)
        mode = "consulted" if agent is not None else "unconsulted"
        prompt = (
            [SystemMessage(DRIFT_SYSTEM), HumanMessage(f"ANSWER:\n{agent}\n\nSAID:\n{spoken}")]
            if agent is not None
            else [SystemMessage(CLAIM_SYSTEM), HumanMessage(f"SAID:\n{spoken}")]
        )
        ctx = TurnContext(
            session_id=self.session_id,
            turn_id=turn_id,
            channel="voice",
            emit=self._emit,
            trace=TraceRecorder(),
            pool=self.pool,
            settings=self.settings,
            chaos=MemoryChaosStore(),
        )
        try:
            result: DriftResult = await self.llm.complete(ctx, "voice_drift", prompt, schema=DriftResult)
        except LLMError:
            log.warning("drift check unavailable for %s", turn_id)
            return
        ctx.trace.add_span(
            "voice_drift", "voice", mode=mode, drift=result.drift, reason=result.reason, said=spoken, answer=agent
        )
        async with self.pool.connection() as conn:
            await append_trace(
                conn,
                turn_id,
                self.session_id,
                "voice",
                spans=[s.model_dump() for s in ctx.trace.spans],
                usage=[u.model_dump() for u in ctx.trace.usage],
            )
        await self.runner.publish_trace(self.session_id, turn_id)
