"""Provider Registry — lightweight registration center for Provider instances.

The registry combines Provider registration, health checks, rate limiting,
retry, fallback, Secret references, cost tracking, versioning, and audit
logging into a single integration point.
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
    """Raised when a requested Provider has not been registered."""


class ProviderAlreadyRegisteredError(ValueError):
    """Raised when registering a Provider whose name is already taken."""


class ProviderRegistry:
    """Central registry for Provider instances.

    Responsibilities:
        - Register and retrieve Provider instances.
        - List Providers by type or name.
        - Resolve configured Secret references.
        - Wrap calls with rate limiting, retry, fallback, audit logging, and
          cost tracking.
        - Run health checks for individual Providers or all registered ones.

    Example::

        registry = ProviderRegistry()
        registry.register(akshare_provider)
        bars, result = registry.call(
            "akshare", "get_bars",
            args=(["000001.SZ"], start, end),
        )

    Attributes:
        _providers: Mapping from Provider name to instance.
        _rate_limiters: Mapping from Provider name to rate limiter.
        _retry_configs: Mapping from Provider name to retry configuration.
        _cost_rates: Mapping from Provider name to cost per call.
        _fallbacks: Mapping from primary Provider name to fallback chain.
        _secret_manager: Secret resolver used during registration.
        _audit_logger: Audit logger used for every call.
    """

    def __init__(
        self,
        secret_manager: SecretManager | None = None,
        audit_logger: AuditLogger | None = None,
    ) -> None:
        """Initialize the registry.

        Args:
            secret_manager: Secret resolver. Defaults to ``SecretManager()``.
            audit_logger: Audit logger. Defaults to ``AuditLogger()``.
        """
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
        """Register a Provider instance.

        Args:
            provider: Provider instance to register.
            rate_limiter: Rate limiter for this Provider. Defaults to
                ``RateLimiter()``.
            retry_config: Retry configuration for this Provider. Defaults to
                ``RetryConfig()``.
            cost_per_call: Cost charged for each successful or failed call.
            fallback_names: Ordered list of fallback Provider names tried when
                this Provider fails.
            allow_override: Whether to replace an existing Provider with the
                same name.

        Raises:
            ProviderAlreadyRegisteredError: When the Provider name is already
                registered and ``allow_override`` is ``False``.
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
        """Retrieve a registered Provider by name.

        Args:
            name: Registered Provider name.

        Returns:
            The registered Provider instance.

        Raises:
            ProviderNotFoundError: When no Provider with the given name is
                registered.
        """
        if name not in self._providers:
            raise ProviderNotFoundError(f"Provider '{name}' not registered")
        return self._providers[name]

    def list_by_type(self, provider_type: ProviderType) -> list[str]:
        """List registered Provider names filtered by capability type.

        Args:
            provider_type: Capability category to filter by.

        Returns:
            List of matching Provider names.
        """
        return [
            name
            for name, p in self._providers.items()
            if p.descriptor.provider_type == provider_type
        ]

    def list_all(self) -> list[str]:
        """List all registered Provider names.

        Returns:
            List of registered Provider names.
        """
        return list(self._providers.keys())

    def resolve_secrets(self, name: str) -> dict[str, str]:
        """Resolve all Secret references for a registered Provider.

        Args:
            name: Registered Provider name.

        Returns:
            Mapping from reference name to resolved Secret value.
        """
        provider = self.get(name)
        return {ref: self._secret_manager.resolve(ref) for ref in provider.descriptor.secret_refs}

    def healthcheck(self, name: str) -> HealthCheckResult:
        """Run a health check for a single Provider.

        Args:
            name: Registered Provider name.

        Returns:
            The Provider's health check result.
        """
        return self.get(name).healthcheck()

    def healthcheck_all(self) -> dict[str, HealthCheckResult]:
        """Run health checks for all registered Providers.

        Returns:
            Mapping from Provider name to health check result.
        """
        return {name: self.get(name).healthcheck() for name in self._providers}

    def call(
        self,
        provider_name: str,
        method: str,
        args: tuple = (),
        kwargs: dict[str, Any] | None = None,
        trace_id: str = "",
    ) -> tuple[Any, CallResult]:
        """Call a Provider method with retry, fallback, audit, and cost tracking.

        Args:
            provider_name: Name of the primary Provider to call.
            method: Method name to invoke (e.g. ``get_bars``).
            args: Positional arguments passed to the method.
            kwargs: Keyword arguments passed to the method.
            trace_id: Optional trace identifier for observability.

        Returns:
            A tuple of (method return value, ``CallResult`` metadata).
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
        """Execute a single Provider call with rate limiting and retry.

        Args:
            name: Provider name to call.
            method: Method name to invoke.
            args: Positional arguments for the method.
            kwargs: Keyword arguments for the method.
            trace_id: Optional trace identifier.
            is_fallback: Whether this Provider is being used as a fallback.

        Returns:
            A tuple of (method return value or ``None``, ``CallResult`` metadata).
        """
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
        """Resolve configured Secret refs and inject them into Providers that opt in.

        Args:
            provider: Provider being registered.
        """
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
    """Map positional arguments to parameter names for audit summaries.

    Args:
        func: Target callable.
        args: Positional arguments passed to ``func``.

    Returns:
        Dictionary mapping parameter names to argument values. Falls back to
        ``argN`` keys when inspection fails.
    """
    try:
        import inspect

        sig = inspect.signature(func)
        params = list(sig.parameters.keys())
        return {params[i]: arg for i, arg in enumerate(args) if i < len(params)}
    except (ValueError, TypeError):
        return {f"arg{i}": arg for i, arg in enumerate(args)}


def _raw_positional_args(args: tuple) -> dict[str, Any]:
    """Map positional arguments to generic ``argN`` keys.

    Args:
        args: Positional arguments.

    Returns:
        Dictionary of the form ``{"arg0": value0, ...}``.
    """
    return {f"arg{i}": arg for i, arg in enumerate(args)}
