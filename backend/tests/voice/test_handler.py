"""The event handler is pure: recorded Realtime events in, effects out. Fixtures come from the voice spike."""

import json
from pathlib import Path

from app.voice.handler import (
    RealtimeEventHandler,
    RecordRealtimeUsage,
    RecordVoiceLatency,
    RunConsult,
    StoreAssistantTranscript,
    StoreUserTranscript,
)

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "realtime"


def replay(name: str) -> list:
    handler = RealtimeEventHandler()
    effects = []
    for line in (FIXTURES / name).read_text(encoding="utf-8").splitlines():
        event = json.loads(line)
        effects.extend(handler.handle(event, now_ms=int(event["t"] * 1000)))
    return effects


def of(effects, kind):
    return [e for e in effects if isinstance(e, kind)]


def test_greeting_stores_both_sides_and_never_consults():
    effects = replay("greeting.jsonl")
    assert of(effects, RunConsult) == []
    assert [u.text for u in of(effects, StoreUserTranscript)] == ["Hi there.", "How are you?"]
    [said] = of(effects, StoreAssistantTranscript)
    assert said.text.startswith("Hi, I") and not said.interrupted


def test_consult_runs_the_agent_once_for_the_users_turn():
    effects = replay("consult.jsonl")
    [consult] = of(effects, RunConsult)
    assert "refund policy" in consult.user_request.lower()
    question = next(u for u in of(effects, StoreUserTranscript) if "refund policy" in u.text.lower())
    assert consult.turn_id == question.turn_id  # the late transcript joins the same turn


def test_holding_lines_are_not_stored_but_the_heard_answer_is():
    stored = of(replay("consult.jsonl"), StoreAssistantTranscript)
    assert not any(s.text.startswith("Let me check") for s in stored)
    assert any(s.text.startswith("Pro plan refunds are available") and not s.interrupted for s in stored)


def test_interruptions_store_only_what_was_heard():
    interrupted = [s for s in of(replay("interrupt.jsonl"), StoreAssistantTranscript) if s.interrupted]
    assert interrupted
    for s in interrupted:
        assert s.text.endswith("…")
        assert len(s.text) < 200


def test_interrupt_scenario_consults_per_question():
    assert len(of(replay("interrupt.jsonl"), RunConsult)) == 3


def test_history_answer_stored():
    stored = of(replay("history.jsonl"), StoreAssistantTranscript)
    assert any("Dana" in s.text and "C-1001" in s.text for s in stored)


def test_usage_recorded_for_responses_and_transcription():
    usage = of(replay("consult.jsonl"), RecordRealtimeUsage)
    kinds = {u.kind for u in usage}
    assert kinds == {"realtime", "transcription"}
    assert all(u.turn_id.startswith("v_") for u in usage)


def test_voice_latency_measured_once_per_turn():
    latencies = of(replay("greeting.jsonl"), RecordVoiceLatency)
    assert latencies and all(0 < lat.ms < 5000 for lat in latencies)
    assert len({lat.turn_id for lat in latencies}) == len(latencies)


def test_truncation_before_transcript_is_applied_when_transcript_arrives():
    h = RealtimeEventHandler()
    h.handle({"type": "input_audio_buffer.committed", "item_id": "u1"}, 0)
    h.handle({"type": "response.created", "response": {"id": "r1"}}, 0)
    assert h.handle({"type": "conversation.item.truncated", "item_id": "a1", "audio_end_ms": 1000}, 0) == []
    out = h.handle(
        {
            "type": "response.output_audio_transcript.done",
            "response_id": "r1",
            "item_id": "a1",
            "transcript": "Refunds for Pro are available within thirty days of the invoice date.",
        },
        0,
    )
    [stored] = of(out, StoreAssistantTranscript)
    assert stored.interrupted and stored.text == "Refunds for Pro…" and stored.turn_id == "v_u1"


def test_silent_tool_call_asks_for_a_holding_line():
    from app.voice.handler import SpeakHoldingLine

    h = RealtimeEventHandler()
    h.handle({"type": "input_audio_buffer.committed", "item_id": "u1"}, 0)
    h.handle({"type": "response.created", "response": {"id": "r1"}}, 0)
    done = {"type": "response.done", "response": {"id": "r1", "output": [{"type": "function_call"}]}}
    assert SpeakHoldingLine("v_u1") in h.handle(done, 0)


def test_spoken_holding_line_needs_no_extra_one():
    from app.voice.handler import SpeakHoldingLine

    effects = replay("consult.jsonl")  # the model said "Let me check that for you" itself
    assert not any(isinstance(e, SpeakHoldingLine) for e in effects)


def test_holding_line_responses_are_never_stored():
    h = RealtimeEventHandler()
    h.handle({"type": "input_audio_buffer.committed", "item_id": "u1"}, 0)
    h.handle({"type": "response.created", "response": {"id": "rh", "metadata": {"purpose": "holding"}}}, 0)
    h.handle(
        {
            "type": "response.output_audio_transcript.done",
            "response_id": "rh",
            "item_id": "a1",
            "transcript": "One moment while I check that for you.",
        },
        0,
    )
    assert h.handle({"type": "output_audio_buffer.stopped", "response_id": "rh"}, 0) == []
