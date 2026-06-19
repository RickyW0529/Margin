"""Persistence boundary for the research candidate dashboard module."""

from __future__ import annotations

from collections.abc import Callable
from typing import Protocol

from sqlalchemy import select
from sqlalchemy.orm import Session

from margin.dashboard.db_models import (
    DashboardFeedbackRow,
    DashboardItemRow,
    DashboardRunRow,
)
from margin.dashboard.models import (
    FeedbackRecord,
    ResearchItem,
    ResearchRun,
)


class DashboardRepository(Protocol):
    """Repository contract consumed by dashboard query and orchestration services."""

    def add_run(self, run: ResearchRun) -> None:
        """Persist a dashboard run."""

    def get_run(self, run_id: str) -> ResearchRun | None:
        """Return one run by identifier."""

    def list_runs(
        self,
        *,
        strategy_id: str | None = None,
        portfolio_id: str | None = None,
        status: str | None = None,
        limit: int = 100,
    ) -> list[ResearchRun]:
        """Return dashboard runs sorted newest first."""

    def add_items(self, items: list[ResearchItem]) -> None:
        """Persist run items."""

    def get_item(self, item_id: str) -> ResearchItem | None:
        """Return one item by identifier."""

    def list_items(self, run_id: str) -> list[ResearchItem]:
        """Return all items for a run."""

    def add_feedback(self, feedback: FeedbackRecord) -> None:
        """Append user feedback."""

    def list_feedback(self, item_id: str) -> list[FeedbackRecord]:
        """Return feedback for one item."""


class MemoryDashboardRepository:
    """In-memory dashboard repository for tests and local usage."""

    def __init__(self) -> None:
        self._runs: dict[str, ResearchRun] = {}
        self._items: dict[str, ResearchItem] = {}
        self._feedback: dict[str, list[FeedbackRecord]] = {}

    def add_run(self, run: ResearchRun) -> None:
        self._runs[run.run_id] = run

    def get_run(self, run_id: str) -> ResearchRun | None:
        return self._runs.get(run_id)

    def list_runs(
        self,
        *,
        strategy_id: str | None = None,
        portfolio_id: str | None = None,
        status: str | None = None,
        limit: int = 100,
    ) -> list[ResearchRun]:
        runs = list(self._runs.values())
        if strategy_id:
            runs = [run for run in runs if run.strategy_id == strategy_id]
        if portfolio_id:
            runs = [run for run in runs if run.portfolio_id == portfolio_id]
        if status:
            runs = [run for run in runs if run.status.value == status]
        runs.sort(key=lambda run: run.created_at, reverse=True)
        return runs[:limit]

    def add_items(self, items: list[ResearchItem]) -> None:
        for item in items:
            self._items[item.item_id] = item

    def get_item(self, item_id: str) -> ResearchItem | None:
        return self._items.get(item_id)

    def list_items(self, run_id: str) -> list[ResearchItem]:
        items = [item for item in self._items.values() if item.run_id == run_id]
        items.sort(key=lambda item: item.created_at)
        return items

    def add_feedback(self, feedback: FeedbackRecord) -> None:
        self._feedback.setdefault(feedback.item_id, []).append(feedback)

    def list_feedback(self, item_id: str) -> list[FeedbackRecord]:
        return list(self._feedback.get(item_id, []))


class SQLAlchemyDashboardRepository:
    """PostgreSQL-backed dashboard repository."""

    def __init__(self, session_factory: Callable[[], Session]) -> None:
        self._session_factory = session_factory

    def add_run(self, run: ResearchRun) -> None:
        with self._session_factory.begin() as session:
            session.merge(_run_to_row(run))

    def get_run(self, run_id: str) -> ResearchRun | None:
        with self._session_factory() as session:
            row = session.get(DashboardRunRow, run_id)
            return _run_from_row(row) if row else None

    def list_runs(
        self,
        *,
        strategy_id: str | None = None,
        portfolio_id: str | None = None,
        status: str | None = None,
        limit: int = 100,
    ) -> list[ResearchRun]:
        with self._session_factory() as session:
            statement = select(DashboardRunRow)
            if strategy_id:
                statement = statement.where(DashboardRunRow.strategy_id == strategy_id)
            if portfolio_id:
                statement = statement.where(DashboardRunRow.portfolio_id == portfolio_id)
            if status:
                statement = statement.where(DashboardRunRow.status == status)
            rows = session.scalars(
                statement.order_by(DashboardRunRow.created_at.desc()).limit(limit)
            ).all()
            return [_run_from_row(row) for row in rows]

    def add_items(self, items: list[ResearchItem]) -> None:
        with self._session_factory.begin() as session:
            for item in items:
                session.merge(_item_to_row(item))

    def get_item(self, item_id: str) -> ResearchItem | None:
        with self._session_factory() as session:
            row = session.get(DashboardItemRow, item_id)
            return _item_from_row(row) if row else None

    def list_items(self, run_id: str) -> list[ResearchItem]:
        with self._session_factory() as session:
            rows = session.scalars(
                select(DashboardItemRow)
                .where(DashboardItemRow.run_id == run_id)
                .order_by(DashboardItemRow.created_at)
            ).all()
            return [_item_from_row(row) for row in rows]

    def add_feedback(self, feedback: FeedbackRecord) -> None:
        with self._session_factory.begin() as session:
            session.add(
                DashboardFeedbackRow(
                    feedback_id=feedback.feedback_id,
                    item_id=feedback.item_id,
                    feedback_type=feedback.feedback_type.value,
                    comment=feedback.comment,
                    created_at=feedback.created_at,
                )
            )

    def list_feedback(self, item_id: str) -> list[FeedbackRecord]:
        with self._session_factory() as session:
            rows = session.scalars(
                select(DashboardFeedbackRow)
                .where(DashboardFeedbackRow.item_id == item_id)
                .order_by(DashboardFeedbackRow.created_at)
            ).all()
            return [
                FeedbackRecord(
                    feedback_id=row.feedback_id,
                    item_id=row.item_id,
                    feedback_type=row.feedback_type,
                    comment=row.comment,
                    created_at=row.created_at,
                )
                for row in rows
            ]


def _run_to_row(run: ResearchRun) -> DashboardRunRow:
    return DashboardRunRow(
        run_id=run.run_id,
        decision_at=run.decision_at,
        strategy_id=run.strategy_id,
        version_id=run.version_id,
        portfolio_id=run.portfolio_id,
        universe=list(run.universe),
        status=run.status.value,
        summary=run.summary,
        item_count=run.item_count,
        published_count=run.published_count,
        abstained_count=run.abstained_count,
        aborted_count=run.aborted_count,
        created_at=run.created_at,
    )


def _item_to_row(item: ResearchItem) -> DashboardItemRow:
    return DashboardItemRow(
        item_id=item.item_id,
        run_id=item.run_id,
        symbol=item.symbol,
        signal_type=item.signal_type,
        confidence=item.confidence,
        statement=item.statement,
        workflow_run_id=item.workflow_run_id,
        snapshot_id=item.snapshot_id,
        status=item.status.value,
        abstain_reason=item.abstain_reason,
        rejection_reasons=list(item.rejection_reasons),
        evidence_ids=list(item.evidence_ids),
        claim_ids=list(item.claim_ids),
        risk_score=item.risk_score,
        counter_arguments=list(item.counter_arguments),
        portfolio_constraint_violations=list(item.portfolio_constraint_violations),
        created_at=item.created_at,
    )


def _run_from_row(row: DashboardRunRow) -> ResearchRun:
    return ResearchRun(
        run_id=row.run_id,
        decision_at=row.decision_at,
        strategy_id=row.strategy_id,
        version_id=row.version_id,
        portfolio_id=row.portfolio_id,
        universe=list(row.universe),
        status=row.status,
        summary=row.summary,
        item_count=row.item_count,
        published_count=row.published_count,
        abstained_count=row.abstained_count,
        aborted_count=row.aborted_count,
        created_at=row.created_at,
    )


def _item_from_row(row: DashboardItemRow) -> ResearchItem:
    return ResearchItem(
        item_id=row.item_id,
        run_id=row.run_id,
        symbol=row.symbol,
        signal_type=row.signal_type,
        confidence=row.confidence,
        statement=row.statement,
        workflow_run_id=row.workflow_run_id,
        snapshot_id=row.snapshot_id,
        status=row.status,
        abstain_reason=row.abstain_reason,
        rejection_reasons=list(row.rejection_reasons),
        evidence_ids=list(row.evidence_ids),
        claim_ids=list(row.claim_ids),
        risk_score=row.risk_score,
        counter_arguments=list(row.counter_arguments),
        portfolio_constraint_violations=list(row.portfolio_constraint_violations),
        created_at=row.created_at,
    )
