from datetime import UTC, datetime

from app.models import Message
from app.voice.session_config import build_session_config, history_items
from app.voice.truncate import truncate_spoken
from tests.fakes import fast_settings


def test_truncate_spoken():
    t = "Refunds for Pro are available within thirty days of the invoice date."
    assert truncate_spoken(t, 2000) == "Refunds for Pro are available…"  # 30 chars @15cps, cut at last word boundary
    assert truncate_spoken(t, 60_000) == t
    assert truncate_spoken(t, 0) == "…"


def test_session_config_has_only_consult_tool_and_pins_english():
    cfg = build_session_config(fast_settings())
    assert [t["name"] for t in cfg["tools"]] == ["consult_agent"]
    assert "consult_agent" in cfg["instructions"] and "add no facts" in cfg["instructions"].lower()
    assert cfg["audio"]["input"]["transcription"]["language"] == "en"
    assert cfg["audio"]["input"]["noise_reduction"] == {"type": "near_field"}
    assert cfg["model"] == "gpt-realtime"


def _msg(i: int, role: str, text: str) -> Message:
    return Message(
        id=i,
        session_id="00000000-0000-0000-0000-000000000001",
        turn_id="t",
        channel="chat",
        role=role,  # type: ignore[arg-type]
        content=text,
        interrupted=False,
        created_at=datetime.now(UTC),
    )


def test_history_items_map_roles_one_to_one():
    items = history_items([_msg(1, "user", "hi"), _msg(2, "assistant", "hello"), _msg(3, "user", "bye")])
    assert [i["type"] for i in items] == ["conversation.item.create"] * 3
    assert [i["item"]["role"] for i in items] == ["user", "assistant", "user"]
    assert [i["item"]["content"][0]["type"] for i in items] == ["input_text", "output_text", "input_text"]
