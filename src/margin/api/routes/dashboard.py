"""Research candidate dashboard API routes for the Margin API.

This module implements the REST surface for the research candidate dashboard,
including research runs, candidate cards, evidence expansion, valuation views,
audit trails, report rendering, exports, feedback, provider status, and nightly
run job records.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field

from margin.api.dependencies import get_dashboard_services
from margin.dashboard.models import (
    AuditView,
    CandidateCard,
    EvidenceView,
    FeedbackRecord,
    FeedbackType,
    HomeSummary,
    JobRun,
    ProviderStatus,
    ReportExport,
    ReportFormat,
    ResearchItem,
    ResearchReport,
    ResearchRun,
    ValuationView,
)
from margin.dashboard.service import DashboardServiceBundle

router = APIRouter(prefix="/api/v1", tags=["dashboard"])
"""APIRouter exposing dashboard-related endpoints under ``/api/v1``."""

Services = Annotated[DashboardServiceBundle, Depends(get_dashboard_services)]
"""FastAPI dependency type that injects the dashboard service bundle."""


class ResearchRunCreate(BaseModel):
    """Request body for triggering a dashboard research run.

    Attributes:
        strategy_id: Identifier of the strategy to use for the run.
        version_id: Strategy version to use. Defaults to ``default``.
        decision_at: Optional timestamp that anchors the research decision.
        portfolio_id: Optional portfolio identifier used to scope the run.
        symbols: Optional list of symbols to evaluate. When omitted the run
            determines candidates internally.
    """

    strategy_id: str = Field(min_length=1)
    version_id: str = "default"
    decision_at: datetime | None = None
    portfolio_id: str | None = None
    symbols: list[str] | None = None


class FeedbackCreate(BaseModel):
    """Request body for recording feedback on a research item.

    Attributes:
        feedback_type: Kind of feedback being recorded. Defaults to ``COMMENT``.
        comment: Free-text comment attached to the feedback.
    """

    feedback_type: FeedbackType = FeedbackType.COMMENT
    comment: str = ""


def _not_found(exc: KeyError) -> HTTPException:
    """Convert a ``KeyError`` into an HTTP 404 exception.

    Args:
        exc: The original key error, typically raised when a dashboard entity
            identifier is not found.

    Returns:
        HTTPException: A 404 ``HTTPException`` carrying the original message.
    """
    return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))


@router.get("/research-runs", response_model=list[ResearchRun])
def list_research_runs(
    services: Services,
    strategy_id: str | None = None,
    portfolio_id: str | None = None,
    status_filter: Annotated[str | None, Query(alias="status")] = None,
    limit: int = 100,
) -> list[ResearchRun]:
    """List dashboard research runs with optional filters.

    Args:
        services: Dashboard service bundle used to query runs.
        strategy_id: Optional strategy identifier filter.
        portfolio_id: Optional portfolio identifier filter.
        status_filter: Optional run status filter supplied as the ``status``
            query parameter.
        limit: Maximum number of runs to return. Defaults to ``100``.

    Returns:
        list[ResearchRun]: Matching dashboard research runs.
    """
    return services.query.list_runs(
        strategy_id=strategy_id,
        portfolio_id=portfolio_id,
        status=status_filter,
        limit=limit,
    )


@router.post(
    "/research-runs",
    response_model=ResearchRun,
    status_code=status.HTTP_201_CREATED,
)
def create_research_run(
    request: ResearchRunCreate,
    services: Services,
) -> ResearchRun:
    """Trigger a synchronous MVP research run.

    Args:
        request: Validated research run creation request.
        services: Dashboard service bundle used to execute the run.

    Returns:
        ResearchRun: The created research run record.
    """
    return services.research.run_batch(
        decision_at=request.decision_at,
        strategy_id=request.strategy_id,
        version_id=request.version_id,
        portfolio_id=request.portfolio_id,
        symbols=request.symbols,
    )


@router.get("/research-runs/{run_id}", response_model=ResearchRun)
def get_research_run(run_id: str, services: Services) -> ResearchRun:
    """Return a single dashboard research run.

    Args:
        run_id: Unique identifier of the research run.
        services: Dashboard service bundle used to load the run.

    Returns:
        ResearchRun: The requested research run.

    Raises:
        HTTPException: 404 if the run cannot be found.
    """
    try:
        return services.query.get_run(run_id)
    except KeyError as exc:
        raise _not_found(exc) from exc


@router.get("/research-runs/{run_id}/items", response_model=list[ResearchItem])
def get_research_run_items(run_id: str, services: Services) -> list[ResearchItem]:
    """Return research items produced by a dashboard run.

    Args:
        run_id: Unique identifier of the research run.
        services: Dashboard service bundle used to load items.

    Returns:
        list[ResearchItem]: Research items belonging to the run.

    Raises:
        HTTPException: 404 if the run cannot be found.
    """
    try:
        return services.query.get_run_items(run_id)
    except KeyError as exc:
        raise _not_found(exc) from exc


@router.get("/research-runs/{run_id}/cards", response_model=list[CandidateCard])
def get_research_run_cards(run_id: str, services: Services) -> list[CandidateCard]:
    """Return candidate cards for a dashboard run.

    Args:
        run_id: Unique identifier of the research run.
        services: Dashboard service bundle used to load candidate cards.

    Returns:
        list[CandidateCard]: Candidate cards belonging to the run.

    Raises:
        HTTPException: 404 if the run cannot be found.
    """
    try:
        return services.query.get_candidate_cards(run_id)
    except KeyError as exc:
        raise _not_found(exc) from exc


@router.get("/research-home", response_model=HomeSummary)
def get_research_home(
    services: Services,
    strategy_id: str | None = None,
    portfolio_id: str | None = None,
) -> HomeSummary:
    """Return the dashboard home summary.

    Args:
        services: Dashboard service bundle used to build the summary.
        strategy_id: Optional strategy identifier used to scope the summary.
        portfolio_id: Optional portfolio identifier used to scope the summary.

    Returns:
        HomeSummary: Aggregated home-page metrics for the dashboard.
    """
    return services.query.get_home_summary(
        strategy_id=strategy_id,
        portfolio_id=portfolio_id,
    )


@router.get("/research-items/{item_id}", response_model=ResearchItem)
def get_research_item(item_id: str, services: Services) -> ResearchItem:
    """Return a single research item.

    Args:
        item_id: Unique identifier of the research item.
        services: Dashboard service bundle used to load the item.

    Returns:
        ResearchItem: The requested research item.

    Raises:
        HTTPException: 404 if the item cannot be found.
    """
    try:
        return services.query.get_item(item_id)
    except KeyError as exc:
        raise _not_found(exc) from exc


@router.get("/research-items/{item_id}/evidence", response_model=EvidenceView)
def get_research_item_evidence(item_id: str, services: Services) -> EvidenceView:
    """Return expanded evidence for a research item.

    Args:
        item_id: Unique identifier of the research item.
        services: Dashboard service bundle used to load the evidence view.

    Returns:
        EvidenceView: Expanded evidence for the item.

    Raises:
        HTTPException: 404 if the item cannot be found.
    """
    try:
        return services.evidence.get_evidence_view(item_id)
    except KeyError as exc:
        raise _not_found(exc) from exc


@router.get("/research-items/{item_id}/valuation", response_model=ValuationView)
def get_research_item_valuation(item_id: str, services: Services) -> ValuationView:
    """Return valuation details for a research item.

    Args:
        item_id: Unique identifier of the research item.
        services: Dashboard service bundle used to load the valuation view.

    Returns:
        ValuationView: Valuation analysis for the item.

    Raises:
        HTTPException: 404 if the item cannot be found.
    """
    try:
        return services.valuation.get_valuation_view(item_id)
    except KeyError as exc:
        raise _not_found(exc) from exc


@router.get("/research-items/{item_id}/audit", response_model=AuditView)
def get_research_item_audit(item_id: str, services: Services) -> AuditView:
    """Return audit metadata for a research item.

    Args:
        item_id: Unique identifier of the research item.
        services: Dashboard service bundle used to load the audit view.

    Returns:
        AuditView: Audit metadata for the item.

    Raises:
        HTTPException: 404 if the item cannot be found.
    """
    try:
        return services.audit.get_audit_view(item_id)
    except KeyError as exc:
        raise _not_found(exc) from exc


@router.get("/research-items/{item_id}/report", response_model=ResearchReport)
def get_research_item_report(item_id: str, services: Services) -> ResearchReport:
    """Return a rendered research report for a dashboard item.

    Args:
        item_id: Unique identifier of the research item.
        services: Dashboard service bundle used to render the report.

    Returns:
        ResearchReport: The rendered research report.

    Raises:
        HTTPException: 404 if the item cannot be found.
    """
    try:
        return services.reports.render_report(item_id)
    except KeyError as exc:
        raise _not_found(exc) from exc


@router.get("/research-items/{item_id}/export", response_model=ReportExport)
def export_research_item_report(
    item_id: str,
    services: Services,
    report_format: Annotated[ReportFormat, Query(alias="format")] = ReportFormat.MARKDOWN,
) -> ReportExport:
    """Return a JSON-wrapped export payload for a research item report.

    Args:
        item_id: Unique identifier of the research item.
        services: Dashboard service bundle used to export the report.
        report_format: Desired export format supplied as the ``format`` query
            parameter. Defaults to ``ReportFormat.MARKDOWN``.

    Returns:
        ReportExport: The exported report payload.

    Raises:
        HTTPException: 404 if the item cannot be found.
    """
    try:
        return services.exports.export_report(item_id, report_format)
    except KeyError as exc:
        raise _not_found(exc) from exc


@router.post(
    "/research-items/{item_id}/feedback",
    response_model=FeedbackRecord,
    status_code=status.HTTP_201_CREATED,
)
def create_research_item_feedback(
    item_id: str,
    request: FeedbackCreate,
    services: Services,
) -> FeedbackRecord:
    """Append feedback for a research item.

    Args:
        item_id: Unique identifier of the research item.
        request: Validated feedback creation request.
        services: Dashboard service bundle used to record feedback.

    Returns:
        FeedbackRecord: The newly created feedback record.

    Raises:
        HTTPException: 404 if the item cannot be found.
    """
    try:
        return services.feedback.record_feedback(
            item_id,
            request.feedback_type,
            request.comment,
        )
    except KeyError as exc:
        raise _not_found(exc) from exc


@router.get("/provider-status", response_model=list[ProviderStatus])
def get_provider_status(services: Services) -> list[ProviderStatus]:
    """Return provider health status used by the dashboard.

    Args:
        services: Dashboard service bundle that owns provider status.

    Returns:
        list[ProviderStatus]: Health status for each configured or missing
        provider.
    """
    return services.providers.list_status()


@router.post(
    "/jobs/nightly-runs",
    response_model=JobRun,
    status_code=status.HTTP_201_CREATED,
)
def create_nightly_run_job(
    request: ResearchRunCreate,
    services: Services,
) -> JobRun:
    """Trigger a synchronous nightly run and return its job record.

    Args:
        request: Validated research run creation request used to drive the
            nightly run.
        services: Dashboard service bundle used to execute and record the job.

    Returns:
        JobRun: The job record for the completed nightly run.
    """
    run = create_research_run(request, services)
    return services.jobs.record_completed_job(run.run_id)


@router.get("/jobs/{job_run_id}", response_model=JobRun)
def get_job_run(job_run_id: str, services: Services) -> JobRun:
    """Return a dashboard job record.

    Args:
        job_run_id: Unique identifier of the job run.
        services: Dashboard service bundle used to load the job record.

    Returns:
        JobRun: The requested job run record.

    Raises:
        HTTPException: 404 if the job run cannot be found.
    """
    try:
        return services.jobs.get_job(job_run_id)
    except KeyError as exc:
        raise _not_found(exc) from exc
