"""Runs one conversational turn end to end, for chat and voice alike.

One turn at a time per session (a per-session lock queues the next one), so messages never interleave. On a
provider outage nothing is persisted and a retryable error goes to the UI, so "Retry" simply re-sends the turn.
"""

import asyncio
import logging
import uuid
from collections import defaultdict
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from langgraph.graph.state import CompiledStateGraph

from app.agent.graph import AgentDeps, run_agent
from app.budget import BudgetGuard
from app.bus import SessionBus
from app.chaos import PgChaosStore
from app.config import Settings
from app.context import TurnContext
from app.db import Pool
from app.events import (
    AgentEvent,
    ErrorCode,
    ErrorEvent,
    TraceEvent,
    TurnCompletedEvent,
    TurnStartedEvent,
    UsageEvent,
)
from app.llm.errors import LLMError
from app.models import Channel, Escalation
from app.observability.trace import Latency, LLMUsage, Span, TraceRecorder
from app.store.sessions import add_message
from app.store.traces import get_trace, save_trace, session_cost_usd
from app.tools.base import ToolEnv

log = logging.getLogger(__name__)

UNAVAILABLE_MESSAGE = "The assistant is temporarily unavailable. Your message wasn't lost — press Retry."
BUDGET_MESSAGE = "The demo has reached today's usage limit. Please try again tomorrow."
INTERNAL_MESSAGE = "Something went wrong on our side. Your message wasn't lost — press Retry."


@dataclass(frozen=True)
class TurnResult:
    turn_id: str
    status: str
    answer: str | None
    escalation: Escalation | None


class TurnRunner:
    def __init__(
        self,
        pool: Pool,
        bus: SessionBus,
        graph: CompiledStateGraph,
        deps: AgentDeps,
        settings: Settings,
        budget: BudgetGuard | None = None,
    ) -> None:
        self.pool = pool
        self.bus = bus
        self.graph = graph
        self.deps = deps
        self.settings = settings
        self.budget = budget
        self._locks: dict[UUID, asyncio.Lock] = defaultdict(asyncio.Lock)
        self._tasks: set[asyncio.Task[Any]] = set()

    @staticmethod
    def new_turn_id() -> str:
        return f"turn_{uuid.uuid4().hex[:12]}"

    def start_turn(self, session_id: UUID, text: str, channel: Channel) -> str:
        """Schedule a turn in the background and return its id (the chat endpoint answers 202 immediately)."""
        turn_id = self.new_turn_id()
        task = asyncio.create_task(self.run_turn(session_id, text, channel, turn_id=turn_id))
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)
        return turn_id

    async def shutdown(self) -> None:
        for task in list(self._tasks):
            task.cancel()
        await asyncio.gather(*self._tasks, return_exceptions=True)

    async def run_turn(
        self,
        session_id: UUID,
        text: str,
        channel: Channel,
        *,
        turn_id: str | None = None,
        persist_user: bool = True,
        persist_answer: bool = True,
    ) -> TurnResult:
        """Voice passes persist_user=False and persist_answer=False: the bridge stores what was actually said and
        heard (transcripts), not the agent's written answer."""
        turn_id = turn_id or self.new_turn_id()

        def emit(event: AgentEvent) -> None:
            self.bus.publish(session_id, event)

        async with self._locks[session_id]:
            if self.budget is not None and await self.budget.exceeded():
                emit(TurnStartedEvent(turn_id=turn_id, channel=channel))
                return self._fail(emit, turn_id, "BUDGET_EXCEEDED", BUDGET_MESSAGE, retryable=False)

            emit(TurnStartedEvent(turn_id=turn_id, channel=channel))
            trace = TraceRecorder()
            ctx = TurnContext(
                session_id=session_id,
                turn_id=turn_id,
                channel=channel,
                emit=emit,
                trace=trace,
                pool=self.pool,
                settings=self.settings,
                chaos=PgChaosStore(self.pool, session_id),
            )
            try:
                env = await ToolEnv.load(ctx, self.deps.embedder)
                final = await run_agent(self.graph, self.deps, ctx, env, text)
            except LLMError:
                log.warning("turn %s failed: LLM unavailable", turn_id)
                await self._finish(ctx, "failed")
                return self._fail(emit, turn_id, "LLM_UNAVAILABLE", UNAVAILABLE_MESSAGE, retryable=True)
            except Exception:
                log.exception("turn %s crashed", turn_id)
                await self._finish(ctx, "failed")
                return self._fail(emit, turn_id, "INTERNAL", INTERNAL_MESSAGE, retryable=True)

            answer = final.get("answer") or ""
            status = final.get("status", "ok")
            async with self.pool.connection() as conn, conn.transaction():
                if persist_user:
                    await add_message(
                        conn, session_id=session_id, turn_id=turn_id, channel=channel, role="user", content=text
                    )
                if answer and persist_answer:
                    await add_message(
                        conn, session_id=session_id, turn_id=turn_id, channel=channel, role="assistant", content=answer
                    )
            await self._finish(ctx, status)
            emit(TurnCompletedEvent(turn_id=turn_id, status=status))
            esc = final.get("escalation")
            return TurnResult(turn_id, status, answer, Escalation(**esc) if esc else None)

    async def _finish(self, ctx: TurnContext, status: str) -> None:
        """Save the trace and publish trace + usage events (also for failed turns: the drawer shows them)."""
        trace = ctx.trace
        trace.latency.total_ms = trace.elapsed_ms()
        async with self.pool.connection() as conn:
            await save_trace(
                conn,
                ctx.turn_id,
                ctx.session_id,
                ctx.channel,
                status,
                [s.model_dump() for s in trace.spans],
                [u.model_dump() for u in trace.usage],
                trace.latency.model_dump(exclude_none=True),
            )
        await self.publish_trace(ctx.session_id, ctx.turn_id)

    async def publish_trace(self, session_id: UUID, turn_id: str) -> None:
        """Publish the turn's stored (merged) trace and usage, so the drawer sees agent and voice parts together."""
        async with self.pool.connection() as conn:
            row = await get_trace(conn, turn_id)
            session_cost = await session_cost_usd(conn, session_id)
        if row is None:
            return
        spans = [Span(**s) for s in row["spans"]]
        calls = [LLMUsage(**u) for u in row["usage"]]
        self.bus.publish(session_id, TraceEvent(turn_id=turn_id, spans=spans))
        self.bus.publish(
            session_id,
            UsageEvent(
                turn_id=turn_id,
                calls=calls,
                turn_cost_usd=round(sum(c.cost_usd for c in calls), 6),
                session_cost_usd=round(session_cost, 6),
                latency=Latency(**row["latency"]),
            ),
        )

    @staticmethod
    def _fail(emit: Any, turn_id: str, code: ErrorCode, message: str, retryable: bool) -> TurnResult:
        emit(ErrorEvent(turn_id=turn_id, code=code, retryable=retryable, message=message))
        emit(TurnCompletedEvent(turn_id=turn_id, status="failed"))
        return TurnResult(turn_id, "failed", None, None)
