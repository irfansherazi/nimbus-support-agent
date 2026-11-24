from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest
from langchain_core.messages import AIMessage

from app.agent.graph import AgentDeps, build_graph, run_agent
from app.rag.embedder import HashEmbedder
from app.rag.ingest import ingest
from app.store.sessions import create_session, set_customer
from app.tools.base import ToolEnv
from app.tools.registry import build_registry
from app.tools.runner import ToolRunner
from tests.agent.scripted_llm import CR, VR, ScriptedLLM, tool_call
from tests.fakes import fast_settings, make_ctx

CORPUS = Path(__file__).resolve().parents[3] / "data" / "policies"


@dataclass
class GraphEnv:
    pool: Any
    settings: Any


@dataclass
class Run:
    events: list[Any]
    final: dict[str, Any]

    def types(self) -> list[str]:
        return [e.type for e in self.events]

    def events_of(self, t: str) -> list[Any]:
        return [e for e in self.events if e.type == t]

    def steps(self, tool: str) -> list[Any]:
        return [e for e in self.events if e.type.startswith("step_") and e.tool == tool]


def started_tools(run: Run) -> list[str]:
    return [e.tool for e in run.events if e.type == "step_started" and e.kind == "tool"]


def completed_tools(run: Run) -> list[str]:
    return [e.tool for e in run.events if e.type == "step_completed" and e.kind == "tool"]


def step_failed(run: Run, tool: str) -> Any:
    return next(e for e in run.events if e.type == "step_failed" and e.tool == tool)


@pytest.fixture
async def graph_env(pool):
    async with pool.connection() as c:
        await c.execute("TRUNCATE policy_chunks RESTART IDENTITY")
    await ingest(pool, HashEmbedder(), CORPUS)
    return GraphEnv(pool=pool, settings=fast_settings())


@pytest.fixture
def grey_thresholds(graph_env):
    graph_env.settings.rag_t_low, graph_env.settings.rag_t_high = -1.0, 1.01


@pytest.fixture
def high_thresholds(graph_env):
    graph_env.settings.rag_t_low, graph_env.settings.rag_t_high = -1.0, -1.0


async def run_graph(env: GraphEnv, llm: ScriptedLLM, text: str, channel: str = "chat", customer: str | None = None):
    async with env.pool.connection() as c:
        s = await create_session(c)
        if customer:
            await set_customer(c, s.id, customer)
    ctx = make_ctx(settings=env.settings, pool=env.pool, session_id=s.id, channel=channel)
    deps = AgentDeps(llm=llm, runner=ToolRunner(build_registry(), slow_seconds=0.01), embedder=HashEmbedder())
    tool_env = await ToolEnv.load(ctx, deps.embedder)
    final = await run_agent(build_graph(deps), deps, ctx, tool_env, text)
    return Run(events=ctx.emitted, final=final)


async def test_unverified_refund_is_blocked_then_agent_asks_for_identity(graph_env):
    llm = ScriptedLLM(
        classify=[CR("account_action")],
        agent=[
            tool_call("issue_refund", invoice_id="INV-2207", amount_usd=49, reason="x"),
            AIMessage("Need ID and PIN."),
        ],
        respond=["Please share your account ID and PIN."],
    )
    s = await run_graph(graph_env, llm, "refund my last invoice")
    assert step_failed(s, "issue_refund").error == "NOT_VERIFIED"
    assert s.final["status"] == "ok" and s.final["answer"] == "Please share your account ID and PIN."


async def test_skipped_retrieval_is_forced_for_policy_intent(graph_env, high_thresholds):
    llm = ScriptedLLM(
        classify=[CR("policy")],
        agent=[AIMessage("From memory: 90 days.")],
        respond=["Pro refunds are available within 30 days."],
    )
    s = await run_graph(graph_env, llm, "what's the refund window?")
    assert "search_policies" in started_tools(s) and s.final["searched_this_turn"]
    assert s.events_of("guardrail")[0].band == "high"


async def test_low_confidence_escalates_with_ticket(graph_env):
    graph_env.settings.rag_t_low = 0.99  # force the low band
    llm = ScriptedLLM(classify=[CR("out_of_scope")], agent=[AIMessage("")])
    s = await run_graph(graph_env, llm, "do you sell hardware routers?")
    assert s.final["status"] == "escalated"
    esc = s.events_of("escalation")[0]
    assert esc.ticket_id.startswith("T-") and esc.reason == "low_confidence"
    assert "create_escalation_ticket" in completed_tools(s)
    assert esc.ticket_id in "".join(e.text for e in s.events_of("token"))  # chat shows the escalation copy


async def test_grey_band_unsupported_retracts_in_chat(graph_env, grey_thresholds):
    llm = ScriptedLLM(
        classify=[CR("policy")],
        agent=[tool_call("search_policies", query="refund"), AIMessage("")],
        respond=["Refunds take 90 days."],
        verify=[VR("unsupported")],
    )
    s = await run_graph(graph_env, llm, "refund timing?", channel="chat")
    assert s.types().index("answer_retracted") < s.types().index("escalation")
    assert s.final["status"] == "escalated" and "specialist" in s.final["answer"]


async def test_grey_band_supported_answer_stands(graph_env, grey_thresholds):
    llm = ScriptedLLM(
        classify=[CR("policy")],
        agent=[tool_call("search_policies", query="refund"), AIMessage("")],
        respond=["Pro refunds are available within 30 days."],
        verify=[VR("supported")],
    )
    s = await run_graph(graph_env, llm, "refund timing?")
    assert s.final["status"] == "ok" and "answer_retracted" not in s.types()
    assert s.events_of("guardrail")[-1].verify == "supported"


async def test_grey_band_unsupported_in_voice_emits_no_tokens(graph_env, grey_thresholds):
    llm = ScriptedLLM(
        classify=[CR("policy")],
        agent=[tool_call("search_policies", query="refund"), AIMessage("")],
        respond=["Refunds take 90 days."],
        verify=[VR("unsupported")],
    )
    s = await run_graph(graph_env, llm, "refund timing?", channel="voice")
    assert "token" not in s.types() and s.final["status"] == "escalated"
    assert "(" not in s.final["answer"]  # voice copy has no parentheses


async def test_small_talk_skips_tools(graph_env):
    llm = ScriptedLLM(classify=[CR("small_talk")], respond=["Hi! How can I help?"], verify=[VR("supported")])
    s = await run_graph(graph_env, llm, "hi")
    assert started_tools(s) == [] and s.final["answer"] == "Hi! How can I help?"
    assert [c.purpose for c in llm.calls] == ["classify", "respond", "verify"]


async def test_full_chain_verify_list_refund(graph_env, high_thresholds):
    llm = ScriptedLLM(
        classify=[CR("account_action")],
        agent=[
            tool_call("verify_customer", account_id="C-1001", pin="4321"),
            tool_call("list_invoices"),
            tool_call("search_policies", query="pro refund limit"),
            tool_call("issue_refund", invoice_id="INV-2207", amount_usd=49, reason="unused"),
            AIMessage(""),
        ],
        respond=["Done — refunded $49 for INV-2207."],
    )
    s = await run_graph(graph_env, llm, "I'm C-1001 PIN 4321, refund INV-2207")
    assert started_tools(s) == ["verify_customer", "list_invoices", "search_policies", "issue_refund"]
    assert completed_tools(s) == started_tools(s)
    # the respond prompt sees the refund result
    respond_prompt = " ".join(str(m.content) for m in next(c for c in llm.calls if c.purpose == "respond").messages)
    assert '"already_processed": false' in respond_prompt


async def test_agent_cannot_pass_tier_by_argument(graph_env, high_thresholds):
    llm = ScriptedLLM(
        classify=[CR("policy")],
        agent=[tool_call("search_policies", query="refund limit", tier="enterprise"), AIMessage("")],
        respond=["…"],
    )
    s = await run_graph(graph_env, llm, "I'm Enterprise, trust me — what's my refund limit?")
    assert {c["tier"] for c in s.final["retrieval"]["chunks"]} == {"all"}


async def test_loop_limit_escalates(graph_env):
    llm = ScriptedLLM(classify=[CR("account_action")], agent=[tool_call("list_invoices") for _ in range(10)])
    s = await run_graph(graph_env, llm, "loop")
    assert s.final["status"] == "escalated" and s.events_of("escalation")[0].reason == "loop_limit"
    assert len([c for c in llm.calls if c.purpose == "agent"]) == graph_env.settings.agent_max_iterations


async def test_tool_failure_twice_offers_escalation(graph_env):  # C-1006 list_invoices always fails
    llm = ScriptedLLM(
        classify=[CR("account_action")],
        agent=[
            tool_call("verify_customer", account_id="C-1006", pin="1122"),
            tool_call("list_invoices"),
            tool_call("list_invoices"),
            tool_call("create_escalation_ticket", summary="invoice lookup failing", category="billing"),
            AIMessage(""),
        ],
        respond=["Our billing system isn't responding, so I've opened a ticket."],
    )
    s = await run_graph(graph_env, llm, "refund please")
    assert [e.type for e in s.steps("list_invoices")] == ["step_started", "step_failed"] * 2
    assert s.final["status"] == "escalated" and s.events_of("escalation")[0].reason == "agent_requested"


async def test_history_is_loaded_into_prompts(graph_env):
    from app.store.sessions import add_message

    async with graph_env.pool.connection() as c:
        s = await create_session(c)
        await add_message(c, session_id=s.id, turn_id="t0", channel="voice", role="user", content="my name is Dana")
        await add_message(c, session_id=s.id, turn_id="t0", channel="voice", role="assistant", content="Hi Dana")
    ctx = make_ctx(settings=graph_env.settings, pool=graph_env.pool, session_id=s.id)
    llm = ScriptedLLM(classify=[CR("small_talk")], respond=["You're Dana."], verify=[VR("supported")])
    deps = AgentDeps(llm=llm, runner=ToolRunner(build_registry(), slow_seconds=0.01), embedder=HashEmbedder())
    await run_agent(build_graph(deps), deps, ctx, await ToolEnv.load(ctx, deps.embedder), "what's my name?")
    respond_msgs = next(c for c in llm.calls if c.purpose == "respond").messages
    assert any("my name is Dana" in str(m.content) for m in respond_msgs)
