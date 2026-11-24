"""Test doubles shared across suites: a scripted chat model and a turn-context factory."""

import json
from collections.abc import AsyncIterator
from typing import Any
from uuid import UUID, uuid4

from langchain_core.messages import AIMessage, AIMessageChunk, BaseMessage
from pydantic import BaseModel

from app.chaos import MemoryChaosStore
from app.config import Settings
from app.context import TurnContext
from app.events import AgentEvent
from app.observability.trace import TraceRecorder


def usage(i: int = 10, o: int = 2) -> dict[str, int]:
    return {"input_tokens": i, "output_tokens": o, "total_tokens": i + o}


class FakeModel:
    """Plays back a script of strings / AIMessages / BaseModels / exceptions, one per call."""

    def __init__(self, script: list[Any], model_name: str = "fake-model") -> None:
        self.script = list(script)
        self.model_name = model_name
        self.calls: list[list[BaseMessage]] = []
        self.bound_tools: list[Any] | None = None

    def _next(self) -> Any:
        if not self.script:
            raise AssertionError(f"{self.model_name}: script exhausted")
        item = self.script.pop(0)
        if isinstance(item, BaseException):
            raise item
        return item

    async def ainvoke(self, messages: list[BaseMessage], **_: Any) -> AIMessage:
        self.calls.append(messages)
        item = self._next()
        if isinstance(item, str):
            return AIMessage(content=item, usage_metadata=usage())
        return item

    async def astream(self, messages: list[BaseMessage], **_: Any) -> AsyncIterator[AIMessageChunk]:
        self.calls.append(messages)
        item = self._next()
        text = item if isinstance(item, str) else str(item.content)
        words = text.split(" ")
        for i, w in enumerate(words):
            last = i == len(words) - 1
            yield AIMessageChunk(content=w + ("" if last else " "), usage_metadata=usage() if last else None)

    def bind_tools(self, tools: list[Any], **_: Any) -> "FakeModel":
        self.bound_tools = tools
        return self

    def with_structured_output(self, schema: type[BaseModel], include_raw: bool = False, **_: Any) -> "_Structured":
        return _Structured(self)


class _Structured:
    def __init__(self, model: FakeModel) -> None:
        self.model = model

    async def ainvoke(self, messages: list[BaseMessage], **_: Any) -> dict[str, Any]:
        self.model.calls.append(messages)
        parsed = self.model._next()
        raw = AIMessage(content=json.dumps(parsed.model_dump()), usage_metadata=usage())
        return {"raw": raw, "parsed": parsed, "parsing_error": None}


def fast_settings(**overrides: Any) -> Settings:
    base: dict[str, Any] = {"llm_backoff_base_s": 0.0, "llm_timeout_s": 0.5, "llm_max_retries": 2}
    base.update(overrides)
    return Settings(_env_file=None, **base)  # type: ignore[call-arg]


def make_ctx(
    settings: Settings | None = None,
    chaos: dict[str, Any] | None = None,
    pool: Any = None,
    channel: str = "chat",
    session_id: UUID | None = None,
) -> TurnContext:
    """A TurnContext whose emitted events are collected on `ctx.emitted`."""
    emitted: list[AgentEvent] = []
    ctx = TurnContext(
        session_id=session_id or uuid4(),
        turn_id="turn_test",
        channel=channel,  # type: ignore[arg-type]
        emit=emitted.append,
        trace=TraceRecorder(),
        pool=pool,
        settings=settings or fast_settings(),
        chaos=MemoryChaosStore(chaos or {}),
    )
    ctx.emitted = emitted  # type: ignore[attr-defined]
    return ctx
