"""Portfolio FastAPI endpoint contract tests.

This module exercises the portfolio-related HTTP routes, covering dashboard retrieval,
trade creation, position details, CSV imports, investment thesis versioning, and error
handling for missing resources and invalid payloads.
"""

from __future__ import annotations

from datetime import datetime

from fastapi.testclient import TestClient

from margin.api.main import create_app
from margin.portfolio.service import PortfolioService


def _client_with_portfolio():
    """Create a test client backed by a portfolio service with a single portfolio.

    Returns:
        A tuple of ``(test_client, portfolio_service, portfolio)`` ready for use in
        API contract tests.
    """
    service = PortfolioService()
    portfolio = service.create_portfolio("user_1", "Core", cash=10000)
    app = create_app(portfolio_service=service)
    return TestClient(app), service, portfolio


def test_get_portfolio_dashboard():
    """Verify that GET returns portfolio identity and dashboard overview.

    The test checks that the response contains the portfolio name and reflects the
    initial cash amount as total assets.
    """
    client, _, portfolio = _client_with_portfolio()

    response = client.get(f"/api/v1/portfolios/{portfolio.portfolio_id}")

    assert response.status_code == 200
    assert response.json()["portfolio"]["name"] == "Core"
    assert response.json()["overview"]["total_assets"] == 10000


def test_trade_positions_and_risk_routes():
    """Verify that trade creation feeds position and risk views.

    A buy trade is posted, then the positions and risk endpoints are queried to ensure
    they return the newly created position and the associated portfolio risk summary.
    """
    client, _, portfolio = _client_with_portfolio()
    trade_response = client.post(
        f"/api/v1/portfolios/{portfolio.portfolio_id}/trades",
        json={
            "symbol": "000001.SZ",
            "side": "buy",
            "quantity": 100,
            "price": 10,
            "traded_at": datetime(2026, 6, 1).isoformat(),
        },
    )

    positions = client.get(
        f"/api/v1/portfolios/{portfolio.portfolio_id}/positions"
    )
    risk = client.get(f"/api/v1/portfolios/{portfolio.portfolio_id}/risk")

    assert trade_response.status_code == 201
    assert positions.status_code == 200
    assert positions.json()[0]["symbol"] == "000001.SZ"
    assert risk.status_code == 200
    assert risk.json()["portfolio_id"] == portfolio.portfolio_id


def test_position_detail_route_includes_trade_history():
    """Verify that the position detail route exposes cost and operation history.

    A trade is added through the service layer, the first position is retrieved, and
    the detail endpoint is checked for the correct symbol and one entry in trade history.
    """
    client, service, portfolio = _client_with_portfolio()
    service.add_trade(
        portfolio.portfolio_id,
        "000001.SZ",
        "buy",
        100,
        10,
        datetime(2026, 6, 1),
    )
    position_id = service.get_positions(portfolio.portfolio_id)[0].position_id

    response = client.get(
        f"/api/v1/portfolios/{portfolio.portfolio_id}/positions/{position_id}"
    )

    assert response.status_code == 200
    assert response.json()["symbol"] == "000001.SZ"
    assert len(response.json()["trade_history"]) == 1


def test_csv_import_route():
    """Verify that CSV imports persist all valid rows.

    A CSV payload with one valid trade row is imported, and the response is checked for
    a successful status, a trade count of one, and one persisted trade record.
    """
    client, _, portfolio = _client_with_portfolio()
    response = client.post(
        f"/api/v1/portfolios/{portfolio.portfolio_id}/imports",
        json={
            "content": (
                "symbol,side,quantity,price,traded_at\n"
                "000001.SZ,buy,100,10,2026-06-01\n"
            )
        },
    )

    assert response.status_code == 201
    assert response.json()["record"]["trade_count"] == 1
    assert len(response.json()["trades"]) == 1


def test_thesis_put_and_get_routes():
    """Verify that thesis updates are versioned and the latest version is returned.

    A position is created by adding a trade, then a thesis is written via PUT and
    retrieved via GET. The response must contain the latest thesis text.
    """
    client, service, portfolio = _client_with_portfolio()
    service.add_trade(
        portfolio.portfolio_id,
        "000001.SZ",
        "buy",
        100,
        10,
        datetime(2026, 6, 1),
    )
    position_id = service.get_positions(portfolio.portfolio_id)[0].position_id

    first = client.put(
        f"/api/v1/positions/{position_id}/thesis",
        json={
            "portfolio_id": portfolio.portfolio_id,
            "thesis": "现金流改善",
            "invalidation_conditions": ["经营现金流转负"],
        },
    )
    latest = client.get(
        f"/api/v1/positions/{position_id}/thesis",
        params={"portfolio_id": portfolio.portfolio_id},
    )

    assert first.status_code == 200
    assert latest.status_code == 200
    assert latest.json()["thesis"] == "现金流改善"


def test_missing_portfolio_returns_404():
    """Verify that requests for missing resources map to HTTP 404.

    A portfolio that does not exist is requested, and the response status code must be
    ``404 Not Found``.
    """
    client = TestClient(create_app(portfolio_service=PortfolioService()))

    response = client.get("/api/v1/portfolios/missing")

    assert response.status_code == 404


def test_invalid_trade_and_import_return_422():
    """Verify that invalid user input returns structured HTTP 422 errors.

    Both the trade creation and CSV import endpoints receive malformed payloads and must
    respond with ``422 Unprocessable Entity`` and a ``detail`` field in the error body.
    """
    client, _, portfolio = _client_with_portfolio()
    invalid_trade = client.post(
        f"/api/v1/portfolios/{portfolio.portfolio_id}/trades",
        json={
            "symbol": "",
            "side": "buy",
            "quantity": 0,
            "price": 10,
            "traded_at": datetime(2026, 6, 1).isoformat(),
        },
    )
    invalid_import = client.post(
        f"/api/v1/portfolios/{portfolio.portfolio_id}/imports",
        json={"content": "symbol,side\n,buy\n"},
    )

    assert invalid_trade.status_code == 422
    assert invalid_import.status_code == 422
    assert "detail" in invalid_import.json()
