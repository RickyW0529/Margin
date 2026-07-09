"""API tests for v1 backfill campaign control plane."""

from __future__ import annotations

from datetime import date

from fastapi.testclient import TestClient

from margin.api.main import create_app
from margin.data.backfill.service import BackfillApplicationService


def test_backfill_campaign_api_full_dry_run_flow() -> None:
    """test_backfill_campaign_api_full_dry_run_flow implementation.

    Returns:
        None: .
    """
    client = TestClient(
        create_app(backfill_application_service=BackfillApplicationService(today=date(2026, 7, 8)))
    )

    create_response = client.post(
        "/api/v1/backfill-campaigns",
        headers={"Idempotency-Key": "bf-create"},
        json={
            "campaign_name": "full_market_20y",
            "providers": ["tushare", "akshare"],
            "start_date": "2006-01-01",
            "end_date": "2006-01-31",
        },
    )

    assert create_response.status_code == 201
    created = create_response.json()
    campaign_id = created["campaign"]["campaign_id"]
    assert campaign_id == "bf_full_market_20y_20260708"
    assert created["campaign"]["start_date"] == "2006-01-01"
    assert created["endpoint_count"] > 0
    assert created["partition_count"] > 0

    get_response = client.get(f"/api/v1/backfill-campaigns/{campaign_id}")
    partitions_response = client.get(f"/api/v1/backfill-campaigns/{campaign_id}/partitions")
    run_response = client.post(
        f"/api/v1/backfill-campaigns/{campaign_id}/run",
        headers={"Idempotency-Key": "bf-run"},
    )
    verify_response = client.post(
        f"/api/v1/backfill-campaigns/{campaign_id}/verify",
        headers={"Idempotency-Key": "bf-verify"},
    )
    quality_response = client.get(f"/api/v1/backfill-campaigns/{campaign_id}/quality-report")
    publish_response = client.post(
        f"/api/v1/backfill-campaigns/{campaign_id}/publish",
        headers={"Idempotency-Key": "bf-publish"},
    )

    assert get_response.status_code == 200
    assert partitions_response.status_code == 200
    assert run_response.status_code == 200
    assert run_response.json()["processed_partitions"] == created["partition_count"]
    assert verify_response.status_code == 200
    assert verify_response.json()["publish_allowed"] is True
    assert quality_response.status_code == 200
    assert publish_response.status_code == 200
    assert publish_response.json()["built_layers"] == [
        "ods",
        "vault",
        "pit",
        "kimball",
        "mart",
    ]


def test_backfill_mutations_require_idempotency_key() -> None:
    """test_backfill_mutations_require_idempotency_key implementation.

    Returns:
        None: .
    """
    client = TestClient(
        create_app(backfill_application_service=BackfillApplicationService(today=date(2026, 7, 8)))
    )

    response = client.post(
        "/api/v1/backfill-campaigns",
        json={"campaign_name": "full_market_20y"},
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "Idempotency-Key header is required"
