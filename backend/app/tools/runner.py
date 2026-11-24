"""Runs one tool call: validates args, applies fault injection, emits step events, records a span, never raises."""

import asyncio
import logging
import time
from typing import Any

from pydantic import ValidationError

from app.events import StepEvent
from app.tools.base import ToolEnv, ToolError, ToolOutcome, ToolSpec

log = logging.getLogger(__name__)


class ToolRunner:
    def __init__(self, registry: dict[str, ToolSpec], slow_seconds: float = 5.0) -> None:
        self.registry = registry
        self._slow_seconds = slow_seconds

    async def run(self, env: ToolEnv, name: str, raw_args: dict[str, Any], call_id: str) -> ToolOutcome:
        ctx = env.ctx
        spec = self.registry.get(name)
        label = spec.label if spec else f"Running {name}…"
        ctx.emit(StepEvent(type="step_started", turn_id=ctx.turn_id, step_id=call_id, tool=name, label=label))
        t0 = time.perf_counter()
        outcome: ToolOutcome
        async with ctx.trace.span(name, "tool", args=raw_args) as attrs:
            try:
                if spec is None:
                    raise ToolError("INVALID_VALUE", f"Unknown tool {name}.")
                try:
                    args = spec.args_model.model_validate(raw_args)
                except ValidationError as exc:
                    raise ToolError("INVALID_VALUE", _validation_message(exc)) from exc
                await self._inject_faults(env, name)
                outcome = ToolOutcome(ok=True, data=await spec.fn(env, args))
            except ToolError as err:
                outcome = ToolOutcome(ok=False, error=err)
            except Exception:
                log.exception("tool %s crashed", name)
                outcome = ToolOutcome(
                    ok=False, error=ToolError("TOOL_FAILED", "The system didn't respond.", retryable=True)
                )

            if outcome.error is not None and outcome.error.code == "TOOL_FAILED":
                env.failures[name] += 1
                if env.failures[name] >= 2:
                    outcome.error.retryable = False
                    outcome.error.hint = "offer_escalation"
            attrs["ok"] = outcome.ok
            attrs["result"] = outcome.for_model()

        duration = int((time.perf_counter() - t0) * 1000)
        ctx.emit(
            StepEvent(
                type="step_completed" if outcome.ok else "step_failed",
                turn_id=ctx.turn_id,
                step_id=call_id,
                tool=name,
                label=label,
                duration_ms=duration,
                error=outcome.error.code if outcome.error else None,
            )
        )
        return outcome

    async def _inject_faults(self, env: ToolEnv, name: str) -> None:
        if await env.ctx.chaos.tool_slow() == name:
            await asyncio.sleep(self._slow_seconds)
        if await env.ctx.chaos.consume_tool_fail(name):
            raise ToolError("TOOL_FAILED", "Simulated failure: the system didn't respond.", retryable=True)
        if env.customer is not None and env.customer.chaos_flags.get(name) == "always_fail":
            raise ToolError("TOOL_FAILED", "The billing system isn't responding.", retryable=True)


def _validation_message(exc: ValidationError) -> str:
    parts = [f"{'.'.join(str(p) for p in e['loc'])}: {e['msg']}" for e in exc.errors()]
    return "Invalid arguments — " + "; ".join(parts)
