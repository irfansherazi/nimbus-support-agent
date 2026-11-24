"""The single door to chat models: timeouts, retries with jittered backoff, a cross-provider fallback,
fault injection, and usage/cost accounting into the turn trace.

Every LLM call in the agent goes through `complete` or `stream`, so resilience and observability are uniform.
"""

import asyncio
import json
import random
import time
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable, Sequence
from dataclasses import dataclass
from typing import Any, Literal, Protocol, TypeVar

import anthropic
import openai
from langchain_core.messages import AIMessage, AIMessageChunk, BaseMessage
from pydantic import BaseModel, SecretStr

from app.budget import BudgetGuard
from app.config import Settings
from app.context import TurnContext
from app.events import StepEvent
from app.llm.errors import LLMError, LLMErrorCode, LLMRateLimited, LLMTimeout, LLMUnavailable
from app.llm.pricing import cost_usd
from app.observability.trace import LLMUsage

Purpose = Literal["classify", "agent", "respond", "verify", "voice_drift"]
T = TypeVar("T")


class ChatModelLike(Protocol):
    async def ainvoke(self, messages: list[BaseMessage], **kwargs: Any) -> Any: ...

    def astream(self, messages: list[BaseMessage], **kwargs: Any) -> AsyncIterator[AIMessageChunk]: ...

    def bind_tools(self, tools: Sequence[Any], **kwargs: Any) -> Any: ...

    def with_structured_output(self, schema: Any, **kwargs: Any) -> Any: ...


@dataclass
class _Chaos:
    timeout: bool = False
    rate_limit: bool = False
    outage: bool = False


def model_name(model: Any) -> str:
    return str(getattr(model, "model_name", None) or getattr(model, "model", None) or type(model).__name__)


def text_of(content: Any) -> str:
    """Message content as plain text (Anthropic returns a list of content blocks)."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(p.get("text", "") if isinstance(p, dict) else str(p) for p in content)
    return str(content or "")


def classify_error(exc: BaseException) -> LLMErrorCode | None:
    """Map provider exceptions to a retryable code, or None for errors a retry won't fix."""
    if isinstance(exc, LLMError):
        return exc.code
    if isinstance(exc, TimeoutError | openai.APITimeoutError | anthropic.APITimeoutError):
        return "LLM_TIMEOUT"
    if isinstance(exc, openai.RateLimitError | anthropic.RateLimitError):
        return "RATE_LIMITED"
    if isinstance(
        exc,
        openai.InternalServerError
        | anthropic.InternalServerError
        | openai.APIConnectionError
        | anthropic.APIConnectionError,
    ):
        return "LLM_UNAVAILABLE"
    return None


class LLMGateway:
    def __init__(
        self,
        primary: dict[str, ChatModelLike],
        fallback: ChatModelLike | None,
        settings: Settings,
        budget: BudgetGuard | None = None,
    ) -> None:
        self._primary = primary
        self._fallback = fallback
        self._settings = settings
        self._budget = budget

    # ------------------------------------------------------------------ public

    async def complete(
        self,
        ctx: TurnContext,
        purpose: Purpose,
        messages: list[BaseMessage],
        *,
        tools: Sequence[Any] | None = None,
        schema: type[BaseModel] | None = None,
    ) -> Any:
        """One non-streaming call. Returns an AIMessage, or the parsed `schema` instance."""

        async def call(model: ChatModelLike) -> Any:
            runnable: Any = model
            if tools:
                runnable = model.bind_tools(tools)
            if schema is not None:
                runnable = model.with_structured_output(schema, include_raw=True)
            t0 = time.perf_counter()
            result = await asyncio.wait_for(runnable.ainvoke(messages), self._settings.llm_timeout_s)
            if schema is not None:
                if result.get("parsed") is None:
                    raise ValueError(f"structured output did not parse: {result.get('parsing_error')}")
                await self._record(
                    ctx, purpose, model, result["raw"], messages, t0, json.dumps(result["parsed"].model_dump())
                )
                return result["parsed"]
            await self._record(ctx, purpose, model, result, messages, t0, _render_output(result))
            return result

        return await self._resilient(ctx, purpose, call)

    async def stream(self, ctx: TurnContext, purpose: Purpose, messages: list[BaseMessage]) -> AsyncIterator[str]:
        """Stream text deltas. Retries and fallback apply until the first token; a stall after that raises."""
        timeout = self._settings.llm_timeout_s

        async def open_stream(model: ChatModelLike) -> tuple[ChatModelLike, AsyncIterator[AIMessageChunk], Any, float]:
            t0 = time.perf_counter()
            it = model.astream(messages).__aiter__()
            try:
                first = await asyncio.wait_for(it.__anext__(), timeout)
            except StopAsyncIteration:
                first = None
            return model, it, first, t0

        model, it, first, t0 = await self._resilient(ctx, purpose, open_stream)
        if first is None:
            return
        if ctx.trace.latency.ttft_ms is None:
            ctx.trace.latency.ttft_ms = ctx.trace.elapsed_ms()
        aggregate: AIMessageChunk = first
        yield text_of(first.content)
        while True:
            try:
                chunk = await asyncio.wait_for(it.__anext__(), timeout)
            except StopAsyncIteration:
                break
            except TimeoutError as exc:
                raise LLMUnavailable("LLM_TIMEOUT", "stream stalled mid-answer") from exc
            aggregate = aggregate + chunk
            yield text_of(chunk.content)
        await self._record(ctx, purpose, model, aggregate, messages, t0, text_of(aggregate.content))

    # ----------------------------------------------------------------- internals

    async def _resilient(self, ctx: TurnContext, purpose: Purpose, call: Callable[[ChatModelLike], Awaitable[T]]) -> T:
        chaos = _Chaos(
            timeout=await ctx.chaos.consume("llm_timeout_next"),
            rate_limit=await ctx.chaos.consume("llm_429_next"),
            outage=await ctx.chaos.consume("llm_outage_next"),
        )
        primary = self._primary[purpose]
        last: LLMErrorCode = "LLM_UNAVAILABLE"
        retries = self._settings.llm_max_retries
        for attempt in range(retries + 1):
            try:
                _simulate(chaos, attempt, is_fallback=False)
                return await call(primary)
            except Exception as exc:  # noqa: BLE001 - every failure is classified below
                code = classify_error(exc)
                last = code or "LLM_UNAVAILABLE"
                if code is None or attempt == retries:
                    break
                if code == "RATE_LIMITED":
                    _system_step(ctx, "Rate limited — retrying…", "step_started")
                await asyncio.sleep(self._settings.llm_backoff_base_s * (2**attempt) * (0.5 + random.random()))
                if code == "RATE_LIMITED":
                    _system_step(ctx, "Rate limited — retrying…", "step_completed")

        if self._fallback is None:
            raise LLMUnavailable(last)
        step_id = uuid.uuid4().hex[:8]
        _system_step(ctx, "Switching to backup model…", "step_started", step_id)
        try:
            _simulate(chaos, 0, is_fallback=True)
            result = await call(self._fallback)
        except Exception as exc:
            _system_step(ctx, "Switching to backup model…", "step_failed", step_id, error=last)
            raise LLMUnavailable(classify_error(exc) or last, str(exc)) from exc
        _system_step(ctx, "Switching to backup model…", "step_completed", step_id)
        return result

    async def _record(
        self,
        ctx: TurnContext,
        purpose: Purpose,
        model: ChatModelLike,
        raw: AIMessage,
        messages: list[BaseMessage],
        t0: float,
        output: str,
    ) -> None:
        meta: dict[str, Any] = dict(raw.usage_metadata or {})
        cached = int((meta.get("input_token_details") or {}).get("cache_read", 0) or 0)
        name = model_name(model)
        usage = LLMUsage(
            model=name,
            purpose=purpose,
            input_tokens=int(meta.get("input_tokens", 0)),
            output_tokens=int(meta.get("output_tokens", 0)),
            cached_input_tokens=cached,
            cost_usd=cost_usd(name, int(meta.get("input_tokens", 0)), int(meta.get("output_tokens", 0)), cached),
            latency_ms=int((time.perf_counter() - t0) * 1000),
        )
        prompt = [{"role": m.type, "content": text_of(m.content)[:4000]} for m in messages]
        ctx.trace.record_llm(usage, prompt=prompt, output=output[:4000])
        if self._budget is not None:
            await self._budget.charge(usage.cost_usd)


def _render_output(msg: AIMessage) -> str:
    text = text_of(msg.content)
    if msg.tool_calls:
        calls = [{"name": c["name"], "args": c["args"]} for c in msg.tool_calls]
        text = (text + "\n" if text else "") + "tool_calls: " + json.dumps(calls)
    return text


def _simulate(chaos: _Chaos, attempt: int, is_fallback: bool) -> None:
    if chaos.outage:
        raise LLMTimeout("simulated provider outage")
    if is_fallback:
        return
    if chaos.timeout:
        raise LLMTimeout("simulated timeout")
    if chaos.rate_limit and attempt == 0:
        raise LLMRateLimited("simulated 429")


def _system_step(
    ctx: TurnContext,
    label: str,
    kind: Literal["step_started", "step_completed", "step_failed"],
    step_id: str | None = None,
    error: str | None = None,
) -> None:
    ctx.emit(
        StepEvent(
            type=kind,
            turn_id=ctx.turn_id,
            step_id=step_id or f"sys-{uuid.uuid4().hex[:8]}",
            tool="llm",
            label=label,
            kind="system",
            error=error,
        )
    )


def build_gateway(settings: Settings, budget: BudgetGuard | None = None) -> LLMGateway:
    from langchain_anthropic import ChatAnthropic
    from langchain_openai import ChatOpenAI

    def openai_model(name: str, temperature: float) -> ChatOpenAI:
        return ChatOpenAI(
            model=name, api_key=SecretStr(settings.openai_api_key), max_retries=0, stream_usage=True, temperature=temperature
        )

    agent = openai_model(settings.agent_model, 0.2)
    small = openai_model(settings.small_model, 0.0)
    primary: dict[str, Any] = {
        "agent": agent,
        "respond": agent,
        "classify": small,
        "verify": small,
        "voice_drift": small,
    }
    fallback: Any = (
        ChatAnthropic(  # type: ignore[call-arg]
            model_name=settings.fallback_model, api_key=SecretStr(settings.anthropic_api_key), max_retries=0
        )
        if settings.anthropic_api_key
        else None
    )
    return LLMGateway(primary, fallback, settings, budget)
