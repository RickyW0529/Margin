"""v0.2 readiness and degradation health-contract tests."""

from __future__ import annotations

from fastapi.testclient import TestClient

from margin.api.main import create_app


def test_ready_health_checks_database_migration_outbox_and_worker() -> None:
    """Test that ready health checks database, migration, outbox, and worker."""
    client = TestClient(create_app())

    response = client.get("/health/ready")

    assert response.status_code in {200, 503}
    body = response.json()
    assert body["status"] in {"ready", "not_ready"}
    assert "checks" in body
    assert {
        "database",
        "migration_head",
        "outbox",
        "provider_config",
        "worker",
    } <= set(body["checks"])
    assert "error" not in body["checks"]["database"]


def test_degraded_health_reports_capacity_and_retry_queues() -> None:
    """Test that degraded health reports capacity and retry queues."""
    client = TestClient(create_app())

    response = client.get("/health/degraded")

    assert response.status_code == 200
    body = response.json()
    assert "degraded" in body
    assert "waiting_budget_count" in body
    assert "waiting_rate_limit_count" in body
    assert "retry_queue_count" in body
    assert "outbox_pending_count" in body
    assert "service" in body
