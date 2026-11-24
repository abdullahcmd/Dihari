"""Abuse controls: sliding-window rate limits (in-process; swap behind this interface for Redis)."""
import time
from collections import defaultdict, deque

from ..settings import get_settings


class RateLimited(Exception):
    def __init__(self, key: str, retry_after: int):
        super().__init__(f"rate limited: {key}")
        self.retry_after = retry_after


class SlidingWindowLimiter:
    def __init__(self):
        self._hits: dict[str, deque] = defaultdict(deque)

    def check(self, key: str, max_calls: int, window_s: int, now: float | None = None) -> None:
        if not get_settings().rate_limit_enabled:
            return
        now = time.monotonic() if now is None else now
        q = self._hits[key]
        while q and q[0] <= now - window_s:
            q.popleft()
        if len(q) >= max_calls:
            raise RateLimited(key, int(q[0] + window_s - now) + 1)
        q.append(now)

    def reset(self):
        self._hits.clear()


limiter = SlidingWindowLimiter()
