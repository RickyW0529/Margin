"""Tests for valuation-discovery production adapters."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from margin.news.models import NewsRefreshRun, NewsRefreshStatus
from margin.valuation_discovery.adapters import NewsRefreshAdapter
from margin.valuation_discovery.orchestrator import RetryableStepError


def test_news_refresh_adapter_waits_when_refresh_run_is_still_running() -> None:
    """A non-terminal news refresh must not release downstream context building.

    Returns:
        None: .
    """
    adapter = NewsRefreshAdapter(
        _FakeNewsRefreshService(
            status=NewsRefreshStatus.RUNNING,
            run_id="news-run-1",
        )
    )

    with pytest.raises(RetryableStepError) as exc_info:
        adapter.refresh(
            scope_version_id="scope-1",
            quant_run_id="quant-1",
            decision_at=datetime(2026, 7, 2, tzinfo=UTC),
            targets=(),
        )

    assert exc_info.value.code == "news_refresh_incomplete"
    assert exc_info.value.output_ref == "news:news-run-1"


class _FakeNewsRefreshService:
    """Return a deterministic news refresh run.."""

    def __init__(self, *, status: NewsRefreshStatus, run_id: str) -> None:
        """Helper _init__.

        Args:
            status: NewsRefreshStatus: .
            run_id: str: .

        Returns:
            None: .
        """
        self._status = status
        self._run_id = run_id

    def refresh_for_targets(self, **kwargs: object) -> NewsRefreshRun:
        """Return a refresh run with the configured status.

        Args:
            **kwargs: object: .

        Returns:
            NewsRefreshRun: .
        """
        decision_at = kwargs["decision_at"]
        assert isinstance(decision_at, datetime)
        return NewsRefreshRun(
            run_id=self._run_id,
            scope_version_id=str(kwargs["scope_version_id"]),
            quant_run_id=str(kwargs["quant_run_id"]),
            decision_at=decision_at,
            status=self._status,
            target_count=1,
            completed_count=0,
            failed_final_count=0,
        )
