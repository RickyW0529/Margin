"""Tests for strategy API routes."""

from __future__ import annotations

from fastapi.testclient import TestClient

from margin.api.main import create_app
from margin.platform_runtime.repository import MemoryIdempotencyStore
from margin.strategy.service import StrategyService


def _client() -> TestClient:
    """Build a test client wired to an in-memory strategy service.

    Returns:
        TestClient: .
    """
    app = create_app(
        strategy_service=StrategyService(),
        idempotency_store=MemoryIdempotencyStore(),
    )
    return TestClient(app)


def _idempotency_headers(key: str) -> dict[str, str]:
    """Return headers required by mutating strategy endpoints.

    Args:
        key: str: .

    Returns:
        dict[str, str]: .
    """
    return {"Idempotency-Key": key}


def test_create_strategy_endpoint():
    """Test that the create strategy endpoint returns the expected strategy.

    Returns:
        Any: .
    """
    client = _client()
    response = client.post(
        "/api/v1/strategies",
        headers=_idempotency_headers("strategy-create"),
        json={"owner_id": "user_1", "template": "value_quality"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["name"] == "价值质量"
    assert len(body["versions"]) == 1


def test_list_templates_endpoint():
    """Test that the list templates endpoint returns all available templates.

    Returns:
        Any: .
    """
    client = _client()
    response = client.get("/api/v1/strategies/templates")
    assert response.status_code == 200
    assert len(response.json()) == 6


def test_create_strategy_replays_idempotency_key():
    """Identical create requests must not mint a second strategy profile."""
    client = _client()
    headers = _idempotency_headers("strategy-create-once")
    body = {"owner_id": "user_1", "template": "value_quality", "name": "once"}

    first = client.post("/api/v1/strategies", headers=headers, json=body)
    second = client.post("/api/v1/strategies", headers=headers, json=body)

    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json()["strategy_id"] == second.json()["strategy_id"]
    listed = client.get("/api/v1/strategies", params={"owner_id": "user_1"})
    assert len(listed.json()) == 1


def test_strategy_mutations_require_idempotency_key():
    """Test that strategy mutations reject missing idempotency keys.

    Returns:
        Any: .
    """
    client = _client()

    response = client.post(
        "/api/v1/strategies",
        json={"owner_id": "user_1", "template": "value_quality"},
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "Idempotency-Key header is required"


def test_get_strategy_endpoint():
    """Test that the get strategy endpoint returns the requested strategy.

    Returns:
        Any: .
    """
    client = _client()
    create_resp = client.post(
        "/api/v1/strategies",
        headers=_idempotency_headers("strategy-get-create"),
        json={"owner_id": "user_1", "template": "value_quality"},
    )
    strategy_id = create_resp.json()["strategy_id"]
    response = client.get(f"/api/v1/strategies/{strategy_id}")
    assert response.status_code == 200
    assert response.json()["strategy_id"] == strategy_id


def test_update_strategy_endpoint():
    """Test that the update strategy endpoint creates a new version.

    Returns:
        Any: .
    """
    client = _client()
    create_resp = client.post(
        "/api/v1/strategies",
        headers=_idempotency_headers("strategy-update-create"),
        json={"owner_id": "user_1", "template": "value_quality"},
    )
    strategy_id = create_resp.json()["strategy_id"]
    response = client.put(
        f"/api/v1/strategies/{strategy_id}",
        headers=_idempotency_headers("strategy-update"),
        json={"config_delta": {"universe": ["000002.SZ"]}},
    )
    assert response.status_code == 200
    assert len(response.json()["versions"]) == 2


def test_activate_version_endpoint():
    """Test that the activate version endpoint sets the active version.

    Returns:
        Any: .
    """
    client = _client()
    create_resp = client.post(
        "/api/v1/strategies",
        headers=_idempotency_headers("strategy-activate-create"),
        json={"owner_id": "user_1", "template": "value_quality"},
    )
    strategy_id = create_resp.json()["strategy_id"]
    version_id = create_resp.json()["versions"][0]["version_id"]
    client.post(
        f"/api/v1/strategies/{strategy_id}/versions/{version_id}/validate",
        headers=_idempotency_headers("strategy-validate"),
    )
    client.post(
        f"/api/v1/strategies/{strategy_id}/versions/{version_id}/backtest",
        headers=_idempotency_headers("strategy-backtest"),
    )
    client.post(
        f"/api/v1/strategies/{strategy_id}/versions/{version_id}/paper-trade",
        headers=_idempotency_headers("strategy-paper"),
    )
    response = client.post(
        f"/api/v1/strategies/{strategy_id}/versions/{version_id}/activate",
        headers=_idempotency_headers("strategy-activate"),
    )
    assert response.status_code == 200
    assert response.json()["active_version_id"] == version_id


def test_get_prompt_endpoint():
    """Test that the get prompt endpoint returns the version prompt.

    Returns:
        Any: .
    """
    client = _client()
    create_resp = client.post(
        "/api/v1/strategies",
        headers=_idempotency_headers("strategy-prompt-create"),
        json={"owner_id": "user_1", "template": "value_quality"},
    )
    strategy_id = create_resp.json()["strategy_id"]
    version_id = create_resp.json()["versions"][0]["version_id"]
    response = client.get(f"/api/v1/strategies/{strategy_id}/versions/{version_id}/prompt")
    assert response.status_code == 200
    assert "prompt" in response.json()
