"""The agent graph (spec §6.2):

load_context -> classify -> agent <-> tools -> guardrail -> respond -> verify_answer -> END
                   |          |  \\-> force_retrieval -/        \\-> escalate      \\-> escalate
                   |          \\-> escalate (loop limit)
                   \\-> respond (small talk)
"""

from typing import Any

from langchain_core.runnables import RunnableConfig
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph

from app.agent.nodes import (
    AgentDeps,
    AgentNodes,
    route_after_agent,
    route_after_classify,
    route_after_guardrail_node,
    route_after_verify,
)
from app.agent.state import AgentState
from app.context import TurnContext
from app.tools.base import ToolEnv

__all__ = ["AgentDeps", "build_graph", "run_agent"]


def _add(g: StateGraph, name: str, node: Any) -> None:
    """Register an async (state, config) node. LangGraph's node protocols don't type bound methods well."""
    g.add_node(name, node)


def build_graph(deps: AgentDeps) -> CompiledStateGraph:
    nodes = AgentNodes(deps)
    g = StateGraph(AgentState)
    _add(g, "load_context", nodes.load_context)
    _add(g, "classify", nodes.classify)
    _add(g, "agent", nodes.agent)
    _add(g, "tools", nodes.tools)
    _add(g, "force_retrieval", nodes.force_retrieval)
    _add(g, "guardrail", nodes.guardrail)
    _add(g, "respond", nodes.respond)
    _add(g, "verify_answer", nodes.verify_answer)
    _add(g, "escalate", nodes.escalate)

    g.add_edge(START, "load_context")
    g.add_edge("load_context", "classify")
    g.add_conditional_edges("classify", route_after_classify, {"respond": "respond", "agent": "agent"})
    g.add_conditional_edges(
        "agent",
        route_after_agent,
        {"escalate": "escalate", "tools": "tools", "force_retrieval": "force_retrieval", "guardrail": "guardrail"},
    )
    g.add_edge("tools", "agent")
    g.add_edge("force_retrieval", "guardrail")
    g.add_conditional_edges("guardrail", route_after_guardrail_node, {"escalate": "escalate", "respond": "respond"})
    g.add_edge("respond", "verify_answer")
    g.add_conditional_edges("verify_answer", route_after_verify, {"escalate": "escalate", END: END})
    g.add_edge("escalate", END)
    return g.compile()


async def run_agent(
    graph: CompiledStateGraph, deps: AgentDeps, ctx: TurnContext, env: ToolEnv, user_text: str
) -> dict[str, Any]:
    """Run one turn; returns the final state (answer, status, intent, retrieval, escalation, ...)."""
    initial: dict[str, Any] = {"session_id": str(ctx.session_id), "channel": ctx.channel, "user_text": user_text}
    config: RunnableConfig = {"configurable": {"ctx": ctx, "env": env}, "recursion_limit": 60}
    result: dict[str, Any] = await graph.ainvoke(initial, config=config)
    return dict(result)
