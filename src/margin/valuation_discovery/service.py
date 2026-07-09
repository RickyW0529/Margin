"""Application service for valuation discovery refreshes."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from margin.core.run_states import OrchestrationRun, StepAttempt
from margin.valuation_discovery.analysis_mart import (
    AnalysisFinding,
    AnalysisMartRepository,
    AnalysisMetric,
    AnalysisSnapshot,
)
from margin.valuation_discovery.models import QuantResult
from margin.valuation_discovery.orchestrator import (
    ValuationDiscoveryOrchestrator,
    ValuationDiscoveryStepWorker,
)
from margin.valuation_discovery.quant.repository import QuantRepository


@dataclass(frozen=True)
class RefreshStartResponse:
    """DTO returned to HTTP/API callers when a refresh is accepted.."""

    run_id: str
    status: str = "accepted"
    http_status: int = 202


@dataclass(frozen=True)
class RefreshStatus:
    """DTO describing the current status of a refresh run.."""

    run_id: str
    state: str
    scope_version_id: str
    steps: list[dict]


@dataclass(frozen=True)
class RefreshSummary:
    """DTO describing one refresh run row in a list view.."""

    run_id: str
    state: str
    scope_version_id: str
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None


class ValuationDiscoveryService:
    """Thin application boundary around the valuation discovery orchestrator.."""

    def __init__(self, orchestrator: ValuationDiscoveryOrchestrator) -> None:
        """Initialize the service with a valuation discovery orchestrator.

        Args:
            orchestrator: ValuationDiscoveryOrchestrator: .

        Returns:
            None: .
        """
        self._orchestrator = orchestrator

    def start_refresh(
        self,
        *,
        scope_version_id: str,
        decision_at: datetime,
        idempotency_key: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> RefreshStartResponse:
        """Start a refresh and return an accepted response DTO.

        Args:
            scope_version_id: str: .
            decision_at: datetime: .
            idempotency_key: str | None: .
            metadata: dict[str, Any] | None: .

        Returns:
            RefreshStartResponse: .
        """
        run = self._orchestrator.start(
            scope_version_id=scope_version_id,
            decision_at=decision_at,
            idempotency_key=idempotency_key,
            metadata=metadata,
        )
        return _response_from_run(run)

    def wake_refresh_worker(
        self,
        *,
        max_steps: int = 1,
        now: datetime | None = None,
        worker_id: str = "api-refresh-wakeup",
    ) -> int:
        """Wake a valuation-discovery worker once after accepting a refresh.

        Args:
            max_steps: int: .
            now: datetime | None: .
            worker_id: str: .

        Returns:
            int: .
        """
        if max_steps <= 0:
            raise ValueError("max_steps must be positive")
        processed = 0
        worker = self.create_step_worker(worker_id=worker_id)
        claimed_at = now or datetime.now(UTC)
        for _ in range(max_steps):
            if not worker.run_once(now=claimed_at):
                break
            processed += 1
            claimed_at = datetime.now(UTC)
        return processed

    def get_refresh_status(self, run_id: str) -> RefreshStatus | None:
        """Return the status of a refresh run, or ``None`` if not found.

        Args:
            run_id: str: .

        Returns:
            RefreshStatus | None: .
        """
        run = self._orchestrator.get_run(run_id)
        if run is None:
            return None
        steps = self._orchestrator.list_steps(run_id)
        return RefreshStatus(
            run_id=run.run_id,
            state=run.state.value,
            scope_version_id=run.scope_version_id or "",
            steps=[_step_to_dict(step) for step in steps.values()],
        )

    def list_refreshes(
        self,
        *,
        scope_version_id: str | None = None,
        state: str | None = None,
        limit: int = 50,
    ) -> list[RefreshSummary]:
        """Return recent refresh runs, newest first.

        Args:
            scope_version_id: str | None: .
            state: str | None: .
            limit: int: .

        Returns:
            list[RefreshSummary]: .
        """
        runs = self._orchestrator.list_runs(
            scope_version_id=scope_version_id,
            state=state,
            limit=limit,
        )
        return [
            RefreshSummary(
                run_id=run.run_id,
                state=run.state.value,
                scope_version_id=run.scope_version_id or "",
                created_at=run.created_at,
                started_at=run.started_at,
                finished_at=run.finished_at,
            )
            for run in runs
        ]

    def create_step_worker(self, *, worker_id: str) -> ValuationDiscoveryStepWorker:
        """Create a lease worker sharing this service's durable dependencies.

        Args:
            worker_id: str: .

        Returns:
            ValuationDiscoveryStepWorker: .
        """
        return ValuationDiscoveryStepWorker(
            self._orchestrator.dependencies,
            worker_id=worker_id,
        )


def _step_to_dict(step: StepAttempt) -> dict:
    """Convert a step attempt into a JSON-serializable dictionary.

    Args:
        step: StepAttempt: .

    Returns:
        dict: .
    """
    return {
        "step_id": step.step_id,
        "state": step.state.value,
        "attempt_no": step.attempt_no,
        "output_ref": step.output_ref,
        "error_code": step.error_code,
        "started_at": step.started_at.isoformat() if step.started_at else None,
        "finished_at": step.finished_at.isoformat() if step.finished_at else None,
    }


def _response_from_run(run: OrchestrationRun) -> RefreshStartResponse:
    """Convert an orchestration run into a refresh start response DTO.

    Args:
        run: OrchestrationRun: .

    Returns:
        RefreshStartResponse: .
    """
    return RefreshStartResponse(run_id=run.run_id)


# ---------------------------------------------------------------------------
# Company quant / analysis profile DTOs and query helpers
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class FactorScoreItem:
    """Single factor group score with label and weight.."""

    factor_key: str
    label: str
    score: float | None
    weight: float


@dataclass(frozen=True)
class CompanyQuantProfile:
    """Quant screening profile for one security, ready for visualization.."""

    security_id: str
    quant_run_id: str
    result_id: str
    decision_at: datetime
    final_score: float
    factor_scores: tuple[FactorScoreItem, ...]
    rank_overall: int | None
    rank_in_industry: int | None
    screening_status: str
    data_status: str
    risk_flags: tuple[str, ...]
    review_required: bool
    review_reasons: tuple[str, ...]
    research_guardrail: str
    reason_summary: str
    factor_details: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class CompanyAnalysisProfile:
    """Fourth-layer Analysis Mart profile for one security.."""

    security_id: str
    analysis_snapshot: AnalysisSnapshot | None
    metrics: tuple[AnalysisMetric, ...]
    findings: tuple[AnalysisFinding, ...]
    evidence_link_count: int


_FACTOR_LABELS: dict[str, str] = {
    "quality_score": "质量",
    "value_score": "价值",
    "growth_score": "成长",
    "momentum_score": "动量",
    "risk_score": "风险",
}

_FACTOR_KEYS: tuple[str, ...] = (
    "quality_score",
    "value_score",
    "growth_score",
    "momentum_score",
    "risk_score",
)

_FACTOR_WEIGHTS: dict[str, float] = {
    "quality_score": 0.35,
    "value_score": 0.25,
    "growth_score": 0.15,
    "momentum_score": 0.15,
    "risk_score": 0.10,
}


class CompanyProfileService:
    """Read-only service that assembles quant and Analysis Mart profiles.."""

    def __init__(
        self,
        quant_repository: QuantRepository,
        analysis_mart_repository: AnalysisMartRepository,
    ) -> None:
        """Initialize with quant and Analysis Mart repositories.

        Args:
            quant_repository: QuantRepository: .
            analysis_mart_repository: AnalysisMartRepository: .

        Returns:
            None: .
        """
        self._quant_repository = quant_repository
        self._analysis_mart_repository = analysis_mart_repository

    def get_quant_profile(self, security_id: str) -> CompanyQuantProfile | None:
        """Return the latest quant profile for a security, or None.

        Args:
            security_id: str: .

        Returns:
            CompanyQuantProfile | None: .
        """
        result = self._quant_repository.latest_result_for_security(security_id)
        if result is None:
            return None
        return _quant_profile_from_result(result)

    def get_analysis_profile(
        self,
        security_id: str,
        scope_version_id: str | None = None,
    ) -> CompanyAnalysisProfile:
        """Return the Analysis Mart profile for a security.

        Args:
            security_id: str: .
            scope_version_id: str | None: .

        Returns:
            CompanyAnalysisProfile: .
        """
        snapshot = self._analysis_mart_repository.latest_snapshot(
            security_id=security_id,
            scope_version_id=scope_version_id,
            as_of=datetime.now(UTC),
        )
        if snapshot is None:
            return CompanyAnalysisProfile(
                security_id=security_id,
                analysis_snapshot=None,
                metrics=(),
                findings=(),
                evidence_link_count=0,
            )
        metrics = tuple(self._analysis_mart_repository.list_metrics(snapshot.analysis_snapshot_id))
        findings = tuple(
            self._analysis_mart_repository.list_findings(snapshot.analysis_snapshot_id)
        )
        links = self._analysis_mart_repository.list_evidence_links(snapshot.analysis_snapshot_id)
        return CompanyAnalysisProfile(
            security_id=security_id,
            analysis_snapshot=snapshot,
            metrics=metrics,
            findings=findings,
            evidence_link_count=len(links),
        )


def _quant_profile_from_result(result: QuantResult) -> CompanyQuantProfile:
    """Convert a QuantResult into a visualization-ready profile DTO.

    Args:
        result: QuantResult: .

    Returns:
        CompanyQuantProfile: .
    """
    factor_scores = tuple(
        FactorScoreItem(
            factor_key=key,
            label=_FACTOR_LABELS[key],
            score=getattr(result, key),
            weight=_FACTOR_WEIGHTS[key],
        )
        for key in _FACTOR_KEYS
    )
    return CompanyQuantProfile(
        security_id=result.security_id,
        quant_run_id=result.quant_run_id,
        result_id=result.result_id,
        decision_at=result.created_at,
        final_score=result.final_score,
        factor_scores=factor_scores,
        rank_overall=result.rank_overall,
        rank_in_industry=result.rank_in_industry,
        screening_status=result.screening_status.value,
        data_status=result.data_status.value,
        risk_flags=result.risk_flags,
        review_required=result.review_required,
        review_reasons=result.review_reasons,
        research_guardrail=result.research_guardrail.value,
        reason_summary=result.reason_summary,
        factor_details=dict(result.factor_details),
    )
