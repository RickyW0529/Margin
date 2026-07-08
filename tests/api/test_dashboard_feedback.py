"""API tests for dashboard feedback mutation guardrails."""

from __future__ import annotations

from fastapi.testclient import TestClient

from margin.api.main import create_app
from margin.dashboard.repository import MemoryDashboardRepository
from margin.dashboard.service import DashboardServiceBundle


def test_dashboard_feedback_requires_idempotency_key() -> None:
    """Feedback creation is a mutation and must require an idempotency key."""
    client = TestClient(
        create_app(
            dashboard_services=DashboardServiceBundle.in_memory(
                dashboard_repository=MemoryDashboardRepository(),
            )
        )
    )

    response = client.post(
        "/api/v1/research-items/item-1/feedback",
        json={"feedback_type": "comment", "comment": "check later"},
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "Idempotency-Key header is required"
