"""API tests for module 09 holdings monitoring routes."""

from __future__ import annotations

from datetime import datetime

from fastapi.testclient import TestClient

from margin.api.main import create_app
from margin.holdings_monitoring.service import MonitoringServiceBundle
from margin.portfolio.service import PortfolioService


def _client_with_position() -> tuple[TestClient, str, str]:
    portfolio_service = PortfolioService()
    portfolio = portfolio_service.create_portfolio("user_1", "Core", cash=10000)
    portfolio_service.add_trade(
        portfolio.portfolio_id,
        "000001.SZ",
        "buy",
        1000,
        10,
        datetime(2026, 6, 1),
    )
    position = portfolio_service.get_positions(portfolio.portfolio_id)[0]
    portfolio_service.update_thesis(
        portfolio.portfolio_id,
        position.position_id,
        thesis="现金流改善与估值修复",
        invalidation_conditions=["价格跌破成本 10%"],
    )
    monitoring_services = MonitoringServiceBundle.in_memory(
        portfolio_service=portfolio_service
    )
    app = create_app(
        portfolio_service=portfolio_service,
        monitoring_services=monitoring_services,
    )
    return TestClient(app), portfolio.portfolio_id, position.position_id


def test_monitoring_api_evaluates_alerts_reviews_and_history():
    client, portfolio_id, position_id = _client_with_position()

    snapshot = client.post(
        f"/api/v1/positions/{position_id}/monitoring/evaluate",
        json={
            "portfolio_id": portfolio_id,
            "current_price": 8.8,
            "evidence_refs": ["ev_price_drop"],
            "decision_at": "2026-06-19T09:30:00Z",
        },
    )
    alerts = client.get(
        f"/api/v1/positions/{position_id}/alerts",
        params={"portfolio_id": portfolio_id},
    )
    alert_id = snapshot.json()["alerts"][0]["alert_id"]
    review = client.post(
        f"/api/v1/positions/{position_id}/reviews",
        json={
            "portfolio_id": portfolio_id,
            "alert_id": alert_id,
            "decision": "reduce",
            "rationale": "价格触发失效条件，降低仓位",
            "action_taken_at": "2026-06-19T10:00:00Z",
        },
    )
    history = client.get(
        f"/api/v1/positions/{position_id}/history",
        params={"portfolio_id": portfolio_id},
    )

    assert snapshot.status_code == 201
    assert snapshot.json()["health_status"] == "invalidated"
    assert snapshot.json()["alerts"][0]["severity"] == "P0"
    assert alerts.status_code == 200
    assert alerts.json()[0]["alert_id"] == alert_id
    assert review.status_code == 201
    assert review.json()["decision"] == "reduce"
    assert history.status_code == 200
    assert [entry["event_type"] for entry in history.json()] == [
        "trade",
        "alert",
        "review",
    ]
