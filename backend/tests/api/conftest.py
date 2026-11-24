import asyncio
import json
from collections.abc import AsyncIterator
from typing import Any

import httpx
import pytest
import uvicorn

from app.agent.graph import AgentDeps
from app.api.deps import build_services
from app.main import create_app
from app.rag.embedder import HashEmbedder
from app.tools.registry import build_registry
from app.tools.runner import ToolRunner
from tests.agent.scripted_llm import CR, VR, ScriptedLLM
from tests.fakes import fast_settings


def small_talk_llm(n: int = 1, answer: str = "Hi! How can I help?") -> ScriptedLLM:
    return ScriptedLLM(
        classify=[CR("small_talk") for _ in range(n)],
        respond=[answer for _ in range(n)],
        verify=[VR("supported") for _ in range(n)],
    )


@pytest.fixture
async def api(pool):
    """Factory: start the real app (with a scripted LLM) on a random local port; returns an httpx client."""
    started: list[tuple[uvicorn.Server, asyncio.Task[None], httpx.AsyncClient]] = []

    async def make(llm: ScriptedLLM, **overrides: Any) -> httpx.AsyncClient:
        settings = fast_settings(**overrides)
        deps = AgentDeps(llm=llm, runner=ToolRunner(build_registry(), slow_seconds=0.01), embedder=HashEmbedder())
        services = build_services(settings, pool, deps)
        app = create_app(settings, services=services)
        server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=0, log_level="warning"))
        task = asyncio.create_task(server.serve())
        while not server.started:
            await asyncio.sleep(0.01)
        port = server.servers[0].sockets[0].getsockname()[1]
        client = httpx.AsyncClient(base_url=f"http://127.0.0.1:{port}", timeout=10)
        client.services = services  # type: ignore[attr-defined]
        started.append((server, task, client))
        return client

    yield make
    for server, task, client in started:
        await client.aclose()
        server.should_exit = True
        await task


async def collect_sse(
    client: httpx.AsyncClient, sid: str, until: str = "turn_completed", last_event_id: int | None = 0, count: int = 1
) -> list[dict[str, Any]]:
    """Read the session's SSE stream until `count` events of type `until` arrive (Last-Event-ID 0 = replay all)."""
    headers = {} if last_event_id is None else {"Last-Event-ID": str(last_event_id)}
    events: list[dict[str, Any]] = []
    seen = 0

    async def read() -> None:
        nonlocal seen
        async with client.stream("GET", f"/api/sessions/{sid}/events", headers=headers) as r:
            assert r.status_code == 200
            assert r.headers["content-type"].startswith("text/event-stream")
            async for line in _lines(r):
                if line.startswith("data:"):
                    event = json.loads(line[5:].strip())
                    events.append(event)
                    if event["type"] == until:
                        seen += 1
                        if seen >= count:
                            return

    await asyncio.wait_for(read(), 10)
    return events


async def _lines(r: httpx.Response) -> AsyncIterator[str]:
    async for line in r.aiter_lines():
        yield line


async def wait_messages(client: httpx.AsyncClient, sid: str, n: int, timeout: float = 10) -> list[dict[str, Any]]:
    deadline = asyncio.get_running_loop().time() + timeout
    while True:
        msgs = (await client.get(f"/api/sessions/{sid}")).json()["messages"]
        if len(msgs) >= n or asyncio.get_running_loop().time() > deadline:
            return msgs
        await asyncio.sleep(0.05)
