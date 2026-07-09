"""Valuation discovery API tests."""

from __future__ import annotations

from dataclasses import dataclass
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from margin.api import dependencies
from margin.api.main import create_app
from margin.settings import get_settings


def test_start_valuation_discovery_refresh_returns_accepted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Test that starting a valuation discovery refresh returns 202 Accepted.

    Args:
        monkeypatch: pytest.MonkeyPatch: .

    Returns:
        None: .
    """
    get_settings.cache_clear()
    valuation_service = _FakeValuationService()
    client = TestClient(create_app(valuation_discovery_service=valuation_service))

    response = client.post(
        "/api/v1/valuation-discovery/refreshes",
        json={
            "scope_version_id": "scope-1",
            "decision_at": "2026-06-22T00:00:00+00:00",
        },
        headers={
            "Idempotency-Key": "valuation-refresh-1",
        },
    )

    assert response.status_code == 202
    assert response.json() == {
        "run_id": "vdr-api-1",
        "status": "accepted",
        "http_status": 202,
    }
    assert valuation_service.wake_calls == [{"max_steps": 1}]


def test_start_refresh_resolves_scope_current_alias_to_active_scope() -> None:
    """Test that scope-current is resolved before the refresh run is created.

    Returns:
        None: .
    """
    valuation_service = _FakeValuationService()
    client = TestClient(
        create_app(
            strategy_service=_FakeStrategyService(),
            valuation_discovery_service=valuation_service,
        )
    )

    response = client.post(
        "/api/v1/valuation-discovery/refreshes",
        json={
            "scope_version_id": "scope-current",
            "decision_at": "2026-07-01T09:00:00+08:00",
        },
        headers={
            "Idempotency-Key": "valuation-refresh-scope-current",
        },
    )

    assert response.status_code == 202
    assert valuation_service.calls[0]["scope_version_id"] == "scope-active"
    assert valuation_service.wake_calls == [{"max_steps": 1}]


def test_valuation_discovery_dependency_maps_provider_config_error_to_503(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Test that provider config errors are mapped to a 503 service error.

    Args:
        monkeypatch: pytest.MonkeyPatch: .

    Returns:
        None: .
    """

    def broken_service() -> object:
        """Raise a LookupError simulating a missing active provider config.

        Returns:
            object: .
        """
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
    """Fake valuation discovery service stub for API tests.."""

    def __init__(self) -> None:
        """Initialize call recording.

        Returns:
            None: .
        """
        self.calls: list[dict[str, object]] = []
        self.wake_calls: list[dict[str, object]] = []

    def start_refresh(self, **kwargs: object) -> _FakeRefreshResponse:
        """Return a fake accepted refresh response.

        Args:
            **kwargs: object: .

        Returns:
            _FakeRefreshResponse: .
        """
        self.calls.append(kwargs)
        return _FakeRefreshResponse(run_id="vdr-api-1")

    def wake_refresh_worker(self, **kwargs: object) -> int:
        """Record a best-effort background wake call.

        Args:
            **kwargs: object: .

        Returns:
            int: .
        """
        self.wake_calls.append(kwargs)
        return 1


class _FakeStrategyService:
    """Fake strategy config service exposing one active scope.."""

    def ensure_current_research_scope(self, owner_id: str) -> SimpleNamespace:
        """Return the reconciled current scope.

        Args:
            owner_id: str: .

        Returns:
            SimpleNamespace: .
        """
        return SimpleNamespace(
            owner_id=owner_id,
            version_id="scope-active",
            lifecycle="active",
        )

    def list_research_scopes(self, owner_id: str) -> list[SimpleNamespace]:
        """Return active scope metadata.

        Args:
            owner_id: str: .

        Returns:
            list[SimpleNamespace]: .
        """
        return [
            SimpleNamespace(
                owner_id=owner_id,
                version_id="scope-active",
                lifecycle="active",
            )
        ]


@dataclass(frozen=True)
class _FakeRefreshResponse:
    """Fake refresh response returned by the valuation discovery stub.."""

    run_id: str
    status: str = "accepted"
    http_status: int = 202
