"""Pure mapping from OpenAI Realtime server events to bridge effects (see docs/spikes/2026-11-24-realtime-sideband.md).

Turn identity: each user utterance is a turn, `v_<user audio item_id>`. Every response created after that item is
committed belongs to the turn (including the follow-up response after a tool output); the user's transcript, which
can arrive late, joins the same turn through its item_id.

What gets remembered is what the customer heard:
- an assistant message is stored when its audio finishes playing (`output_audio_buffer.stopped`), or, if the
  customer talked over it, when `conversation.item.truncated` says how much played (cut with `truncate_spoken`);
- holding lines (a response that also called a tool) are never stored;
- generated-but-never-played responses are never stored.
"""

import json
from dataclasses import dataclass, field
from typing import Any, Literal

from app.voice.truncate import truncate_spoken


@dataclass(frozen=True)
class StoreUserTranscript:
    turn_id: str
    text: str


@dataclass(frozen=True)
class StoreAssistantTranscript:
    turn_id: str
    text: str
    interrupted: bool


@dataclass(frozen=True)
class RunConsult:
    turn_id: str
    call_id: str
    user_request: str


@dataclass(frozen=True)
class RecordRealtimeUsage:
    turn_id: str
    kind: Literal["realtime", "transcription"]
    usage: dict[str, Any]


@dataclass(frozen=True)
class RecordVoiceLatency:
    turn_id: str
    ms: int


@dataclass(frozen=True)
class RealtimeError:
    message: str


Effect = (
    StoreUserTranscript
    | StoreAssistantTranscript
    | RunConsult
    | RecordRealtimeUsage
    | RecordVoiceLatency
    | RealtimeError
)


def turn_for_item(item_id: str | None) -> str:
    return f"v_{item_id}" if item_id else "v_start"


@dataclass
class RealtimeEventHandler:
    last_user_item: str | None = None
    resp_turn: dict[str, str] = field(default_factory=dict)
    resp_has_call: set[str] = field(default_factory=set)
    resp_items: dict[str, list[str]] = field(default_factory=dict)
    item_resp: dict[str, str] = field(default_factory=dict)
    item_text: dict[str, str] = field(default_factory=dict)
    pending_truncation: dict[str, int] = field(default_factory=dict)
    settled_items: set[str] = field(default_factory=set)
    speech_stopped_ms: dict[str, int] = field(default_factory=dict)
    latency_done: set[str] = field(default_factory=set)

    def handle(self, event: dict[str, Any], now_ms: int) -> list[Effect]:
        method = getattr(self, "_on_" + event.get("type", "").replace(".", "_"), None)
        return method(event, now_ms) if method else []

    # ---------------------------------------------------------------- user side

    def _on_input_audio_buffer_committed(self, e: dict[str, Any], now: int) -> list[Effect]:
        self.last_user_item = e.get("item_id")
        return []

    def _on_input_audio_buffer_speech_stopped(self, e: dict[str, Any], now: int) -> list[Effect]:
        self.speech_stopped_ms[turn_for_item(e.get("item_id"))] = now
        return []

    def _on_conversation_item_input_audio_transcription_completed(self, e: dict[str, Any], now: int) -> list[Effect]:
        turn = turn_for_item(e.get("item_id"))
        out: list[Effect] = []
        text = (e.get("transcript") or "").strip()
        if text:
            out.append(StoreUserTranscript(turn, text))
        if e.get("usage"):
            out.append(RecordRealtimeUsage(turn, "transcription", e["usage"]))
        return out

    # ---------------------------------------------------------------- responses

    def _turn_of(self, response_id: str | None) -> str:
        if response_id and response_id in self.resp_turn:
            return self.resp_turn[response_id]
        return turn_for_item(self.last_user_item)

    def _on_response_created(self, e: dict[str, Any], now: int) -> list[Effect]:
        rid = (e.get("response") or {}).get("id")
        if rid:
            self.resp_turn[rid] = turn_for_item(self.last_user_item)
        return []

    def _on_response_output_item_added(self, e: dict[str, Any], now: int) -> list[Effect]:
        if (e.get("item") or {}).get("type") == "function_call" and e.get("response_id"):
            self.resp_has_call.add(e["response_id"])
        return []

    def _on_response_function_call_arguments_done(self, e: dict[str, Any], now: int) -> list[Effect]:
        rid = e.get("response_id")
        if rid:
            self.resp_has_call.add(rid)
        try:
            args = json.loads(e.get("arguments") or "{}")
        except json.JSONDecodeError:
            args = {}
        request = str(args.get("user_request") or "").strip()
        return [RunConsult(self._turn_of(rid), e.get("call_id", ""), request)]

    def _on_response_output_audio_transcript_done(self, e: dict[str, Any], now: int) -> list[Effect]:
        rid, item = e.get("response_id", ""), e.get("item_id", "")
        self.item_text[item] = e.get("transcript") or ""
        self.item_resp[item] = rid
        self.resp_items.setdefault(rid, []).append(item)
        if item in self.pending_truncation:
            return self._settle(item, self.pending_truncation.pop(item))
        return []

    def _on_response_done(self, e: dict[str, Any], now: int) -> list[Effect]:
        response = e.get("response") or {}
        rid = response.get("id")
        if rid and any(o.get("type") == "function_call" for o in response.get("output") or []):
            self.resp_has_call.add(rid)
        usage = response.get("usage")
        return [RecordRealtimeUsage(self._turn_of(rid), "realtime", usage)] if usage else []

    # ---------------------------------------------------------------- playback

    def _on_output_audio_buffer_started(self, e: dict[str, Any], now: int) -> list[Effect]:
        turn = self._turn_of(e.get("response_id"))
        if turn in self.speech_stopped_ms and turn not in self.latency_done:
            self.latency_done.add(turn)
            return [RecordVoiceLatency(turn, now - self.speech_stopped_ms[turn])]
        return []

    def _on_output_audio_buffer_stopped(self, e: dict[str, Any], now: int) -> list[Effect]:
        out: list[Effect] = []
        for item in self.resp_items.get(e.get("response_id", ""), []):
            out.extend(self._settle(item, None))
        return out

    def _on_conversation_item_truncated(self, e: dict[str, Any], now: int) -> list[Effect]:
        item, played = e.get("item_id", ""), int(e.get("audio_end_ms") or 0)
        if item not in self.item_text:
            self.pending_truncation[item] = played  # the transcript hasn't arrived yet
            return []
        return self._settle(item, played)

    def _settle(self, item: str, played_ms: int | None) -> list[Effect]:
        """Store an assistant item once: in full (played_ms None) or cut to what played."""
        if item in self.settled_items:
            return []
        self.settled_items.add(item)
        rid = self.item_resp.get(item, "")
        text = self.item_text.get(item, "").strip()
        if not text or rid in self.resp_has_call:  # holding line, or nothing said
            return []
        if played_ms is None:
            return [StoreAssistantTranscript(self._turn_of(rid), text, interrupted=False)]
        return [StoreAssistantTranscript(self._turn_of(rid), truncate_spoken(text, played_ms), interrupted=True)]

    # ---------------------------------------------------------------- errors

    def _on_error(self, e: dict[str, Any], now: int) -> list[Effect]:
        return [RealtimeError(str((e.get("error") or {}).get("message") or e))]
