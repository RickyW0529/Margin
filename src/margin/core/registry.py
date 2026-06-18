"""Provider Registry — 轻量级注册中心（架构 §27: 自研轻量注册表）。

整合 Provider 注册、健康检查、限流、重试、Fallback、Secret 引用、
成本统计、版本号与审计日志。

对应 spec 01 §3 接口契约。
对应 plan 0101 全部工作项。
"""

from __future__ import annotations

import time
from collections.abc import Callable
from datetime import datetime
from typing import Any, TypeVar

from margin.core.audit import AuditLogger, compute_hash
from margin.core.provider import (
    BaseProvider,
    CallResult,
    HealthCheckResult,
    ProviderType,
)
from margin.core.resilience import (
    ProviderError,
    RateLimiter,
    RetryConfig,
    with_retry,
)
from margin.core.secret import SecretManager, SecretNotFoundError

T = TypeVar("T")


class ProviderNotFoundError(KeyError):
    """Provider 未注册。"""


class ProviderAlreadyRegisteredError(ValueError):
    """Provider 已注册且不允许覆盖。"""


class ProviderRegistry:
    """Provider 注册中心。

    职责：
    - 注册/获取 Provider 实例；
    - 按 type 查询可用 Provider 列表；
    - 对 Provider 调用包装限流、重试、Fallback、审计与成本统计；
    - 批量健康检查。

    用法::

        registry = ProviderRegistry()
        registry.register(akshare_provider)
        bars, result = registry.call(
            "akshare", "get_bars",
            args=(["000001.SZ"], start, end),
        )
    """

    def __init__(
        self,
        secret_manager: SecretManager | None = None,
        audit_logger: AuditLogger | None = None,
    ) -> None:
        self._providers: dict[str, BaseProvider] = {}
        self._rate_limiters: dict[str, RateLimiter] = {}
        self._retry_configs: dict[str, RetryConfig] = {}
        self._cost_rates: dict[str, float] = {}
        self._fallbacks: dict[str, list[str]] = {}
        self._secret_manager = secret_manager or SecretManager()
        self._audit_logger = audit_logger or AuditLogger()

    def register(
        self,
        provider: BaseProvider,
        *,
        rate_limiter: RateLimiter | None = None,
        retry_config: RetryConfig | None = None,
        cost_per_call: float = 0.0,
        fallback_names: list[str] | None = None,
        allow_override: bool = False,
    ) -> None:
        """注册一个 Provider 实例。

        Args:
            provider: Provider 实例。
            rate_limiter: 限流器，默认 60 次/分钟。
            retry_config: 重试配置，默认 3 次指数退避。
            cost_per_call: 每次调用成本（用于成本统计）。
            fallback_names: 备用 Provider 名称列表（主源失败时依次尝试）。
            allow_override: 是否允许覆盖同名 Provider。
        """
        name = provider.descriptor.name
        if name in self._providers and not allow_override:
            raise ProviderAlreadyRegisteredError(
                f"Provider '{name}' already registered. "
                "Use allow_override=True to replace."
            )
        self._inject_secrets(provider)
        self._providers[name] = provider
        self._rate_limiters[name] = rate_limiter or RateLimiter()
        self._retry_configs[name] = retry_config or RetryConfig()
        self._cost_rates[name] = cost_per_call
        if fallback_names:
            self._fallbacks[name] = list(fallback_names)

    def get(self, name: str) -> BaseProvider:
        """按名称获取 Provider 实例。"""
        if name not in self._providers:
            raise ProviderNotFoundError(f"Provider '{name}' not registered")
        return self._providers[name]

    def list_by_type(self, provider_type: ProviderType) -> list[str]:
        """按类型列出已注册 Provider 名称。"""
        return [
            name
            for name, p in self._providers.items()
            if p.descriptor.provider_type == provider_type
        ]

    def list_all(self) -> list[str]:
        """列出全部已注册 Provider 名称。"""
        return list(self._providers.keys())

    def resolve_secrets(self, name: str) -> dict[str, str]:
        """解析 Provider 的全部 Secret 引用。"""
        provider = self.get(name)
        return {ref: self._secret_manager.resolve(ref) for ref in provider.descriptor.secret_refs}

    def healthcheck(self, name: str) -> HealthCheckResult:
        """对单个 Provider 执行健康检查。"""
        return self.get(name).healthcheck()

    def healthcheck_all(self) -> dict[str, HealthCheckResult]:
        """对所有已注册 Provider 执行健康检查。"""
        return {name: self.get(name).healthcheck() for name in self._providers}

    def call(
        self,
        provider_name: str,
        method: str,
        args: tuple = (),
        kwargs: dict[str, Any] | None = None,
        trace_id: str = "",
    ) -> tuple[Any, CallResult]:
        """调用 Provider 方法，自动包装限流、重试、Fallback、审计与成本统计。

        Args:
            provider_name: Provider 名称。
            method: 要调用的方法名（如 ``get_bars``）。
            args: 位置参数。
            kwargs: 关键字参数。
            trace_id: 追踪 ID（用于审计与可观测性）。

        Returns:
            (方法返回值, CallResult 审计元数据)。
        """
        kwargs = kwargs or {}
        chain = [provider_name] + self._fallbacks.get(provider_name, [])
        last_result: CallResult | None = None
        last_data: Any = None

        for idx, name in enumerate(chain):
            is_fallback = idx > 0
            data, result = self._call_single(
                name, method, args, kwargs, trace_id, is_fallback
            )
            last_result = result
            last_data = data
            if result.success:
                return last_data, last_result

        assert last_result is not None
        return last_data, last_result

    def _call_single(
        self,
        name: str,
        method: str,
        args: tuple,
        kwargs: dict[str, Any],
        trace_id: str,
        is_fallback: bool,
    ) -> tuple[Any, CallResult]:
        """对单个 Provider 执行带限流与重试的调用。"""
        provider = self.get(name)
        descriptor = provider.descriptor
        func = getattr(provider, method, None)
        if func is None or not callable(func):
            result = CallResult(
                provider_name=name,
                provider_version=descriptor.version,
                success=False,
                error=f"Method '{method}' not found on provider '{name}'",
                from_fallback=is_fallback,
            )
            self._audit_logger.log_call(
                provider_name=name,
                provider_version=descriptor.version,
                method=method,
                params={**_raw_positional_args(args), **kwargs},
                result=result,
                trace_id=trace_id,
            )
            return None, result

        start = time.monotonic()
        retry_config = self._retry_configs[name]
        rate_limiter = self._rate_limiters[name]
        cost = self._cost_rates[name]
        should_raise = False
        raise_message = ""

        try:
            data, attempt_count = with_retry(
                func, args=args, kwargs=kwargs, config=retry_config, rate_limiter=rate_limiter
            )
            latency_ms = (time.monotonic() - start) * 1000
            response_hash = compute_hash(data)

            result = CallResult(
                provider_name=name,
                provider_version=descriptor.version,
                success=True,
                data=data,
                fetched_at=datetime.now(),
                response_hash=response_hash,
                cost=cost * attempt_count,
                latency_ms=latency_ms,
                attempt_count=attempt_count,
                from_fallback=is_fallback,
            )
        except Exception as exc:
            latency_ms = (time.monotonic() - start) * 1000
            retry_config_retry_on = retry_config.retry_on
            is_retryable = isinstance(exc, retry_config_retry_on)
            error_msg = (
                f"{type(exc).__name__}: {exc}"
                if not is_retryable
                else str(exc)
            )
            attempt_count = retry_config.max_retries if is_retryable else 1
            result = CallResult(
                provider_name=name,
                provider_version=descriptor.version,
                success=False,
                error=error_msg,
                fetched_at=datetime.now(),
                cost=cost * attempt_count,
                latency_ms=latency_ms,
                attempt_count=attempt_count,
                from_fallback=is_fallback,
            )
            data = None
            if not is_retryable:
                should_raise = True
                raise_message = error_msg

        self._audit_logger.log_call(
            provider_name=name,
            provider_version=descriptor.version,
            method=method,
            params={**_positional_args(func, args), **kwargs},
            result=result,
            trace_id=trace_id,
        )
        if should_raise:
            raise ProviderError(raise_message)
        return data, result

    def _inject_secrets(self, provider: BaseProvider) -> None:
        """Resolve configured Secret refs and inject them into providers that opt in."""
        refs = provider.descriptor.secret_refs
        if not refs:
            return

        secrets: dict[str, str] = {}
        for ref in refs:
            try:
                secrets[ref] = self._secret_manager.resolve(ref)
            except SecretNotFoundError:
                continue

        if not secrets:
            return

        configure = getattr(provider, "configure_secrets", None)
        if callable(configure):
            configure(secrets)
            return

        set_token = getattr(provider, "set_token", None)
        if callable(set_token) and len(secrets) == 1:
            set_token(next(iter(secrets.values())))


def _positional_args(func: Callable, args: tuple) -> dict[str, Any]:
    """将位置参数映射到参数名（用于审计摘要）。"""
    try:
        import inspect

        sig = inspect.signature(func)
        params = list(sig.parameters.keys())
        return {params[i]: arg for i, arg in enumerate(args) if i < len(params)}
    except (ValueError, TypeError):
        return {f"arg{i}": arg for i, arg in enumerate(args)}


def _raw_positional_args(args: tuple) -> dict[str, Any]:
    return {f"arg{i}": arg for i, arg in enumerate(args)}
