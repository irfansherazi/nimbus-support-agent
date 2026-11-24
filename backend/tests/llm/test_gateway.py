import asyncio

import pytest
from langchain_core.messages import AIMessage, HumanMessage
from pydantic import BaseModel

from app.llm.errors import LLMRateLimited, LLMUnavailable
from app.llm.gateway import LLMGateway
from tests.fakes import FakeModel, fast_settings, make_ctx, usage


class Verdict(BaseModel):
    verdict: str


def labels(ctx):
    return [e.label for e in ctx.emitted if e.type.startswith("step_")]


async def test_retries_rate_limit_then_succeeds():
    ctx = make_ctx()
    gw = LLMGateway({"agent": FakeModel([LLMRateLimited(), "ok"])}, fallback=None, settings=fast_settings())
    assert (await gw.complete(ctx, "agent", [HumanMessage("hi")])).content == "ok"
    assert "Rate limited — retrying…" in labels(ctx)


async def test_timeout_exhausts_then_fallback():
    ctx = make_ctx()
    slow = FakeModel([TimeoutError(), TimeoutError(), TimeoutError()])
    gw = LLMGateway({"agent": slow}, fallback=FakeModel(["fb"], model_name="fake-fallback"), settings=fast_settings())
    assert (await gw.complete(ctx, "agent", [HumanMessage("hi")])).content == "fb"
    assert ctx.trace.usage[-1].model == "fake-fallback"
    assert labels(ctx).count("Switching to backup model…") == 2  # started + completed
    assert [e.type for e in ctx.emitted][-1] == "step_completed"


async def test_real_slow_call_times_out():
    class Slow(FakeModel):
        async def ainvoke(self, messages, **_):
            await asyncio.sleep(5)

    ctx = make_ctx(settings=fast_settings(llm_timeout_s=0.05, llm_max_retries=0))
    gw = LLMGateway({"agent": Slow([])}, fallback=FakeModel(["fb"]), settings=ctx.settings)
    assert (await gw.complete(ctx, "agent", [HumanMessage("hi")])).content == "fb"


async def test_outage_raises_unavailable_and_clears_flag():
    ctx = make_ctx(chaos={"llm_outage_next": True})
    gw = LLMGateway({"agent": FakeModel(["never"])}, fallback=FakeModel(["never"]), settings=fast_settings())
    with pytest.raises(LLMUnavailable):
        await gw.complete(ctx, "agent", [HumanMessage("hi")])
    assert not (await ctx.chaos.get()).get("llm_outage_next")
    assert [e.type for e in ctx.emitted][-1] == "step_failed"


async def test_no_fallback_raises_unavailable_with_cause():
    ctx = make_ctx()
    gw = LLMGateway({"agent": FakeModel([LLMRateLimited()] * 3)}, fallback=None, settings=fast_settings())
    with pytest.raises(LLMUnavailable) as ei:
        await gw.complete(ctx, "agent", [HumanMessage("hi")])
    assert ei.value.cause == "RATE_LIMITED"


async def test_chaos_timeout_flag_is_one_shot():
    ctx = make_ctx(chaos={"llm_timeout_next": True})
    gw = LLMGateway({"agent": FakeModel(["a", "b"])}, fallback=FakeModel(["fb"]), settings=fast_settings())
    assert (await gw.complete(ctx, "agent", [HumanMessage("1")])).content == "fb"
    assert (await gw.complete(ctx, "agent", [HumanMessage("2")])).content == "a"


async def test_chaos_429_only_first_attempt():
    ctx = make_ctx(chaos={"llm_429_next": True})
    gw = LLMGateway({"agent": FakeModel(["a"])}, fallback=None, settings=fast_settings())
    assert (await gw.complete(ctx, "agent", [HumanMessage("1")])).content == "a"
    assert "Rate limited — retrying…" in labels(ctx)


async def test_usage_recorded_with_cost():
    ctx = make_ctx()
    msg = AIMessage("ok", usage_metadata=usage(100, 10))
    gw = LLMGateway({"agent": FakeModel([msg], model_name="gpt-4.1-mini")}, None, fast_settings())
    await gw.complete(ctx, "agent", [HumanMessage("hi")])
    u = ctx.trace.usage[-1]
    assert (u.input_tokens, u.output_tokens, u.purpose, u.model) == (100, 10, "agent", "gpt-4.1-mini")
    assert u.cost_usd == pytest.approx((100 * 0.40 + 10 * 1.60) / 1_000_000)
    assert ctx.trace.spans[-1].kind == "llm"


async def test_structured_output_returns_parsed_model():
    ctx = make_ctx()
    gw = LLMGateway({"verify": FakeModel([Verdict(verdict="supported")])}, None, fast_settings())
    out = await gw.complete(ctx, "verify", [HumanMessage("x")], schema=Verdict)
    assert out == Verdict(verdict="supported") and ctx.trace.usage[-1].purpose == "verify"


async def test_tools_are_bound():
    ctx = make_ctx()
    model = FakeModel(["ok"])
    gw = LLMGateway({"agent": model}, None, fast_settings())
    await gw.complete(ctx, "agent", [HumanMessage("x")], tools=[{"type": "function", "function": {"name": "t"}}])
    assert model.bound_tools and model.bound_tools[0]["function"]["name"] == "t"


async def test_stream_yields_tokens_and_records_ttft():
    ctx = make_ctx()
    gw = LLMGateway({"respond": FakeModel(["Hello there friend"])}, None, fast_settings())
    out = [t async for t in gw.stream(ctx, "respond", [HumanMessage("hi")])]
    assert "".join(out) == "Hello there friend" and ctx.trace.latency.ttft_ms is not None
    assert ctx.trace.usage[-1].output_tokens == 2


async def test_stream_falls_back_before_first_token():
    ctx = make_ctx(chaos={"llm_timeout_next": True})
    gw = LLMGateway({"respond": FakeModel(["primary"])}, FakeModel(["backup answer"]), fast_settings())
    out = [t async for t in gw.stream(ctx, "respond", [HumanMessage("hi")])]
    assert "".join(out) == "backup answer"
