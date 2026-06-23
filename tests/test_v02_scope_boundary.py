"""Scope guardrails for the v0.2 valuation-discovery product."""

from __future__ import annotations

from importlib.util import find_spec

from margin.api.main import create_app
from margin.research.llm import TaskType
from margin.strategy.models import RiskConfig
from margin.worker import build_scheduler


def test_v02_exposes_no_portfolio_or_holdings_api() -> None:
    """Portfolio and holdings-monitoring routes are outside the v0.2 product."""
    paths = set(create_app().openapi()["paths"])

    assert not any(path.startswith("/api/v1/portfolios") for path in paths)
    assert not any(path.startswith("/api/v1/monitoring") for path in paths)


def test_v02_worker_schedules_only_research_pipeline_jobs() -> None:
    """The v0.2 worker must not run a holdings-monitoring sweep."""
    scheduler = build_scheduler(
        interval_seconds=300,
        indexing_job=lambda: None,
        data_sync_job=lambda: None,
        orchestration_job=lambda: None,
    )

    assert scheduler.get_job("holdings-monitoring") is None
    assert scheduler.get_job("document-indexing") is not None
    assert scheduler.get_job("data-provider-sync") is not None
    assert scheduler.get_job("orchestration-steps") is not None


def test_v02_source_tree_has_no_holdings_domain_packages() -> None:
    """Removed v0.1 holdings domains must not remain importable."""
    assert find_spec("margin.portfolio") is None
    assert find_spec("margin.holdings_monitoring") is None


def test_v02_runtime_models_have_no_portfolio_or_position_controls() -> None:
    """Research routing and strategy config must not expose removed holdings controls."""
    assert "portfolio" not in {task.value for task in TaskType}
    assert "max_position_weight" not in RiskConfig.model_fields
    assert "max_sector_weight" not in RiskConfig.model_fields
