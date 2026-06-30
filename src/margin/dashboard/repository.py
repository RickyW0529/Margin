"""Persistence boundary for the research candidate dashboard module."""

from __future__ import annotations

import base64
import json
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Protocol

from sqlalchemy.orm import Session

from margin.dashboard.db_models import (
    DashboardFeedbackRow,
    DashboardItemRow,
    DashboardRunRow,
)
from margin.dashboard.models import (
    DashboardFilters,
    DashboardPageInfo,
    DashboardSort,
    FeedbackRecord,
    ItemStatus,
    ResearchCandidateListItemV2,
    ResearchCandidateListResponse,
    ResearchItem,
    ResearchRun,
)
from margin.sql.dashboard_queries import (
    dashboard_feedback_by_item,
    dashboard_items_by_run,
    dashboard_items_by_run_ids,
    dashboard_runs,
    dashboard_runs_by_scope,
)


class DashboardRepository(Protocol):
    """Repository contract consumed by dashboard query and orchestration services."""

    def add_run(self, run: ResearchRun) -> None:
        """Persist a dashboard run.

        Args:
            run: The research run to persist.
        """

    def get_run(self, run_id: str) -> ResearchRun | None:
        """Return one run by identifier.

        Args:
            run_id: Unique identifier of the run.

        Returns:
            The matching research run, or None if not found.
        """

    def list_runs(
        self,
        *,
        strategy_id: str | None = None,
        status: str | None = None,
        limit: int = 100,
    ) -> list[ResearchRun]:
        """Return dashboard runs sorted newest first.

        Args:
            strategy_id: Optional strategy filter.
            status: Optional status filter.
            limit: Maximum number of runs to return.

        Returns:
            A list of matching research runs.
        """

    def add_items(self, items: list[ResearchItem]) -> None:
        """Persist run items.

        Args:
            items: Research items to persist.
        """

    def get_item(self, item_id: str) -> ResearchItem | None:
        """Return one item by identifier.

        Args:
            item_id: Unique identifier of the item.

        Returns:
            The matching research item, or None if not found.
        """

    def list_items(self, run_id: str) -> list[ResearchItem]:
        """Return all items for a run.

        Args:
            run_id: Identifier of the parent research run.

        Returns:
            All research items belonging to the run.
        """

    def add_feedback(self, feedback: FeedbackRecord) -> None:
        """Append user feedback.

        Args:
            feedback: Feedback record to persist.
        """

    def list_feedback(self, item_id: str) -> list[FeedbackRecord]:
        """Return feedback for one item.

        Args:
            item_id: Identifier of the research item.

        Returns:
            A list of feedback records for the item.
        """

    def list_research_candidates_v2(
        self,
        *,
        scope_version_id: str,
        universe_code: str,
        filters: DashboardFilters,
        sort: DashboardSort,
        cursor: str | None,
        limit: int,
    ) -> ResearchCandidateListResponse:
        """Return one cursor page of v0.2 research candidate list items."""


class MemoryDashboardRepository:
    """In-memory dashboard repository for tests and local usage."""

    def __init__(self) -> None:
        """Initialize empty in-memory stores for runs, items, and feedback."""
        self._runs: dict[str, ResearchRun] = {}
        self._items: dict[str, ResearchItem] = {}
        self._feedback: dict[str, list[FeedbackRecord]] = {}

    def add_run(self, run: ResearchRun) -> None:
        """Persist a dashboard run in memory.

        Args:
            run: The research run to store.
        """
        self._runs[run.run_id] = run

    def get_run(self, run_id: str) -> ResearchRun | None:
        """Return one run by identifier.

        Args:
            run_id: Unique identifier of the run.

        Returns:
            The matching research run, or None if not found.
        """
        return self._runs.get(run_id)

    def list_runs(
        self,
        *,
        strategy_id: str | None = None,
        status: str | None = None,
        limit: int = 100,
    ) -> list[ResearchRun]:
        """Return dashboard runs sorted newest first.

        Args:
            strategy_id: Optional strategy filter.
            status: Optional status filter.
            limit: Maximum number of runs to return.

        Returns:
            A list of matching research runs.
        """
        runs = list(self._runs.values())
        if strategy_id:
            runs = [run for run in runs if run.strategy_id == strategy_id]
        if status:
            runs = [run for run in runs if run.status.value == status]
        runs.sort(key=lambda run: run.created_at, reverse=True)
        return runs[:limit]

    def add_items(self, items: list[ResearchItem]) -> None:
        """Persist run items in memory.

        Args:
            items: Research items to store.
        """
        for item in items:
            self._items[item.item_id] = item

    def get_item(self, item_id: str) -> ResearchItem | None:
        """Return one item by identifier.

        Args:
            item_id: Unique identifier of the item.

        Returns:
            The matching research item, or None if not found.
        """
        return self._items.get(item_id)

    def list_items(self, run_id: str) -> list[ResearchItem]:
        """Return all items for a run.

        Args:
            run_id: Identifier of the parent research run.

        Returns:
            All research items belonging to the run, sorted by created_at.
        """
        items = [item for item in self._items.values() if item.run_id == run_id]
        items.sort(key=lambda item: item.created_at)
        return items

    def add_feedback(self, feedback: FeedbackRecord) -> None:
        """Append user feedback in memory.

        Args:
            feedback: Feedback record to store.
        """
        self._feedback.setdefault(feedback.item_id, []).append(feedback)

    def list_feedback(self, item_id: str) -> list[FeedbackRecord]:
        """Return feedback for one item.

        Args:
            item_id: Identifier of the research item.

        Returns:
            A list of feedback records for the item.
        """
        return list(self._feedback.get(item_id, []))

    def list_research_candidates_v2(
        self,
        *,
        scope_version_id: str,
        universe_code: str,
        filters: DashboardFilters,
        sort: DashboardSort,
        cursor: str | None,
        limit: int,
    ) -> ResearchCandidateListResponse:
        """Return one cursor page of v0.2 research candidate list items."""
        del universe_code
        runs = [
            run for run in self._runs.values() if run.version_id == scope_version_id
        ]
        run_by_id = {run.run_id: run for run in runs}
        candidates = [
            _candidate_from_item(item, run_by_id[item.run_id])
            for item in self._items.values()
            if item.run_id in run_by_id
        ]
        return _candidate_page(
            candidates,
            scope_version_id=scope_version_id,
            filters=filters,
            sort=sort,
            cursor=cursor,
            limit=limit,
        )


class SQLAlchemyDashboardRepository:
    """PostgreSQL-backed dashboard repository."""

    def __init__(self, session_factory: Callable[[], Session]) -> None:
        """Initialize the repository with a SQLAlchemy session factory.

        Args:
            session_factory: Callable that returns a new SQLAlchemy session.
        """
        self._session_factory = session_factory

    def add_run(self, run: ResearchRun) -> None:
        """Persist a dashboard run to PostgreSQL.

        Args:
            run: The research run to persist.
        """
        with self._session_factory.begin() as session:
            session.merge(_run_to_row(run))

    def get_run(self, run_id: str) -> ResearchRun | None:
        """Return one run by identifier.

        Args:
            run_id: Unique identifier of the run.

        Returns:
            The matching research run, or None if not found.
        """
        with self._session_factory() as session:
            row = session.get(DashboardRunRow, run_id)
            return _run_from_row(row) if row else None

    def list_runs(
        self,
        *,
        strategy_id: str | None = None,
        status: str | None = None,
        limit: int = 100,
    ) -> list[ResearchRun]:
        """Return dashboard runs sorted newest first.

        Args:
            strategy_id: Optional strategy filter.
            status: Optional status filter.
            limit: Maximum number of runs to return.

        Returns:
            A list of matching research runs.
        """
        with self._session_factory() as session:
            statement = dashboard_runs(
                strategy_id=strategy_id,
                status=status,
                limit=limit,
            )
            rows = session.scalars(statement).all()
            return [_run_from_row(row) for row in rows]

    def add_items(self, items: list[ResearchItem]) -> None:
        """Persist run items to PostgreSQL.

        Args:
            items: Research items to persist.
        """
        with self._session_factory.begin() as session:
            for item in items:
                session.merge(_item_to_row(item))

    def get_item(self, item_id: str) -> ResearchItem | None:
        """Return one item by identifier.

        Args:
            item_id: Unique identifier of the item.

        Returns:
            The matching research item, or None if not found.
        """
        with self._session_factory() as session:
            row = session.get(DashboardItemRow, item_id)
            return _item_from_row(row) if row else None

    def list_items(self, run_id: str) -> list[ResearchItem]:
        """Return all items for a run.

        Args:
            run_id: Identifier of the parent research run.

        Returns:
            All research items belonging to the run, sorted by created_at.
        """
        with self._session_factory() as session:
            rows = session.scalars(
                dashboard_items_by_run(run_id)
            ).all()
            return [_item_from_row(row) for row in rows]

    def add_feedback(self, feedback: FeedbackRecord) -> None:
        """Append user feedback to PostgreSQL.

        Args:
            feedback: Feedback record to persist.
        """
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
        """Return feedback for one item.

        Args:
            item_id: Identifier of the research item.

        Returns:
            A list of feedback records for the item.
        """
        with self._session_factory() as session:
            rows = session.scalars(
                dashboard_feedback_by_item(item_id)
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

    def list_research_candidates_v2(
        self,
        *,
        scope_version_id: str,
        universe_code: str,
        filters: DashboardFilters,
        sort: DashboardSort,
        cursor: str | None,
        limit: int,
    ) -> ResearchCandidateListResponse:
        """Return one cursor page of v0.2 research candidate list items."""
        del universe_code
        with self._session_factory() as session:
            run_rows = session.scalars(
                dashboard_runs_by_scope(scope_version_id)
            ).all()
            run_by_id = {row.run_id: _run_from_row(row) for row in run_rows}
            if not run_by_id:
                return ResearchCandidateListResponse(
                    items=(),
                    page_info=DashboardPageInfo(page_size=limit),
                    facets={},
                    as_of=datetime.now(UTC),
                    scope_version_id=scope_version_id,
                )
            item_rows = session.scalars(
                dashboard_items_by_run_ids(tuple(run_by_id))
            ).all()
        candidates = [
            _candidate_from_item(_item_from_row(row), run_by_id[row.run_id])
            for row in item_rows
        ]
        return _candidate_page(
            candidates,
            scope_version_id=scope_version_id,
            filters=filters,
            sort=sort,
            cursor=cursor,
            limit=limit,
        )


def _run_to_row(run: ResearchRun) -> DashboardRunRow:
    """run to row."""
    return DashboardRunRow(
        run_id=run.run_id,
        decision_at=run.decision_at,
        strategy_id=run.strategy_id,
        version_id=run.version_id,
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
    """item to row."""
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
        created_at=item.created_at,
    )


def _run_from_row(row: DashboardRunRow) -> ResearchRun:
    """run from row."""
    return ResearchRun(
        run_id=row.run_id,
        decision_at=row.decision_at,
        strategy_id=row.strategy_id,
        version_id=row.version_id,
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
    """item from row."""
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
        created_at=row.created_at,
    )


def _candidate_from_item(
    item: ResearchItem,
    run: ResearchRun,
) -> ResearchCandidateListItemV2:
    """Build a v0.2 candidate list item from a research item and its run."""
    screening_status = "pass" if item.status == ItemStatus.PUBLISHED else item.status.value
    data_status = "complete" if item.status == ItemStatus.PUBLISHED else "partial"
    return ResearchCandidateListItemV2(
        item_id=item.item_id,
        security_id=item.symbol,
        symbol=item.symbol.split(".")[0],
        name=item.symbol,
        scope_version_id=run.version_id,
        screening_status=screening_status,
        data_status=data_status,
        risk_flags=tuple(item.rejection_reasons),
        review_required=item.status != ItemStatus.PUBLISHED,
        research_guardrail=(
            "allow_research"
            if item.status == ItemStatus.PUBLISHED
            else "review_required"
        ),
        current_review_outcome=(
            "update_assessment"
            if item.status == ItemStatus.PUBLISHED
            else "abstain"
        ),
        effective_assessment_id=item.snapshot_id,
        assessment_freshness="current" if item.status == ItemStatus.PUBLISHED else "stale",
        stale_reason=item.abstain_reason,
        final_score=round(item.confidence * 100, 4),
        discount_rate=None,
        confidence=item.confidence,
        last_checked_at=item.created_at,
    )


def _candidate_page(
    candidates: list[ResearchCandidateListItemV2],
    *,
    scope_version_id: str,
    filters: DashboardFilters,
    sort: DashboardSort,
    cursor: str | None,
    limit: int,
) -> ResearchCandidateListResponse:
    """Filter, sort, and paginate candidates into a cursor-paged response."""
    page_size = max(1, min(limit, 200))
    filtered = _apply_filters(candidates, filters)
    ordered = _sort_candidates(filtered, sort)
    start = _cursor_offset(ordered, cursor)
    page = ordered[start : start + page_size + 1]
    visible = tuple(page[:page_size])
    has_next = len(page) > page_size
    next_cursor = _encode_cursor(visible[-1], sort) if has_next and visible else None
    return ResearchCandidateListResponse(
        items=visible,
        page_info=DashboardPageInfo(
            next_cursor=next_cursor,
            has_next_page=has_next,
            page_size=page_size,
        ),
        facets=_facets(filtered),
        as_of=datetime.now(UTC),
        scope_version_id=scope_version_id,
    )


def _apply_filters(
    candidates: list[ResearchCandidateListItemV2],
    filters: DashboardFilters,
) -> list[ResearchCandidateListItemV2]:
    """Filter candidates by screening status, data status, freshness, and query text."""
    result = candidates
    if filters.screening_status:
        result = [
            item for item in result if item.screening_status == filters.screening_status
        ]
    if filters.data_status:
        result = [item for item in result if item.data_status == filters.data_status]
    if filters.review_required is not None:
        result = [
            item for item in result if item.review_required == filters.review_required
        ]
    if filters.assessment_freshness:
        result = [
            item
            for item in result
            if item.assessment_freshness == filters.assessment_freshness
        ]
    if filters.query:
        query = filters.query.lower()
        result = [
            item
            for item in result
            if query in item.symbol.lower()
            or query in item.security_id.lower()
            or query in item.name.lower()
        ]
    return result


def _sort_candidates(
    candidates: list[ResearchCandidateListItemV2],
    sort: DashboardSort,
) -> list[ResearchCandidateListItemV2]:
    """Sort candidates by the requested field and direction with a stable tiebreaker."""
    reverse = sort.direction == "desc"

    def key(item: ResearchCandidateListItemV2):
        """Return a sort key treating missing values as extremes."""
        value = getattr(item, sort.field)
        if value is None:
            value = -1 if reverse else float("inf")
        return (value, item.item_id)

    return sorted(candidates, key=key, reverse=reverse)


def _cursor_offset(
    ordered: list[ResearchCandidateListItemV2],
    cursor: str | None,
) -> int:
    """Return the start index for the next page based on a decoded cursor."""
    if not cursor:
        return 0
    decoded = _decode_cursor(cursor)
    item_id = decoded.get("item_id")
    for index, item in enumerate(ordered):
        if item.item_id == item_id:
            return index + 1
    return 0


def _encode_cursor(item: ResearchCandidateListItemV2, sort: DashboardSort) -> str:
    """Base64-encode a cursor payload identifying the last item of a page."""
    payload = {
        "item_id": item.item_id,
        "sort_field": sort.field,
        "sort_direction": sort.direction,
        "sort_value": getattr(item, sort.field),
    }
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _decode_cursor(cursor: str) -> dict[str, object]:
    """Decode a base64 cursor payload, returning an empty dict on failure."""
    padded = cursor + "=" * (-len(cursor) % 4)
    try:
        decoded = base64.urlsafe_b64decode(padded.encode("ascii"))
        payload = json.loads(decoded)
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def _facets(
    candidates: list[ResearchCandidateListItemV2],
) -> dict[str, dict[str, int]]:
    """Aggregate facet counts for screening status, data status, and freshness."""
    facets: dict[str, dict[str, int]] = {
        "screening_status": {},
        "data_status": {},
        "assessment_freshness": {},
    }
    for item in candidates:
        _increment(facets["screening_status"], item.screening_status)
        _increment(facets["data_status"], item.data_status)
        if item.assessment_freshness:
            _increment(facets["assessment_freshness"], item.assessment_freshness)
    return facets


def _increment(values: dict[str, int], key: str) -> None:
    """Increment the count for a facet key, initializing to 1 when absent."""
    values[key] = values.get(key, 0) + 1
