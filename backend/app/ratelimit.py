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


def client_ip(headers: Mapping[str, str], peer: str | None, trusted_hops: int = 1) -> str:
    """The client's address as seen by our proxy (Railway appends it to X-Forwarded-For).

    Entries to the left of the ones our proxies added are whatever the caller sent, so they can't be trusted: with
    `trusted_hops` proxies in front, the client is the trusted_hops-th entry from the right.
    """
    forwarded = [h.strip() for h in (headers.get("x-forwarded-for") or "").split(",") if h.strip()]
    if forwarded:
        return forwarded[-trusted_hops] if len(forwarded) >= trusted_hops else forwarded[0]
    return peer or "unknown"
