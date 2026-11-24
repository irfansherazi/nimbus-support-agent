import asyncio
from uuid import uuid4

from pydantic import TypeAdapter

from app.bus import SessionBus
from app.events import AgentEvent, ErrorEvent, StepEvent, TokenEvent
from tests.helpers import take

SID = uuid4()


async def test_bus_seq_and_replay_after_last_event_id():
    bus = SessionBus(buffer_size=500)
    for i in range(5):
        bus.publish(SID, TokenEvent(turn_id="t", text=str(i)))
    got = [e async for e in take(bus.subscribe(SID, last_seq=2), 2)]
    assert [e.seq for e in got] == [3, 4] and [e.text for e in got] == ["2", "3"]


async def test_bus_buffer_bounded():
    bus = SessionBus(buffer_size=3)
    for i in range(10):
        bus.publish(SID, TokenEvent(turn_id="t", text=str(i)))
    got = [e async for e in take(bus.subscribe(SID, last_seq=0), 3)]
    assert [e.seq for e in got] == [8, 9, 10]


async def test_bus_live_delivery_after_replay():
    bus = SessionBus()
    bus.publish(SID, TokenEvent(turn_id="t", text="old"))

    async def collect():
        return [e async for e in take(bus.subscribe(SID, last_seq=0), 2)]

    task = asyncio.create_task(collect())
    await asyncio.sleep(0.01)
    bus.publish(SID, TokenEvent(turn_id="t", text="new"))
    got = await asyncio.wait_for(task, 1)
    assert [e.text for e in got] == ["old", "new"]


async def test_subscribe_without_last_seq_gets_only_live_events():
    bus = SessionBus()
    bus.publish(SID, TokenEvent(turn_id="t", text="old"))

    async def first():
        async for e in bus.subscribe(SID, last_seq=None):
            return e

    task = asyncio.create_task(first())
    await asyncio.sleep(0.01)
    bus.publish(SID, TokenEvent(turn_id="t", text="live"))
    assert (await asyncio.wait_for(task, 1)).text == "live"


async def test_sessions_are_isolated():
    bus = SessionBus()
    other = uuid4()
    assert bus.publish(SID, TokenEvent(turn_id="t", text="a")) == 1
    assert bus.publish(other, TokenEvent(turn_id="t", text="b")) == 1


def test_event_union_discriminates_on_type():
    ta = TypeAdapter(AgentEvent)
    e = ta.validate_python(
        {
            "type": "step_started",
            "turn_id": "t",
            "step_id": "s1",
            "tool": "verify_customer",
            "label": "Verifying account & tier…",
            "kind": "tool",
        }
    )
    assert isinstance(e, StepEvent) and e.type == "step_started"
    err = ta.validate_python(
        {"type": "error", "turn_id": "t", "code": "LLM_TIMEOUT", "retryable": True, "message": "m"}
    )
    assert isinstance(err, ErrorEvent)
