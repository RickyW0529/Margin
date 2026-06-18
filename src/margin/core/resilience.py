"""容错机制：限流、重试、Fallback（架构 §8.1 Provider 必须具备限流、重试）。

对应 plan 0101.2：健康检查、限流、重试、Fallback 通用机制。
对应架构 §25 故障降级：数据源失败 → 备用源/使用旧数据并降级。
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, TypeVar

T = TypeVar("T")


class RateLimitError(Exception):
    """限流触发。"""


class ProviderError(Exception):
    """Provider 调用失败。"""


@dataclass
class RateLimiter:
    """令牌桶限流器。

    按 ``max_calls`` / ``per_seconds`` 控制调用频率。
    线程不安全（MVP 单线程 Worker 场景足够）。
    """

    max_calls: int = 60
    per_seconds: float = 60.0
    _tokens: float = field(init=False)
    _last_refill: float = field(init=False)

    def __post_init__(self) -> None:
        self._tokens = float(self.max_calls)
        self._last_refill = time.monotonic()

    def _refill(self) -> None:
        now = time.monotonic()
        elapsed = now - self._last_refill
        new_tokens = elapsed * (self.max_calls / self.per_seconds)
        self._tokens = min(self.max_calls, self._tokens + new_tokens)
        self._last_refill = now

    def acquire(self) -> None:
        """获取一个令牌，不足时抛 RateLimitError。"""
        self._refill()
        if self._tokens < 1.0:
            raise RateLimitError(
                f"Rate limit exceeded: {self.max_calls}/{self.per_seconds}s"
            )
        self._tokens -= 1.0

    def try_acquire(self) -> bool:
        """尝试获取令牌，成功返回 True，不抛异常。"""
        try:
            self.acquire()
            return True
        except RateLimitError:
            return False


@dataclass
class RetryConfig:
    """重试配置。"""

    max_retries: int = 3
    base_delay: float = 1.0
    max_delay: float = 30.0
    backoff_factor: float = 2.0
    retry_on: tuple[type[Exception], ...] = (ProviderError,)

    def compute_delay(self, attempt: int) -> float:
        """计算第 attempt 次重试的延迟（指数退避）。"""
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
    """带重试与限流的函数调用包装。

    Args:
        func: 要调用的函数。
        args: 位置参数。
        kwargs: 关键字参数。
        config: 重试配置，默认 3 次指数退避。
        rate_limiter: 可选限流器。
        sleep: 睡眠函数（可注入用于测试）。

    Returns:
        (结果, 实际尝试次数)。

    Raises:
        最后一次重试仍失败时抛出原始异常。
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
