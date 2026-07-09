"""Production adapters wiring orchestrator dependencies to real services.

This module provides adapter classes that bridge the orchestrator's protocol
boundaries to concrete service implementations:

- ``NewsRefreshAdapter`` wraps ``NewsRefreshService`` to expose ``refresh``.
- ``ResearchContextBuilderAdapter`` builds frozen context snapshots from quant
  results and news targets.
- ``AIReviewAdapter`` wraps ``ResearchService`` to review multiple context
  snapshots.
- ``ValuationPublisherAdapter`` publishes assessments and refreshes dashboards.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from margin.dashboard.models import ItemStatus, ResearchItem, ResearchRun, RunStatus
from margin.dashboard.repository import DashboardRepository
from margin.data.freshness import DataDomain, FreshnessStatus
from margin.data.ingestion import DataWarehouseIngestionStack
from margin.data.sync_models import DataSyncRequest, DataSyncStatus
from margin.data.warehouse_repository import SQLAlchemyWarehouseRepository
from margin.evidence.package_builder import EvidencePackageBuilder
from margin.evidence.repository import EvidenceRepository
from margin.news.context_bundle import NewsContextBundleBuilder
from margin.news.models import NewsRefreshRun, NewsRefreshStatus
from margin.news.refresh_service import NewsRefreshService
from margin.research.delta_repository import ResearchDeltaRepository
from margin.research.graph.state import ReviewOutcome
from margin.research.service import ResearchContextSnapshot, ResearchService
from margin.sql.valuation_queries import (
    context_snapshots_by_scope,
    latest_delta_review_id_for_context,
    latest_effective_pointer,
    previous_quant_result,
    quant_input_snapshot_id_for_run,
)
from margin.storage.database import SessionFactory
from margin.strategy.models import ConfigLifecycle
from margin.strategy.validator import StrategyActivationValidator
from margin.valuation_discovery.analysis_mart import AnalysisMartRepository
from margin.valuation_discovery.assessments import EffectiveAssessmentService
from margin.valuation_discovery.db_models import (
    EffectiveAssessmentPointerRow,
    QuantInputSnapshotRow,
    QuantScreenResultRow,
    QuantScreenRunRow,
    ResearchContextSnapshotRow,
)
from margin.valuation_discovery.etl import AnalysisResultMartETLPipeline
from margin.valuation_discovery.models import (
    DataStatus,
    QuantResult,
    ResearchGuardrail,
    ScreeningStatus,
    ValuationAssessment,
    ValuationAssessmentEvidence,
)
from margin.valuation_discovery.orchestrator import RetryableStepError
from margin.valuation_discovery.repository import ValuationDiscoveryRepository


@dataclass(frozen=True)
class DataFreshnessDecision:
    """Persistable decision describing whether a warehouse sync is required.."""

    sync_required: bool
    status_by_endpoint: dict[str, str]


class DataReadinessAdapter:
    """Bridge warehouse freshness and durable data-sync runs into orchestration.."""

    def __init__(
        self,
        *,
        warehouse: SQLAlchemyWarehouseRepository,
        ingestion_stack: DataWarehouseIngestionStack,
        provider: str,
        retry_delay: timedelta = timedelta(minutes=1),
    ) -> None:
        """Initialize the adapter.

        Args:
            warehouse: SQLAlchemyWarehouseRepository: .
            ingestion_stack: DataWarehouseIngestionStack: .
            provider: str: .
            retry_delay: timedelta: .

        Returns:
            None: .
        """
        self._warehouse = warehouse
        self._stack = ingestion_stack
        self._provider = provider
        self._retry_delay = retry_delay

    def check(
        self,
        *,
        scope_version_id: str,
        decision_at: datetime,
    ) -> DataFreshnessDecision:
        """Read persisted endpoint freshness without calling Providers.

        Args:
            scope_version_id: str: .
            decision_at: datetime: .

        Returns:
            DataFreshnessDecision: .
        """
        del scope_version_id, decision_at
        records = self._warehouse.freshness(
            {
                DataDomain.MARKET,
                DataDomain.VALUATION,
                DataDomain.FINANCIAL,
            }
        )
        statuses = {
            f"{record.provider}:{record.endpoint_code}": record.status.value for record in records
        }
        sync_required = not records or any(
            record.status is not FreshnessStatus.FRESH for record in records
        )
        return DataFreshnessDecision(
            sync_required=sync_required,
            status_by_endpoint=statuses,
        )

    def ensure_sync(
        self,
        *,
        orchestration_run_id: str,
        scope_version_id: str,
        decision_at: datetime,
        freshness: DataFreshnessDecision | None,
    ) -> str:
        """Create or poll one durable sync run and wait until terminal success.

        Args:
            orchestration_run_id: str: .
            scope_version_id: str: .
            decision_at: datetime: .
            freshness: DataFreshnessDecision | None: .

        Returns:
            str: .
        """
        del scope_version_id
        if freshness is not None and not freshness.sync_required:
            return "not_required"
        requested_by = f"valuation:{orchestration_run_id}"
        sync_run = self._stack.sync_repository.find_latest_run(requested_by=requested_by)
        if sync_run is None:
            sync_run = self._stack.create_sync_run(
                DataSyncRequest(
                    provider=self._provider,
                    requested_by=requested_by,
                )
            )
        if sync_run.status in {DataSyncStatus.SUCCEEDED, DataSyncStatus.PARTIAL}:
            return sync_run.run_id
        if sync_run.status in {
            DataSyncStatus.FAILED_FINAL,
            DataSyncStatus.CANCELLED,
        }:
            raise RuntimeError(f"data sync terminal failure: {sync_run.status.value}")
        raise RetryableStepError(
            "data_sync_pending",
            retry_after=decision_at + self._retry_delay,
            output_ref=f"data-sync:{sync_run.run_id}",
        )


class ScopeResolutionAdapter:
    """Validate that an explicitly requested frozen scope is executable.."""

    def __init__(self, repository: object) -> None:
        """Initialize the adapter.

        Args:
            repository: object: .

        Returns:
            None: .
        """
        self._repository = repository
        self._validator = StrategyActivationValidator()

    def resolve(
        self,
        *,
        scope_version_id: str,
        decision_at: datetime,
    ) -> object:
        """Return an active scope after validating all frozen references.

        Args:
            scope_version_id: str: .
            decision_at: datetime: .

        Returns:
            object: .
        """
        del decision_at
        scope = self._repository.get_research_scope(scope_version_id)
        if scope is None:
            raise KeyError(f"research scope not found: {scope_version_id}")
        if scope.lifecycle is not ConfigLifecycle.ACTIVE:
            raise ValueError(f"research scope is not active: {scope_version_id}")
        self._validator.validate_research_scope_activation(
            scope,
            self._repository,
        )
        return scope


@dataclass(frozen=True)
class NewsRefreshAdapterResult:
    """Result returned by ``NewsRefreshAdapter.refresh``.."""

    run_id: str
    status: str
    target_count: int


class ProviderRefreshWaiting(RuntimeError):
    """Signal a durable provider wait state to the outer orchestrator.."""

    def __init__(
        self,
        *,
        code: str,
        run_id: str,
        retry_after_seconds: int,
    ) -> None:
        """Initialize a token-safe wait signal with durable output lineage.

        Args:
            code: str: .
            run_id: str: .
            retry_after_seconds: int: .

        Returns:
            None: .
        """
        self.code = code
        self.output_ref = f"news:{run_id}"
        self.retry_after_seconds = retry_after_seconds
        self.retryable = code == "provider_429"
        super().__init__(code)


class NewsRefreshAdapter:
    """Adapt ``NewsRefreshService`` to the orchestrator's ``refresh`` protocol.."""

    def __init__(self, refresh_service: NewsRefreshService) -> None:
        """Initialize the adapter with a news refresh service.

        Args:
            refresh_service: NewsRefreshService: .

        Returns:
            None: .
        """
        self._refresh_service = refresh_service

    def refresh(
        self,
        *,
        scope_version_id: str,
        quant_run_id: str,
        decision_at: datetime,
        targets: Any,
    ) -> NewsRefreshAdapterResult:
        """Run a target-driven news refresh and return a summary.

        Args:
            scope_version_id: str: .
            quant_run_id: str: .
            decision_at: datetime: .
            targets: Any: .

        Returns:
            NewsRefreshAdapterResult: .
        """
        run: NewsRefreshRun = self._refresh_service.refresh_for_targets(
            scope_version_id=scope_version_id,
            quant_run_id=quant_run_id,
            decision_at=decision_at,
            targets=list(targets),
        )
        if run.status is NewsRefreshStatus.WAITING_BUDGET:
            raise ProviderRefreshWaiting(
                code=str(
                    run.error_summary.get(
                        "error_code",
                        "provider_budget_exceeded",
                    )
                ),
                run_id=run.run_id,
                retry_after_seconds=3600,
            )
        if run.status is NewsRefreshStatus.WAITING_RATE_LIMIT:
            raise ProviderRefreshWaiting(
                code="provider_429",
                run_id=run.run_id,
                retry_after_seconds=int(run.error_summary.get("retry_after_seconds", 60) or 60),
            )
        if run.status in {NewsRefreshStatus.PENDING, NewsRefreshStatus.RUNNING}:
            raise RetryableStepError(
                "news_refresh_incomplete",
                retry_after=datetime.now(UTC) + timedelta(minutes=1),
                output_ref=f"news:{run.run_id}",
            )
        return NewsRefreshAdapterResult(
            run_id=run.run_id,
            status=run.status.value,
            target_count=run.target_count,
        )


class ResearchContextBuilderAdapter:
    """Build frozen research context snapshots from quant results and targets.."""

    def __init__(
        self,
        session_factory: SessionFactory,
        *,
        news_bundle_builder: NewsContextBundleBuilder | None = None,
        retrieval_tool: Any | None = None,
        evidence_package_builder: EvidencePackageBuilder | None = None,
        evidence_repository: EvidenceRepository | None = None,
        analysis_mart_repository: AnalysisMartRepository | None = None,
    ) -> None:
        """Initialize the adapter with session and optional service boundaries.

        Args:
            session_factory: SessionFactory: .
            news_bundle_builder: NewsContextBundleBuilder | None: .
            retrieval_tool: Any | None: .
            evidence_package_builder: EvidencePackageBuilder | None: .
            evidence_repository: EvidenceRepository | None: .
            analysis_mart_repository: AnalysisMartRepository | None: .

        Returns:
            None: .
        """
        self._session_factory = session_factory
        self._news_bundle_builder = news_bundle_builder
        self._retrieval_tool = retrieval_tool
        self._evidence_package_builder = evidence_package_builder
        self._evidence_repository = evidence_repository
        self._analysis_mart_repository = analysis_mart_repository

    def build(
        self,
        *,
        scope_version_id: str,
        quant_run_id: str,
        news_refresh_run_id: str | None = None,
        decision_at: datetime,
        targets: Any,
        results: Any = (),
    ) -> tuple[str, ...]:
        """Build and persist context snapshots for each target.

        Args:
            scope_version_id: str: .
            quant_run_id: str: .
            news_refresh_run_id: str | None: .
            decision_at: datetime: .
            targets: Any: .
            results: Any: .

        Returns:
            tuple[str, ...]: .
        """
        target_list = list(targets)
        result_list: list[QuantResult] = list(results)
        result_by_security = {result.security_id: result for result in result_list}
        context_ids: list[str] = []
        for target in target_list:
            security_id = target.security_id
            result = result_by_security.get(security_id)
            news_bundle = (
                self._news_bundle_builder.build_for_run(
                    run_id=news_refresh_run_id,
                    security_id=security_id,
                )
                if self._news_bundle_builder is not None and news_refresh_run_id is not None
                else None
            )
            questions = _research_questions()
            evidence_package = self._build_evidence_package(
                security_id=security_id,
                decision_at=decision_at,
                scope_version_id=scope_version_id,
                quant_run_id=quant_run_id,
                questions=questions,
                news_bundle_id=(news_bundle.bundle_id if news_bundle is not None else None),
            )
            previous_pointer = self._latest_effective_pointer(
                security_id=security_id,
                scope_version_id=scope_version_id,
            )
            quant_lineage = self._quant_lineage(quant_run_id)
            quant_input_snapshot_id = quant_lineage["input_snapshot_id"]
            previous_result = self._previous_quant_result(
                security_id=security_id,
                scope_version_id=scope_version_id,
                current_quant_run_id=quant_run_id,
            )
            material_quant_change = _is_material_quant_change(
                previous_result,
                result,
            )
            quant_factor_details = result.factor_details if result else {}
            analysis_snapshot = self._publish_analysis_snapshot(
                scope_version_id=scope_version_id,
                decision_at=decision_at,
                quant_result=result,
                quant_lineage=quant_lineage,
                evidence_ids=(
                    evidence_package.evidence_ids if evidence_package is not None else ()
                ),
            )
            payload: dict[str, Any] = {
                "quant_run_id": quant_run_id,
                "quant_input_valid": (
                    result is not None
                    and result.data_status is DataStatus.OK
                    and quant_input_snapshot_id is not None
                ),
                "pit_valid": self._quant_input_is_pit_valid(quant_input_snapshot_id),
                "news_target_complete": (
                    news_bundle is not None and news_bundle.target_completion_state == "complete"
                ),
                "provider_budget_available": (
                    news_bundle is not None
                    and "provider_budget_exceeded" not in news_bundle.incomplete_reason_codes
                ),
                "review_due": (
                    previous_pointer is None or (result is not None and result.review_required)
                ),
                "material_quant_change": material_quant_change,
                "material_valuation_change": False,
                "material_news_change": bool(news_bundle is not None and news_bundle.documents),
                "assumption_change": False,
                "ambiguous_change": False,
                "quant_input_snapshot_id": quant_input_snapshot_id,
                "current_quant_result_id": (result.result_id if result else None),
                "previous_effective_assessment_id": (
                    previous_pointer.effective_assessment_id
                    if previous_pointer is not None
                    else None
                ),
                "screening_status": (result.screening_status.value if result else None),
                "final_score": result.final_score if result else 0.0,
                "quant_factor_details": quant_factor_details,
                "quant_ai_profile": quant_factor_details.get(
                    "ai_quant_profile",
                    {},
                ),
                "analysis_snapshot_id": (
                    analysis_snapshot.analysis_snapshot_id
                    if analysis_snapshot is not None
                    else None
                ),
                "analysis_summary": (
                    analysis_snapshot.summary if analysis_snapshot is not None else {}
                ),
                "news_target_reason": target.trigger_type.value,
                "news_context_bundle_id": (
                    news_bundle.bundle_id if news_bundle is not None else None
                ),
                "news_document_ids": (
                    tuple(document.event_id for document in news_bundle.documents)
                    if news_bundle is not None
                    else ()
                ),
                "evidence_package_id": (
                    evidence_package.package_id if evidence_package is not None else None
                ),
                "evidence_ids": (
                    evidence_package.evidence_ids if evidence_package is not None else ()
                ),
                "evidence_quality_status": (
                    evidence_package.quality_status.value
                    if evidence_package is not None
                    else "unavailable"
                ),
                "evidence_blocks": self._evidence_blocks(evidence_package),
            }
            context_snapshot = _build_context_snapshot(
                security_id=security_id,
                scope_version_id=scope_version_id,
                decision_at=decision_at,
                payload=payload,
            )
            self._persist_context_snapshot(context_snapshot)
            context_ids.append(context_snapshot.context_snapshot_id)
        return tuple(context_ids)

    def _build_evidence_package(
        self,
        *,
        security_id: str,
        decision_at: datetime,
        scope_version_id: str,
        quant_run_id: str,
        questions: tuple[str, ...],
        news_bundle_id: str | None,
    ) -> Any | None:
        """Retrieve indexed evidence and freeze one auditable package.

        Args:
            security_id: str: .
            decision_at: datetime: .
            scope_version_id: str: .
            quant_run_id: str: .
            questions: tuple[str, ...]: .
            news_bundle_id: str | None: .

        Returns:
            Any | None: .
        """
        if self._retrieval_tool is None or self._evidence_package_builder is None:
            return None
        results = self._retrieval_tool.search(
            query="\n".join(questions),
            symbol=security_id,
            decision_at=decision_at,
            top_k=20,
        )
        return self._evidence_package_builder.build(
            security_id=security_id,
            decision_at=decision_at,
            questions=questions,
            retrieval_results=results,
            news_bundle_id=news_bundle_id,
            scope_hash=_hash_payload(
                {
                    "scope_version_id": scope_version_id,
                    "quant_run_id": quant_run_id,
                }
            ),
        )

    def _latest_effective_pointer(
        self,
        *,
        security_id: str,
        scope_version_id: str,
    ) -> EffectiveAssessmentPointerRow | None:
        """Load the latest effective assessment pointer.

        Args:
            security_id: str: .
            scope_version_id: str: .

        Returns:
            EffectiveAssessmentPointerRow | None: .
        """
        with self._session_factory() as session:
            return session.scalar(latest_effective_pointer(security_id, scope_version_id))

    def _evidence_blocks(self, package: Any | None) -> tuple[dict[str, Any], ...]:
        """Load immutable evidence text and locator metadata for prompting.

        Args:
            package: Any | None: .

        Returns:
            tuple[dict[str, Any], ...]: .
        """
        if package is None or self._evidence_repository is None:
            return ()
        blocks: list[dict[str, Any]] = []
        for evidence_id in package.evidence_ids:
            evidence = self._evidence_repository.get_evidence(evidence_id)
            if evidence is None:
                raise KeyError(f"evidence not found: {evidence_id}")
            blocks.append(
                {
                    "evidence_id": evidence.evidence_id,
                    "source_level": int(evidence.source_level),
                    "content": evidence.content,
                    "source_url": evidence.source_url,
                    "snapshot_id": evidence.snapshot_id,
                    "page": evidence.page,
                    "section": evidence.section,
                    "quote_span": evidence.quote_span,
                }
            )
        return tuple(blocks)

    def _quant_input_snapshot_id(self, quant_run_id: str) -> str | None:
        """Resolve the frozen input snapshot behind one quant run.

        Args:
            quant_run_id: str: .

        Returns:
            str | None: .
        """
        with self._session_factory() as session:
            return session.scalar(quant_input_snapshot_id_for_run(quant_run_id))

    def _quant_lineage(self, quant_run_id: str) -> dict[str, Any]:
        """Load quant run and input snapshot lineage for Analysis Mart.

        Args:
            quant_run_id: str: .

        Returns:
            dict[str, Any]: .
        """
        with self._session_factory() as session:
            run = session.get(QuantScreenRunRow, quant_run_id)
            if run is None:
                return {
                    "input_snapshot_id": None,
                    "input_hash": _hash_payload({"quant_run_id": quant_run_id}),
                    "strategy_version_id": None,
                    "config_hash": None,
                }
            input_row = session.get(QuantInputSnapshotRow, run.input_snapshot_id)
            return {
                "input_snapshot_id": run.input_snapshot_id,
                "input_hash": (
                    input_row.input_hash if input_row is not None else run.input_snapshot_id
                ),
                "strategy_version_id": run.strategy_version_id,
                "config_hash": run.config_hash,
            }

    def _publish_analysis_snapshot(
        self,
        *,
        scope_version_id: str,
        decision_at: datetime,
        quant_result: QuantResult | None,
        quant_lineage: dict[str, Any],
        evidence_ids: tuple[str, ...],
    ) -> Any | None:
        """Publish the fourth-layer analysis snapshot for one quant result.

        Args:
            scope_version_id: str: .
            decision_at: datetime: .
            quant_result: QuantResult | None: .
            quant_lineage: dict[str, Any]: .
            evidence_ids: tuple[str, ...]: .

        Returns:
            Any | None: .
        """
        if self._analysis_mart_repository is None or quant_result is None:
            return None
        return AnalysisResultMartETLPipeline(self._analysis_mart_repository).publish_quant_result(
            scope_version_id=scope_version_id,
            decision_at=decision_at,
            trading_date=decision_at.date(),
            quant_result=quant_result,
            input_snapshot_id=quant_lineage["input_snapshot_id"],
            strategy_version_id=quant_lineage["strategy_version_id"],
            config_hash=quant_lineage["config_hash"],
            input_hash=quant_lineage["input_hash"],
            evidence_ids=evidence_ids,
        )

    def _quant_input_is_pit_valid(
        self,
        snapshot_id: str | None,
    ) -> bool:
        """Return whether the persisted quant input passed PIT validation.

        Args:
            snapshot_id: str | None: .

        Returns:
            bool: .
        """
        if snapshot_id is None:
            return False
        with self._session_factory() as session:
            row = session.get(QuantInputSnapshotRow, snapshot_id)
            return bool(
                row is not None
                and row.data_status == DataStatus.OK.value
                and not row.pit_validation_errors
            )

    def _previous_quant_result(
        self,
        *,
        security_id: str,
        scope_version_id: str,
        current_quant_run_id: str,
    ) -> QuantScreenResultRow | None:
        """Load the immediately preceding quant result for delta routing.

        Args:
            security_id: str: .
            scope_version_id: str: .
            current_quant_run_id: str: .

        Returns:
            QuantScreenResultRow | None: .
        """
        with self._session_factory() as session:
            return session.scalar(
                previous_quant_result(
                    security_id,
                    scope_version_id,
                    current_quant_run_id,
                )
            )

    def _persist_context_snapshot(self, snapshot: ResearchContextSnapshot) -> None:
        """Persist a frozen context snapshot.

        Args:
            snapshot: ResearchContextSnapshot: .

        Returns:
            None: .
        """
        with self._session_factory.begin() as session:
            existing = session.get(
                ResearchContextSnapshotRow,
                snapshot.context_snapshot_id,
            )
            if existing is not None:
                if (
                    existing.payload_hash != snapshot.payload_hash
                    or dict(existing.payload_json) != snapshot.payload
                ):
                    raise ValueError("conflicting research context snapshot")
                return
            session.add(
                ResearchContextSnapshotRow(
                    context_snapshot_id=snapshot.context_snapshot_id,
                    security_id=snapshot.security_id,
                    scope_version_id=snapshot.scope_version_id,
                    decision_at=snapshot.decision_at,
                    payload_json=snapshot.payload,
                    payload_hash=snapshot.payload_hash,
                    created_at=snapshot.created_at or datetime.now(UTC),
                )
            )

    def list_context_snapshot_ids(
        self,
        *,
        scope_version_id: str,
        quant_run_id: str,
    ) -> tuple[str, ...]:
        """Reload context IDs for orchestration recovery.

        Args:
            scope_version_id: str: .
            quant_run_id: str: .

        Returns:
            tuple[str, ...]: .
        """
        with self._session_factory() as session:
            rows = session.scalars(context_snapshots_by_scope(scope_version_id)).all()
        return tuple(
            row.context_snapshot_id
            for row in rows
            if str(row.payload_json.get("quant_run_id", "")) == quant_run_id
        )


def _build_context_snapshot(
    *,
    security_id: str,
    scope_version_id: str,
    decision_at: datetime,
    payload: dict[str, Any],
) -> ResearchContextSnapshot:
    """Build a frozen ``ResearchContextSnapshot`` with a deterministic ID.

    Args:
        security_id: str: .
        scope_version_id: str: .
        decision_at: datetime: .
        payload: dict[str, Any]: .

    Returns:
        ResearchContextSnapshot: .
    """
    payload_hash = _hash_payload(payload)
    context_snapshot_id = "rcs_" + payload_hash.removeprefix("sha256:")[:24]
    return ResearchContextSnapshot(
        context_snapshot_id=context_snapshot_id,
        security_id=security_id,
        scope_version_id=scope_version_id,
        decision_at=decision_at,
        payload_hash=payload_hash,
        payload=payload,
        created_at=datetime.now(UTC),
    )


def _hash_payload(payload: dict[str, Any]) -> str:
    """Hash a payload dict to a deterministic SHA-256 digest string.

    Args:
        payload: dict[str, Any]: .

    Returns:
        str: .
    """
    rendered = json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str)
    return "sha256:" + hashlib.sha256(rendered.encode("utf-8")).hexdigest()


def _research_questions() -> tuple[str, ...]:
    """Return the stable evidence questions for one company review.

    Returns:
        tuple[str, ...]: .
    """
    return (
        "核心基本面较上一有效结论发生了什么变化？",
        "当前估值假设是否仍然成立？",
        "有哪些风险或反方证据可能推翻原结论？",
    )


def _is_material_quant_change(
    previous: QuantScreenResultRow | None,
    current: QuantResult | None,
) -> bool:
    """Classify deterministic quant deltas for graph routing.

    Args:
        previous: QuantScreenResultRow | None: .
        current: QuantResult | None: .

    Returns:
        bool: .
    """
    if current is None:
        return False
    if previous is None:
        return True
    return bool(
        previous.screening_status != current.screening_status.value
        or abs(float(previous.final_score) - float(current.final_score)) >= 5.0
        or previous.research_guardrail != current.research_guardrail.value
    )


@dataclass(frozen=True)
class AIReviewSummary:
    """Summary returned by ``AIReviewAdapter.review``.."""

    review_ids: tuple[str, ...]
    context_snapshot_ids: tuple[str, ...]


class AIReviewAdapter:
    """Wrap ``ResearchService`` to review multiple context snapshots.."""

    def __init__(
        self,
        research_service: ResearchService,
        *,
        session_factory: SessionFactory | None = None,
    ) -> None:
        """Initialize the adapter with a research service and optional session.

        Args:
            research_service: ResearchService: .
            session_factory: SessionFactory | None: .

        Returns:
            None: .
        """
        self._research_service = research_service
        self._session_factory = session_factory

    def review(
        self,
        *,
        context_snapshot_ids: Any,
        decision_at: datetime,
    ) -> AIReviewSummary:
        """Run AI delta reviews for each context snapshot.

        Args:
            context_snapshot_ids: Any: .
            decision_at: datetime: .

        Returns:
            AIReviewSummary: .
        """
        review_ids: list[str] = []
        snapshot_ids = tuple(context_snapshot_ids)
        for context_snapshot_id in snapshot_ids:
            existing_id = self._existing_review_id(context_snapshot_id)
            if existing_id is not None:
                review_ids.append(existing_id)
                continue
            result = self._research_service.run_delta_review(context_snapshot_id)
            review_ids.append(result.review_id)
        return AIReviewSummary(
            review_ids=tuple(review_ids),
            context_snapshot_ids=snapshot_ids,
        )

    def load_summary(
        self,
        *,
        context_snapshot_ids: Any,
    ) -> AIReviewSummary:
        """Reload terminal review IDs for all requested contexts.

        Args:
            context_snapshot_ids: Any: .

        Returns:
            AIReviewSummary: .
        """
        snapshot_ids = tuple(str(value) for value in context_snapshot_ids)
        review_ids: list[str] = []
        for context_snapshot_id in snapshot_ids:
            review_id = self._existing_review_id(context_snapshot_id)
            if review_id is None:
                raise KeyError(f"research delta review not found: {context_snapshot_id}")
            review_ids.append(review_id)
        return AIReviewSummary(
            review_ids=tuple(review_ids),
            context_snapshot_ids=snapshot_ids,
        )

    def _existing_review_id(
        self,
        context_snapshot_id: str,
    ) -> str | None:
        """Return a persisted terminal review ID for one context.

        Args:
            context_snapshot_id: str: .

        Returns:
            str | None: .
        """
        if self._session_factory is None:
            return None
        with self._session_factory() as session:
            return session.scalar(latest_delta_review_id_for_context(context_snapshot_id))


@dataclass(frozen=True)
class ValuationPublishResult:
    """Result returned by ``ValuationPublisherAdapter.publish``.."""

    assessment_count: int
    pointer_count: int
    skipped_review_ids: tuple[str, ...]
    scope_version_id: str


@dataclass(frozen=True)
class DashboardProjectionResult:
    """Persisted effective-assessment projection visible to the dashboard.."""

    scope_version_id: str
    effective_assessment_count: int
    as_of: datetime
    dashboard_run_id: str | None = None
    visible_item_count: int = 0


class ValuationPublisherAdapter:
    """Publish valuation assessments and refresh dashboards.."""

    def __init__(
        self,
        *,
        assessment_service: EffectiveAssessmentService,
        review_repository: ResearchDeltaRepository,
        valuation_repository: ValuationDiscoveryRepository,
        dashboard_repository: DashboardRepository | None = None,
        stock_analyst_agent: Any | None = None,
    ) -> None:
        """Initialize the publisher with assessment and repository dependencies.

        Args:
            assessment_service: EffectiveAssessmentService: .
            review_repository: ResearchDeltaRepository: .
            valuation_repository: ValuationDiscoveryRepository: .
            dashboard_repository: DashboardRepository | None: .
            stock_analyst_agent: Any | None: .

        Returns:
            None: .
        """
        self._assessment_service = assessment_service
        self._review_repository = review_repository
        self._valuation_repository = valuation_repository
        self._dashboard_repository = dashboard_repository
        self._stock_analyst_agent = stock_analyst_agent

    def publish(
        self,
        *,
        scope_version_id: str,
        decision_at: datetime,
        quant_run_id: str,
        review_summary: Any = None,
    ) -> ValuationPublishResult:
        """Apply review outcomes to effective assessment pointers.

        Args:
            scope_version_id: str: .
            decision_at: datetime: .
            quant_run_id: str: .
            review_summary: Any: .

        Returns:
            ValuationPublishResult: .
        """
        assessment_count = 0
        pointer_count = 0
        skipped_review_ids: list[str] = []
        if review_summary is not None:
            review_ids = tuple(getattr(review_summary, "review_ids", ()) or ())
            for review_id in review_ids:
                review = self._review_repository.get_review(str(review_id))
                if review is None:
                    raise KeyError(f"research delta review not found: {review_id}")
                creates_assessment = review.outcome in {
                    ReviewOutcome.UPDATE_ASSESSMENT,
                    ReviewOutcome.DOWNGRADE_CONFIDENCE,
                    ReviewOutcome.INVALIDATE,
                }
                if creates_assessment and not review.conclusion.strip():
                    raise ValueError(f"review conclusion is required: {review.review_id}")
                if not creates_assessment and review.previous_effective_assessment_id is None:
                    skipped_review_ids.append(review.review_id)
                    continue
                assessment = (
                    ValuationAssessment(
                        assessment_id=_required_assessment_id(review),
                        security_id=review.security_id,
                        scope_version_id=scope_version_id,
                        decision_at=review.decision_at,
                        valuation_model="ai_delta_review_v0.2",
                        conclusion=review.conclusion,
                        evidence_refs=review.evidence_ids,
                        created_at=review.decision_at,
                    )
                    if creates_assessment
                    else None
                )
                evidence_edges = (
                    tuple(
                        ValuationAssessmentEvidence(
                            edge_id=_assessment_evidence_edge_id(
                                assessment.assessment_id,
                                evidence_id,
                            ),
                            assessment_id=assessment.assessment_id,
                            evidence_id=evidence_id,
                            role="supporting",
                            created_at=review.decision_at,
                        )
                        for evidence_id in review.evidence_ids
                    )
                    if assessment is not None
                    else ()
                )
                pointer = self._assessment_service.apply_review_result(
                    security_id=review.security_id,
                    scope_version_id=scope_version_id,
                    previous_effective_assessment_id=review.previous_effective_assessment_id,
                    current_review_outcome=review.outcome.value,
                    new_assessment_id=(
                        review.effective_assessment_id if creates_assessment else None
                    ),
                    stale_reason=review.stale_reason,
                    last_successful_data_check_at=decision_at,
                    last_successful_news_check_at=decision_at,
                    effective_from=decision_at,
                )
                self._valuation_repository.publish_valuation_result(
                    assessment=assessment,
                    evidence_edges=evidence_edges,
                    pointer=pointer,
                )
                assessment_count += int(assessment is not None)
                pointer_count += 1
        return ValuationPublishResult(
            assessment_count=assessment_count,
            pointer_count=pointer_count,
            skipped_review_ids=tuple(skipped_review_ids),
            scope_version_id=scope_version_id,
        )

    def refresh_dashboard(
        self,
        *,
        scope_version_id: str,
        decision_at: datetime,
        quant_run_id: str | None = None,
        quant_results: Any = (),
        agent_run_id: str | None = None,
    ) -> DashboardProjectionResult:
        """Persist and read the dashboard projection for the latest refresh.

        Args:
            scope_version_id: str: .
            decision_at: datetime: .
            quant_run_id: str | None: .
            quant_results: Any: .
            agent_run_id: str | None: .

        Returns:
            DashboardProjectionResult: .
        """
        dashboard_run_id: str | None = None
        visible_item_count = 0
        if self._dashboard_repository is not None and quant_run_id:
            visible_results = _dashboard_visible_quant_results(quant_results)
            dashboard_run_id = _dashboard_run_id(
                scope_version_id=scope_version_id,
                quant_run_id=quant_run_id,
            )
            dashboard_run = _dashboard_run_from_quant_results(
                run_id=dashboard_run_id,
                scope_version_id=scope_version_id,
                quant_run_id=quant_run_id,
                decision_at=decision_at,
                results=visible_results,
            )
            dashboard_items = [
                _dashboard_item_from_quant_result(
                    run_id=dashboard_run_id,
                    quant_run_id=quant_run_id,
                    result=result,
                    decision_at=decision_at,
                )
                for result in visible_results
            ]
            self._dashboard_repository.add_run(dashboard_run)
            self._dashboard_repository.add_items(dashboard_items)
            visible_item_count = len(dashboard_items)
            if self._stock_analyst_agent is not None and visible_results:
                adjustment = self._stock_analyst_agent.adjust_quant_candidates(
                    run_id=agent_run_id or f"ar_dashboard_{quant_run_id}",
                    candidates=_dashboard_adjustment_candidates(
                        items=tuple(dashboard_items),
                        results=visible_results,
                    ),
                    max_stock_exposure=0.80,
                )
                if getattr(adjustment, "dashboard_run_id", None):
                    dashboard_run_id = str(adjustment.dashboard_run_id)
                    visible_item_count = sum(
                        1
                        for item in getattr(adjustment, "adjustments", ())
                        if item.get("action") != "delete"
                    )
        return DashboardProjectionResult(
            scope_version_id=scope_version_id,
            effective_assessment_count=(
                self._valuation_repository.count_effective_assessments(
                    scope_version_id=scope_version_id,
                    as_of=decision_at,
                )
            ),
            as_of=decision_at,
            dashboard_run_id=dashboard_run_id,
            visible_item_count=visible_item_count,
        )


def _dashboard_visible_quant_results(quant_results: Any) -> tuple[QuantResult, ...]:
    """Return quant results that should be visible on the user dashboard.

    Args:
        quant_results: Any: .

    Returns:
        tuple[QuantResult, ...]: .
    """
    visible_statuses = {
        ScreeningStatus.PASS,
        ScreeningStatus.NEAR_THRESHOLD,
        ScreeningStatus.WATCHLIST,
    }
    results: list[QuantResult] = []
    for result in tuple(quant_results or ()):
        if not isinstance(result, QuantResult):
            continue
        if result.screening_status not in visible_statuses:
            continue
        if result.research_guardrail is ResearchGuardrail.RESEARCH_BLOCKED:
            continue
        results.append(result)
    return tuple(
        sorted(
            results,
            key=lambda item: (item.final_score, item.security_id),
            reverse=True,
        )
    )


def _dashboard_run_from_quant_results(
    *,
    run_id: str,
    scope_version_id: str,
    quant_run_id: str,
    decision_at: datetime,
    results: tuple[QuantResult, ...],
) -> ResearchRun:
    """Build the latest user-facing dashboard run from quant output.

    Args:
        run_id: str: .
        scope_version_id: str: .
        quant_run_id: str: .
        decision_at: datetime: .
        results: tuple[QuantResult, ...]: .

    Returns:
        ResearchRun: .
    """
    created_at = datetime.now(UTC)
    published_count = sum(
        1 for result in results if _dashboard_item_status(result) is ItemStatus.PUBLISHED
    )
    abstained_count = len(results) - published_count
    status = (
        RunStatus.PUBLISHED
        if results and abstained_count == 0
        else RunStatus.PARTIAL
        if results
        else RunStatus.ABSTAINED
    )
    return ResearchRun(
        run_id=run_id,
        decision_at=decision_at,
        strategy_id=quant_run_id,
        version_id=scope_version_id,
        universe=[result.security_id for result in results],
        status=status,
        summary=f"latest quant projection from {quant_run_id}",
        item_count=len(results),
        published_count=published_count,
        abstained_count=abstained_count,
        aborted_count=0,
        created_at=created_at,
    )


def _dashboard_item_from_quant_result(
    *,
    run_id: str,
    quant_run_id: str,
    result: QuantResult,
    decision_at: datetime,
) -> ResearchItem:
    """Build one dashboard item from a quant result without exposing internals.

    Args:
        run_id: str: .
        quant_run_id: str: .
        result: QuantResult: .
        decision_at: datetime: .

    Returns:
        ResearchItem: .
    """
    status = _dashboard_item_status(result)
    return ResearchItem(
        item_id=_dashboard_item_id(run_id, result.security_id),
        run_id=run_id,
        symbol=result.security_id,
        signal_type=f"quant_screen:{result.screening_status.value}",
        confidence=_score_to_confidence(result.final_score),
        statement=result.reason_summary or result.screening_status.value,
        workflow_run_id=quant_run_id,
        snapshot_id=result.result_id,
        status=status,
        abstain_reason=(
            "; ".join(result.review_reasons)
            if result.review_reasons
            else None
            if status is ItemStatus.PUBLISHED
            else result.screening_status.value
        ),
        rejection_reasons=list(dict.fromkeys((*result.risk_flags, *result.review_reasons))),
        risk_score=result.risk_score,
        target_weight=_dashboard_target_weight(result),
        adjusted_weight=_dashboard_target_weight(result),
        agent_adjustment=_dashboard_agent_adjustment(result),
        counter_arguments=list(result.review_reasons),
        created_at=decision_at,
    )


def _dashboard_adjustment_candidates(
    *,
    items: tuple[ResearchItem, ...],
    results: tuple[QuantResult, ...],
) -> tuple[dict[str, Any], ...]:
    """Build StockAnalystAgent candidate payloads from persisted dashboard items.

    Args:
        items: tuple[ResearchItem, ...]: .
        results: tuple[QuantResult, ...]: .

    Returns:
        tuple[dict[str, Any], ...]: .
    """
    result_by_security_id = {result.security_id: result for result in results}
    candidates: list[dict[str, Any]] = []
    for item in items:
        result = result_by_security_id.get(item.symbol)
        if result is None:
            continue
        candidates.append(
            {
                "item_id": item.item_id,
                "run_id": item.run_id,
                "security_id": item.symbol,
                "target_weight": item.target_weight,
                "screening_status": result.screening_status.value,
                "review_required": result.review_required,
                "risk_flags": list(result.risk_flags),
            }
        )
    return tuple(candidates)


def _dashboard_item_status(result: QuantResult) -> ItemStatus:
    """Map quant status into the dashboard item's current-review state.

    Args:
        result: QuantResult: .

    Returns:
        ItemStatus: .
    """
    if result.screening_status is ScreeningStatus.PASS and not result.review_required:
        return ItemStatus.PUBLISHED
    return ItemStatus.ABSTAINED


def _dashboard_target_weight(result: QuantResult) -> float | None:
    """Return ML target weight carried by a quant result, if present.

    Args:
        result: QuantResult: .

    Returns:
        float | None: .
    """
    ml_strategy = result.factor_details.get("ml_strategy")
    if not isinstance(ml_strategy, dict):
        return None
    value = ml_strategy.get("target_weight")
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _dashboard_agent_adjustment(result: QuantResult) -> dict[str, Any]:
    """Return default agent-adjustment metadata for dashboard projection.

    Args:
        result: QuantResult: .

    Returns:
        dict[str, Any]: .
    """
    target_weight = _dashboard_target_weight(result)
    if target_weight is None:
        return {}
    return {
        "source": "quant_default",
        "action": "keep",
        "target_weight": target_weight,
        "adjusted_weight": target_weight,
    }


def _score_to_confidence(score: float) -> float:
    """Convert a 0-100 quant score into a 0-1 dashboard confidence.

    Args:
        score: float: .

    Returns:
        float: .
    """
    return max(0.0, min(float(score) / 100.0, 1.0))


def _dashboard_run_id(*, scope_version_id: str, quant_run_id: str) -> str:
    """Build a stable dashboard run ID for idempotent refresh retries.

    Args:
        scope_version_id: str: .
        quant_run_id: str: .

    Returns:
        str: .
    """
    material = f"{scope_version_id}|{quant_run_id}"
    return "dr_" + hashlib.sha256(material.encode("utf-8")).hexdigest()[:24]


def _dashboard_item_id(run_id: str, security_id: str) -> str:
    """Build a stable dashboard item ID for idempotent refresh retries.

    Args:
        run_id: str: .
        security_id: str: .

    Returns:
        str: .
    """
    material = f"{run_id}|{security_id}"
    return "di_" + hashlib.sha256(material.encode("utf-8")).hexdigest()[:24]


def _required_assessment_id(review: Any) -> str:
    """Return the graph-generated assessment ID for a new conclusion.

    Args:
        review: Any: .

    Returns:
        str: .
    """
    if not review.effective_assessment_id:
        raise ValueError(f"effective assessment ID is required: {review.review_id}")
    return str(review.effective_assessment_id)


def _assessment_evidence_edge_id(
    assessment_id: str,
    evidence_id: str,
) -> str:
    """Build a stable assessment-evidence edge ID.

    Args:
        assessment_id: str: .
        evidence_id: str: .

    Returns:
        str: .
    """
    material = f"{assessment_id}|{evidence_id}|supporting"
    return "vae_" + hashlib.sha256(material.encode("utf-8")).hexdigest()[:24]
