import asyncio
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest

from app.agent.runner import TurnResult
from app.bus import SessionBus
from app.store.sessions import create_session, recent_messages
from app.store.traces import list_traces
from app.voice.bridge import VoiceBridge
from app.voice.drift import DriftResult
from app.voice.registry import VoiceBusy, VoiceRegistry
from tests.agent.scripted_llm import ScriptedLLM
from tests.fakes import fast_settings

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "realtime"


def fixture_events(name: str) -> list[dict[str, Any]]:
    return [json.loads(line) for line in (FIXTURES / name).read_text(encoding="utf-8").splitlines()]


class FakeTransport:
    def __init__(self, events: list[dict[str, Any]] | None = None, hold_open: bool = False) -> None:
        self.events = events or []
        self.hold_open = hold_open
        self.sent: list[dict[str, Any]] = []
        self.closed = asyncio.Event()
        self.connected = False

    async def connect(self) -> None:
        self.connected = True

    async def send(self, event: dict[str, Any]) -> None:
        self.sent.append(event)

    async def __aiter__(self):
        for e in self.events:
            yield e
            await asyncio.sleep(0)
        if self.hold_open:
            await self.closed.wait()

    async def close(self) -> None:
        self.closed.set()

    async def hangup(self) -> None:
        pass

    def sent_types(self) -> list[str]:
        return [e["type"] for e in self.sent]


@dataclass
class StubRunner:
    answer: str = "Pro plan refunds are available up to $200 within 30 days."
    status: str = "ok"
    calls: list[dict[str, Any]] = field(default_factory=list)
    published: list[str] = field(default_factory=list)

    async def run_turn(self, session_id, text, channel, **kw):
        self.calls.append({"text": text, "channel": channel, **kw})
        return TurnResult(kw["turn_id"], self.status, self.answer if self.status != "failed" else None, None)

    async def publish_trace(self, session_id, turn_id):
        self.published.append(turn_id)


async def new_session(pool):
    async with pool.connection() as c:
        return (await create_session(c)).id


def make_bridge(pool, sid, transport, runner=None, settings=None, drift: bool = False, bus=None):
    llm = ScriptedLLM(voice_drift=[DriftResult(drift=drift, reason="test") for _ in range(10)])
    return VoiceBridge(
        session_id=sid,
        transport=transport,
        runner=runner or StubRunner(),
        pool=pool,
        bus=bus or SessionBus(),
        llm=llm,
        settings=settings or fast_settings(),
        watchdog_interval_s=0.02,
    )


async def test_consult_runs_agent_and_returns_its_answer_to_the_voice(pool):
    sid = await new_session(pool)
    transport, runner = FakeTransport(fixture_events("consult.jsonl")), StubRunner()
    await make_bridge(pool, sid, transport, runner).run(history=[])
    assert transport.connected
    i = transport.sent_types().index("conversation.item.create")
    assert transport.sent[i]["item"] == {
        "type": "function_call_output",
        "call_id": transport.sent[i]["item"]["call_id"],
        "output": runner.answer,
    }
    assert transport.sent_types()[i + 1] == "response.create"
    [call] = runner.calls
    assert call["channel"] == "voice" and call["persist_user"] is False and call["persist_answer"] is False
    assert "refund policy" in call["text"].lower() and call["turn_id"].startswith("v_")


async def test_transcripts_are_stored_as_heard_and_published(pool):
    sid = await new_session(pool)
    bus = SessionBus()
    await make_bridge(pool, sid, FakeTransport(fixture_events("interrupt.jsonl")), bus=bus).run(history=[])
    async with pool.connection() as c:
        msgs = await recent_messages(c, sid, 50)
    assert all(m.channel == "voice" for m in msgs)
    assert any(m.role == "user" for m in msgs) and any(m.role == "assistant" and m.interrupted for m in msgs)
    assert not any(m.role == "assistant" and m.content.startswith("Let me check that for you. I'll get") for m in msgs)
    published = [e async for e in _drain(bus, sid)]
    assert any(e.type == "transcript" and e.interrupted for e in published)


async def test_voice_usage_and_latency_land_in_the_turn_trace(pool):
    sid = await new_session(pool)
    await make_bridge(pool, sid, FakeTransport(fixture_events("greeting.jsonl"))).run(history=[])
    async with pool.connection() as c:
        traces = await list_traces(c, sid)
    usage = [u for t in traces for u in t["usage"]]
    assert any(u["model"] == "gpt-realtime" and u["audio_output_tokens"] > 0 and u["cost_usd"] > 0 for u in usage)
    assert any(u["purpose"] == "transcription" for u in usage)
    assert any("voice_e2e_ms" in t["latency"] for t in traces)


async def test_spoken_answer_is_checked_for_drift(pool):
    sid = await new_session(pool)
    await make_bridge(pool, sid, FakeTransport(fixture_events("consult.jsonl")), drift=True).run(history=[])
    async with pool.connection() as c:
        spans = [s for t in await list_traces(c, sid) for s in t["spans"]]
    drift = [s for s in spans if s["name"] == "voice_drift"]
    assert drift and drift[0]["attrs"]["drift"] is True


async def test_failed_agent_turn_gives_the_voice_a_safe_line(pool):
    sid = await new_session(pool)
    transport = FakeTransport(fixture_events("consult.jsonl"))
    await make_bridge(pool, sid, transport, StubRunner(status="failed")).run(history=[])
    output = next(e for e in transport.sent if e["type"] == "conversation.item.create")["item"]["output"]
    assert "trouble" in output.lower()


async def test_history_is_injected_before_events(pool):
    from datetime import UTC, datetime

    from app.models import Message

    sid = await new_session(pool)
    transport = FakeTransport([])
    m = Message(
        id=1,
        session_id=sid,
        turn_id="t",
        channel="chat",
        role="user",
        content="hi",
        interrupted=False,
        created_at=datetime.now(UTC),
    )
    await make_bridge(pool, sid, transport).run(history=[m])
    assert transport.sent[0]["item"]["content"][0]["text"] == "hi"


async def test_idle_timeout_ends_call_with_voice_limit(pool):
    sid = await new_session(pool)
    bus, transport = SessionBus(), FakeTransport(hold_open=True)
    bridge = make_bridge(pool, sid, transport, settings=fast_settings(voice_idle_seconds=0), bus=bus)
    await asyncio.wait_for(bridge.run(history=[]), 3)
    errors = [e async for e in _drain(bus, sid) if e.type == "error"]
    assert errors and errors[-1].code == "VOICE_LIMIT" and transport.closed.is_set()


async def test_registry_allows_one_call_per_session(pool):
    sid = await new_session(pool)
    transports: list[FakeTransport] = []

    async def fake_create_call(settings, offer_sdp, session):
        return "v=0 answer", "rtc_test"

    def fake_transport(settings, call_id):
        transports.append(FakeTransport(hold_open=True))
        return transports[-1]

    registry = VoiceRegistry(
        pool=pool,
        bus=SessionBus(),
        runner=StubRunner(),
        llm=ScriptedLLM(),
        settings=fast_settings(),
        call_factory=fake_create_call,
        transport_factory=fake_transport,
    )
    assert await registry.start(sid, "v=0 offer") == "v=0 answer"
    assert registry.active(sid)
    with pytest.raises(VoiceBusy):
        await registry.start(sid, "v=0 offer")
    await registry.end(sid)
    await asyncio.sleep(0.05)
    assert not registry.active(sid) and transports[0].closed.is_set()
    await registry.shutdown()


async def _drain(bus: SessionBus, sid):
    async def collect():
        out = []
        async for e in bus.subscribe(sid, last_seq=0):
            out.append(e)
            if e.seq >= bus.last_seq(sid):
                return out
        return out

    if bus.last_seq(sid) == 0:
        return
    for e in await asyncio.wait_for(collect(), 2):
        yield e
