"""Valuation discovery API routes."""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict, Field

from margin.api.dependencies import (
    get_company_profile_service,
    get_strategy_service,
    get_valuation_discovery_service_for_api,
    require_idempotency_key,
    require_local_admin,
)
from margin.strategy.service import StrategyService
from margin.valuation_discovery.service import (
    CompanyAnalysisProfile,
    CompanyProfileService,
    CompanyQuantProfile,
    FactorScoreItem,
    ValuationDiscoveryService,
)

router = APIRouter(prefix="/api/v1/valuation-discovery", tags=["valuation-discovery"])
logger = logging.getLogger(__name__)


class StartRefreshRequest(BaseModel):
    """Request body for starting a valuation discovery refresh.."""

    model_config = ConfigDict(extra="forbid")

    scope_version_id: str = Field(min_length=1, max_length=64)
    decision_at: datetime


class StartRefreshResponse(BaseModel):
    """Accepted refresh response.."""

    run_id: str
    status: str
    http_status: int


class RefreshStatusResponse(BaseModel):
    """Valuation discovery refresh run status.."""

    run_id: str
    state: str
    scope_version_id: str
    steps: list[dict[str, Any]]


class RefreshSummaryResponse(BaseModel):
    """One refresh run row in the list view.."""

    run_id: str
    state: str
    scope_version_id: str
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None


class RefreshListResponse(BaseModel):
    """Paginated refresh run list response.."""

    items: list[RefreshSummaryResponse]
    next_cursor: str | None
    page_size: int


TERMINAL_STATES = frozenset({"succeeded", "failed_final", "cancelled", "skipped"})


def _has_next(items: list, limit: int) -> str | None:
    """Return a cursor for the last item when more rows may exist.

    Args:
        items: list: .
        limit: int: .

    Returns:
        str | None: .
    """
    if len(items) >= limit and items:
        return items[-1].run_id
    return None


@router.post(
    "/refreshes",
    response_model=StartRefreshResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
def start_refresh(
    request: StartRefreshRequest,
    background_tasks: BackgroundTasks,
    idempotency_key: Annotated[str, Depends(require_idempotency_key)],
    _actor_id: Annotated[str, Depends(require_local_admin)],
    strategy_service: Annotated[StrategyService, Depends(get_strategy_service)],
    service: Annotated[
        ValuationDiscoveryService,
        Depends(get_valuation_discovery_service_for_api),
    ],
) -> StartRefreshResponse:
    """Start a valuation discovery refresh.

    Args:
        request: StartRefreshRequest: .
        background_tasks: BackgroundTasks: .
        idempotency_key: Annotated[str, Depends(require_idempotency_key)]: .
        _actor_id: Annotated[str, Depends(require_local_admin)]: .
        strategy_service: Annotated[StrategyService, Depends(get_strategy_service)]: .
        service: Annotated[
            ValuationDiscoveryService,
            Depends(get_valuation_discovery_service_for_api),
        ]: .

    Returns:
        StartRefreshResponse: .
    """
    scope_version_id = _resolve_scope_alias(
        request.scope_version_id,
        strategy_service=strategy_service,
    )
    response = service.start_refresh(
        scope_version_id=scope_version_id,
        decision_at=request.decision_at,
        idempotency_key=idempotency_key,
    )
    background_tasks.add_task(_wake_refresh_worker, service)
    return StartRefreshResponse(
        run_id=response.run_id,
        status=response.status,
        http_status=response.http_status,
    )


def _wake_refresh_worker(service: ValuationDiscoveryService) -> None:
    """Best-effort worker wake after a refresh request is accepted.

    Args:
        service: ValuationDiscoveryService: .

    Returns:
        None: .
    """
    try:
        service.wake_refresh_worker(max_steps=1)
    except Exception:  # noqa: BLE001
        logger.exception("valuation_refresh_worker_wakeup_failed")


def _resolve_scope_alias(
    scope_version_id: str,
    *,
    strategy_service: StrategyService,
    owner_id: str = "local-admin",
) -> str:
    """Resolve user-facing scope aliases to persisted scope version IDs.

    Args:
        scope_version_id: str: .
        strategy_service: StrategyService: .
        owner_id: str: .

    Returns:
        str: .
    """
    if scope_version_id != "scope-current":
        return scope_version_id
    try:
        scope = strategy_service.ensure_current_research_scope(owner_id)
    except KeyError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "code": "service_not_configured",
                "message": "active research scope not found",
            },
        ) from exc
    return str(scope.version_id)


@router.get(
    "/runs",
    response_model=RefreshListResponse,
)
def list_refresh_runs(
    service: Annotated[
        ValuationDiscoveryService,
        Depends(get_valuation_discovery_service_for_api),
    ],
    scope_version_id: Annotated[str | None, Query()] = None,
    state: Annotated[str | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> RefreshListResponse:
    """List recent valuation-discovery refresh runs, newest first.

    Args:
        service: Annotated[
            ValuationDiscoveryService,
            Depends(get_valuation_discovery_service_for_api),
        ]: .
        scope_version_id: Annotated[str | None, Query()]: .
        state: Annotated[str | None, Query()]: .
        limit: Annotated[int, Query(ge=1, le=200)]: .

    Returns:
        RefreshListResponse: .
    """
    summaries = service.list_refreshes(
        scope_version_id=scope_version_id,
        state=state,
        limit=limit + 1,
    )
    items = summaries[:limit]
    return RefreshListResponse(
        items=[
            RefreshSummaryResponse(
                run_id=item.run_id,
                state=item.state,
                scope_version_id=item.scope_version_id,
                created_at=item.created_at,
                started_at=item.started_at,
                finished_at=item.finished_at,
            )
            for item in items
        ],
        next_cursor=items[-1].run_id if len(summaries) > limit and items else None,
        page_size=len(items),
    )


@router.get(
    "/runs/{run_id}",
    response_model=RefreshStatusResponse,
)
def get_refresh_status(
    run_id: str,
    service: Annotated[
        ValuationDiscoveryService,
        Depends(get_valuation_discovery_service_for_api),
    ],
) -> RefreshStatusResponse:
    """Return the status of a valuation discovery refresh run.

    Args:
        run_id: str: .
        service: Annotated[
            ValuationDiscoveryService,
            Depends(get_valuation_discovery_service_for_api),
        ]: .

    Returns:
        RefreshStatusResponse: .
    """
    status_dto = service.get_refresh_status(run_id)
    if status_dto is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"refresh run '{run_id}' not found",
        )
    return RefreshStatusResponse(
        run_id=status_dto.run_id,
        state=status_dto.state,
        scope_version_id=status_dto.scope_version_id,
        steps=status_dto.steps,
    )


# ---------------------------------------------------------------------------
# Company quant / analysis profile endpoints (visualization-facing)
# ---------------------------------------------------------------------------


class FactorScoreItemResponse(BaseModel):
    """Single factor group score with label and weight.."""

    model_config = ConfigDict(frozen=True)

    factor_key: str
    label: str
    score: float | None = None
    weight: float


class CompanyQuantProfileResponse(BaseModel):
    """Quant screening profile for one security, ready for visualization.."""

    model_config = ConfigDict(frozen=True)

    security_id: str
    quant_run_id: str
    result_id: str
    decision_at: datetime
    final_score: float
    factor_scores: list[FactorScoreItemResponse]
    rank_overall: int | None = None
    rank_in_industry: int | None = None
    screening_status: str
    data_status: str
    risk_flags: list[str] = Field(default_factory=list)
    review_required: bool = False
    review_reasons: list[str] = Field(default_factory=list)
    research_guardrail: str
    reason_summary: str = ""
    factor_details: dict[str, Any] = Field(default_factory=dict)


class AnalysisMetricResponse(BaseModel):
    """One Analysis Mart metric row.."""

    model_config = ConfigDict(frozen=True)

    metric_id: str
    metric_code: str
    metric_name: str
    metric_group: str
    numeric_value: float | None = None
    unit: str | None = None
    direction: str
    percentile_market: float | None = None
    percentile_industry: float | None = None
    rank_market: int | None = None
    rank_industry: int | None = None


class AnalysisFindingResponse(BaseModel):
    """One Analysis Mart finding row.."""

    model_config = ConfigDict(frozen=True)

    finding_id: str
    finding_type: str
    severity: str
    title: str
    description: str
    confidence: float
    evidence_ids: list[str] = Field(default_factory=list)


class AnalysisSnapshotHeaderResponse(BaseModel):
    """Header metadata for an analysis snapshot.."""

    model_config = ConfigDict(frozen=True)

    analysis_snapshot_id: str
    decision_at: datetime
    trading_date: str
    analysis_version: str
    analysis_kind: str
    quant_run_id: str | None = None
    quant_result_id: str | None = None
    input_hash: str
    result_hash: str


class CompanyAnalysisProfileResponse(BaseModel):
    """Fourth-layer Analysis Mart profile for one security.."""

    model_config = ConfigDict(frozen=True)

    security_id: str
    snapshot: AnalysisSnapshotHeaderResponse | None = None
    metrics: list[AnalysisMetricResponse] = Field(default_factory=list)
    findings: list[AnalysisFindingResponse] = Field(default_factory=list)
    evidence_link_count: int = 0


ProfileService = Annotated[CompanyProfileService, Depends(get_company_profile_service)]


def _quant_profile_to_response(profile: CompanyQuantProfile) -> CompanyQuantProfileResponse:
    """Convert a company quant profile DTO to its HTTP response model.

    Args:
        profile: CompanyQuantProfile: .

    Returns:
        CompanyQuantProfileResponse: .
    """
    return CompanyQuantProfileResponse(
        security_id=profile.security_id,
        quant_run_id=profile.quant_run_id,
        result_id=profile.result_id,
        decision_at=profile.decision_at,
        final_score=profile.final_score,
        factor_scores=[_factor_item_to_response(item) for item in profile.factor_scores],
        rank_overall=profile.rank_overall,
        rank_in_industry=profile.rank_in_industry,
        screening_status=profile.screening_status,
        data_status=profile.data_status,
        risk_flags=list(profile.risk_flags),
        review_required=profile.review_required,
        review_reasons=list(profile.review_reasons),
        research_guardrail=profile.research_guardrail,
        reason_summary=profile.reason_summary,
        factor_details=dict(profile.factor_details),
    )


def _factor_item_to_response(item: FactorScoreItem) -> FactorScoreItemResponse:
    """Convert a factor score item DTO to its HTTP response model.

    Args:
        item: FactorScoreItem: .

    Returns:
        FactorScoreItemResponse: .
    """
    return FactorScoreItemResponse(
        factor_key=item.factor_key,
        label=item.label,
        score=item.score,
        weight=item.weight,
    )


def _analysis_profile_to_response(
    profile: CompanyAnalysisProfile,
) -> CompanyAnalysisProfileResponse:
    """Convert a company analysis profile DTO to its HTTP response model.

    Args:
        profile: CompanyAnalysisProfile: .

    Returns:
        CompanyAnalysisProfileResponse: .
    """
    snapshot = profile.analysis_snapshot
    return CompanyAnalysisProfileResponse(
        security_id=profile.security_id,
        snapshot=_snapshot_to_response(snapshot) if snapshot is not None else None,
        metrics=[_metric_to_response(m) for m in profile.metrics],
        findings=[_finding_to_response(f) for f in profile.findings],
        evidence_link_count=profile.evidence_link_count,
    )


def _snapshot_to_response(snapshot: Any) -> AnalysisSnapshotHeaderResponse:
    """Convert an AnalysisSnapshot dataclass to its HTTP response model.

    Args:
        snapshot: Any: .

    Returns:
        AnalysisSnapshotHeaderResponse: .
    """
    return AnalysisSnapshotHeaderResponse(
        analysis_snapshot_id=snapshot.analysis_snapshot_id,
        decision_at=snapshot.decision_at,
        trading_date=str(snapshot.trading_date),
        analysis_version=snapshot.analysis_version,
        analysis_kind=snapshot.analysis_kind,
        quant_run_id=snapshot.quant_run_id,
        quant_result_id=snapshot.quant_result_id,
        input_hash=snapshot.input_hash,
        result_hash=snapshot.result_hash,
    )


def _metric_to_response(metric: Any) -> AnalysisMetricResponse:
    """Convert an AnalysisMetric dataclass to its HTTP response model.

    Args:
        metric: Any: .

    Returns:
        AnalysisMetricResponse: .
    """
    return AnalysisMetricResponse(
        metric_id=metric.metric_id,
        metric_code=metric.metric_code,
        metric_name=metric.metric_name,
        metric_group=metric.metric_group,
        numeric_value=metric.numeric_value,
        unit=metric.unit,
        direction=metric.direction,
        percentile_market=metric.percentile_market,
        percentile_industry=metric.percentile_industry,
        rank_market=metric.rank_market,
        rank_industry=metric.rank_industry,
    )


def _finding_to_response(finding: Any) -> AnalysisFindingResponse:
    """Convert an AnalysisFinding dataclass to its HTTP response model.

    Args:
        finding: Any: .

    Returns:
        AnalysisFindingResponse: .
    """
    return AnalysisFindingResponse(
        finding_id=finding.finding_id,
        finding_type=finding.finding_type,
        severity=finding.severity,
        title=finding.title,
        description=finding.description,
        confidence=finding.confidence,
        evidence_ids=list(finding.evidence_ids),
    )


@router.get(
    "/companies/{security_id}/quant",
    response_model=CompanyQuantProfileResponse,
)
def get_company_quant_profile(
    security_id: str,
    service: ProfileService,
) -> CompanyQuantProfileResponse:
    """Return the latest quant screening profile for a security.

    Args:
        security_id: str: .
        service: ProfileService: .

    Returns:
        CompanyQuantProfileResponse: .
    """
    profile = service.get_quant_profile(security_id)
    if profile is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"no quant result found for security '{security_id}'",
        )
    return _quant_profile_to_response(profile)


@router.get(
    "/companies/{security_id}/analysis",
    response_model=CompanyAnalysisProfileResponse,
)
def get_company_analysis_profile(
    security_id: str,
    service: ProfileService,
    scope_version_id: Annotated[str | None, Query(max_length=64)] = None,
) -> CompanyAnalysisProfileResponse:
    """Return the Analysis Mart profile for a security.

    Args:
        security_id: str: .
        service: ProfileService: .
        scope_version_id: Annotated[str | None, Query(max_length=64)]: .

    Returns:
        CompanyAnalysisProfileResponse: .
    """
    profile = service.get_analysis_profile(
        security_id=security_id,
        scope_version_id=scope_version_id,
    )
    return _analysis_profile_to_response(profile)
