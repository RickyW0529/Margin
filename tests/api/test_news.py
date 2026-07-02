"""News refresh API tests."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient

from margin.api.main import create_app
from margin.news.models import NewsRefreshRun, NewsRefreshStatus
from margin.news.service import NewsRunStatus
from margin.settings import get_settings


def test_news_refresh_status_returns_reconciliation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Test that news refresh status returns reconciliation details."""
    get_settings.cache_clear()
    client = TestClient(create_app(news_service=_FakeNewsService()))

    response = client.get("/api/v1/news/runs/run-1")

    assert response.status_code == 200
    assert response.json()["run_id"] == "run-1"
    assert response.json()["target_count"] == 1
    assert response.json()["failed_final_count"] == 0


def test_news_refresh_submit_returns_accepted_run_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Test that news refresh submit returns an accepted run id."""
    get_settings.cache_clear()
    service = _FakeNewsService()
    client = TestClient(create_app(news_service=service))

    response = client.post(
        "/api/v1/news/refresh",
        json={
            "scope_version_id": "scope-1",
            "quant_run_id": "quant-1",
            "decision_at": "2026-06-22T00:00:00Z",
            "targets": [
                {
                    "security_id": "000001.SZ",
                    "symbol": "000001",
                    "name": "平安银行",
                    "trigger_type": "new_pass",
                    "priority": 40,
                }
            ],
        },
        headers={
            "Idempotency-Key": "news-refresh-1",
        },
    )

    assert response.status_code == 202
    assert response.json()["run_id"] == "run-1"
    assert service.received_target_count == 1


@dataclass
class _FakeNewsService:
    """Fake news service stub used by the API tests."""

    received_target_count: int = 0

    def start_refresh(self, **kwargs: object) -> NewsRefreshRun:
        """Capture the refresh request and return a completed run."""
        targets = kwargs["targets"]
        self.received_target_count = len(targets)  # type: ignore[arg-type]
        return NewsRefreshRun(
            run_id="run-1",
            scope_version_id="scope-1",
            quant_run_id="quant-1",
            decision_at=datetime(2026, 6, 22, tzinfo=UTC),
            status=NewsRefreshStatus.COMPLETED,
            target_count=self.received_target_count,
            completed_count=self.received_target_count,
        )

    def get_run_status(self, run_id: str) -> NewsRunStatus:
        """Return a fake completed run status for the given run id."""
        return NewsRunStatus(
            run_id=run_id,
            status="completed",
            target_count=1,
            pending_count=0,
            claimed_count=0,
            retry_count=0,
            completed_count=1,
            failed_final_count=0,
            error_summary={},
        )
