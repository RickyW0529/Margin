"""Tests for module 08 dashboard domain models."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from margin.dashboard.models import (
    CandidateCard,
    ItemStatus,
    ResearchItem,
    ResearchRun,
    RunStatus,
)


def test_research_run_defaults_and_utc_normalization():
    run = ResearchRun(
        decision_at=datetime(2026, 6, 19, 9, 30, tzinfo=UTC),
        strategy_id="st_demo",
        version_id="sv_demo",
        universe=["000001.SZ"],
    )

    assert run.run_id.startswith("dr_")
    assert run.status == RunStatus.PUBLISHED
    assert run.item_count == 0
    assert run.decision_at.tzinfo == UTC


def test_research_item_validates_confidence_range():
    with pytest.raises(ValueError, match="confidence"):
        ResearchItem(
            run_id="dr_1",
            symbol="000001.SZ",
            confidence=1.5,
        )


def test_candidate_card_contains_non_trading_disclaimer():
    card = CandidateCard(
        item_id="di_1",
        run_id="dr_1",
        symbol="000001.SZ",
        signal_type="research_candidate",
        research_status=ItemStatus.PUBLISHED.value,
        strategy_version="sv_demo",
    )

    assert "不构成买卖指令" in card.disclaimer
