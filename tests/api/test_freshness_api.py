"""API tests for data freshness safe status."""

from __future__ import annotations

from fastapi.testclient import TestClient

from margin.api.main import create_app


def test_data_freshness_returns_explicit_never_synced_state() -> None:
    """test_data_freshness_returns_explicit_never_synced_state implementation.

    Returns:
        None: .
    """
    client = TestClient(create_app())

    response = client.get(
        "/api/v1/data-freshness",
        params={
            "domains": ["market", "news"],
            "now": "2026-07-08T18:30:00+08:00",
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert [item["domain"] for item in body["items"]] == ["market", "news"]
    assert {item["status"] for item in body["items"]} == {"never_synced"}
