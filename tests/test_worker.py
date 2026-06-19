"""Tests for the persistent scheduler worker."""

from __future__ import annotations

from margin.worker import build_scheduler


def test_worker_registers_holdings_monitoring_job():
    scheduler = build_scheduler(lambda: None, interval_seconds=300)

    job = scheduler.get_job("holdings-monitoring")

    assert job is not None
    assert job.max_instances == 1
    assert job.coalesce is True
