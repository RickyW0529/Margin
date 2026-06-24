"""Dashboard query factory."""

from __future__ import annotations

from sqlalchemy import Select, select

from margin.dashboard.db_models import (
    DashboardFeedbackRow,
    DashboardItemRow,
    DashboardRunRow,
)


def dashboard_runs(
    strategy_id: str | None = None,
    status: str | None = None,
    limit: int = 100,
) -> Select:
    """Return dashboard runs sorted newest first with optional filters."""
    statement = select(DashboardRunRow)
    if strategy_id:
        statement = statement.where(DashboardRunRow.strategy_id == strategy_id)
    if status:
        statement = statement.where(DashboardRunRow.status == status)
    return statement.order_by(DashboardRunRow.created_at.desc()).limit(limit)


def dashboard_items_by_run(run_id: str) -> Select:
    """Return all items for a run ordered by created_at."""
    return (
        select(DashboardItemRow)
        .where(DashboardItemRow.run_id == run_id)
        .order_by(DashboardItemRow.created_at)
    )


def dashboard_feedback_by_item(item_id: str) -> Select:
    """Return feedback for one item ordered by created_at."""
    return (
        select(DashboardFeedbackRow)
        .where(DashboardFeedbackRow.item_id == item_id)
        .order_by(DashboardFeedbackRow.created_at)
    )


def dashboard_runs_by_scope(scope_version_id: str) -> Select:
    """Return dashboard runs for a scope version."""
    return select(DashboardRunRow).where(
        DashboardRunRow.version_id == scope_version_id
    )


def dashboard_items_by_run_ids(run_ids: tuple[str, ...]) -> Select:
    """Return dashboard items for a set of run IDs."""
    return select(DashboardItemRow).where(
        DashboardItemRow.run_id.in_(run_ids)
    )
