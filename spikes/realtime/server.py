"""THROWAWAY SPIKE (Task 2): confirm the OpenAI Realtime WebRTC + server-side "sideband" flow before building voice.

Run:  cd backend && uv run python ../spikes/realtime/server.py     then open http://localhost:8001 in Chrome.

What it checks:
  1. The browser's SDP offer can go through OUR server (API key never in the browser) to POST /v1/realtime/calls.
  2. The server can attach to that call over wss://.../v1/realtime?call_id=... (the sideband) and receive
     function calls / transcripts, and answer a tool call.
  3. Which event names actually arrive (server side and browser data channel), for each scenario.
Every event is appended to spikes/realtime/fixtures/<scenario>.server.jsonl and <scenario>.client.jsonl.
"""

import asyncio
import json
import os
import sys
import time
from pathlib import Path

import httpx
import uvicorn
import websockets
from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, PlainTextResponse

HERE = Path(__file__).resolve().parent
FIXTURES = HERE / "fixtures"
FIXTURES.mkdir(exist_ok=True)
sys.path.insert(0, str(HERE.parents[1] / "backend"))
from app.config import Settings  # noqa: E402

settings = Settings(_env_file=str(HERE.parents[1] / "backend" / ".env"))
KEY = settings.openai_api_key
app = FastAPI()
tasks: set[asyncio.Task[None]] = set()

SESSION = {
    "type": "realtime",
    "model": settings.realtime_model,
    "instructions": (
        "You are the voice of Nimbus customer support. Greet briefly. For ANY question about accounts, billing, "
        "refunds, plans or policies, first say a short holding line like 'Let me check that for you', then call "
        "consult_agent with the customer's request, and read its answer back faithfully without adding facts."
    ),
    "audio": {
        "input": {
            "transcription": {"model": settings.transcription_model},
            "turn_detection": {"type": "server_vad"},
        },
        "output": {"voice": settings.realtime_voice},
    },
    "tools": [
        {
            "type": "function",
            "name": "consult_agent",
            "description": "Ask the support agent (it has the customer's account and the policy docs).",
            "parameters": {
                "type": "object",
                "properties": {"user_request": {"type": "string"}},
                "required": ["user_request"],
            },
        }
    ],
    "tool_choice": "auto",
}

HISTORY = [
    ("user", "input_text", "Hi, my name is Dana and my account is C-1001."),
    ("assistant", "output_text", "Thanks Dana. I have your account C-1001 noted."),
]

CANNED = (
    "Pro plan refunds are available up to two hundred dollars within thirty days of the invoice date. "
    "Your invoice INV 2207 for forty-nine dollars qualifies."
)


def log(scenario: str, side: str, event: dict) -> None:
    with open(FIXTURES / f"{scenario}.{side}.jsonl", "a", encoding="utf-8") as f:
        f.write(json.dumps({"t": round(time.time(), 3), **event}) + "\n")


async def sideband(call_id: str, scenario: str) -> None:
    url = f"wss://api.openai.com/v1/realtime?call_id={call_id}"
    try:
        async with websockets.connect(url, additional_headers={"Authorization": f"Bearer {KEY}"}) as ws:
            log(scenario, "server", {"type": "spike.sideband_connected", "call_id": call_id})
            if scenario == "history":
                for role, ctype, text in HISTORY:
                    await ws.send(json.dumps({
                        "type": "conversation.item.create",
                        "item": {"type": "message", "role": role, "content": [{"type": ctype, "text": text}]},
                    }))
            async for raw in ws:
                event = json.loads(raw)
                log(scenario, "server", event)
                if event.get("type") == "response.function_call_arguments.done":
                    await asyncio.sleep(2)  # simulate the agent working
                    await ws.send(json.dumps({
                        "type": "conversation.item.create",
                        "item": {"type": "function_call_output", "call_id": event["call_id"], "output": CANNED},
                    }))
                    await ws.send(json.dumps({"type": "response.create"}))
    except Exception as exc:  # noqa: BLE001 - spike: record whatever happens
        log(scenario, "server", {"type": "spike.sideband_error", "error": repr(exc)})


@app.get("/")
async def index() -> FileResponse:
    return FileResponse(HERE / "index.html")


@app.post("/offer")
async def offer(request: Request, scenario: str = "default") -> PlainTextResponse:
    sdp = (await request.body()).decode()
    async with httpx.AsyncClient(timeout=20) as client:
        r = await client.post(
            "https://api.openai.com/v1/realtime/calls",
            headers={"Authorization": f"Bearer {KEY}"},
            files={"sdp": (None, sdp), "session": (None, json.dumps(SESSION))},
        )
    log(scenario, "server", {"type": "spike.calls_response", "status": r.status_code,
                             "location": r.headers.get("location"), "body_head": r.text[:300]})
    if r.status_code >= 300:
        return PlainTextResponse(r.text, status_code=502)
    call_id = (r.headers.get("location") or "").rstrip("/").split("/")[-1]
    task = asyncio.create_task(sideband(call_id, scenario))
    tasks.add(task)
    task.add_done_callback(tasks.discard)
    return PlainTextResponse(r.text, media_type="application/sdp")


@app.post("/client-log")
async def client_log(request: Request, scenario: str = "default") -> dict:
    log(scenario, "client", await request.json())
    return {"ok": True}


if __name__ == "__main__":
    if not KEY:
        raise SystemExit("OPENAI_API_KEY missing in backend/.env")
    uvicorn.run(app, host="127.0.0.1", port=int(os.environ.get("PORT", "8001")), log_level="warning")
