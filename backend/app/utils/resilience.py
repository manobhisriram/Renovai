"""Retries with exponential backoff + jitter, and a small circuit breaker."""

from __future__ import annotations

import logging
import random
import threading
import time
from collections.abc import Callable

log = logging.getLogger(__name__)


class CircuitOpenError(RuntimeError):
    pass


class CircuitBreaker:
    """Opens after N consecutive failures; half-opens after a cool-down."""

    def __init__(self, name: str, failure_threshold: int = 5, reset_timeout: float = 30.0,
                 clock: Callable[[], float] = time.monotonic):
        self.name = name
        self.failure_threshold = failure_threshold
        self.reset_timeout = reset_timeout
        self._clock = clock
        self._failures = 0
        self._opened_at: float | None = None
        self._lock = threading.Lock()

    @property
    def state(self) -> str:
        with self._lock:
            if self._opened_at is None:
                return "closed"
            if self._clock() - self._opened_at >= self.reset_timeout:
                return "half_open"
            return "open"

    def allow(self) -> bool:
        return self.state != "open"

    def record_success(self) -> None:
        with self._lock:
            self._failures = 0
            self._opened_at = None

    def record_failure(self) -> None:
        with self._lock:
            self._failures += 1
            if self._failures >= self.failure_threshold:
                self._opened_at = self._clock()


def backoff_delay(attempt: int, base: float, cap: float, jitter: Callable[[], float] = random.random) -> float:
    """Exponential backoff with jitter for a 1-based attempt number."""
    ceiling = min(cap, base * (2 ** (attempt - 1)))
    return ceiling * (0.5 + 0.5 * jitter())


def retry_call[T](
    fn: Callable[[], T],
    *,
    attempts: int = 3,
    base_delay: float = 0.5,
    max_delay: float = 8.0,
    retry_on: tuple[type[BaseException], ...] = (Exception,),
    sleep: Callable[[float], None] = time.sleep,
    breaker: CircuitBreaker | None = None,
) -> T:
    """Call ``fn`` at most ``attempts`` times. Never loops forever."""
    if attempts < 1:
        raise ValueError("attempts must be >= 1")
    last: BaseException | None = None
    for attempt in range(1, attempts + 1):
        if breaker is not None and not breaker.allow():
            raise CircuitOpenError(f"circuit '{breaker.name}' is open")
        try:
            result = fn()
        except retry_on as exc:
            last = exc
            if breaker is not None:
                breaker.record_failure()
            if attempt == attempts:
                break
            delay = backoff_delay(attempt, base_delay, max_delay)
            log.warning("retrying after failure attempt=%s delay=%.2fs error=%s", attempt, delay, type(exc).__name__)
            sleep(delay)
        else:
            if breaker is not None:
                breaker.record_success()
            return result
    assert last is not None
    raise last
