"""Token-bucket rate limiter per principal. In multi-replica deployments, back this with Redis
or enforce limits at the gateway as well; the in-process limiter is per replica."""

from __future__ import annotations

import threading
import time
from collections.abc import Callable


class TokenBucketLimiter:
    def __init__(self, per_minute: int, burst: int | None = None, clock: Callable[[], float] = time.monotonic) -> None:
        self._rate = per_minute / 60.0
        self._capacity = float(burst or per_minute)
        self._clock = clock
        self._buckets: dict[str, tuple[float, float]] = {}
        self._lock = threading.Lock()

    def allow(self, key: str) -> bool:
        now = self._clock()
        with self._lock:
            tokens, last = self._buckets.get(key, (self._capacity, now))
            tokens = min(self._capacity, tokens + (now - last) * self._rate)
            if tokens < 1.0:
                self._buckets[key] = (tokens, now)
                return False
            self._buckets[key] = (tokens - 1.0, now)
            return True
