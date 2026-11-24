import asyncio
from uuid import uuid4

from langchain_core.messages import AIMessage

from app.llm.errors import LLMUnavailable
from tests.agent.scripted_llm import CR, ScriptedLLM
from tests.api.conftest import collect_sse, small_talk_llm, wait_messages


async def new_session(client) -> str:
    r = await client.post("/api/sessions")
    assert r.status_code == 201
    return r.json()["session_id"]


async def test_unknown_session_404(api):
    client = await api(small_talk_llm())
    assert (await client.get(f"/api/sessions/{uuid4()}")).status_code == 404
    assert (await client.post(f"/api/sessions/{uuid4()}/messages", json={"text": "hi"})).status_code == 404


async def test_new_session_view_is_empty(api):
    client = await api(small_talk_llm())
    view = (await client.get(f"/api/sessions/{await new_session(client)}")).json()
    assert view["customer"] is None and view["escalation"] is None and view["messages"] == []
    assert view["last_event_seq"] == 0


async def test_post_message_streams_turn(api):
    client = await api(small_talk_llm())
    sid = await new_session(client)
    r = await client.post(f"/api/sessions/{sid}/messages", json={"text": "hi"})
    assert r.status_code == 202
    turn = r.json()["turn_id"]
    events = await collect_sse(client, sid)
    assert events[0]["type"] == "turn_started" and events[0]["turn_id"] == turn
    types = {e["type"] for e in events}
    assert {"token", "trace", "usage", "turn_completed"} <= types
    assert events[-1]["status"] == "ok"
    msgs = await wait_messages(client, sid, 2)
    assert [(m["role"], m["content"]) for m in msgs] == [("user", "hi"), ("assistant", "Hi! How can I help?")]


async def test_concurrent_messages_run_sequentially(api):
    client = await api(small_talk_llm(2))
    sid = await new_session(client)
    await asyncio.gather(*(client.post(f"/api/sessions/{sid}/messages", json={"text": t}) for t in ("one", "two")))
    msgs = await wait_messages(client, sid, 4)
    assert [m["role"] for m in msgs] == ["user", "assistant", "user", "assistant"]


async def test_llm_outage_persists_nothing_and_emits_retryable_error(api):
    client = await api(ScriptedLLM(classify=[LLMUnavailable("LLM_TIMEOUT")]))
    sid = await new_session(client)
    await client.post(f"/api/sessions/{sid}/messages", json={"text": "hi"})
    events = await collect_sse(client, sid)
    err = next(e for e in events if e["type"] == "error")
    assert err["code"] == "LLM_UNAVAILABLE" and err["retryable"] and events[-1]["status"] == "failed"
    assert (await client.get(f"/api/sessions/{sid}")).json()["messages"] == []


async def test_message_length_validated(api):
    client = await api(small_talk_llm())
    sid = await new_session(client)
    for text in ("", "   ", "x" * 2001):
        assert (await client.post(f"/api/sessions/{sid}/messages", json={"text": text})).status_code == 422


async def test_rate_limit_21st_message(api):
    client = await api(small_talk_llm(25))
    sid = await new_session(client)
    codes = [(await client.post(f"/api/sessions/{sid}/messages", json={"text": "hi"})).status_code for _ in range(21)]
    assert codes[:20] == [202] * 20 and codes[20] == 429
    r = await client.post(f"/api/sessions/{sid}/messages", json={"text": "hi"})
    assert r.json()["detail"]["code"] == "RATE_LIMITED"


async def test_budget_exceeded_blocks_turn(api, pool):
    from app.store.spend import add_spend

    client = await api(small_talk_llm(), daily_budget_usd=0.01)
    async with pool.connection() as c:
        await add_spend(c, 0.02)
    sid = await new_session(client)
    await client.post(f"/api/sessions/{sid}/messages", json={"text": "hi"})
    events = await collect_sse(client, sid)
    assert any(e["type"] == "error" and e["code"] == "BUDGET_EXCEEDED" for e in events)


async def test_traces_tickets_and_chaos_endpoints(api):
    llm = ScriptedLLM(classify=[CR("out_of_scope")], agent=[AIMessage("")])
    client = await api(llm, rag_t_low=0.99)
    sid = await new_session(client)
    await client.post(f"/api/sessions/{sid}/messages", json={"text": "do you sell routers?"})
    await collect_sse(client, sid)
    traces = (await client.get(f"/api/sessions/{sid}/traces")).json()
    assert traces[0]["status"] == "escalated" and traces[0]["spans"] and traces[0]["latency"]["total_ms"] >= 0
    tickets = (await client.get(f"/api/sessions/{sid}/tickets")).json()
    assert tickets[0]["id"].startswith("T-") and tickets[0]["reason"] == "low_confidence"
    view = (await client.get(f"/api/sessions/{sid}")).json()
    assert view["escalation"]["ticket_id"] == tickets[0]["id"]
    r = await client.put(f"/api/sessions/{sid}/chaos", json={"llm_timeout_next": True, "tool_slow": "search_policies"})
    assert r.status_code == 200 and r.json()["llm_timeout_next"] is True


async def test_metrics_endpoint_records_voice_latency(api, pool):
    from app.store.traces import save_trace

    client = await api(small_talk_llm())
    sid = await new_session(client)
    async with pool.connection() as c:
        await save_trace(c, "turn_v1", sid, "voice", "ok", [], [], {"total_ms": 900})
    r = await client.post(f"/api/sessions/{sid}/metrics", json={"kind": "voice_e2e_ms", "value": 1234})
    assert r.status_code == 204
    traces = (await client.get(f"/api/sessions/{sid}/traces")).json()
    assert traces[0]["latency"]["voice_e2e_ms"] == 1234


async def test_openapi_exposes_event_union(api):
    client = await api(small_talk_llm())
    schema = (await client.get("/openapi.json")).json()
    assert {"TokenEvent", "StepEvent", "ErrorEvent", "TurnCompletedEvent"} <= set(schema["components"]["schemas"])


async def test_session_view_reports_chaos_flags(api):
    client = await api(small_talk_llm())
    sid = await new_session(client)
    assert (await client.get(f"/api/sessions/{sid}")).json()["chaos"]["tool_fail_next"] is None
    await client.put(f"/api/sessions/{sid}/chaos", json={"tool_fail_next": "issue_refund"})
    assert (await client.get(f"/api/sessions/{sid}")).json()["chaos"]["tool_fail_next"] == "issue_refund"


async def test_voice_turn_persists_nothing_itself(pool):
    from app.agent.graph import AgentDeps, build_graph
    from app.agent.runner import TurnRunner
    from app.bus import SessionBus
    from app.rag.embedder import HashEmbedder
    from app.store.sessions import create_session, recent_messages
    from app.tools.registry import build_registry
    from app.tools.runner import ToolRunner
    from tests.fakes import fast_settings

    llm = small_talk_llm(answer="Hello from voice")
    deps = AgentDeps(llm=llm, runner=ToolRunner(build_registry()), embedder=HashEmbedder())
    runner = TurnRunner(pool, SessionBus(), build_graph(deps), deps, fast_settings())
    async with pool.connection() as c:
        sid = (await create_session(c)).id
    result = await runner.run_turn(sid, "hi", "voice", turn_id="v_x", persist_user=False, persist_answer=False)
    assert result.answer == "Hello from voice" and result.status == "ok"
    async with pool.connection() as c:
        assert await recent_messages(c, sid, 10) == []
