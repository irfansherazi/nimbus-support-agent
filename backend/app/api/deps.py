"""The app's long-lived services, built once at startup (or injected by tests)."""

import logging
from dataclasses import dataclass, field
from typing import Any

from fastapi import Request

from app.agent.graph import AgentDeps, build_graph
from app.agent.runner import TurnRunner
from app.budget import BudgetGuard
from app.bus import SessionBus
from app.config import Settings
from app.db import Pool, create_pool
from app.ratelimit import SlidingWindowLimiter

log = logging.getLogger(__name__)


@dataclass
class Services:
    settings: Settings
    pool: Pool
    bus: SessionBus
    runner: TurnRunner
    budget: BudgetGuard
    deps: AgentDeps
    chat_ip_limiter: SlidingWindowLimiter
    chat_session_limiter: SlidingWindowLimiter
    session_create_limiter: SlidingWindowLimiter
    voice_ip_limiter: SlidingWindowLimiter
    owns_pool: bool = False
    extras: dict[str, Any] = field(default_factory=dict)  # e.g. the voice call registry


def build_services(settings: Settings, pool: Pool, deps: AgentDeps, owns_pool: bool = False) -> Services:
    bus = SessionBus()
    budget = BudgetGuard(pool, settings)
    runner = TurnRunner(pool, bus, build_graph(deps), deps, settings, budget)
    services = Services(
        settings=settings,
        pool=pool,
        bus=bus,
        runner=runner,
        budget=budget,
        deps=deps,
        chat_ip_limiter=SlidingWindowLimiter(settings.chat_rate_per_min, 60),
        chat_session_limiter=SlidingWindowLimiter(settings.chat_rate_per_min, 60),
        session_create_limiter=SlidingWindowLimiter(30, 60),
        voice_ip_limiter=SlidingWindowLimiter(settings.voice_calls_per_hour, 3600),
        owns_pool=owns_pool,
    )
    from app.voice.registry import VoiceRegistry

    services.extras["voice"] = VoiceRegistry(
        pool=pool, bus=bus, runner=runner, llm=deps.llm, settings=settings, budget=budget
    )
    return services


async def build_production_services(settings: Settings) -> Services:
    from app.llm.gateway import build_gateway
    from app.rag.embedder import Embedder, HashEmbedder, OpenAIEmbedder
    from app.tools.registry import build_registry
    from app.tools.runner import ToolRunner

    pool = await create_pool(settings.database_url)
    budget = BudgetGuard(pool, settings)
    embedder: Embedder
    if settings.openai_api_key:
        embedder = OpenAIEmbedder(settings)
    else:
        log.warning("OPENAI_API_KEY not set: using the offline hashing embedder (retrieval quality will be poor)")
        embedder = HashEmbedder()
    deps = AgentDeps(llm=build_gateway(settings, budget), runner=ToolRunner(build_registry()), embedder=embedder)
    return build_services(settings, pool, deps, owns_pool=True)


def get_services(request: Request) -> Services:
    return request.app.state.services  # type: ignore[no-any-return]
