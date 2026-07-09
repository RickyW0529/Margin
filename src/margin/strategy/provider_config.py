"""Provider configuration health checks and SSRF protection."""

from __future__ import annotations

import ipaddress
import socket
import time
from collections.abc import Callable, Mapping
from datetime import datetime
from typing import Literal
from urllib.parse import urlparse

from pydantic import BaseModel

from margin.core.secret_store import SecretMetadata, SecretRedactor, SecretStore
from margin.news.models import utc_now
from margin.strategy.models import ProviderConfigVersion


class ProviderSSRFError(ValueError):
    """Raised when a provider base URL violates SSRF guardrails.."""


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

        if config.base_url:
            self.validate_base_url(
                config.base_url,
                provider_name=config.provider_name,
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
        adapter = self._health_adapters.get(config.provider_name.lower())
        if adapter is None:
            return self._result(
                config,
                checked_at=checked_at,
                started=started,
                status="failed",
                error_code="health_adapter_missing",
                redacted_error=(
                    f"health adapter is not configured for provider {config.provider_name}"
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

    def validate_base_url(
        self,
        base_url: str,
        *,
        provider_name: str | None = None,
        allow_custom_base_url: bool = False,
    ) -> None:
        """Validate a provider URL against SSRF guardrails.

        Args:
            base_url: str: .
            provider_name: str | None: .
            allow_custom_base_url: bool: .

        Returns:
            None: .
        """
        parsed = urlparse(base_url)
        if parsed.scheme not in {"http", "https"}:
            raise ProviderSSRFError("provider base_url must be http or https")
        if parsed.scheme == "http" and not self._allow_local_development:
            raise ProviderSSRFError("provider base_url must use https")
        if not parsed.hostname:
            raise ProviderSSRFError("provider base_url must include a hostname")

        host = parsed.hostname.strip("[]").lower()
        if host == "localhost":
            if self._allow_local_development:
                return
            raise ProviderSSRFError("provider base_url cannot target localhost")

        addresses = self._parse_or_resolve_host(host)
        for address in addresses:
            if _is_forbidden_ip(address):
                if self._allow_local_development and address.is_loopback:
                    continue
                raise ProviderSSRFError(f"provider base_url targets forbidden network: {address}")

        if provider_name is not None:
            allowed_hosts = self._host_allowlists.get(provider_name.lower())
            if allowed_hosts and host not in allowed_hosts and not allow_custom_base_url:
                raise ProviderSSRFError(
                    f"provider base_url host is outside the {provider_name} allowlist"
                )

    def _parse_or_resolve_host(
        self,
        host: str,
    ) -> tuple[ipaddress.IPv4Address | ipaddress.IPv6Address, ...]:
        """parse or resolve host.

        Args:
            host: str: .

        Returns:
            tuple[ipaddress.IPv4Address | ipaddress.IPv6Address, ...]: .
        """
        try:
            return (ipaddress.ip_address(host),)
        except ValueError:
            if not self._resolve_dns:
                return ()

        resolved: set[ipaddress.IPv4Address | ipaddress.IPv6Address] = set()
        try:
            infos = socket.getaddrinfo(host, None, type=socket.SOCK_STREAM)
        except socket.gaierror as exc:
            raise ProviderSSRFError(f"provider base_url host cannot resolve: {host}") from exc
        for info in infos:
            resolved.add(ipaddress.ip_address(info[4][0]))
        return tuple(sorted(resolved, key=str))

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
        """result.

        Args:
            config: ProviderConfigVersion: .
            checked_at: datetime: .
            started: float: .
            status: Literal['ok', 'failed', 'not_configured']: .
            error_code: str | None: .
            redacted_error: str | None: .
            secret_metadata: SecretMetadata | None: .

        Returns:
            ProviderHealth: .
        """
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


def _is_forbidden_ip(
    address: ipaddress.IPv4Address | ipaddress.IPv6Address,
) -> bool:
    """is forbidden ip.

    Args:
        address: ipaddress.IPv4Address | ipaddress.IPv6Address: .

    Returns:
        bool: .
    """
    return (
        address.is_loopback
        or address.is_link_local
        or address.is_private
        or address.is_multicast
        or address.is_reserved
        or address.is_unspecified
    )
