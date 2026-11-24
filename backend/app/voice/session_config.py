"""Realtime session configuration: the voice model is only the voice; the LangGraph agent is the brain."""

from typing import Any

from app.config import Settings
from app.models import Message

VOICE_FRONTEND_INSTRUCTIONS = """You are the voice of Nimbus customer support.
Speak English only, in short, natural sentences.

- Handle greetings, thanks and goodbyes yourself, briefly, without calling any tool.
- For anything about the customer's account, identity, invoices, billing, refunds, plans, policies, support hours
  or troubleshooting: say ONE short holding line (for example "Let me check that for you."), then call
  consult_agent with the customer's request in their own words, including any account ID or PIN they said.
- When consult_agent returns, say its answer faithfully and add no facts: do not add, change or guess any number,
  date, limit, policy or ID. You may shorten it slightly, but keep every number and ID.
- Never answer account or policy questions from memory or from earlier in the conversation. Call consult_agent
  again, even if the topic came up before.
- If the customer asks for a human, call consult_agent with that request.
- If you couldn't make out what they said, or it wasn't English, ask them to repeat it. Don't guess."""

CONSULT_TOOL: dict[str, Any] = {
    "type": "function",
    "name": "consult_agent",
    "description": (
        "Ask Nimbus's support agent, which can verify the customer, look up invoices, issue refunds, update the "
        "account, open tickets and answer from the policy documents."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "user_request": {"type": "string", "description": "The customer's request, in their own words."}
        },
        "required": ["user_request"],
    },
}


def build_session_config(settings: Settings) -> dict[str, Any]:
    return {
        "type": "realtime",
        "model": settings.realtime_model,
        "instructions": VOICE_FRONTEND_INSTRUCTIONS,
        "audio": {
            "input": {
                "transcription": {"model": settings.transcription_model, "language": "en"},
                "noise_reduction": {"type": "near_field"},
                "turn_detection": {"type": "server_vad"},
            },
            "output": {"voice": settings.realtime_voice},
        },
        "tools": [CONSULT_TOOL],
        "tool_choice": "auto",
    }


def history_items(messages: list[Message]) -> list[dict[str, Any]]:
    """Earlier turns (chat or voice) injected into the call, so the voice can talk naturally about them."""
    return [
        {
            "type": "conversation.item.create",
            "item": {
                "type": "message",
                "role": m.role,
                "content": [{"type": "input_text" if m.role == "user" else "output_text", "text": m.content}],
            },
        }
        for m in messages
    ]
