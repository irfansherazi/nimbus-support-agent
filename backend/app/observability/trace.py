"""Per-turn tracing: a span tree, LLM usage records and latency, shown in the observability drawer."""

import contextvars
import time
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any, Literal

from pydantic import BaseModel

SpanKind = Literal["node", "llm", "tool", "retrieval", "guardrail", "voice"]


class Span(BaseModel):
    span_id: str
    parent_id: str | None
    name: str
    kind: SpanKind
    start_ms: int
    duration_ms: int
    attrs: dict[str, Any] = {}


class LLMUsage(BaseModel):
    model: str
    purpose: str
    input_tokens: int = 0
    output_tokens: int = 0
    cached_input_tokens: int = 0
    audio_input_tokens: int = 0
    audio_output_tokens: int = 0
    cost_usd: float = 0.0
    latency_ms: int = 0


class Latency(BaseModel):
    ttft_ms: int | None = None
    total_ms: int | None = None
    voice_e2e_ms: int | None = None


class TraceRecorder:
    def __init__(self) -> None:
        self._t0 = time.perf_counter()
        self._current: contextvars.ContextVar[str | None] = contextvars.ContextVar(f"span-{id(self)}", default=None)
        self.spans: list[Span] = []
        self.usage: list[LLMUsage] = []
        self.latency = Latency()

    def elapsed_ms(self) -> int:
        return int((time.perf_counter() - self._t0) * 1000)

    @asynccontextmanager
    async def span(self, name: str, kind: SpanKind, **attrs: Any) -> AsyncIterator[dict[str, Any]]:
        span_id = uuid.uuid4().hex[:12]
        parent = self._current.get()
        token = self._current.set(span_id)
        start = self.elapsed_ms()
        try:
            yield attrs
        except BaseException as exc:
            attrs["error"] = f"{type(exc).__name__}: {exc}"
            raise
        finally:
            self._current.reset(token)
            self.spans.append(
                Span(
                    span_id=span_id,
                    parent_id=parent,
                    name=name,
                    kind=kind,
                    start_ms=start,
                    duration_ms=self.elapsed_ms() - start,
                    attrs=attrs,
                )
            )

    def add_span(self, name: str, kind: SpanKind, duration_ms: int = 0, **attrs: Any) -> Span:
        span = Span(
            span_id=uuid.uuid4().hex[:12],
            parent_id=self._current.get(),
            name=name,
            kind=kind,
            start_ms=max(self.elapsed_ms() - duration_ms, 0),
            duration_ms=duration_ms,
            attrs=attrs,
        )
        self.spans.append(span)
        return span

    def record_llm(self, usage: LLMUsage, prompt: list[dict[str, Any]], output: str) -> None:
        self.usage.append(usage)
        self.add_span(
            f"llm:{usage.purpose}",
            "llm",
            duration_ms=usage.latency_ms,
            model=usage.model,
            purpose=usage.purpose,
            input_tokens=usage.input_tokens,
            output_tokens=usage.output_tokens,
            cost_usd=usage.cost_usd,
            prompt=prompt,
            output=output,
        )

    def total_cost_usd(self) -> float:
        return round(sum(u.cost_usd for u in self.usage), 6)
