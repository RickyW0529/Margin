"""Persistence repositories for module 09 holdings monitoring."""

from __future__ import annotations

from collections.abc import Callable
from typing import Protocol

from sqlalchemy import select
from sqlalchemy.orm import Session

from margin.holdings_monitoring.db_models import AlertEventRow, PositionReviewRow
from margin.holdings_monitoring.models import (
    AlertEvent,
    AlertPriority,
    AlertType,
    PositionReviewRecord,
    ReviewDecision,
)


class MonitoringRepository(Protocol):
    """Persistence contract consumed by holdings monitoring services."""

    def add_alert(self, alert: AlertEvent) -> None:
        """Append an alert event."""
        ...

    def list_alerts(
        self,
        portfolio_id: str,
        position_id: str | None = None,
    ) -> list[AlertEvent]:
        """Return alerts for a portfolio, optionally filtered by position."""
        ...

    def get_alert(self, alert_id: str) -> AlertEvent | None:
        """Return one alert by identifier."""
        ...

    def get_latest_alert(
        self,
        portfolio_id: str,
        position_id: str,
        rule_name: str,
    ) -> AlertEvent | None:
        """Return the latest alert emitted by one monitoring rule."""
        ...

    def add_review(self, review: PositionReviewRecord) -> None:
        """Append a manual position review."""
        ...

    def list_reviews(
        self,
        portfolio_id: str,
        position_id: str | None = None,
    ) -> list[PositionReviewRecord]:
        """Return review records for a portfolio or position."""
        ...


class MemoryMonitoringRepository:
    """In-memory monitoring repository for tests and embedded usage."""

    def __init__(self) -> None:
        self._alerts: dict[str, AlertEvent] = {}
        self._reviews: dict[str, PositionReviewRecord] = {}

    def add_alert(self, alert: AlertEvent) -> None:
        self._alerts[alert.alert_id] = alert

    def list_alerts(
        self,
        portfolio_id: str,
        position_id: str | None = None,
    ) -> list[AlertEvent]:
        alerts = [
            alert for alert in self._alerts.values()
            if alert.portfolio_id == portfolio_id
        ]
        if position_id is not None:
            alerts = [alert for alert in alerts if alert.position_id == position_id]
        return sorted(alerts, key=lambda item: (item.triggered_at, item.alert_id))

    def get_alert(self, alert_id: str) -> AlertEvent | None:
        return self._alerts.get(alert_id)

    def get_latest_alert(
        self,
        portfolio_id: str,
        position_id: str,
        rule_name: str,
    ) -> AlertEvent | None:
        alerts = [
            alert
            for alert in self._alerts.values()
            if alert.portfolio_id == portfolio_id
            and alert.position_id == position_id
            and alert.rule_name == rule_name
        ]
        return max(alerts, key=lambda item: item.triggered_at, default=None)

    def add_review(self, review: PositionReviewRecord) -> None:
        self._reviews[review.review_id] = review

    def list_reviews(
        self,
        portfolio_id: str,
        position_id: str | None = None,
    ) -> list[PositionReviewRecord]:
        reviews = [
            review for review in self._reviews.values()
            if review.portfolio_id == portfolio_id
        ]
        if position_id is not None:
            reviews = [review for review in reviews if review.position_id == position_id]
        return sorted(reviews, key=lambda item: (item.created_at, item.review_id))


class SQLAlchemyMonitoringRepository:
    """PostgreSQL monitoring repository backed by short SQLAlchemy sessions."""

    def __init__(self, session_factory: Callable[[], Session]) -> None:
        self._session_factory = session_factory

    def add_alert(self, alert: AlertEvent) -> None:
        with self._session_factory.begin() as session:
            session.add(_alert_to_row(alert))

    def list_alerts(
        self,
        portfolio_id: str,
        position_id: str | None = None,
    ) -> list[AlertEvent]:
        statement = select(AlertEventRow).where(
            AlertEventRow.portfolio_id == portfolio_id
        )
        if position_id is not None:
            statement = statement.where(AlertEventRow.position_id == position_id)
        statement = statement.order_by(
            AlertEventRow.triggered_at,
            AlertEventRow.alert_id,
        )
        with self._session_factory() as session:
            return [_alert_from_row(row) for row in session.scalars(statement).all()]

    def get_alert(self, alert_id: str) -> AlertEvent | None:
        with self._session_factory() as session:
            row = session.get(AlertEventRow, alert_id)
            return _alert_from_row(row) if row is not None else None

    def get_latest_alert(
        self,
        portfolio_id: str,
        position_id: str,
        rule_name: str,
    ) -> AlertEvent | None:
        statement = (
            select(AlertEventRow)
            .where(
                AlertEventRow.portfolio_id == portfolio_id,
                AlertEventRow.position_id == position_id,
                AlertEventRow.rule_name == rule_name,
            )
            .order_by(AlertEventRow.triggered_at.desc())
            .limit(1)
        )
        with self._session_factory() as session:
            row = session.scalar(statement)
            return _alert_from_row(row) if row is not None else None

    def add_review(self, review: PositionReviewRecord) -> None:
        with self._session_factory.begin() as session:
            session.add(_review_to_row(review))

    def list_reviews(
        self,
        portfolio_id: str,
        position_id: str | None = None,
    ) -> list[PositionReviewRecord]:
        statement = select(PositionReviewRow).where(
            PositionReviewRow.portfolio_id == portfolio_id
        )
        if position_id is not None:
            statement = statement.where(PositionReviewRow.position_id == position_id)
        statement = statement.order_by(
            PositionReviewRow.created_at,
            PositionReviewRow.review_id,
        )
        with self._session_factory() as session:
            return [_review_from_row(row) for row in session.scalars(statement).all()]


def _alert_to_row(alert: AlertEvent) -> AlertEventRow:
    return AlertEventRow(
        alert_id=alert.alert_id,
        portfolio_id=alert.portfolio_id,
        position_id=alert.position_id,
        symbol=alert.symbol,
        alert_type=alert.alert_type.value,
        severity=alert.severity.value,
        message=alert.message,
        rule_name=alert.rule_name,
        triggered_at=alert.triggered_at,
        evidence_refs=list(alert.evidence_refs),
        changed_thesis=alert.changed_thesis,
        acknowledged_at=alert.acknowledged_at,
    )


def _alert_from_row(row: AlertEventRow) -> AlertEvent:
    return AlertEvent(
        alert_id=row.alert_id,
        portfolio_id=row.portfolio_id,
        position_id=row.position_id,
        symbol=row.symbol,
        alert_type=AlertType(row.alert_type),
        severity=AlertPriority(row.severity),
        message=row.message,
        rule_name=row.rule_name,
        triggered_at=row.triggered_at,
        evidence_refs=list(row.evidence_refs),
        changed_thesis=row.changed_thesis,
        acknowledged_at=row.acknowledged_at,
    )


def _review_to_row(review: PositionReviewRecord) -> PositionReviewRow:
    return PositionReviewRow(
        review_id=review.review_id,
        portfolio_id=review.portfolio_id,
        position_id=review.position_id,
        alert_id=review.alert_id,
        decision=review.decision.value,
        rationale=review.rationale,
        action_taken_at=review.action_taken_at,
        created_at=review.created_at,
    )


def _review_from_row(row: PositionReviewRow) -> PositionReviewRecord:
    return PositionReviewRecord(
        review_id=row.review_id,
        portfolio_id=row.portfolio_id,
        position_id=row.position_id,
        alert_id=row.alert_id,
        decision=ReviewDecision(row.decision),
        rationale=row.rationale,
        action_taken_at=row.action_taken_at,
        created_at=row.created_at,
    )
