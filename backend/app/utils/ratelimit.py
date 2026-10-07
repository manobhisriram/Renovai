"""Fixed-window rate limiter. Redis when configured (shared across replicas), in-process otherwise."""

from __future__ import annotations

import logging
import threading
import time
from typing import Any

log = logging.getLogger(__name__)


class MemoryBackend:
    def __init__(self) -> None:
        self._hits: dict[str, tuple[int, int]] = {}
        self._lock = threading.Lock()

    def hit(self, key: str, window_s: int) -> int:
        bucket = int(time.time() // window_s)
        with self._lock:
            b, n = self._hits.get(key, (bucket, 0))
            n = n + 1 if b == bucket else 1
            self._hits[key] = (bucket, n)
            if len(self._hits) > 10_000:  # bound memory
                self._hits = {k: v for k, v in self._hits.items() if v[0] == bucket}
            return n


class RedisBackend:
    def __init__(self, client: Any):
        self._r = client

    def hit(self, key: str, window_s: int) -> int:
        k = f"renovai:rl:{key}:{int(time.time() // window_s)}"
        pipe = self._r.pipeline()
        pipe.incr(k)
        pipe.expire(k, window_s + 1)
        return int(pipe.execute()[0])


class RateLimiter:
    def __init__(self, redis_client: Any | None = None):
        self._mem = MemoryBackend()
        self._redis = RedisBackend(redis_client) if redis_client is not None else None

    def check(self, key: str, limit: int, window_s: int = 60) -> tuple[bool, int]:
        """Returns (allowed, retry_after_seconds). Fails open (to memory) if Redis is down."""
        backend: Any = self._redis or self._mem
        try:
            n = backend.hit(key, window_s)
        except Exception as exc:
            log.warning("rate limiter backend failed (%s); using in-process counters", type(exc).__name__)
            n = self._mem.hit(key, window_s)
        return n <= limit, window_s - int(time.time()) % window_s
