"""Tests for health endpoints.

Covers liveness, readiness, degraded aggregation, and the guarantee that the
ready endpoint never leaks internal error details in its JSON body.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from margin.api.main import create_app
from margin.strategy.models import ConfigLifecycle, ProviderConfigVersion


def test_health_returns_ok():
    """Test that the health endpoint returns ok.

    Returns:
        Any: .
    """
    app = create_app()
    client = TestClient(app)
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_ready_endpoint_checks_database():
    """Test that the ready endpoint checks the database.

    Returns:
        Any: .
    """
    app = create_app()
    client = TestClient(app)
    response = client.get("/health/ready")
    assert response.status_code in {200, 503}


def test_degraded_endpoint_returns_status():
    """Test that the degraded endpoint returns status.

    Returns:
        Any: .
    """
    app = create_app()
    client = TestClient(app)
    response = client.get("/health/degraded")
    assert response.status_code == 200
    assert "degraded" in response.json()


def test_capabilities_endpoint_reports_feature_status_without_live_providers():
    """Test that capability status is derived from config, not live provider calls.

    Returns:
        Any: .
    """
    app = create_app(strategy_repository=_FakeStrategyRepository(()))
    client = TestClient(app)

    response = client.get("/health/capabilities")

    assert response.status_code == 200
    body = response.json()
    assert body["capabilities"]["api"]["enabled"] is True
    assert body["capabilities"]["valuation_discovery"]["enabled"] is False
    assert (
        "data_source.quant_required_financials"
        in body["capabilities"]["valuation_discovery"]["missing"]
    )


def test_capabilities_endpoint_reports_enabled_features_from_active_configs():
    """Test that active provider config metadata enables feature capability status.

    Returns:
        Any: .
    """
    app = create_app(
        strategy_repository=_FakeStrategyRepository(
            (
                ProviderConfigVersion(
                    version_id="provider-tushare-active",
                    provider_name="tushare",
                    provider_type="market_data",
                    secret_version_id="secret-tushare",
                    lifecycle=ConfigLifecycle.ACTIVE,
                ),
                ProviderConfigVersion(
                    version_id="provider-llm-active",
                    provider_name="llm",
                    provider_type="llm",
                    secret_version_id="secret-llm",
                    lifecycle=ConfigLifecycle.ACTIVE,
                ),
                ProviderConfigVersion(
                    version_id="provider-websearch-active",
                    provider_name="tavily",
                    provider_type="websearch",
                    secret_version_id="secret-tavily",
                    lifecycle=ConfigLifecycle.ACTIVE,
                ),
                ProviderConfigVersion(
                    version_id="provider-embedding-active",
                    provider_name="embedding",
                    provider_type="embedding",
                    secret_version_id="secret-embedding",
                    lifecycle=ConfigLifecycle.ACTIVE,
                ),
            )
        )
    )
    client = TestClient(app)

    response = client.get("/health/capabilities")

    assert response.status_code == 200
    capabilities = response.json()["capabilities"]
    assert capabilities["valuation_discovery"]["enabled"] is True
    assert capabilities["agent_runtime"]["enabled"] is True


def test_ready_endpoint_returns_valid_sanitized_json_on_database_failure(monkeypatch):
    """Test that the ready endpoint returns sanitized JSON on database failure.

    Args:
        monkeypatch: Any: .

    Returns:
        Any: .
    """

    def fail_engine(*args, **kwargs):
        """Raise a runtime error simulating database unavailability.

        Args:
            *args: Any: .
            **kwargs: Any: .

        Returns:
            Any: .
        """
        del args, kwargs
        raise RuntimeError('database "secret" unavailable')

    monkeypatch.setattr(
        "margin.api.routes.health.create_database_engine",
        fail_engine,
    )
    client = TestClient(create_app())

    response = client.get("/health/ready")

    assert response.status_code == 503
    assert response.json()["status"] == "not_ready"
    assert "checks" in response.json()
    # Internal error text must not appear in the externally visible response.
    assert "secret" not in response.text


class _FakeStrategyRepository:
    """Fake provider config repository for health capability tests.."""

    def __init__(self, configs: tuple[ProviderConfigVersion, ...]) -> None:
        """Helper _init__.

        Args:
            configs: tuple[ProviderConfigVersion, ...]: .

        Returns:
            None: .
        """
        self._configs = configs

    def list_active_provider_configs(
        self,
        owner_id: str,
    ) -> tuple[ProviderConfigVersion, ...]:
        """Process list_active_provider_configs.

        Args:
            owner_id: str: .

        Returns:
            tuple[ProviderConfigVersion, ...]: .
        """
        del owner_id
        return self._configs
