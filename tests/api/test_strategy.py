"""Tests for strategy API routes."""

from __future__ import annotations

from fastapi.testclient import TestClient

from margin.api.main import create_app
from margin.strategy.service import StrategyService


def _client() -> TestClient:
    app = create_app(strategy_service=StrategyService())
    return TestClient(app)


def test_create_strategy_endpoint():
    client = _client()
    response = client.post(
        "/strategies",
        json={"owner_id": "user_1", "template": "value_quality"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["name"] == "价值质量"
    assert len(body["versions"]) == 1


def test_list_templates_endpoint():
    client = _client()
    response = client.get("/strategies/templates")
    assert response.status_code == 200
    assert len(response.json()) == 6


def test_get_strategy_endpoint():
    client = _client()
    create_resp = client.post(
        "/strategies",
        json={"owner_id": "user_1", "template": "value_quality"},
    )
    strategy_id = create_resp.json()["strategy_id"]
    response = client.get(f"/strategies/{strategy_id}")
    assert response.status_code == 200
    assert response.json()["strategy_id"] == strategy_id


def test_update_strategy_endpoint():
    client = _client()
    create_resp = client.post(
        "/strategies",
        json={"owner_id": "user_1", "template": "value_quality"},
    )
    strategy_id = create_resp.json()["strategy_id"]
    response = client.put(
        f"/strategies/{strategy_id}",
        json={"config_delta": {"universe": ["000002.SZ"]}},
    )
    assert response.status_code == 200
    assert len(response.json()["versions"]) == 2


def test_activate_version_endpoint():
    client = _client()
    create_resp = client.post(
        "/strategies",
        json={"owner_id": "user_1", "template": "value_quality"},
    )
    strategy_id = create_resp.json()["strategy_id"]
    version_id = create_resp.json()["versions"][0]["version_id"]
    client.post(f"/strategies/{strategy_id}/versions/{version_id}/validate")
    client.post(f"/strategies/{strategy_id}/versions/{version_id}/backtest")
    client.post(f"/strategies/{strategy_id}/versions/{version_id}/paper-trade")
    response = client.post(
        f"/strategies/{strategy_id}/versions/{version_id}/activate"
    )
    assert response.status_code == 200
    assert response.json()["active_version_id"] == version_id


def test_get_prompt_endpoint():
    client = _client()
    create_resp = client.post(
        "/strategies",
        json={"owner_id": "user_1", "template": "value_quality"},
    )
    strategy_id = create_resp.json()["strategy_id"]
    version_id = create_resp.json()["versions"][0]["version_id"]
    response = client.get(f"/strategies/{strategy_id}/versions/{version_id}/prompt")
    assert response.status_code == 200
    assert "prompt" in response.json()
