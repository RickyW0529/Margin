"""Tests for health endpoints."""

from __future__ import annotations

from fastapi.testclient import TestClient

from margin.api.main import create_app


def test_health_returns_ok():
    app = create_app()
    client = TestClient(app)
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_ready_endpoint_checks_database():
    app = create_app()
    client = TestClient(app)
    response = client.get("/health/ready")
    assert response.status_code in {200, 503}


def test_degraded_endpoint_returns_status():
    app = create_app()
    client = TestClient(app)
    response = client.get("/health/degraded")
    assert response.status_code == 200
    assert "degraded" in response.json()
