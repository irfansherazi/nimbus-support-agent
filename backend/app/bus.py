"""In-process per-session event bus with a bounded replay buffer (for SSE Last-Event-ID resume).

Single-instance by design (see README trade-offs): a multi-instance deploy would swap this for Redis streams.
"""

import asyncio
import uuid
from collections import defaultdict, deque
from collections.abc import AsyncIterator
from uuid import UUID

from app.events import AgentEvent


class SessionBus:
    def __init__(self, buffer_size: int = 500) -> None:
        self.epoch = uuid.uuid4().hex[:12]  # changes when the process restarts (sequence numbers start over)
        self._buffer_size = buffer_size
        self._buffers: dict[UUID, deque[AgentEvent]] = defaultdict(lambda: deque(maxlen=self._buffer_size))
        self._seq: dict[UUID, int] = defaultdict(int)
        self._subscribers: dict[UUID, set[asyncio.Queue[AgentEvent]]] = defaultdict(set)

    def publish(self, session_id: UUID, event: AgentEvent) -> int:
        self._seq[session_id] += 1
        event.seq = self._seq[session_id]
        self._buffers[session_id].append(event)
        for q in self._subscribers[session_id]:
            q.put_nowait(event)
        return event.seq

    def last_seq(self, session_id: UUID) -> int:
        return self._seq[session_id]

    async def subscribe(self, session_id: UUID, last_seq: int | None) -> AsyncIterator[AgentEvent]:
        """Replay buffered events with seq > last_seq (none if last_seq is None), then stream live events."""
        queue: asyncio.Queue[AgentEvent] = asyncio.Queue()
        self._subscribers[session_id].add(queue)
        try:
            replayed = 0
            if last_seq is not None:
                for event in list(self._buffers[session_id]):
                    if event.seq > last_seq:
                        replayed = event.seq
                        yield event
            while True:
                event = await queue.get()
                if event.seq > replayed:
                    yield event
        finally:
            self._subscribers[session_id].discard(queue)
