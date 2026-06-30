"""Tests for health endpoints.

Covers liveness, readiness, degraded aggregation, and the guarantee that the
ready endpoint never leaks internal error details in its JSON body.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from margin.api.main import create_app


def test_health_returns_ok():
    """Test that the health endpoint returns ok."""
    app = create_app()
    client = TestClient(app)
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_ready_endpoint_checks_database():
    """Test that the ready endpoint checks the database."""
    app = create_app()
    client = TestClient(app)
    response = client.get("/health/ready")
    assert response.status_code in {200, 503}


def test_degraded_endpoint_returns_status():
    """Test that the degraded endpoint returns status."""
    app = create_app()
    client = TestClient(app)
    response = client.get("/health/degraded")
    assert response.status_code == 200
    assert "degraded" in response.json()


def test_ready_endpoint_returns_valid_sanitized_json_on_database_failure(monkeypatch):
    """Test that the ready endpoint returns sanitized JSON on database failure."""
    def fail_engine(*args, **kwargs):
        """Raise a runtime error simulating database unavailability."""
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
