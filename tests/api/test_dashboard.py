"""Tests for module 08 dashboard API routes."""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi.testclient import TestClient

from margin.api.main import create_app
from margin.dashboard.models import FeedbackType
from margin.dashboard.repository import MemoryDashboardRepository
from margin.dashboard.service import DashboardServiceBundle
from margin.research.repository import MemoryResearchRepository
from margin.research.service import ResearchService


def _client_with_seeded_run() -> tuple[TestClient, str, str]:
    dashboard_repository = MemoryDashboardRepository()
    research_repository = MemoryResearchRepository()
    bundle = DashboardServiceBundle.in_memory(
        dashboard_repository=dashboard_repository,
        research_repository=research_repository,
        research_service=ResearchService(repository=research_repository),
    )
    run = bundle.research.run_batch(
        decision_at=datetime(2026, 6, 19, tzinfo=UTC),
        strategy_id="st_api",
        version_id="sv_api",
        symbols=["000001.SZ"],
    )
    item = dashboard_repository.list_items(run.run_id)[0]
    app = create_app(dashboard_services=bundle)
    return TestClient(app), run.run_id, item.item_id


def test_dashboard_api_lists_runs_items_and_views():
    client, run_id, item_id = _client_with_seeded_run()

    runs = client.get("/api/v1/research-runs")
    items = client.get(f"/api/v1/research-runs/{run_id}/items")
    item = client.get(f"/api/v1/research-items/{item_id}")
    evidence = client.get(f"/api/v1/research-items/{item_id}/evidence")
    valuation = client.get(f"/api/v1/research-items/{item_id}/valuation")
    audit = client.get(f"/api/v1/research-items/{item_id}/audit")
    report = client.get(f"/api/v1/research-items/{item_id}/report")
    exported = client.get(f"/api/v1/research-items/{item_id}/export?format=json")

    assert runs.status_code == 200
    assert runs.json()[0]["run_id"] == run_id
    assert items.status_code == 200
    assert items.json()[0]["item_id"] == item_id
    assert item.status_code == 200
    assert evidence.status_code == 200
    assert valuation.status_code == 200
    assert audit.status_code == 200
    assert report.status_code == 200
    assert "不构成买卖指令" in report.json()["content"]
    assert exported.status_code == 200
    assert exported.json()["mime_type"] == "application/json"


def test_dashboard_api_records_feedback_and_provider_status():
    client, _, item_id = _client_with_seeded_run()

    feedback = client.post(
        f"/api/v1/research-items/{item_id}/feedback",
        json={"feedback_type": FeedbackType.WATCH.value, "comment": "继续观察"},
    )
    provider_status = client.get("/api/v1/provider-status")

    assert feedback.status_code == 201
    assert feedback.json()["comment"] == "继续观察"
    assert provider_status.status_code == 200
    assert provider_status.json()[0]["provider"] == "dashboard"
