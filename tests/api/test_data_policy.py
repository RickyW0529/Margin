"""Data policy API tests for frontend configuration."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from margin.api.dependencies import get_data_policy_service
from margin.api.main import create_app
from margin.data.policy import (
    DataAcquisitionPolicyService,
    MemoryDataAcquisitionPolicyRepository,
)
from margin.settings import get_settings


@pytest.fixture
def data_policy_client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    """Return an authenticated API client with an isolated policy repository.

    Args:
        monkeypatch: Pytest fixture for patching environment variables.

    Returns:
        A ``TestClient`` wired to an in-memory data policy service.
    """
    monkeypatch.setenv("MARGIN_ADMIN_API_TOKEN", "admin-test-token")
    monkeypatch.setenv("MARGIN_CSRF_TOKEN", "valid")
    get_settings.cache_clear()
    service = DataAcquisitionPolicyService(
        MemoryDataAcquisitionPolicyRepository()
    )
    app = create_app()
    app.dependency_overrides[get_data_policy_service] = lambda: service
    return TestClient(app)


def _headers(key: str) -> dict[str, str]:
    """Build authenticated request headers with the given idempotency key."""
    return {
        "Authorization": "Bearer admin-test-token",
        "X-CSRF-Token": "valid",
        "Idempotency-Key": key,
    }


def test_frontend_can_create_activate_and_list_rolling_policy(
    data_policy_client: TestClient,
) -> None:
    """Test that the UI contract exposes versioned policy mutations and active state."""
    created = data_policy_client.post(
        "/api/v1/data-policies",
        json={
            "rolling_window_months": 24,
            "revision_lookback_days": 30,
            "financial_comparison_years": 1,
        },
        headers=_headers("create-policy-24"),
    )
    assert created.status_code == 201
    version_id = created.json()["version_id"]

    activated = data_policy_client.post(
        f"/api/v1/data-policies/{version_id}/activate",
        headers=_headers("activate-policy-24"),
    )
    assert activated.status_code == 200
    assert activated.json()["lifecycle"] == "active"

    listed = data_policy_client.get("/api/v1/data-policies")
    assert listed.status_code == 200
    assert listed.json()["active_version_id"] == version_id
    assert listed.json()["versions"][0]["rolling_window_months"] == 24
    assert listed.json()["versions"][0]["window_start"]


def test_frontend_policy_rejects_more_than_60_months(
    data_policy_client: TestClient,
) -> None:
    """Test that invalid storage windows fail before persistence."""
    response = data_policy_client.post(
        "/api/v1/data-policies",
        json={"rolling_window_months": 61},
        headers=_headers("create-policy-61"),
    )

    assert response.status_code == 422
