"""Cache with fail-open behavior. A cache outage must slow the system, never break it.

Cache keys must include the caller's teams. Otherwise one team's cached answer
could be served to a team that is not allowed to see its sources.
"""

from __future__ import annotations

import hashlib
import logging
import time
from collections.abc import Callable
from typing import Protocol

log = logging.getLogger(__name__)


class Cache(Protocol):
    def get(self, key: str) -> str | None: ...
    def set(self, key: str, value: str, ttl_s: int) -> None: ...


class InMemoryCache:
    def __init__(self, clock: Callable[[], float] = time.monotonic) -> None:
        self._data: dict[str, tuple[str, float]] = {}
        self._clock = clock

    def get(self, key: str) -> str | None:
        item = self._data.get(key)
        if item is None:
            return None
        value, expires = item
        if self._clock() > expires:
            self._data.pop(key, None)
            return None
        return value

    def set(self, key: str, value: str, ttl_s: int) -> None:
        self._data[key] = (value, self._clock() + ttl_s)


class RedisCache:
    def __init__(self, url: str) -> None:
        import redis

        self._client = redis.Redis.from_url(url, decode_responses=True, socket_timeout=0.5)

    def get(self, key: str) -> str | None:
        return self._client.get(key)

    def set(self, key: str, value: str, ttl_s: int) -> None:
        self._client.set(key, value, ex=ttl_s)


class FailOpenCache:
    def __init__(self, inner: Cache) -> None:
        self._inner = inner

    def get(self, key: str) -> str | None:
        try:
            return self._inner.get(key)
        except Exception:
            log.warning("cache get failed; continuing without cache")
            return None

    def set(self, key: str, value: str, ttl_s: int) -> None:
        try:
            self._inner.set(key, value, ttl_s)
        except Exception:
            log.warning("cache set failed; continuing without cache")


def cache_key(namespace: str, *parts: str) -> str:
    digest = hashlib.sha256("\x1f".join(parts).encode()).hexdigest()
    return f"pia:{namespace}:{digest}"


def build_cache(redis_url: str | None) -> Cache:
    inner: Cache = RedisCache(redis_url) if redis_url else InMemoryCache()
    return FailOpenCache(inner)
