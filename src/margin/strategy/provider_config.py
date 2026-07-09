"""Provider configuration health checks and SSRF protection."""

from __future__ import annotations

import time
from collections.abc import Callable, Mapping
from datetime import datetime
from typing import Literal
from urllib.parse import urlparse

from pydantic import BaseModel

from margin.core.secret_store import SecretMetadata, SecretRedactor, SecretStore
from margin.core.ssrf import SSRFError, assert_public_http_url
from margin.news.models import utc_now
from margin.strategy.models import ProviderConfigVersion
from margin.strategy.provider_router import detect_provider_from_url, provider_category_for_config


class ProviderSSRFError(SSRFError):
    """Raised when a provider base URL violates SSRF guardrails."""


class ProviderHealth(BaseModel):
    """Safe provider health result for API responses and audits.."""

    provider_name: str
    provider_config_version_id: str
    status: Literal["ok", "failed", "not_configured"]
    checked_at: datetime
    latency_ms: int | None = None
    error_code: str | None = None
    redacted_error: str | None = None
    secret_metadata: SecretMetadata | None = None


HealthCheckCallable = Callable[[ProviderConfigVersion, str], None]


class ProviderConfigHealthService:
    """Run read-only provider config health checks without leaking secrets.."""

    def __init__(
        self,
        repository: object,
        secret_store: SecretStore,
        *,
        health_adapters: Mapping[str, HealthCheckCallable] | None = None,
        host_allowlists: Mapping[str, set[str]] | None = None,
        allow_local_development: bool = False,
        resolve_dns: bool = False,
    ) -> None:
        """Initialize the instance.

        Args:
            repository: object: .
            secret_store: SecretStore: .
            health_adapters: Mapping[str, HealthCheckCallable] | None: .
            host_allowlists: Mapping[str, set[str]] | None: .
            allow_local_development: bool: .
            resolve_dns: bool: .

        Returns:
            None: .
        """
        self._repository = repository
        self._secret_store = secret_store
        self._health_adapters = {
            key.lower(): value for key, value in (health_adapters or {}).items()
        }
        self._host_allowlists = {
            key.lower(): {host.lower() for host in hosts}
            for key, hosts in (host_allowlists or {}).items()
        }
        self._allow_local_development = allow_local_development
        self._resolve_dns = resolve_dns

    def test_connection(self, provider_config_version_id: str) -> ProviderHealth:
        """Test a frozen provider config version using its stored secret version.

        Args:
            provider_config_version_id: str: .

        Returns:
            ProviderHealth: .
        """
        started = time.perf_counter()
        checked_at = utc_now()
        config = self._repository.get_provider_config(provider_config_version_id)
        if config is None:
            raise KeyError(f"provider config '{provider_config_version_id}' not found")
        adapter_name = self._adapter_name_for_config(config)

        if config.base_url:
            self.validate_base_url(
                config.base_url,
                provider_name=adapter_name,
                allow_custom_base_url=bool(
                    config.non_sensitive_config.get(
                        "allow_custom_base_url",
                        False,
                    )
                ),
            )

        if not config.enabled:
            return self._result(
                config,
                checked_at=checked_at,
                started=started,
                status="not_configured",
                error_code="provider_disabled",
                redacted_error="provider config is disabled",
            )

        secret_required = bool(config.non_sensitive_config.get("secret_required", True))
        if secret_required and not config.secret_version_id:
            return self._result(
                config,
                checked_at=checked_at,
                started=started,
                status="not_configured",
                error_code="secret_not_configured",
                redacted_error="provider secret is not configured",
            )

        secret_metadata = None
        secret_value = ""
        if config.secret_version_id:
            secret_metadata = self._secret_store.metadata(config.secret_version_id)
            secret_value = self._secret_store.resolve(secret_metadata.ref).get_secret_value()
        redactor = SecretRedactor(values=(secret_value,))
        adapter = self._health_adapters.get(adapter_name)
        if adapter is None:
            return self._result(
                config,
                checked_at=checked_at,
                started=started,
                status="failed",
                error_code="health_adapter_missing",
                redacted_error=(
                    f"health adapter is not configured for provider {adapter_name}"
                ),
                secret_metadata=secret_metadata,
            )

        try:
            adapter(config, secret_value)
        except Exception as exc:  # noqa: BLE001 - redact before surfacing adapter errors.
            return self._result(
                config,
                checked_at=checked_at,
                started=started,
                status="failed",
                error_code=exc.__class__.__name__,
                redacted_error=redactor.redact(str(exc)),
                secret_metadata=secret_metadata,
            )

        return self._result(
            config,
            checked_at=checked_at,
            started=started,
            status="ok",
            secret_metadata=secret_metadata,
        )

    def _adapter_name_for_config(self, config: ProviderConfigVersion) -> str:
        """Return the concrete health adapter key for a provider config."""
        provider_name = config.provider_name.strip().lower()
        if provider_name in self._health_adapters:
            return provider_name
        detected_provider = str(
            config.non_sensitive_config.get("detected_provider") or ""
        ).strip().lower()
        if detected_provider in self._health_adapters:
            return detected_provider
        category = provider_category_for_config(
            config.provider_type,
            config.provider_name,
            config.non_sensitive_config,
        )
        detected = detect_provider_from_url(
            category,
            config.base_url,
            fallback_provider_name=config.provider_name,
        )
        if detected.provider_id in self._health_adapters:
            return detected.provider_id
        return provider_name

    def validate_base_url(
        self,
        base_url: str,
        *,
        provider_name: str | None = None,
        allow_custom_base_url: bool = False,
    ) -> None:
        """Validate a provider URL against SSRF guardrails.

        Args:
            base_url: Provider base URL.
            provider_name: Optional adapter name for host allowlists.
            allow_custom_base_url: When True, skip host allowlist enforcement.

        Returns:
            None
        """
        try:
            assert_public_http_url(
                base_url,
                allow_local=self._allow_local_development,
                resolve_dns=self._resolve_dns,
            )
        except SSRFError as exc:
            message = str(exc).replace("url ", "provider base_url ", 1)
            raise ProviderSSRFError(message) from exc

        parsed = urlparse(base_url)
        host = (parsed.hostname or "").strip("[]").lower()
        if provider_name is not None:
            allowed_hosts = self._host_allowlists.get(provider_name.lower())
            if allowed_hosts and host not in allowed_hosts and not allow_custom_base_url:
                raise ProviderSSRFError(
                    f"provider base_url host is outside the {provider_name} allowlist"
                )

    def _result(
        self,
        config: ProviderConfigVersion,
        *,
        checked_at: datetime,
        started: float,
        status: Literal["ok", "failed", "not_configured"],
        error_code: str | None = None,
        redacted_error: str | None = None,
        secret_metadata: SecretMetadata | None = None,
    ) -> ProviderHealth:
        """Build a health result with measured latency."""
        latency_ms = int((time.perf_counter() - started) * 1000)
        return ProviderHealth(
            provider_name=config.provider_name,
            provider_config_version_id=config.version_id,
            status=status,
            checked_at=checked_at,
            latency_ms=latency_ms,
            error_code=error_code,
            redacted_error=redacted_error,
            secret_metadata=secret_metadata,
        )
