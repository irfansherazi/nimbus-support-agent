"""A stand-in for LLMGateway that plays back per-purpose scripts, so graph routing is tested deterministically."""

import itertools
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any

from langchain_core.messages import AIMessage, BaseMessage

from app.agent.guardrails import ClassifyResult, VerifyResult
from app.context import TurnContext

_ids = itertools.count(1)


def tool_call(name: str, **args: Any) -> AIMessage:
    return AIMessage(content="", tool_calls=[{"name": name, "args": args, "id": f"call_{next(_ids)}"}])


def CR(intent: str) -> ClassifyResult:  # noqa: N802
    return ClassifyResult(intent=intent, rationale="test")  # type: ignore[arg-type]


def VR(verdict: str) -> VerifyResult:  # noqa: N802
    return VerifyResult(verdict=verdict, reason="test")  # type: ignore[arg-type]


@dataclass
class Call:
    purpose: str
    messages: list[BaseMessage]
    tools: Any = None


@dataclass
class ScriptedLLM:
    classify: list[Any] = field(default_factory=list)
    agent: list[Any] = field(default_factory=list)
    respond: list[str] = field(default_factory=list)
    verify: list[Any] = field(default_factory=list)
    voice_drift: list[Any] = field(default_factory=list)
    calls: list[Call] = field(default_factory=list)

    def _pop(self, purpose: str) -> Any:
        queue = getattr(self, purpose)
        if not queue:
            raise AssertionError(f"ScriptedLLM: no scripted response left for '{purpose}'")
        item = queue.pop(0)
        if isinstance(item, BaseException):
            raise item
        return item

    async def complete(
        self, ctx: TurnContext, purpose: str, messages: list[BaseMessage], *, tools: Any = None, schema: Any = None
    ) -> Any:
        self.calls.append(Call(purpose, messages, tools))
        item = self._pop(purpose)
        return AIMessage(content=item) if isinstance(item, str) else item

    async def stream(self, ctx: TurnContext, purpose: str, messages: list[BaseMessage]) -> AsyncIterator[str]:
        self.calls.append(Call(purpose, messages))
        text = self._pop(purpose)
        words = text.split(" ")
        for i, w in enumerate(words):
            yield w + ("" if i == len(words) - 1 else " ")
