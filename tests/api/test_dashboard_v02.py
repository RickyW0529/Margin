"""v0.2 dashboard BFF API tests."""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi.testclient import TestClient

from margin.api.main import create_app
from margin.dashboard.models import ResearchItem, ResearchRun
from margin.dashboard.repository import MemoryDashboardRepository
from margin.dashboard.service import DashboardServiceBundle

DECISION_AT = datetime(2026, 6, 22, tzinfo=UTC)


def test_research_list_returns_paged_items_and_facets() -> None:
    """Test that the research list returns paged items and facets."""
    client, _, _ = _client_with_seeded_v2_data()

    response = client.get(
        "/api/v1/research",
        params={
            "scope_version_id": "scope-1",
            "universe": "ALL_A",
            "limit": 50,
            "screening_status": "pass",
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert set(body) == {"items", "page_info", "facets", "as_of", "scope_version_id"}
    assert len(body["items"]) <= 50
    assert body["items"][0]["current_review_outcome"] == "update_assessment"

def test_research_item_detail_returns_current_and_effective_context() -> None:
    """Test that v2 item detail separates current review from effective assessment."""
    client, _, item_id = _client_with_seeded_v2_data()

    response = client.get(f"/api/v1/research/items/{item_id}")

    assert response.status_code == 200
    body = response.json()
    assert set(body) == {
        "item",
        "current_review",
        "effective_assessment",
        "factors",
        "thesis",
        "evidence",
        "versions",
    }
    assert body["item"]["item_id"] == item_id
    assert body["current_review"]["outcome"] == "update_assessment"
    assert body["effective_assessment"]["assessment_id"] == "assess-old"
    assert body["versions"]["workflow_run_id"] == "wf-1"
    assert "prompt" not in str(body).lower()


def test_copilot_rejects_mutating_intent() -> None:
    """Test that the read-only Copilot rejects refresh or rerun requests."""
    client, _, _ = _client_with_seeded_v2_data()

    response = client.post(
        "/api/v1/research/copilot",
        json={"scope_version_id": "scope-1", "message": "帮我重新跑一次今天的估值"},
    )

    assert response.status_code == 403
    assert response.json()["code"] == "copilot_read_only"


def test_copilot_answer_contains_business_api_references() -> None:
    """Test that the read-only Copilot answers with business API references."""
    client, _, _ = _client_with_seeded_v2_data()

    response = client.post(
        "/api/v1/research/copilot",
        json={"scope_version_id": "scope-1", "message": "今天哪些公司值得继续看"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["references"]
    assert "GET /api/v1/research" in body["references"][0]["api"]


def _client_with_seeded_v2_data() -> tuple[TestClient, str, str]:
    """Build a test client seeded with v2 dashboard data."""
    dashboard_repository = MemoryDashboardRepository()
    bundle = DashboardServiceBundle.in_memory(
        dashboard_repository=dashboard_repository,
    )
    run = ResearchRun(
        run_id="run-1",
        decision_at=DECISION_AT,
        strategy_id="strategy-1",
        version_id="scope-1",
        universe=["000001.SZ"],
        status="partial",
        item_count=1,
        published_count=1,
    )
    item = ResearchItem(
        item_id="item-1",
        run_id=run.run_id,
        symbol="000001.SZ",
        signal_type="research_candidate",
        confidence=0.82,
        statement="经营现金流改善",
        workflow_run_id="wf-1",
        snapshot_id="assess-old",
        status="published",
    )
    dashboard_repository.add_run(run)
    dashboard_repository.add_items([item])
    app = create_app(dashboard_services=bundle)
    return TestClient(app), run.run_id, item.item_id
