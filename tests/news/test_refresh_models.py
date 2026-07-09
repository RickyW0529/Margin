"""v0.2 news refresh domain model tests."""

from __future__ import annotations

from datetime import UTC, datetime

from margin.news.models import (
    NewsRefreshStatus,
    NewsTarget,
    NewsTargetStatus,
    TargetTriggerType,
)


def test_news_target_dedupe_key_is_stable() -> None:
    """The same scope/quant/security/trigger/date must produce a stable work key.

    Returns:
        None: .
    """
    target = NewsTarget(
        scope_version_id="scope-1",
        quant_run_id="quant-1",
        security_id="000001.SZ",
        symbol="000001",
        name="平安银行",
        trigger_type=TargetTriggerType.NEW_PASS,
        decision_at=datetime(2026, 6, 22, tzinfo=UTC),
        priority=40,
    )

    assert target.dedupe_key == ("73550515d619ea34fa570179881731e0a4316d0251b3250a5c0636b1fc3d5eef")
    assert target.status == NewsTargetStatus.PENDING


def test_run_terminal_invariant_requires_all_targets_accounted() -> None:
    """A refresh run is terminal only when all persisted targets are accounted for.

    Returns:
        None: .
    """
    assert NewsRefreshStatus.is_terminal_counts(
        target_count=3,
        completed_count=2,
        failed_final_count=1,
    )
    assert not NewsRefreshStatus.is_terminal_counts(
        target_count=3,
        completed_count=1,
        failed_final_count=1,
    )
