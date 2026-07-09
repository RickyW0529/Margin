"""Tests for resilience primitives: ``RateLimiter``, ``RetryConfig``, and ``with_retry``."""

import pytest

from margin.core.resilience import (
    ProviderError,
    RateLimiter,
    RateLimitError,
    RetryConfig,
    with_retry,
)


class TestRateLimiter:
    """Tests covering ``RateLimiter`` acquire, try-acquire, and refill behavior.."""

    def test_allows_within_limit(self):
        """Test that acquires up to ``max_calls`` succeed without raising.

        Returns:
            Any: .
        """
        rl = RateLimiter(max_calls=3, per_seconds=60.0)
        rl.acquire()
        rl.acquire()
        rl.acquire()

    def test_raises_when_exhausted(self):
        """Test that an ``acquire`` beyond ``max_calls`` raises ``RateLimitError``.

        Returns:
            Any: .
        """
        rl = RateLimiter(max_calls=1, per_seconds=60.0)
        rl.acquire()
        with pytest.raises(RateLimitError):
            rl.acquire()

    def test_try_acquire_returns_false_when_exhausted(self):
        """Test that ``try_acquire`` returns ``True`` then ``False`` once exhausted.

        Returns:
            Any: .
        """
        rl = RateLimiter(max_calls=1, per_seconds=60.0)
        assert rl.try_acquire() is True
        assert rl.try_acquire() is False

    def test_refills_over_time(self):
        """Test that tokens refill after ``per_seconds`` has elapsed.

        Returns:
            Any: .
        """
        rl = RateLimiter(max_calls=1, per_seconds=0.1)
        rl.acquire()
        assert rl.try_acquire() is False
        import time

        time.sleep(0.15)
        assert rl.try_acquire() is True


class TestRetryConfig:
    """Tests covering ``RetryConfig`` delay computation and default values.."""

    def test_compute_delay_exponential(self):
        """Test that delays follow an exponential back-off based on the attempt number.

        Returns:
            Any: .
        """
        config = RetryConfig(base_delay=1.0, backoff_factor=2.0, max_delay=30.0)
        assert config.compute_delay(1) == 1.0
        assert config.compute_delay(2) == 2.0
        assert config.compute_delay(3) == 4.0

    def test_compute_delay_capped(self):
        """Test that computed delays are capped at ``max_delay``.

        Returns:
            Any: .
        """
        config = RetryConfig(base_delay=1.0, backoff_factor=10.0, max_delay=5.0)
        assert config.compute_delay(3) == 5.0

    def test_default_retry_on(self):
        """Test that the default retry-on set includes ``ProviderError``.

        Returns:
            Any: .
        """
        config = RetryConfig()
        assert ProviderError in config.retry_on


class TestWithRetry:
    """Tests covering ``with_retry`` invocation, retries, and integrations.."""

    def test_success_first_try(self):
        """Test that a successful call returns immediately after one attempt.

        Returns:
            Any: .
        """
        calls = []

        def func():
            """Append a marker to the call list and return ok.

            Returns:
                Any: .
            """
            calls.append(1)
            return "ok"

        result, attempts = with_retry(func)
        assert result == "ok"
        assert attempts == 1
        assert len(calls) == 1

    def test_retries_on_provider_error(self):
        """Test that ``ProviderError`` triggers retries until the function succeeds.

        Returns:
            Any: .
        """
        calls = []

        def func():
            """Fail twice then return ok.

            Returns:
                Any: .
            """
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
        """Test that the last ``ProviderError`` is re-raised after all retries.

        Returns:
            Any: .
        """
        calls = []

        def func():
            """Always raise a ``ProviderError``.

            Returns:
                Any: .
            """
            calls.append(1)
            raise ProviderError("always fail")

        config = RetryConfig(max_retries=2, base_delay=0.001)
        with pytest.raises(ProviderError, match="always fail"):
            with_retry(func, config=config)
        assert len(calls) == 2

    def test_non_retry_exception_propagates_immediately(self):
        """Test that non-retryable exceptions are raised immediately without retries.

        Returns:
            Any: .
        """
        calls = []

        def func():
            """Raise a non-retryable ``ValueError``.

            Returns:
                Any: .
            """
            calls.append(1)
            raise ValueError("not retryable")

        config = RetryConfig(max_retries=3, base_delay=0.001)
        with pytest.raises(ValueError):
            with_retry(func, config=config)
        assert len(calls) == 1

    def test_uses_injected_sleep(self):
        """Test that ``with_retry`` calls the injected ``sleep`` with computed delays.

        Returns:
            Any: .
        """
        sleep_calls = []

        def fake_sleep(seconds):
            """Record the requested sleep duration.

            Args:
                seconds: Any: .

            Returns:
                Any: .
            """
            sleep_calls.append(seconds)

        attempts = []

        def func():
            """Fail twice then return ok.

            Returns:
                Any: .
            """
            attempts.append(1)
            if len(attempts) < 3:
                raise ProviderError("fail")
            return "ok"

        config = RetryConfig(max_retries=3, base_delay=2.0, backoff_factor=2.0)
        with_retry(func, config=config, sleep=fake_sleep)
        assert sleep_calls == [2.0, 4.0]

    def test_rate_limiter_integration(self):
        """Test that ``with_retry`` respects an optional ``RateLimiter`` before each attempt.

        Returns:
            Any: .
        """
        rl = RateLimiter(max_calls=10, per_seconds=60.0)
        calls = []

        def func():
            """Append a marker to the call list and return ok.

            Returns:
                Any: .
            """
            calls.append(1)
            return "ok"

        result, attempts = with_retry(func, rate_limiter=rl)
        assert result == "ok"
        assert attempts == 1
