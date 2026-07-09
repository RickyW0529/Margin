"""News and filing query factory."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Delete, Select, delete, func, or_, select

from margin.news.db_models import (
    DedupRecordRow,
    DocumentEventRow,
    DocumentMaterialityScoreRow,
    DocumentOutboxRow,
    DocumentSecurityLinkRow,
    NewsAgentTaskRow,
    NewsArticleFindingRow,
    NewsRefreshTargetRow,
    NewsSearchPlanRow,
    NewsSecurityBriefRow,
    RepostEdgeRow,
    SearchResultRow,
)


def outbox_id_by_event_topic(event_id: str, topic: str) -> Select:
    """Return the outbox id for an event/topic pair, if present.

    Args:
        event_id: str: .
        topic: str: .

    Returns:
        Select: .
    """
    return select(DocumentOutboxRow.outbox_id).where(
        DocumentOutboxRow.event_id == event_id,
        DocumentOutboxRow.topic == topic,
    )


def unique_document_events() -> Select:
    """List events that have not been marked as duplicates.

    Returns:
        Select: .
    """
    duplicate_ids = select(DedupRecordRow.duplicate_event_id)
    return (
        select(DocumentEventRow)
        .where(DocumentEventRow.event_id.not_in(duplicate_ids))
        .order_by(DocumentEventRow.source_level, DocumentEventRow.published_at)
    )


def outbox_pending_by_topic(topic: str, limit: int) -> Select:
    """Claim pending outbox messages with SKIP LOCKED.

    Args:
        topic: str: .
        limit: int: .

    Returns:
        Select: .
    """
    return (
        select(DocumentOutboxRow)
        .where(
            DocumentOutboxRow.topic == topic,
            DocumentOutboxRow.status == "pending",
        )
        .order_by(DocumentOutboxRow.created_at, DocumentOutboxRow.outbox_id)
        .limit(limit)
        .with_for_update(skip_locked=True)
    )


def outbox_by_event_topic(event_id: str, topic: str) -> Select:
    """Return one outbox row by event/topic.

    Args:
        event_id: str: .
        topic: str: .

    Returns:
        Select: .
    """
    return select(DocumentOutboxRow).where(
        DocumentOutboxRow.event_id == event_id,
        DocumentOutboxRow.topic == topic,
    )


def outbox_claimable_by_topic(topic: str, cutoff: datetime, limit: int) -> Select:
    """Claim pending/retryable/expired processing outbox rows with SKIP LOCKED.

    Args:
        topic: str: .
        cutoff: datetime: .
        limit: int: .

    Returns:
        Select: .
    """
    return (
        select(DocumentOutboxRow)
        .where(
            DocumentOutboxRow.topic == topic,
            (
                DocumentOutboxRow.status.in_(["pending", "failed_retryable"])
                | (
                    (DocumentOutboxRow.status == "processing")
                    & (DocumentOutboxRow.claimed_at < cutoff)
                )
            ),
        )
        .order_by(DocumentOutboxRow.created_at, DocumentOutboxRow.outbox_id)
        .limit(limit)
        .with_for_update(skip_locked=True)
    )


def delete_search_results_by_query(query_id: str) -> Delete:
    """Delete all search result rows for a query.

    Args:
        query_id: str: .

    Returns:
        Delete: .
    """
    return delete(SearchResultRow).where(SearchResultRow.query_id == query_id)


def search_results_by_query(query_id: str) -> Select:
    """Return ordered search result rows for a query.

    Args:
        query_id: str: .

    Returns:
        Select: .
    """
    return (
        select(SearchResultRow)
        .where(SearchResultRow.query_id == query_id)
        .order_by(SearchResultRow.result_index)
    )


def repost_edges_by_parent(parent_event_id: str) -> Select:
    """List direct repost edges for a canonical event.

    Args:
        parent_event_id: str: .

    Returns:
        Select: .
    """
    return (
        select(RepostEdgeRow)
        .where(RepostEdgeRow.parent_event_id == parent_event_id)
        .order_by(RepostEdgeRow.created_at, RepostEdgeRow.child_event_id)
    )


def news_target_dedupe_keys_by_run(run_id: str) -> Select:
    """Return dedupe keys already persisted for a refresh run.

    Args:
        run_id: str: .

    Returns:
        Select: .
    """
    return select(NewsRefreshTargetRow.dedupe_key).where(NewsRefreshTargetRow.run_id == run_id)


def news_target_count_by_run(run_id: str) -> Select:
    """Count refresh targets for a run.

    Args:
        run_id: str: .

    Returns:
        Select: .
    """
    return (
        select(func.count())
        .select_from(NewsRefreshTargetRow)
        .where(NewsRefreshTargetRow.run_id == run_id)
    )


def claimable_news_targets(
    run_id: str,
    statuses: list[str],
    now: datetime,
    limit: int,
) -> Select:
    """Claim eligible pending/retry targets for processing with SKIP LOCKED.

    Args:
        run_id: str: .
        statuses: list[str]: .
        now: datetime: .
        limit: int: .

    Returns:
        Select: .
    """
    return (
        select(NewsRefreshTargetRow)
        .where(
            NewsRefreshTargetRow.run_id == run_id,
            NewsRefreshTargetRow.status.in_(statuses),
            or_(
                NewsRefreshTargetRow.next_attempt_at.is_(None),
                NewsRefreshTargetRow.next_attempt_at <= now,
            ),
        )
        .order_by(
            NewsRefreshTargetRow.priority.desc(),
            NewsRefreshTargetRow.next_attempt_at.asc().nullsfirst(),
            NewsRefreshTargetRow.created_at.asc(),
        )
        .limit(limit)
        .with_for_update(skip_locked=True)
    )


def news_targets_by_run(run_id: str) -> Select:
    """Return all refresh targets for a run.

    Args:
        run_id: str: .

    Returns:
        Select: .
    """
    return select(NewsRefreshTargetRow).where(NewsRefreshTargetRow.run_id == run_id)


def materiality_score_by_event_security_version(
    event_id: str,
    security_id: str,
    scoring_version: str,
) -> Select:
    """Return a materiality score row by event/security/version.

    Args:
        event_id: str: .
        security_id: str: .
        scoring_version: str: .

    Returns:
        Select: .
    """
    return select(DocumentMaterialityScoreRow).where(
        DocumentMaterialityScoreRow.event_id == event_id,
        DocumentMaterialityScoreRow.security_id == security_id,
        DocumentMaterialityScoreRow.scoring_version == scoring_version,
    )


def news_context_documents(security_id: str, max_documents: int) -> Select:
    """Return ranked context candidates for a security.

    Args:
        security_id: str: .
        max_documents: int: .

    Returns:
        Select: .
    """
    return (
        select(DocumentEventRow, DocumentMaterialityScoreRow)
        .join(
            DocumentSecurityLinkRow,
            DocumentSecurityLinkRow.event_id == DocumentEventRow.event_id,
        )
        .join(
            DocumentMaterialityScoreRow,
            (DocumentMaterialityScoreRow.event_id == DocumentEventRow.event_id)
            & (DocumentMaterialityScoreRow.security_id == DocumentSecurityLinkRow.security_id),
        )
        .where(DocumentSecurityLinkRow.security_id == security_id)
        .order_by(
            DocumentEventRow.source_level.asc(),
            DocumentMaterialityScoreRow.materiality_score.desc(),
            DocumentMaterialityScoreRow.novelty_score.desc(),
            DocumentEventRow.published_at.desc(),
        )
        .limit(max_documents)
    )


def news_target_statuses_by_run_security(
    run_id: str,
    security_id: str,
) -> Select:
    """List target statuses for one security in a refresh run.

    Args:
        run_id: str: .
        security_id: str: .

    Returns:
        Select: .
    """
    return (
        select(NewsRefreshTargetRow.status)
        .where(
            NewsRefreshTargetRow.run_id == run_id,
            NewsRefreshTargetRow.security_id == security_id,
        )
        .order_by(NewsRefreshTargetRow.priority.desc())
    )


def news_search_plans_by_run(run_id: str) -> Select:
    """Return reviewed agentic search plans for one run.

    Args:
        run_id: str: .

    Returns:
        Select: .
    """
    return (
        select(NewsSearchPlanRow)
        .where(NewsSearchPlanRow.run_id == run_id)
        .order_by(NewsSearchPlanRow.security_id, NewsSearchPlanRow.plan_id)
    )


def news_agent_tasks_by_run(run_id: str) -> Select:
    """Return agentic task audit rows for one run.

    Args:
        run_id: str: .

    Returns:
        Select: .
    """
    return (
        select(NewsAgentTaskRow)
        .where(NewsAgentTaskRow.run_id == run_id)
        .order_by(
            NewsAgentTaskRow.security_id.nullsfirst(),
            NewsAgentTaskRow.task_type,
            NewsAgentTaskRow.attempt,
            NewsAgentTaskRow.task_id,
        )
    )


def news_article_findings_by_run(
    run_id: str,
    security_id: str | None = None,
) -> Select:
    """Return article findings for one agentic run.

    Args:
        run_id: str: .
        security_id: str | None: .

    Returns:
        Select: .
    """
    statement = select(NewsArticleFindingRow).where(NewsArticleFindingRow.run_id == run_id)
    if security_id is not None:
        statement = statement.where(NewsArticleFindingRow.security_id == security_id)
    return statement.order_by(
        NewsArticleFindingRow.security_id,
        NewsArticleFindingRow.created_at,
        NewsArticleFindingRow.finding_id,
    )


def news_security_briefs_by_run(run_id: str) -> Select:
    """Return security briefs for one agentic run.

    Args:
        run_id: str: .

    Returns:
        Select: .
    """
    return (
        select(NewsSecurityBriefRow)
        .where(NewsSecurityBriefRow.run_id == run_id)
        .order_by(NewsSecurityBriefRow.security_id, NewsSecurityBriefRow.brief_id)
    )


def document_events_by_ids(event_ids: list[str]) -> Select:
    """Return document events by event ids.

    Args:
        event_ids: list[str]: .

    Returns:
        Select: .
    """
    return (
        select(DocumentEventRow)
        .where(DocumentEventRow.event_id.in_(event_ids))
        .order_by(DocumentEventRow.published_at, DocumentEventRow.event_id)
    )
