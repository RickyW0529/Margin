"""v0.2 dashboard BFF API tests."""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace

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


def test_research_list_resolves_scope_current_alias() -> None:
    """Test that the dashboard list resolves scope-current before querying."""
    client, _, _ = _client_with_seeded_v2_data(active_scope_id="scope-active")

    response = client.get(
        "/api/v1/research",
        params={
            "scope_version_id": "scope-current",
            "universe": "ALL_A",
            "limit": 50,
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["scope_version_id"] == "scope-active"
    assert body["items"][0]["scope_version_id"] == "scope-active"


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


def _client_with_seeded_v2_data(
    *,
    active_scope_id: str = "scope-1",
) -> tuple[TestClient, str, str]:
    """Build a test client seeded with v2 dashboard data."""
    dashboard_repository = MemoryDashboardRepository()
    bundle = DashboardServiceBundle.in_memory(
        dashboard_repository=dashboard_repository,
    )
    run = ResearchRun(
        run_id="run-1",
        decision_at=DECISION_AT,
        strategy_id="strategy-1",
        version_id=active_scope_id,
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
    app = create_app(
        dashboard_services=bundle,
        strategy_service=_FakeStrategyService(active_scope_id),
    )
    return TestClient(app), run.run_id, item.item_id


class _FakeStrategyService:
    """Fake strategy service exposing one active research scope."""

    def __init__(self, active_scope_id: str) -> None:
        """Store the active scope ID."""
        self._active_scope_id = active_scope_id

    def ensure_current_research_scope(self, owner_id: str) -> SimpleNamespace:
        """Return the reconciled current scope."""
        return SimpleNamespace(
            owner_id=owner_id,
            version_id=self._active_scope_id,
            lifecycle="active",
        )

    def list_research_scopes(self, owner_id: str) -> list[SimpleNamespace]:
        """Return active scope metadata."""
        return [
            SimpleNamespace(
                owner_id=owner_id,
                version_id=self._active_scope_id,
                lifecycle="active",
            )
        ]
