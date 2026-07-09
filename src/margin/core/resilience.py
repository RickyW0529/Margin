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
    """Raised when a rate limiter has no available tokens.."""


class ProviderError(Exception):
    """Raised when a Provider call fails.."""


@dataclass
class RateLimiter:
    """Token-bucket rate limiter.."""

    max_calls: int = 60
    per_seconds: float = 60.0
    _tokens: float = field(init=False)
    _last_refill: float = field(init=False)

    def __post_init__(self) -> None:
        """Initialize the token bucket to full capacity.

        Returns:
            None: .
        """
        self._tokens = float(self.max_calls)
        self._last_refill = time.monotonic()

    def _refill(self) -> None:
        """Refill tokens based on elapsed time since the last refill.

        Returns:
            None: .
        """
        now = time.monotonic()
        elapsed = now - self._last_refill
        new_tokens = elapsed * (self.max_calls / self.per_seconds)
        self._tokens = min(self.max_calls, self._tokens + new_tokens)
        self._last_refill = now

    def acquire(self) -> None:
        """Acquire one token, raising if the bucket is empty.

        Returns:
            None: .
        """
        self._refill()
        if self._tokens < 1.0:
            raise RateLimitError(f"Rate limit exceeded: {self.max_calls}/{self.per_seconds}s")
        self._tokens -= 1.0

    def try_acquire(self) -> bool:
        """Try to acquire one token without raising.

        Returns:
            bool: .
        """
        try:
            self.acquire()
            return True
        except RateLimitError:
            return False


@dataclass
class RetryConfig:
    """Configuration for retry behavior.."""

    max_retries: int = 3
    base_delay: float = 1.0
    max_delay: float = 30.0
    backoff_factor: float = 2.0
    retry_on: tuple[type[Exception], ...] = (ProviderError,)

    def compute_delay(self, attempt: int) -> float:
        """Compute the delay before retry ``attempt`` using exponential backoff.

        Args:
            attempt: int: .

        Returns:
            float: .
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
        func: Callable[..., T]: .
        args: tuple: .
        kwargs: dict[str, Any] | None: .
        config: RetryConfig | None: .
        rate_limiter: RateLimiter | None: .
        sleep: Callable[[float], None]: .

    Returns:
        tuple[T, int]: .
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
