"""Valuation discovery API tests."""

from __future__ import annotations

from dataclasses import dataclass

import pytest
from fastapi.testclient import TestClient

from margin.api import dependencies
from margin.api.main import create_app
from margin.settings import get_settings


def test_start_valuation_discovery_refresh_returns_accepted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Test that starting a valuation discovery refresh returns 202 Accepted."""
    monkeypatch.setenv("MARGIN_ADMIN_API_TOKEN", "admin-test-token")
    monkeypatch.setenv("MARGIN_CSRF_TOKEN", "valid")
    get_settings.cache_clear()
    client = TestClient(create_app(valuation_discovery_service=_FakeValuationService()))

    response = client.post(
        "/api/v1/valuation-discovery/refreshes",
        json={
            "scope_version_id": "scope-1",
            "decision_at": "2026-06-22T00:00:00+00:00",
        },
        headers={
            "Authorization": "Bearer admin-test-token",
            "X-CSRF-Token": "valid",
            "Idempotency-Key": "valuation-refresh-1",
        },
    )

    assert response.status_code == 202
    assert response.json() == {
        "run_id": "vdr-api-1",
        "status": "accepted",
        "http_status": 202,
    }


def test_valuation_discovery_dependency_maps_provider_config_error_to_503(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Test that provider config errors are mapped to a 503 service error."""

    def broken_service() -> object:
        """Raise a LookupError simulating a missing active provider config."""
        raise LookupError("active provider config not found: tavily")

    monkeypatch.setattr(
        dependencies,
        "get_valuation_discovery_service",
        broken_service,
    )

    with pytest.raises(Exception) as exc_info:
        dependencies.get_valuation_discovery_service_for_api()

    assert getattr(exc_info.value, "status_code", None) == 503
    assert exc_info.value.detail["code"] == "service_not_configured"


class _FakeValuationService:
    """Fake valuation discovery service stub for API tests."""

    def start_refresh(self, **_: object) -> _FakeRefreshResponse:
        """Return a fake accepted refresh response."""
        return _FakeRefreshResponse(run_id="vdr-api-1")


@dataclass(frozen=True)
class _FakeRefreshResponse:
    """Fake refresh response returned by the valuation discovery stub."""

    run_id: str
    status: str = "accepted"
    http_status: int = 202
