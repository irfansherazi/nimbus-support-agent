"""In-memory sliding-window rate limiting (single instance; see README trade-offs)."""

import time
from collections import defaultdict, deque
from collections.abc import Callable, Mapping


class SlidingWindowLimiter:
    def __init__(self, limit: int, window_s: float, clock: Callable[[], float] = time.monotonic) -> None:
        self.limit = limit
        self.window_s = window_s
        self._clock = clock
        self._hits: dict[str, deque[float]] = defaultdict(deque)

    def hit(self, key: str) -> bool:
        """Record a hit for `key`; False if it is over the limit (the hit is then not recorded)."""
        now = self._clock()
        q = self._hits[key]
        while q and q[0] <= now - self.window_s:
            q.popleft()
        if len(q) >= self.limit:
            return False
        q.append(now)
        return True


def client_ip(headers: Mapping[str, str], peer: str | None) -> str:
    """The original client address: the first X-Forwarded-For hop (Railway/Vercel sit behind proxies)."""
    forwarded = headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return peer or "unknown"
