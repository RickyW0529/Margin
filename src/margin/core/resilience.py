"""Resilience primitives: rate limiting, retry with exponential backoff, and fallback.

These utilities wrap Provider calls so that transient failures can be retried,
rate limits can be enforced, and non-retryable errors propagate quickly.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, TypeVar

T = TypeVar("T")


class RateLimitError(Exception):
    """Raised when a rate limiter has no available tokens."""


class ProviderError(Exception):
    """Raised when a Provider call fails."""


@dataclass
class RateLimiter:
    """Token-bucket rate limiter.

    Controls call frequency using ``max_calls`` per ``per_seconds``. This
    implementation is not thread-safe, which is acceptable for the MVP single-
    threaded worker use case.

    Attributes:
        max_calls: Maximum number of tokens (calls) in the bucket.
        per_seconds: Time window over which ``max_calls`` tokens are allocated.
        _tokens: Current number of available tokens.
        _last_refill: Timestamp of the last token refill.
    """

    max_calls: int = 60
    per_seconds: float = 60.0
    _tokens: float = field(init=False)
    _last_refill: float = field(init=False)

    def __post_init__(self) -> None:
        """Initialize the token bucket to full capacity."""
        self._tokens = float(self.max_calls)
        self._last_refill = time.monotonic()

    def _refill(self) -> None:
        """Refill tokens based on elapsed time since the last refill."""
        now = time.monotonic()
        elapsed = now - self._last_refill
        new_tokens = elapsed * (self.max_calls / self.per_seconds)
        self._tokens = min(self.max_calls, self._tokens + new_tokens)
        self._last_refill = now

    def acquire(self) -> None:
        """Acquire one token, raising if the bucket is empty.

        Raises:
            RateLimitError: When no tokens are available.
        """
        self._refill()
        if self._tokens < 1.0:
            raise RateLimitError(
                f"Rate limit exceeded: {self.max_calls}/{self.per_seconds}s"
            )
        self._tokens -= 1.0

    def try_acquire(self) -> bool:
        """Try to acquire one token without raising.

        Returns:
            ``True`` if a token was acquired, otherwise ``False``.
        """
        try:
            self.acquire()
            return True
        except RateLimitError:
            return False


@dataclass
class RetryConfig:
    """Configuration for retry behavior.

    Attributes:
        max_retries: Maximum number of retry attempts.
        base_delay: Initial delay between retries in seconds.
        max_delay: Maximum delay between retries in seconds.
        backoff_factor: Multiplier applied to the delay on each retry.
        retry_on: Tuple of exception types that should trigger a retry.
    """

    max_retries: int = 3
    base_delay: float = 1.0
    max_delay: float = 30.0
    backoff_factor: float = 2.0
    retry_on: tuple[type[Exception], ...] = (ProviderError,)

    def compute_delay(self, attempt: int) -> float:
        """Compute the delay before retry ``attempt`` using exponential backoff.

        Args:
            attempt: The retry attempt number (1-based).

        Returns:
            Delay in seconds, capped at ``max_delay``.
        """
        delay = self.base_delay * (self.backoff_factor ** (attempt - 1))
        return min(delay, self.max_delay)


def with_retry(
    func: Callable[..., T],
    args: tuple = (),
    kwargs: dict[str, Any] | None = None,
    config: RetryConfig | None = None,
    rate_limiter: RateLimiter | None = None,
    sleep: Callable[[float], None] = time.sleep,
) -> tuple[T, int]:
    """Call a function with retry, backoff, and optional rate limiting.

    Args:
        func: The callable to invoke.
        args: Positional arguments passed to ``func``.
        kwargs: Keyword arguments passed to ``func``.
        config: Retry configuration. Defaults to ``RetryConfig()``.
        rate_limiter: Optional rate limiter to acquire before each attempt.
        sleep: Sleep function used between retries. Injectable for testing.

    Returns:
        A tuple of (``func`` return value, number of attempts made).

    Raises:
        Exception: The last exception encountered when all retries are exhausted.
            Non-retryable exceptions propagate immediately.
    """
    config = config or RetryConfig()
    kwargs = kwargs or {}
    last_exc: Exception | None = None

    for attempt in range(1, config.max_retries + 1):
        if rate_limiter is not None:
            rate_limiter.acquire()
        try:
            result = func(*args, **kwargs)
            return result, attempt
        except config.retry_on as exc:
            last_exc = exc
            if attempt < config.max_retries:
                delay = config.compute_delay(attempt)
                sleep(delay)
            continue
        except Exception:
            raise

    assert last_exc is not None
    raise last_exc
