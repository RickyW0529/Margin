"""Tests for strategy API routes."""

from __future__ import annotations

from fastapi.testclient import TestClient

from margin.api.main import create_app
from margin.strategy.service import StrategyService


def _client() -> TestClient:
    """Build a test client wired to an in-memory strategy service."""
    app = create_app(strategy_service=StrategyService())
    return TestClient(app)


def _idempotency_headers(key: str) -> dict[str, str]:
    """Return headers required by mutating strategy endpoints."""
    return {"Idempotency-Key": key}


def test_create_strategy_endpoint():
    """Test that the create strategy endpoint returns the expected strategy."""
    client = _client()
    response = client.post(
        "/strategies",
        headers=_idempotency_headers("strategy-create"),
        json={"owner_id": "user_1", "template": "value_quality"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["name"] == "价值质量"
    assert len(body["versions"]) == 1


def test_list_templates_endpoint():
    """Test that the list templates endpoint returns all available templates."""
    client = _client()
    response = client.get("/strategies/templates")
    assert response.status_code == 200
    assert len(response.json()) == 6


def test_strategy_mutations_require_idempotency_key():
    """Test that strategy mutations reject missing idempotency keys."""
    client = _client()

    response = client.post(
        "/strategies",
        json={"owner_id": "user_1", "template": "value_quality"},
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "Idempotency-Key header is required"


def test_get_strategy_endpoint():
    """Test that the get strategy endpoint returns the requested strategy."""
    client = _client()
    create_resp = client.post(
        "/strategies",
        headers=_idempotency_headers("strategy-get-create"),
        json={"owner_id": "user_1", "template": "value_quality"},
    )
    strategy_id = create_resp.json()["strategy_id"]
    response = client.get(f"/strategies/{strategy_id}")
    assert response.status_code == 200
    assert response.json()["strategy_id"] == strategy_id


def test_update_strategy_endpoint():
    """Test that the update strategy endpoint creates a new version."""
    client = _client()
    create_resp = client.post(
        "/strategies",
        headers=_idempotency_headers("strategy-update-create"),
        json={"owner_id": "user_1", "template": "value_quality"},
    )
    strategy_id = create_resp.json()["strategy_id"]
    response = client.put(
        f"/strategies/{strategy_id}",
        headers=_idempotency_headers("strategy-update"),
        json={"config_delta": {"universe": ["000002.SZ"]}},
    )
    assert response.status_code == 200
    assert len(response.json()["versions"]) == 2


def test_activate_version_endpoint():
    """Test that the activate version endpoint sets the active version."""
    client = _client()
    create_resp = client.post(
        "/strategies",
        headers=_idempotency_headers("strategy-activate-create"),
        json={"owner_id": "user_1", "template": "value_quality"},
    )
    strategy_id = create_resp.json()["strategy_id"]
    version_id = create_resp.json()["versions"][0]["version_id"]
    client.post(
        f"/strategies/{strategy_id}/versions/{version_id}/validate",
        headers=_idempotency_headers("strategy-validate"),
    )
    client.post(
        f"/strategies/{strategy_id}/versions/{version_id}/backtest",
        headers=_idempotency_headers("strategy-backtest"),
    )
    client.post(
        f"/strategies/{strategy_id}/versions/{version_id}/paper-trade",
        headers=_idempotency_headers("strategy-paper"),
    )
    response = client.post(
        f"/strategies/{strategy_id}/versions/{version_id}/activate",
        headers=_idempotency_headers("strategy-activate"),
    )
    assert response.status_code == 200
    assert response.json()["active_version_id"] == version_id


def test_get_prompt_endpoint():
    """Test that the get prompt endpoint returns the version prompt."""
    client = _client()
    create_resp = client.post(
        "/strategies",
        headers=_idempotency_headers("strategy-prompt-create"),
        json={"owner_id": "user_1", "template": "value_quality"},
    )
    strategy_id = create_resp.json()["strategy_id"]
    version_id = create_resp.json()["versions"][0]["version_id"]
    response = client.get(f"/strategies/{strategy_id}/versions/{version_id}/prompt")
    assert response.status_code == 200
    assert "prompt" in response.json()
