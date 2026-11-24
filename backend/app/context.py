"""Everything one agent turn needs, passed to graph nodes via config["configurable"]["ctx"]."""

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Protocol
from uuid import UUID

from app.config import Settings
from app.db import Pool
from app.events import AgentEvent
from app.models import Channel
from app.observability.trace import TraceRecorder


class ChaosStore(Protocol):
    """Per-session fault-injection flags (see app.chaos for the Postgres and in-memory implementations)."""

    async def get(self) -> dict[str, Any]: ...

    async def set(self, flags: dict[str, Any]) -> None: ...

    async def consume(self, flag: str) -> bool:
        """Atomically read-and-clear a one-shot boolean flag."""
        ...

    async def consume_tool_fail(self, tool: str) -> bool:
        """True (and cleared) if the next call to `tool` should fail."""
        ...

    async def tool_slow(self) -> str | None: ...


@dataclass
class TurnContext:
    session_id: UUID
    turn_id: str
    channel: Channel
    emit: Callable[[AgentEvent], None]
    trace: TraceRecorder
    pool: Pool | None
    settings: Settings
    chaos: ChaosStore
    now: Callable[[], datetime] = field(default=lambda: datetime.now(UTC))
