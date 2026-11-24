"""Run the agent scenarios end to end with the real models, on the TEST database (reset first).

Run from backend/:  uv run python ../evals/run_scenarios.py
Writes evals/results/scenarios.md. Needs OPENAI_API_KEY. Costs a few cents.
"""

import asyncio
import sys
import time
from pathlib import Path
from typing import Any

import yaml

HERE = Path(__file__).resolve().parent
BACKEND = HERE.parent / "backend"
sys.path.insert(0, str(BACKEND))

from app.agent.graph import AgentDeps, build_graph  # noqa: E402
from app.agent.runner import TurnRunner  # noqa: E402
from app.bus import SessionBus  # noqa: E402
from app.config import Settings  # noqa: E402
from app.db import create_pool, migrate, run_sql_file  # noqa: E402
from app.llm.gateway import build_gateway  # noqa: E402
from app.rag.embedder import OpenAIEmbedder  # noqa: E402
from app.rag.ingest import ingest  # noqa: E402
from app.store.sessions import create_session  # noqa: E402
from app.store.traces import session_cost_usd  # noqa: E402
from app.tools.registry import build_registry  # noqa: E402
from app.tools.runner import ToolRunner  # noqa: E402


async def events_of(bus: SessionBus, sid: Any) -> list[Any]:
    out: list[Any] = []
    if bus.last_seq(sid) == 0:
        return out
    async for e in bus.subscribe(sid, last_seq=0):
        out.append(e)
        if e.seq >= bus.last_seq(sid):
            break
    return out


def check(expect: dict[str, Any], events: list[Any], answer: str, status: str) -> list[str]:
    completed = {e.tool for e in events if e.type == "step_completed" and e.kind == "tool"}
    refusals = {e.error for e in events if e.type == "step_failed" and e.error}
    low = answer.lower()
    problems = []
    if "status" in expect and status != expect["status"]:
        problems.append(f"status {status}, expected {expect['status']}")
    problems += [f"{t} did not complete" for t in expect.get("completed", []) if t not in completed]
    problems += [f"{t} completed but must not" for t in expect.get("not_completed", []) if t in completed]
    problems += [f"no {c} refusal" for c in expect.get("refusals", []) if c not in refusals]
    if "answer_has_any" in expect and not any(s.lower() in low for s in expect["answer_has_any"]):
        problems.append(f"answer lacks any of {expect['answer_has_any']}")
    problems += [f"answer contains {s!r}" for s in expect.get("answer_has_none", []) if s.lower() in low]
    return problems


async def main() -> None:
    settings = Settings()
    settings.database_url = settings.test_database_url
    scenarios = yaml.safe_load((HERE / "scenarios.yaml").read_text(encoding="utf-8"))
    pool = await create_pool(settings.test_database_url)
    await migrate(pool, BACKEND / "migrations")
    async with pool.connection() as conn:
        await conn.execute("TRUNCATE sessions, messages, refunds, tickets, traces, spend RESTART IDENTITY CASCADE")
    await run_sql_file(pool, BACKEND / "seed" / "seed.sql")
    embedder = OpenAIEmbedder(settings)
    await ingest(pool, embedder, HERE.parent / "data" / "policies")

    deps = AgentDeps(llm=build_gateway(settings), runner=ToolRunner(build_registry()), embedder=embedder)
    bus = SessionBus()
    runner = TurnRunner(pool, bus, build_graph(deps), deps, settings)

    rows, passed, total_cost = [], 0, 0.0
    for sc in scenarios:
        async with pool.connection() as conn:
            sid = (await create_session(conn)).id
        t0 = time.perf_counter()
        result = None
        for message in sc["messages"]:
            result = await runner.run_turn(sid, message, "chat")
        assert result is not None
        seconds = time.perf_counter() - t0
        events = await events_of(bus, sid)
        problems = check(sc["expect"], events, result.answer or "", result.status)
        async with pool.connection() as conn:
            cost = await session_cost_usd(conn, sid)
        total_cost += cost
        passed += not problems
        verdict = "pass" if not problems else "FAIL: " + "; ".join(problems)
        answer = (result.answer or "").replace("\n", " ").replace("|", "/")[:160]
        rows.append(f"| {sc['name']} | {verdict} | {seconds:.1f}s | ${cost:.4f} | {answer} |")
        print(f"{'PASS' if not problems else 'FAIL'}  {sc['name']}  {'; '.join(problems)}")

    await pool.close()
    lines = [
        "# Agent scenarios",
        "",
        f"**{passed}/{len(scenarios)} passed** with `{settings.agent_model}` (thresholds {settings.rag_t_low:.2f}/"
        f"{settings.rag_t_high:.2f}). Total cost ${total_cost:.4f}.",
        "",
        "| Scenario | Result | Time | Cost | Final answer (first 160 chars) |",
        "|---|---|---|---|---|",
        *rows,
    ]
    (HERE / "results" / "scenarios.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"\n{passed}/{len(scenarios)} passed, ${total_cost:.4f}")


if __name__ == "__main__":
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())  # type: ignore[attr-defined]
    asyncio.run(main())
