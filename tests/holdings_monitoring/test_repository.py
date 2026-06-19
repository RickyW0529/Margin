"""Repository tests for module 09 holdings monitoring."""

from __future__ import annotations

from datetime import UTC, datetime

from margin.holdings_monitoring.models import (
    AlertEvent,
    AlertPriority,
    AlertType,
    PositionReviewRecord,
    ReviewDecision,
)
from margin.holdings_monitoring.repository import MemoryMonitoringRepository


def test_memory_repository_preserves_alerts_and_reviews_by_position():
    repository = MemoryMonitoringRepository()
    alert = AlertEvent(
        portfolio_id="pf_1",
        position_id="pos_1",
        symbol="000001.SZ",
        alert_type=AlertType.PRICE_INVALIDATION,
        severity=AlertPriority.P0,
        message="价格触及失效条件",
        rule_name="price_invalidation",
        triggered_at=datetime(2026, 6, 19, tzinfo=UTC),
    )
    review = PositionReviewRecord(
        portfolio_id="pf_1",
        position_id="pos_1",
        alert_id=alert.alert_id,
        decision=ReviewDecision.REDUCE,
        rationale="降低仓位",
    )

    repository.add_alert(alert)
    repository.add_review(review)

    assert repository.list_alerts("pf_1", "pos_1") == [alert]
    assert repository.list_reviews("pf_1", "pos_1") == [review]
