"""Tests for module 09 holdings monitoring services."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from margin.holdings_monitoring.models import (
    AlertPriority,
    AlertType,
    ReviewDecision,
)
from margin.holdings_monitoring.repository import MemoryMonitoringRepository
from margin.holdings_monitoring.service import HoldingsMonitoringService
from margin.portfolio.models import (
    Position,
    PositionHealthStatus,
    PositionThesis,
    ThesisStatus,
    Trade,
    TradeSide,
)


def _position(current_price: float | None = 10.0) -> Position:
    return Position(
        position_id="pos_1",
        portfolio_id="pf_1",
        symbol="000001.SZ",
        quantity=1000,
        cost_price=10.0,
        cost_amount=10000.0,
        current_price=current_price,
        market_value=current_price * 1000 if current_price is not None else None,
    )


def _thesis(next_review_at: datetime | None = None) -> PositionThesis:
    return PositionThesis(
        thesis_id="th_1",
        position_id="pos_1",
        thesis="现金流改善与估值修复",
        hold_conditions=["经营现金流保持增长"],
        invalidation_conditions=["价格跌破成本 10%"],
        next_review_at=next_review_at,
        status=ThesisStatus.THESIS_VALID,
    )


def test_evaluate_position_marks_data_missing_and_creates_p2_alert():
    repository = MemoryMonitoringRepository()
    service = HoldingsMonitoringService(repository=repository)

    snapshot = service.evaluate_position(
        portfolio_id="pf_1",
        position=_position(current_price=None),
        thesis=_thesis(),
        current_price=None,
        decision_at=datetime(2026, 6, 19, 9, 30, tzinfo=UTC),
    )

    assert snapshot.health_status == PositionHealthStatus.DATA_MISSING
    assert snapshot.alerts[0].alert_type == AlertType.DATA_QUALITY
    assert snapshot.alerts[0].severity == AlertPriority.P2
    assert repository.list_alerts("pf_1", "pos_1") == snapshot.alerts


def test_evaluate_position_triggers_p0_price_invalidation_with_evidence():
    repository = MemoryMonitoringRepository()
    service = HoldingsMonitoringService(repository=repository)

    snapshot = service.evaluate_position(
        portfolio_id="pf_1",
        position=_position(current_price=8.8),
        thesis=_thesis(),
        current_price=8.8,
        evidence_refs=["ev_price_drop"],
        decision_at=datetime(2026, 6, 19, 9, 30, tzinfo=UTC),
    )

    assert snapshot.health_status == PositionHealthStatus.INVALIDATED
    assert snapshot.thesis_status == ThesisStatus.THESIS_INVALIDATED
    assert snapshot.alerts[0].alert_type == AlertType.PRICE_INVALIDATION
    assert snapshot.alerts[0].severity == AlertPriority.P0
    assert snapshot.alerts[0].changed_thesis is True
    assert snapshot.alerts[0].evidence_refs == ["ev_price_drop"]


def test_evaluate_position_marks_event_pending_when_review_is_due():
    repository = MemoryMonitoringRepository()
    service = HoldingsMonitoringService(repository=repository)
    decision_at = datetime(2026, 6, 19, 9, 30, tzinfo=UTC)

    snapshot = service.evaluate_position(
        portfolio_id="pf_1",
        position=_position(current_price=10.5),
        thesis=_thesis(next_review_at=decision_at - timedelta(hours=1)),
        current_price=10.5,
        decision_at=decision_at,
    )

    assert snapshot.health_status == PositionHealthStatus.EVENT_PENDING
    assert snapshot.alerts[0].alert_type == AlertType.KEY_EVENT_PENDING
    assert snapshot.alerts[0].severity == AlertPriority.P2


def test_review_records_and_operation_history_are_append_only():
    repository = MemoryMonitoringRepository()
    service = HoldingsMonitoringService(repository=repository)
    decision_at = datetime(2026, 6, 19, 9, 30, tzinfo=UTC)
    snapshot = service.evaluate_position(
        portfolio_id="pf_1",
        position=_position(current_price=8.8),
        thesis=_thesis(),
        current_price=8.8,
        decision_at=decision_at,
    )
    trade = Trade(
        trade_id="trd_1",
        portfolio_id="pf_1",
        symbol="000001.SZ",
        side=TradeSide.BUY,
        quantity=1000,
        price=10,
        traded_at=decision_at - timedelta(days=10),
    )

    review = service.record_review(
        portfolio_id="pf_1",
        position_id="pos_1",
        alert_id=snapshot.alerts[0].alert_id,
        decision=ReviewDecision.REDUCE,
        rationale="价格触及失效条件，降低仓位",
        action_taken_at=decision_at + timedelta(minutes=30),
    )
    metrics = service.get_behavior_metrics("pf_1", "pos_1")
    history = service.get_operation_history(
        portfolio_id="pf_1",
        position_id="pos_1",
        trades=[trade],
    )

    assert repository.list_reviews("pf_1", "pos_1") == [review]
    assert metrics[0].action_latency_seconds == 1800
    assert [entry.event_type for entry in history] == ["trade", "alert", "review"]
