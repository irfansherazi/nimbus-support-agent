"""Graph nodes. Each node reads live objects (TurnContext, ToolEnv) from the run config and returns a state update.

Routing rules that matter for safety (forced retrieval, confidence bands, verification, loop limit) are decided
here in code, from pure functions in app.agent.guardrails, never left to the model.
"""

import json
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable, Sequence
from dataclasses import dataclass
from functools import wraps
from typing import Any, Literal, Protocol

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_core.runnables import RunnableConfig

from app.agent import prompts
from app.agent.guardrails import (
    ClassifyResult,
    VerifyResult,
    band_for,
    needs_forced_retrieval,
    needs_verification,
    route_after_guardrail,
)
from app.agent.state import AgentState
from app.context import TurnContext
from app.events import AnswerRetractedEvent, Band, EscalationEvent, GuardrailEvent, TokenEvent
from app.llm.gateway import text_of
from app.rag.embedder import Embedder
from app.store.sessions import recent_messages
from app.tools.base import ToolEnv
from app.tools.registry import tool_schemas
from app.tools.runner import ToolRunner

HISTORY_FOR_CLASSIFY = 6
TICKET_CATEGORY = {"policy": "policy", "mixed": "policy", "account_action": "account"}
REASON_TEXT = {
    "low_confidence": "No confident answer in the knowledge base",
    "unsupported_answer": "Drafted answer failed the grounding check",
    "loop_limit": "Agent hit its step limit",
    "agent_requested": "Agent requested a specialist",
}


class AgentLLM(Protocol):
    async def complete(
        self,
        ctx: TurnContext,
        purpose: Any,
        messages: list[BaseMessage],
        *,
        tools: Sequence[Any] | None = None,
        schema: Any = None,
    ) -> Any: ...

    def stream(self, ctx: TurnContext, purpose: Any, messages: list[BaseMessage]) -> AsyncIterator[str]: ...


@dataclass
class AgentDeps:
    llm: AgentLLM
    runner: ToolRunner
    embedder: Embedder


def _ctx(config: RunnableConfig) -> TurnContext:
    return config["configurable"]["ctx"]  # type: ignore[no-any-return]


def _env(config: RunnableConfig) -> ToolEnv:
    return config["configurable"]["env"]  # type: ignore[no-any-return]


NodeFn = Callable[[Any, AgentState, RunnableConfig], Awaitable[dict[str, Any]]]


def traced(name: str) -> Callable[[NodeFn], NodeFn]:
    """Wrap a node in a trace span so the drawer shows the graph path and node timings."""

    def deco(fn: NodeFn) -> NodeFn:
        @wraps(fn)
        async def wrapper(self: Any, state: AgentState, config: RunnableConfig) -> dict[str, Any]:
            async with _ctx(config).trace.span(name, "node"):
                return await fn(self, state, config)

        return wrapper

    return deco


def _current_turn(messages: list[BaseMessage]) -> tuple[list[BaseMessage], list[BaseMessage]]:
    """Split into (history before this turn's user message, messages from this turn after it)."""
    idx = max(i for i, m in enumerate(messages) if isinstance(m, HumanMessage))
    return messages[:idx], messages[idx + 1 :]


def _plain(messages: list[BaseMessage]) -> list[BaseMessage]:
    """Customer-visible conversation only: no tool calls or tool results."""
    return [
        m
        for m in messages
        if isinstance(m, HumanMessage) or (isinstance(m, AIMessage) and not m.tool_calls and text_of(m.content))
    ]


def _band(state: AgentState) -> Band:
    retrieval = state.get("retrieval")
    return retrieval.get("band", "skipped") if retrieval else "skipped"  # type: ignore[no-any-return]


def _sources_block(state: AgentState) -> str:
    retrieval = state.get("retrieval")
    if not retrieval or _band(state) not in ("high", "grey"):
        return "SOURCES: (none)"
    lines = ["SOURCES:"]
    for i, c in enumerate(retrieval["chunks"], 1):
        lines.append(f"[{i}] {c['section_path']}\n{c['content']}")
    return "\n\n".join(lines)


def _tool_results_block(state: AgentState) -> str:
    _, this_turn = _current_turn(state["messages"])
    results = [f"- {m.name}: {m.content}" for m in this_turn if isinstance(m, ToolMessage)]
    return "TOOL RESULTS:\n" + ("\n".join(results) if results else "(none)")


def _customer_line(env: ToolEnv) -> str:
    c = env.customer
    if c is None:
        return "Customer: NOT verified."
    return f"Customer: verified — {c.name} ({c.id}), {c.tier} plan, contract {c.contract_status}."


def _escalation_line(env: ToolEnv) -> str:
    esc = env.session.escalation
    return f"Open ticket: {esc.ticket_id} ({esc.reason})." if esc else "Open ticket: none."


class AgentNodes:
    def __init__(self, deps: AgentDeps) -> None:
        self.deps = deps
        self.tool_schemas = tool_schemas(deps.runner.registry)

    # ---------------------------------------------------------------- context

    @traced("load_context")
    async def load_context(self, state: AgentState, config: RunnableConfig) -> dict[str, Any]:
        ctx, env = _ctx(config), _env(config)
        assert ctx.pool is not None
        async with ctx.pool.connection() as conn:
            history = await recent_messages(conn, ctx.session_id, ctx.settings.voice_history_turns)
        msgs: list[BaseMessage] = [
            HumanMessage(m.content) if m.role == "user" else AIMessage(m.content) for m in history
        ]
        # Voice stores the user's transcript before the turn runs; don't count it twice.
        if (
            msgs
            and isinstance(msgs[-1], HumanMessage)
            and text_of(msgs[-1].content).strip() == state["user_text"].strip()
        ):
            msgs.pop()
        env.recent_turns = [{"role": m.role, "content": m.content} for m in history[-6:]]
        env.customer_said = [m.content for m in history if m.role == "user"] + [state["user_text"]]
        env.last_assistant = next((m.content for m in reversed(history) if m.role == "assistant"), "")
        return {
            "messages": [*msgs, HumanMessage(state["user_text"])],
            "iterations": 0,
            "searched_this_turn": False,
            "retrieval": None,
            "escalate_reason": None,
            "escalation": None,
            "status": "ok",
        }

    @traced("classify")
    async def classify(self, state: AgentState, config: RunnableConfig) -> dict[str, Any]:
        ctx = _ctx(config)
        recent = _plain(state["messages"])[-(HISTORY_FOR_CLASSIFY + 1) :]
        result: ClassifyResult = await self.deps.llm.complete(
            ctx, "classify", [SystemMessage(prompts.CLASSIFY_SYSTEM), *recent], schema=ClassifyResult
        )
        ctx.trace.add_span("intent", "guardrail", intent=result.intent, rationale=result.rationale)
        return {"intent": result.intent}

    # ---------------------------------------------------------------- reasoning loop

    @traced("agent")
    async def agent(self, state: AgentState, config: RunnableConfig) -> dict[str, Any]:
        ctx, env = _ctx(config), _env(config)
        if state.get("iterations", 0) >= ctx.settings.agent_max_iterations:
            return {"escalate_reason": "loop_limit"}
        status = f"{_customer_line(env)}\n{_escalation_line(env)}\nIntent: {state.get('intent')}."
        system = SystemMessage(prompts.AGENT_SYSTEM.format(state=status))
        ai = await self.deps.llm.complete(ctx, "agent", [system, *state["messages"]], tools=self.tool_schemas)
        return {"messages": [ai], "iterations": state.get("iterations", 0) + 1}

    @traced("tools")
    async def tools(self, state: AgentState, config: RunnableConfig) -> dict[str, Any]:
        ctx, env = _ctx(config), _env(config)
        last = state["messages"][-1]
        assert isinstance(last, AIMessage)
        update: dict[str, Any] = {}
        out: list[BaseMessage] = []
        for call in last.tool_calls:
            call_id = call.get("id") or f"call-{uuid.uuid4().hex[:8]}"
            outcome = await self.deps.runner.run(env, call["name"], call["args"], call_id)
            out.append(
                ToolMessage(json.dumps(outcome.for_model(), default=str), tool_call_id=call_id, name=call["name"])
            )
            if call["name"] == "search_policies":
                update["searched_this_turn"] = True
                if outcome.ok:
                    update["retrieval"] = dict(outcome.data or {})
            if call["name"] == "create_escalation_ticket" and outcome.ok and outcome.data:
                ticket_id = outcome.data["ticket_id"]
                ctx.emit(EscalationEvent(turn_id=ctx.turn_id, ticket_id=ticket_id, reason=env.escalation_reason))
                update["escalation"] = {"ticket_id": ticket_id, "reason": env.escalation_reason}
                update["status"] = "escalated"
        return {"messages": out, **update}

    @traced("force_retrieval")
    async def force_retrieval(self, state: AgentState, config: RunnableConfig) -> dict[str, Any]:
        """The model answered a policy question without searching; code searches on its behalf."""
        env = _env(config)
        outcome = await self.deps.runner.run(
            env, "search_policies", {"query": state["user_text"]}, f"forced-{uuid.uuid4().hex[:8]}"
        )
        return {"searched_this_turn": True, "retrieval": dict(outcome.data or {}) if outcome.ok else None}

    # ---------------------------------------------------------------- guardrails

    @traced("guardrail")
    async def guardrail(self, state: AgentState, config: RunnableConfig) -> dict[str, Any]:
        ctx = _ctx(config)
        found = state.get("retrieval")
        retrieval = dict(found) if found else None
        top = retrieval.get("top_score") if retrieval else None
        band: Band = (
            band_for(top, ctx.settings.rag_t_low, ctx.settings.rag_t_high)
            if state.get("searched_this_turn")
            else "skipped"
        )
        if retrieval is not None:
            retrieval["band"] = band
        ctx.emit(GuardrailEvent(turn_id=ctx.turn_id, band=band, top_score=top))
        ctx.trace.add_span(
            "confidence",
            "guardrail",
            band=band,
            top_score=top,
            t_low=ctx.settings.rag_t_low,
            t_high=ctx.settings.rag_t_high,
        )
        route = route_after_guardrail(band, state.get("intent") or "policy")
        return {"retrieval": retrieval, "escalate_reason": "low_confidence" if route == "escalate" else None}

    @traced("respond")
    async def respond(self, state: AgentState, config: RunnableConfig) -> dict[str, Any]:
        ctx, env = _ctx(config), _env(config)
        history, _ = _current_turn(state["messages"])
        style = prompts.STYLE_VOICE if ctx.channel == "voice" else prompts.STYLE_CHAT
        context = f"{_customer_line(env)}\n\n{_sources_block(state)}\n\n{_tool_results_block(state)}"
        messages = [
            SystemMessage(prompts.RESPOND_SYSTEM.format(style=style, context=context)),
            *_plain(history),
            HumanMessage(state["user_text"]),
        ]
        if ctx.channel == "chat":
            parts: list[str] = []
            async for delta in self.deps.llm.stream(ctx, "respond", messages):
                if delta:
                    parts.append(delta)
                    ctx.emit(TokenEvent(turn_id=ctx.turn_id, text=delta))
            answer = "".join(parts)
        else:
            answer = text_of((await self.deps.llm.complete(ctx, "respond", messages)).content)
        return {"answer": answer.strip()}

    @traced("verify_answer")
    async def verify_answer(self, state: AgentState, config: RunnableConfig) -> dict[str, Any]:
        ctx = _ctx(config)
        band = _band(state)
        if not needs_verification(state.get("intent") or "policy", band):
            return {}
        check = (
            f"{_sources_block(state)}\n\n{_tool_results_block(state)}\n\nREPLY TO CHECK:\n{state.get('answer') or ''}"
        )
        result: VerifyResult = await self.deps.llm.complete(
            ctx, "verify", [SystemMessage(prompts.VERIFY_SYSTEM), HumanMessage(check)], schema=VerifyResult
        )
        retrieval = state.get("retrieval")
        ctx.emit(
            GuardrailEvent(
                turn_id=ctx.turn_id,
                band=band,
                top_score=retrieval.get("top_score") if retrieval else None,
                verify=result.verdict,
            )
        )
        ctx.trace.add_span("verify_answer", "guardrail", verdict=result.verdict, reason=result.reason)
        if result.verdict == "supported":
            return {"verify": result.model_dump()}
        if ctx.channel == "chat":
            ctx.emit(AnswerRetractedEvent(turn_id=ctx.turn_id, reason=result.reason))
        return {"verify": result.model_dump(), "escalate_reason": "unsupported_answer"}

    @traced("escalate")
    async def escalate(self, state: AgentState, config: RunnableConfig) -> dict[str, Any]:
        ctx, env = _ctx(config), _env(config)
        reason = state.get("escalate_reason") or "agent_requested"
        env.escalation_reason = reason
        intent = state.get("intent") or "other"
        args = {
            "summary": f'{REASON_TEXT.get(reason, reason)}. Customer asked: "{state["user_text"][:300]}"',
            "category": TICKET_CATEGORY.get(intent, "other"),
            "priority": "normal",
        }
        outcome = await self.deps.runner.run(env, "create_escalation_ticket", args, f"esc-{uuid.uuid4().hex[:8]}")
        if outcome.ok and outcome.data:
            ticket_id = outcome.data["ticket_id"]
            ctx.emit(EscalationEvent(turn_id=ctx.turn_id, ticket_id=ticket_id, reason=reason))
            copy = prompts.ESCALATION_COPY_VOICE if ctx.channel == "voice" else prompts.ESCALATION_COPY_CHAT
            answer = copy.format(ticket_id=ticket_id)
            update: dict[str, Any] = {"status": "escalated", "escalation": {"ticket_id": ticket_id, "reason": reason}}
        else:
            answer = prompts.ESCALATION_FAILED_COPY
            update = {"status": "ok"}
        if ctx.channel == "chat":
            ctx.emit(TokenEvent(turn_id=ctx.turn_id, text=answer))
        return {"answer": answer, **update}


# ------------------------------------------------------------------- routing (pure)


def route_after_classify(state: AgentState) -> Literal["respond", "agent"]:
    return "respond" if state.get("intent") == "small_talk" else "agent"


def route_after_agent(state: AgentState) -> Literal["escalate", "tools", "force_retrieval", "guardrail"]:
    if state.get("escalate_reason"):
        return "escalate"
    last = state["messages"][-1]
    if isinstance(last, AIMessage) and last.tool_calls:
        return "tools"
    if needs_forced_retrieval(state.get("intent") or "policy", bool(state.get("searched_this_turn"))):
        return "force_retrieval"
    return "guardrail"


def route_after_guardrail_node(state: AgentState) -> Literal["escalate", "respond"]:
    return "escalate" if state.get("escalate_reason") else "respond"


def route_after_verify(state: AgentState) -> Literal["escalate", "__end__"]:
    return "escalate" if state.get("escalate_reason") else "__end__"
