"""Research candidate dashboard API routes."""

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

Services = Annotated[DashboardServiceBundle, Depends(get_dashboard_services)]


class ResearchRunCreate(BaseModel):
    """Request body for triggering a dashboard research run."""

    strategy_id: str = Field(min_length=1)
    version_id: str = "default"
    decision_at: datetime | None = None
    portfolio_id: str | None = None
    symbols: list[str] | None = None


class FeedbackCreate(BaseModel):
    """Request body for recording item feedback."""

    feedback_type: FeedbackType = FeedbackType.COMMENT
    comment: str = ""


def _not_found(exc: KeyError) -> HTTPException:
    return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))


@router.get("/research-runs", response_model=list[ResearchRun])
def list_research_runs(
    services: Services,
    strategy_id: str | None = None,
    portfolio_id: str | None = None,
    status_filter: Annotated[str | None, Query(alias="status")] = None,
    limit: int = 100,
) -> list[ResearchRun]:
    """List dashboard research runs."""
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
    """Trigger a synchronous MVP research run."""
    return services.research.run_batch(
        decision_at=request.decision_at,
        strategy_id=request.strategy_id,
        version_id=request.version_id,
        portfolio_id=request.portfolio_id,
        symbols=request.symbols,
    )


@router.get("/research-runs/{run_id}", response_model=ResearchRun)
def get_research_run(run_id: str, services: Services) -> ResearchRun:
    """Return one dashboard run."""
    try:
        return services.query.get_run(run_id)
    except KeyError as exc:
        raise _not_found(exc) from exc


@router.get("/research-runs/{run_id}/items", response_model=list[ResearchItem])
def get_research_run_items(run_id: str, services: Services) -> list[ResearchItem]:
    """Return items for a dashboard run."""
    try:
        return services.query.get_run_items(run_id)
    except KeyError as exc:
        raise _not_found(exc) from exc


@router.get("/research-runs/{run_id}/cards", response_model=list[CandidateCard])
def get_research_run_cards(run_id: str, services: Services) -> list[CandidateCard]:
    """Return candidate cards for a dashboard run."""
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
    """Return the dashboard home summary."""
    return services.query.get_home_summary(
        strategy_id=strategy_id,
        portfolio_id=portfolio_id,
    )


@router.get("/research-items/{item_id}", response_model=ResearchItem)
def get_research_item(item_id: str, services: Services) -> ResearchItem:
    """Return one research item."""
    try:
        return services.query.get_item(item_id)
    except KeyError as exc:
        raise _not_found(exc) from exc


@router.get("/research-items/{item_id}/evidence", response_model=EvidenceView)
def get_research_item_evidence(item_id: str, services: Services) -> EvidenceView:
    """Return expanded evidence for a research item."""
    try:
        return services.evidence.get_evidence_view(item_id)
    except KeyError as exc:
        raise _not_found(exc) from exc


@router.get("/research-items/{item_id}/valuation", response_model=ValuationView)
def get_research_item_valuation(item_id: str, services: Services) -> ValuationView:
    """Return valuation details for a research item."""
    try:
        return services.valuation.get_valuation_view(item_id)
    except KeyError as exc:
        raise _not_found(exc) from exc


@router.get("/research-items/{item_id}/audit", response_model=AuditView)
def get_research_item_audit(item_id: str, services: Services) -> AuditView:
    """Return audit metadata for a research item."""
    try:
        return services.audit.get_audit_view(item_id)
    except KeyError as exc:
        raise _not_found(exc) from exc


@router.get("/research-items/{item_id}/report", response_model=ResearchReport)
def get_research_item_report(item_id: str, services: Services) -> ResearchReport:
    """Return a rendered research report for a dashboard item."""
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
    """Return a JSON-wrapped export payload for a research item report."""
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
    """Append feedback for a research item."""
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
    """Return provider health status used by the dashboard."""
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
    """Trigger a synchronous nightly run and return its job record."""
    run = create_research_run(request, services)
    return services.jobs.record_completed_job(run.run_id)


@router.get("/jobs/{job_run_id}", response_model=JobRun)
def get_job_run(job_run_id: str, services: Services) -> JobRun:
    """Return a dashboard job record."""
    try:
        return services.jobs.get_job(job_run_id)
    except KeyError as exc:
        raise _not_found(exc) from exc
