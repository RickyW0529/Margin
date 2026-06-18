"""容错机制测试：RateLimiter、RetryConfig、with_retry。"""

import pytest

from margin.core.resilience import (
    ProviderError,
    RateLimiter,
    RateLimitError,
    RetryConfig,
    with_retry,
)


class TestRateLimiter:
    def test_allows_within_limit(self):
        rl = RateLimiter(max_calls=3, per_seconds=60.0)
        rl.acquire()
        rl.acquire()
        rl.acquire()

    def test_raises_when_exhausted(self):
        rl = RateLimiter(max_calls=1, per_seconds=60.0)
        rl.acquire()
        with pytest.raises(RateLimitError):
            rl.acquire()

    def test_try_acquire_returns_false_when_exhausted(self):
        rl = RateLimiter(max_calls=1, per_seconds=60.0)
        assert rl.try_acquire() is True
        assert rl.try_acquire() is False

    def test_refills_over_time(self):
        rl = RateLimiter(max_calls=1, per_seconds=0.1)
        rl.acquire()
        assert rl.try_acquire() is False
        import time
        time.sleep(0.15)
        assert rl.try_acquire() is True


class TestRetryConfig:
    def test_compute_delay_exponential(self):
        config = RetryConfig(base_delay=1.0, backoff_factor=2.0, max_delay=30.0)
        assert config.compute_delay(1) == 1.0
        assert config.compute_delay(2) == 2.0
        assert config.compute_delay(3) == 4.0

    def test_compute_delay_capped(self):
        config = RetryConfig(base_delay=1.0, backoff_factor=10.0, max_delay=5.0)
        assert config.compute_delay(3) == 5.0

    def test_default_retry_on(self):
        config = RetryConfig()
        assert ProviderError in config.retry_on


class TestWithRetry:
    def test_success_first_try(self):
        calls = []
        def func():
            calls.append(1)
            return "ok"

        result, attempts = with_retry(func)
        assert result == "ok"
        assert attempts == 1
        assert len(calls) == 1

    def test_retries_on_provider_error(self):
        calls = []
        def func():
            calls.append(1)
            if len(calls) < 3:
                raise ProviderError("fail")
            return "ok"

        config = RetryConfig(max_retries=3, base_delay=0.001)
        result, attempts = with_retry(func, config=config)
        assert result == "ok"
        assert attempts == 3
        assert len(calls) == 3

    def test_raises_after_max_retries(self):
        calls = []
        def func():
            calls.append(1)
            raise ProviderError("always fail")

        config = RetryConfig(max_retries=2, base_delay=0.001)
        with pytest.raises(ProviderError, match="always fail"):
            with_retry(func, config=config)
        assert len(calls) == 2

    def test_non_retry_exception_propagates_immediately(self):
        calls = []
        def func():
            calls.append(1)
            raise ValueError("not retryable")

        config = RetryConfig(max_retries=3, base_delay=0.001)
        with pytest.raises(ValueError):
            with_retry(func, config=config)
        assert len(calls) == 1

    def test_uses_injected_sleep(self):
        sleep_calls = []
        def fake_sleep(seconds):
            sleep_calls.append(seconds)

        attempts = []
        def func():
            attempts.append(1)
            if len(attempts) < 3:
                raise ProviderError("fail")
            return "ok"

        config = RetryConfig(max_retries=3, base_delay=2.0, backoff_factor=2.0)
        with_retry(func, config=config, sleep=fake_sleep)
        assert sleep_calls == [2.0, 4.0]

    def test_rate_limiter_integration(self):
        rl = RateLimiter(max_calls=10, per_seconds=60.0)
        calls = []
        def func():
            calls.append(1)
            return "ok"

        result, attempts = with_retry(func, rate_limiter=rl)
        assert result == "ok"
        assert attempts == 1
