"""Integration tests for ``ProviderRegistry``: registration, calls, fallback, secrets, and costs."""

from datetime import datetime

import pytest

from margin.core.audit import AuditLogger
from margin.core.provider import (
    BaseProvider,
    HealthCheckResult,
    ProviderDescriptor,
    ProviderStatus,
    ProviderType,
)
from margin.core.registry import (
    ProviderAlreadyRegisteredError,
    ProviderNotFoundError,
    ProviderRegistry,
)
from margin.core.resilience import ProviderError, RetryConfig
from margin.core.secret import SecretManager
from margin.data.providers import TushareProvider


class MockProvider(BaseProvider):
    """A configurable mock provider used to exercise ``ProviderRegistry`` behavior.

    Attributes:
        _descriptor: The descriptor returned by the ``descriptor`` property.
        _health_status: The status reported by ``healthcheck``.
        call_log: Records of method calls made during tests.
    """

    def __init__(
        self,
        name: str = "mock",
        version: str = "1.0.0",
        provider_type: ProviderType = ProviderType.MARKET_DATA,
        capabilities: list[str] | None = None,
        secret_refs: list[str] | None = None,
        health_status: ProviderStatus = ProviderStatus.HEALTHY,
    ) -> None:
        """Create a mock provider with a configurable descriptor and health status.

        Args:
            name: Provider name exposed in the descriptor.
            version: Provider version exposed in the descriptor.
            provider_type: Category of the provider.
            capabilities: List of supported method names.
            secret_refs: List of secret references required by the provider.
            health_status: Status returned from ``healthcheck``.
        """
        self._descriptor = ProviderDescriptor(
            name=name,
            version=version,
            provider_type=provider_type,
            capabilities=capabilities or [],
            secret_refs=secret_refs or [],
        )
        self._health_status = health_status
        self.call_log: list[tuple[str, tuple, dict]] = []

    @property
    def descriptor(self) -> ProviderDescriptor:
        """Returns:
            The configured provider descriptor.
        """
        return self._descriptor

    def healthcheck(self) -> HealthCheckResult:
        """Returns:
            A health result using the configured status.
        """
        return HealthCheckResult(
            provider_name=self._descriptor.name,
            status=self._health_status,
            checked_at=datetime.now(),
        )

    def get_bars(self, symbols, start, end, frequency="1d"):
        self.call_log.append(("get_bars", (symbols, start, end), {"frequency": frequency}))
        return [{"symbol": s, "close": 100.0} for s in symbols]

    def get_financials(self, symbols, start, end):
        self.call_log.append(("get_financials", (symbols, start, end), {}))
        return [{"symbol": s, "revenue": 1e8} for s in symbols]

    def failing_method(self, *args, **kwargs):
        self.call_log.append(("failing_method", args, kwargs))
        raise ProviderError("simulated failure")

    def non_retry_failure(self):
        self.call_log.append(("non_retry_failure", (), {}))
        raise ValueError("bad input")


@pytest.fixture
def registry(tmp_path, monkeypatch):
    """Build a ``ProviderRegistry`` wired to a temporary secret manager and audit logger.

    Args:
        tmp_path: Pytest fixture providing a temporary directory.
        monkeypatch: Pytest fixture for patching the environment.

    Returns:
        A configured ``ProviderRegistry`` instance.
    """
    monkeypatch.setenv("MARGIN_SECRET_MOCK_TOKEN", "test_secret")
    sm = SecretManager(secrets_dir=tmp_path / "secrets")
    al = AuditLogger(log_path=tmp_path / "audit.jsonl")
    return ProviderRegistry(secret_manager=sm, audit_logger=al)


class TestRegistration:
    """Tests covering provider registration, retrieval, and listing."""

    def test_register_and_get(self, registry):
        """A registered provider can be retrieved by name."""
        p = MockProvider(name="akshare")
        registry.register(p)
        assert registry.get("akshare") is p

    def test_register_duplicate_raises(self, registry):
        """Registering the same name twice without override raises an error."""
        registry.register(MockProvider(name="dup"))
        with pytest.raises(ProviderAlreadyRegisteredError):
            registry.register(MockProvider(name="dup"))

    def test_register_override(self, registry):
        """``allow_override=True`` replaces an existing provider registration."""
        p1 = MockProvider(name="p", version="1.0")
        registry.register(p1)
        p2 = MockProvider(name="p", version="2.0")
        registry.register(p2, allow_override=True)
        assert registry.get("p").descriptor.version == "2.0"

    def test_get_unregistered_raises(self, registry):
        """Retrieving an unregistered provider raises ``ProviderNotFoundError``."""
        with pytest.raises(ProviderNotFoundError):
            registry.get("nonexistent")

    def test_list_by_type(self, registry):
        """``list_by_type`` filters registered providers by their type."""
        registry.register(MockProvider(name="akshare", provider_type=ProviderType.MARKET_DATA))
        registry.register(MockProvider(name="tushare", provider_type=ProviderType.MARKET_DATA))
        registry.register(MockProvider(name="openai", provider_type=ProviderType.LLM))

        market_data = registry.list_by_type(ProviderType.MARKET_DATA)
        assert set(market_data) == {"akshare", "tushare"}

        llms = registry.list_by_type(ProviderType.LLM)
        assert llms == ["openai"]

    def test_list_all(self, registry):
        """``list_all`` returns the names of every registered provider."""
        registry.register(MockProvider(name="a"))
        registry.register(MockProvider(name="b"))
        assert set(registry.list_all()) == {"a", "b"}


class TestHealthCheck:
    """Tests covering registry-level health checks."""

    def test_single_healthcheck(self, registry):
        """``healthcheck`` for a single provider returns that provider's status."""
        registry.register(MockProvider(name="p", health_status=ProviderStatus.HEALTHY))
        result = registry.healthcheck("p")
        assert result.status == ProviderStatus.HEALTHY

    def test_healthcheck_all(self, registry):
        """``healthcheck_all`` returns statuses for all registered providers."""
        registry.register(MockProvider(name="a", health_status=ProviderStatus.HEALTHY))
        registry.register(MockProvider(name="b", health_status=ProviderStatus.DEGRADED))
        results = registry.healthcheck_all()
        assert results["a"].status == ProviderStatus.HEALTHY
        assert results["b"].status == ProviderStatus.DEGRADED


class TestCall:
    """Tests covering ``registry.call``, retries, fallback, and audit logging."""

    def test_call_success(self, registry):
        """A successful call returns data and a populated ``CallResult``."""
        provider = MockProvider(name="akshare")
        registry.register(provider)
        symbols = ["000001.SZ", "600000.SH"]
        start = datetime(2026, 6, 1)
        end = datetime(2026, 6, 18)

        data, result = registry.call(
            "akshare", "get_bars",
            args=(symbols, start, end),
            kwargs={"frequency": "1d"},
            trace_id="trace_001",
        )

        assert result.success is True
        assert result.provider_name == "akshare"
        assert result.provider_version == "1.0.0"
        assert len(data) == 2
        assert result.response_hash is not None
        assert result.response_hash.startswith("sha256:")
        assert result.latency_ms is not None
        assert result.attempt_count == 1
        assert result.from_fallback is False

    def test_call_logs_audit(self, registry, tmp_path):
        """``registry.call`` writes an audit record for the invocation."""
        registry.register(MockProvider(name="akshare"))
        registry.call("akshare", "get_bars",
                       args=(["000001.SZ"], datetime(2026, 6, 1), datetime(2026, 6, 18)))

        records = registry._audit_logger.read_all()
        assert len(records) == 1
        assert records[0].provider_name == "akshare"
        assert records[0].method == "get_bars"
        assert records[0].success is True

    def test_call_with_retry(self, registry):
        """Transient ``ProviderError`` failures are retried up to ``max_retries``."""
        provider = MockProvider(name="flaky")
        registry.register(
            provider,
            retry_config=RetryConfig(max_retries=3, base_delay=0.001),
        )

        call_count = 0
        original = provider.get_bars
        def flaky_get_bars(symbols, start, end, frequency="1d"):
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise ProviderError("transient")
            return original(symbols, start, end, frequency)
        provider.get_bars = flaky_get_bars

        data, result = registry.call(
            "flaky", "get_bars",
            args=(["000001.SZ"], datetime(2026, 6, 1), datetime(2026, 6, 18)),
        )

        assert result.success is True
        assert result.attempt_count == 3

    def test_call_failure_recorded(self, registry):
        """A failing call returns a failure result and writes an audit record."""
        provider = MockProvider(name="bad")
        registry.register(
            provider,
            retry_config=RetryConfig(max_retries=2, base_delay=0.001),
        )

        data, result = registry.call("bad", "failing_method")

        assert result.success is False
        assert "simulated failure" in result.error
        assert result.attempt_count == 2
        assert data is None

        records = registry._audit_logger.read_all()
        assert records[0].success is False
        assert records[0].error is not None

    def test_call_method_not_found(self, registry):
        """Calling a missing method records a failure without invoking the provider."""
        registry.register(MockProvider(name="p"))
        data, result = registry.call("p", "nonexistent_method")
        assert result.success is False
        assert "not found" in result.error

        records = registry._audit_logger.read_all()
        assert len(records) == 1
        assert records[0].success is False
        assert "not found" in records[0].error

    def test_call_non_retry_exception_is_audited_before_raise(self, registry):
        """Non-retryable exceptions are audited and then wrapped in ``ProviderError``."""
        registry.register(MockProvider(name="p"))

        with pytest.raises(ProviderError, match="ValueError: bad input"):
            registry.call("p", "non_retry_failure")

        records = registry._audit_logger.read_all()
        assert len(records) == 1
        assert records[0].success is False
        assert "ValueError: bad input" in records[0].error

    def test_call_with_fallback(self, registry):
        """When the primary provider fails, the configured fallback is used."""
        primary = MockProvider(name="primary")
        secondary = MockProvider(name="secondary")

        def failing_get_bars(symbols, start, end, frequency="1d"):
            raise ProviderError("primary down")

        primary.get_bars = failing_get_bars

        registry.register(
            primary,
            retry_config=RetryConfig(max_retries=2, base_delay=0.001),
        )
        registry.register(secondary)
        registry._fallbacks["primary"] = ["secondary"]

        def secondary_method(symbols, start, end, frequency="1d"):
            return [{"symbol": s, "close": 200.0} for s in symbols]
        secondary.get_bars = secondary_method

        data, result = registry.call(
            "primary", "get_bars",
            args=(["000001.SZ"], datetime(2026, 6, 1), datetime(2026, 6, 18)),
        )

        assert result.success is True
        assert result.provider_name == "secondary"
        assert result.from_fallback is True

        records = registry._audit_logger.read_all()
        assert len(records) == 2
        assert records[0].provider_name == "primary"
        assert records[0].success is False
        assert records[1].provider_name == "secondary"
        assert records[1].success is True
        assert records[1].from_fallback is True


class TestSecretResolution:
    """Tests covering secret resolution via the registry."""

    def test_resolve_secrets(self, registry, monkeypatch):
        """``resolve_secrets`` maps declared secret refs to their resolved values."""
        monkeypatch.setenv("MARGIN_SECRET_TUSHARE_TOKEN", "real_token")
        registry.register(MockProvider(name="tushare", secret_refs=["tushare_token"]))
        secrets = registry.resolve_secrets("tushare")
        assert secrets == {"tushare_token": "real_token"}

    def test_register_injects_secret_refs_into_configurable_provider(self, registry, monkeypatch):
        """Registration injects resolved secrets into providers that declare ``secret_refs``."""
        monkeypatch.setenv("MARGIN_SECRET_TUSHARE_TOKEN", "real_token")
        provider = TushareProvider()

        registry.register(provider)

        assert provider._token == "real_token"


class TestCostTracking:
    """Tests covering per-call cost tracking in the registry."""

    def test_cost_recorded(self, registry):
        """A successful call records the configured cost in the result and audit log."""
        registry.register(MockProvider(name="paid"), cost_per_call=0.05)
        _, result = registry.call(
            "paid", "get_bars",
            args=(["000001.SZ"], datetime(2026, 6, 1), datetime(2026, 6, 18)),
        )
        assert result.cost == 0.05

        records = registry._audit_logger.read_all()
        assert records[0].cost == 0.05

    def test_cost_multiplied_by_attempts(self, registry):
        """Total cost is multiplied by the number of retry attempts consumed."""
        provider = MockProvider(name="flaky_paid")
        registry.register(
            provider,
            retry_config=RetryConfig(max_retries=3, base_delay=0.001),
            cost_per_call=0.01,
        )

        call_count = 0
        original = provider.get_bars
        def flaky(symbols, start, end, frequency="1d"):
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise ProviderError("fail")
            return original(symbols, start, end, frequency)
        provider.get_bars = flaky

        _, result = registry.call(
            "flaky_paid", "get_bars",
            args=(["000001.SZ"], datetime(2026, 6, 1), datetime(2026, 6, 18)),
        )
        assert result.attempt_count == 3
        assert result.cost == 0.03
