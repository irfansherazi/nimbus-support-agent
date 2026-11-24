import asyncio

from app.observability.trace import LLMUsage, TraceRecorder


async def test_trace_span_nesting_and_duration():
    tr = TraceRecorder()
    async with tr.span("agent", "node"):
        async with tr.span("verify_customer", "tool") as attrs:
            attrs["ok"] = True
            await asyncio.sleep(0.01)
    by_name = {s.name: s for s in tr.spans}
    outer, inner = by_name["agent"], by_name["verify_customer"]
    assert inner.parent_id == outer.span_id and inner.duration_ms >= 10
    assert inner.attrs == {"ok": True} and outer.parent_id is None


async def test_span_records_error_and_reraises():
    tr = TraceRecorder()
    try:
        async with tr.span("boom", "tool"):
            raise ValueError("x")
    except ValueError:
        pass
    assert tr.spans[0].attrs["error"] == "ValueError: x"


def test_record_llm_adds_usage_and_span():
    tr = TraceRecorder()
    u = LLMUsage(model="m", purpose="agent", input_tokens=10, output_tokens=2, cost_usd=0.01, latency_ms=50)
    tr.record_llm(u, prompt=[{"role": "user", "content": "hi"}], output="hello")
    assert tr.usage == [u] and tr.spans[0].kind == "llm" and tr.spans[0].attrs["output"] == "hello"
    assert tr.total_cost_usd() == 0.01
