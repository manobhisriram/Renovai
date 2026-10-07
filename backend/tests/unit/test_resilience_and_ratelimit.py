from __future__ import annotations

import pytest

from app.utils.ratelimit import RateLimiter
from app.utils.resilience import CircuitBreaker, CircuitOpenError, backoff_delay, retry_call


def test_retry_is_bounded_and_backs_off():
    calls, sleeps = [], []

    def boom():
        calls.append(1)
        raise ConnectionError("x")

    with pytest.raises(ConnectionError):
        retry_call(boom, attempts=4, base_delay=1, max_delay=3, sleep=sleeps.append)
    assert len(calls) == 4 and len(sleeps) == 3 and all(s <= 3 for s in sleeps)


def test_retry_returns_on_success_and_only_catches_listed_errors():
    state = {"n": 0}

    def flaky():
        state["n"] += 1
        if state["n"] < 3:
            raise TimeoutError
        return "ok"

    assert retry_call(flaky, attempts=5, retry_on=(TimeoutError,), sleep=lambda _: None) == "ok"
    with pytest.raises(ValueError):
        retry_call(lambda: (_ for _ in ()).throw(ValueError("no retry")), attempts=3, retry_on=(TimeoutError,), sleep=lambda _: None)


def test_backoff_grows_and_is_capped():
    d = [backoff_delay(a, 1.0, 5.0, jitter=lambda: 1.0) for a in range(1, 6)]
    assert d == [1.0, 2.0, 4.0, 5.0, 5.0]


def test_circuit_breaker_opens_and_half_opens():
    now = [0.0]
    cb = CircuitBreaker("t", failure_threshold=2, reset_timeout=10, clock=lambda: now[0])
    assert cb.state == "closed"
    cb.record_failure(); cb.record_failure()
    assert cb.state == "open" and not cb.allow()
    with pytest.raises(CircuitOpenError):
        retry_call(lambda: 1, breaker=cb)
    now[0] = 11
    assert cb.state == "half_open" and cb.allow()
    cb.record_success()
    assert cb.state == "closed"


def test_rate_limiter_blocks_over_limit_and_is_per_key():
    rl = RateLimiter()
    results = [rl.check("ip1", 3)[0] for _ in range(5)]
    assert results == [True, True, True, False, False]
    assert rl.check("ip2", 3)[0] is True


def test_rate_limiter_fails_open_to_memory_when_redis_down():
    class Down:
        def pipeline(self):
            raise ConnectionError("redis down")

    rl = RateLimiter(Down())
    assert rl.check("k", 2)[0] is True and rl.check("k", 2)[0] is True and rl.check("k", 2)[0] is False
