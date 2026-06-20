"""High-level services for the research candidate dashboard module."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from margin.dashboard.models import (
    AuditView,
    CandidateCard,
    ClaimView,
    EvidenceLocator,
    EvidenceView,
    FeedbackRecord,
    FeedbackType,
    HomeSummary,
    ItemStatus,
    JobRun,
    ProviderStatus,
    ReportExport,
    ReportFormat,
    ResearchItem,
    ResearchReport,
    ResearchRun,
    RunStatus,
    ValuationView,
)
from margin.dashboard.repository import DashboardRepository, MemoryDashboardRepository
from margin.research.models import SignalType, WorkflowState
from margin.research.repository import MemoryResearchRepository, ResearchRepository
from margin.research.service import ResearchService
from margin.research.workflow import WorkflowResult


class DashboardResearchService:
    """Run module 06 workflows and aggregate them into module 08 runs/items."""

    def __init__(
        self,
        research_service: Any,
        repository: DashboardRepository,
    ) -> None:
        """Initialize the service.

        Args:
            research_service: Service capable of running symbol research workflows.
            repository: Dashboard repository used to persist runs and items.
        """
        self._research = research_service
        self._repository = repository

    def run_batch(
        self,
        *,
        decision_at: datetime | None = None,
        strategy_id: str,
        version_id: str,
        portfolio_id: str | None = None,
        symbols: list[str] | None = None,
    ) -> ResearchRun:
        """Run research workflows for a batch of symbols and persist the run.

        Args:
            decision_at: Optional decision timestamp; defaults to now.
            strategy_id: Identifier of the strategy driving the run.
            version_id: Version of the strategy.
            portfolio_id: Optional portfolio context.
            symbols: Optional list of symbols to research; defaults to a demo symbol.

        Returns:
            The persisted aggregate research run.
        """
        resolved_decision_at = decision_at or datetime.now(UTC)
        universe = symbols or ["000001.SZ"]
        temporary_run = ResearchRun(
            decision_at=resolved_decision_at,
            strategy_id=strategy_id,
            version_id=version_id,
            portfolio_id=portfolio_id,
            universe=universe,
        )
        items = [
            self._item_from_result(
                temporary_run.run_id,
                symbol,
                self._research.run(
                    symbol=symbol,
                    decision_at=resolved_decision_at,
                    portfolio_id=portfolio_id,
                ),
            )
            for symbol in universe
        ]
        published_count = sum(1 for item in items if item.status == ItemStatus.PUBLISHED)
        abstained_count = sum(1 for item in items if item.status == ItemStatus.ABSTAINED)
        aborted_count = sum(1 for item in items if item.status == ItemStatus.ABORTED)
        status = _run_status(published_count, abstained_count, aborted_count, len(items))
        run = temporary_run.model_copy(
            update={
                "status": status,
                "summary": (
                    f"{len(items)} symbols: {published_count} published, "
                    f"{abstained_count} abstained, {aborted_count} aborted"
                ),
                "item_count": len(items),
                "published_count": published_count,
                "abstained_count": abstained_count,
                "aborted_count": aborted_count,
            }
        )
        self._repository.add_run(run)
        self._repository.add_items(items)
        return run

    def _item_from_result(
        self,
        run_id: str,
        symbol: str,
        result: WorkflowResult,
    ) -> ResearchItem:
        signal = result.signals[0] if result.signals else None
        status = _item_status(result.state, signal.signal_type if signal else None)
        snapshot_id = None
        if result.snapshot_persisted and result.snapshot:
            snapshot_id = result.snapshot.get("snapshot_id")
        rejection_reasons = []
        if result.error:
            rejection_reasons.append(result.error)
        if signal and signal.signal_type == SignalType.ABSTAINED and signal.statement:
            rejection_reasons.append(signal.statement)
        return ResearchItem(
            run_id=run_id,
            symbol=symbol,
            signal_type=signal.signal_type.value if signal else "",
            confidence=signal.confidence if signal else 0.0,
            statement=signal.statement if signal else result.error or "",
            workflow_run_id=result.run_id,
            snapshot_id=snapshot_id,
            status=status,
            abstain_reason=result.error if status != ItemStatus.PUBLISHED else None,
            rejection_reasons=list(dict.fromkeys(rejection_reasons)),
            evidence_ids=list(signal.evidence_refs) if signal else [],
            claim_ids=list(signal.claim_ids) if signal else [],
            risk_score=signal.risk_score if signal else None,
            counter_arguments=list(signal.counter_arguments) if signal else [],
            portfolio_constraint_violations=(
                list(signal.portfolio_constraint_violations) if signal else []
            ),
        )


class DashboardQueryService:
    """Read-only dashboard query service and card/home-summary BFF."""

    def __init__(
        self,
        repository: DashboardRepository,
        research_repository: ResearchRepository,
    ) -> None:
        """Initialize the query service.

        Args:
            repository: Dashboard repository for runs, items, and feedback.
            research_repository: Repository for module 06 research snapshots.
        """
        self._repository = repository
        self._research_repository = research_repository

    def list_runs(
        self,
        *,
        strategy_id: str | None = None,
        portfolio_id: str | None = None,
        status: str | None = None,
        limit: int = 100,
    ) -> list[ResearchRun]:
        """List research runs.

        Args:
            strategy_id: Optional strategy filter.
            portfolio_id: Optional portfolio filter.
            status: Optional status filter.
            limit: Maximum number of runs to return.

        Returns:
            A list of matching research runs.
        """
        return self._repository.list_runs(
            strategy_id=strategy_id,
            portfolio_id=portfolio_id,
            status=status,
            limit=limit,
        )

    def get_run(self, run_id: str) -> ResearchRun:
        """Fetch a research run by identifier.

        Args:
            run_id: Unique identifier of the run.

        Returns:
            The requested research run.

        Raises:
            KeyError: If the run does not exist.
        """
        run = self._repository.get_run(run_id)
        if run is None:
            raise KeyError(f"research run '{run_id}' not found")
        return run

    def get_run_items(self, run_id: str) -> list[ResearchItem]:
        """Fetch all items for a research run.

        Args:
            run_id: Unique identifier of the run.

        Returns:
            A list of research items belonging to the run.

        Raises:
            KeyError: If the run does not exist.
        """
        self.get_run(run_id)
        return self._repository.list_items(run_id)

    def get_item(self, item_id: str) -> ResearchItem:
        """Fetch a research item by identifier.

        Args:
            item_id: Unique identifier of the item.

        Returns:
            The requested research item.

        Raises:
            KeyError: If the item does not exist.
        """
        item = self._repository.get_item(item_id)
        if item is None:
            raise KeyError(f"research item '{item_id}' not found")
        return item

    def get_candidate_cards(self, run_id: str) -> list[CandidateCard]:
        """Build candidate cards for a run.

        Args:
            run_id: Unique identifier of the run.

        Returns:
            A list of candidate cards for the run.

        Raises:
            KeyError: If the run does not exist.
        """
        run = self.get_run(run_id)
        return [self._card_from_item(run, item) for item in self.get_run_items(run_id)]

    def get_home_summary(
        self,
        *,
        portfolio_id: str | None = None,
        strategy_id: str | None = None,
    ) -> HomeSummary:
        """Build the six-block home summary for the dashboard.

        Args:
            portfolio_id: Optional portfolio filter.
            strategy_id: Optional strategy filter.

        Returns:
            A populated home summary, or an empty summary if no runs exist.
        """
        runs = self.list_runs(
            portfolio_id=portfolio_id,
            strategy_id=strategy_id,
            limit=1,
        )
        if not runs:
            return HomeSummary(run_stats={"item_count": 0})
        run = runs[0]
        cards = self.get_candidate_cards(run.run_id)
        return HomeSummary(
            decision_at=run.decision_at,
            run_id=run.run_id,
            strategy_id=run.strategy_id,
            version_id=run.version_id,
            run_status=run.status.value,
            today_candidates=[
                card for card in cards if card.signal_type == "research_candidate"
            ],
            high_priority_risks=[
                card for card in cards if card.signal_type in {"watch", "abstained"}
            ],
            rejections=[
                card
                for card in cards
                if card.research_status in {"abstained", "aborted", "data_missing"}
            ],
            run_stats={
                "item_count": run.item_count,
                "published_count": run.published_count,
                "abstained_count": run.abstained_count,
                "aborted_count": run.aborted_count,
            },
        )

    def _card_from_item(self, run: ResearchRun, item: ResearchItem) -> CandidateCard:
        valuation = ValuationViewService(
            self._repository,
            self._research_repository,
        ).get_valuation_view(item.item_id)
        return CandidateCard(
            item_id=item.item_id,
            run_id=item.run_id,
            symbol=item.symbol,
            signal_type=item.signal_type,
            confidence=item.confidence,
            statement=item.statement,
            research_status=item.status.value,
            valuation_range=valuation.base_valuation_range,
            margin_of_safety=valuation.margin_of_safety,
            value_trap_score=item.risk_score,
            counter_arguments=item.counter_arguments,
            evidence_summary={
                "count": len(item.evidence_ids),
                "levels": {"unknown": len(item.evidence_ids)}
                if item.evidence_ids
                else {},
            },
            watch_conditions=["证据和估值继续满足策略约束"]
            if item.status == ItemStatus.PUBLISHED
            else [],
            invalidation_conditions=item.rejection_reasons
            or item.portfolio_constraint_violations,
            strategy_version=run.version_id,
        )


class EvidenceViewService:
    """Build an evidence expansion view from item and snapshot metadata."""

    def __init__(
        self,
        repository: DashboardRepository,
        research_repository: ResearchRepository,
    ) -> None:
        """Initialize the evidence view service.

        Args:
            repository: Dashboard repository for items.
            research_repository: Repository for module 06 research snapshots.
        """
        self._repository = repository
        self._research_repository = research_repository

    def get_evidence_view(self, item_id: str) -> EvidenceView:
        """Build the evidence view for a research item.

        Args:
            item_id: Unique identifier of the research item.

        Returns:
            An evidence view populated from the item and its snapshot.

        Raises:
            KeyError: If the item does not exist.
        """
        item = _must_get_item(self._repository, item_id)
        snapshot = (
            self._research_repository.get_snapshot(item.snapshot_id)
            if item.snapshot_id
            else None
        )
        evidence_ids = list(item.evidence_ids)
        claim_ids = list(item.claim_ids)
        confidence = item.confidence
        if snapshot is not None:
            evidence_ids = list(snapshot.evidence_ids) or evidence_ids
            claim_ids = list(snapshot.claim_ids) or claim_ids
            if snapshot.signals:
                confidence = max(signal.confidence for signal in snapshot.signals)
        locators = [
            EvidenceLocator(evidence_id=evidence_id)
            for evidence_id in evidence_ids
        ]
        claims = [
            ClaimView(
                claim_id=claim_id,
                statement=item.statement,
                confidence=confidence,
                evidence_ids=evidence_ids,
            )
            for claim_id in claim_ids
        ]
        return EvidenceView(
            item_id=item_id,
            claims=claims,
            evidence_by_level={"unknown": locators} if locators else {},
            source_distribution={"unknown": len(locators)} if locators else {},
            overall_confidence=confidence,
            locators_available=bool(locators),
        )


class ValuationViewService:
    """Build valuation details from module 06 snapshot prior outputs."""

    def __init__(
        self,
        repository: DashboardRepository,
        research_repository: ResearchRepository,
    ) -> None:
        """Initialize the valuation view service.

        Args:
            repository: Dashboard repository for items.
            research_repository: Repository for module 06 research snapshots.
        """
        self._repository = repository
        self._research_repository = research_repository

    def get_valuation_view(self, item_id: str) -> ValuationView:
        """Build the valuation view for a research item.

        Args:
            item_id: Unique identifier of the research item.

        Returns:
            A valuation view with ranges derived from snapshot outputs when available.

        Raises:
            KeyError: If the item does not exist.
        """
        item = _must_get_item(self._repository, item_id)
        snapshot = (
            self._research_repository.get_snapshot(item.snapshot_id)
            if item.snapshot_id
            else None
        )
        prior_outputs = _snapshot_prior_outputs(snapshot)
        value = prior_outputs.get("valuation_tool", {}).get("value")
        risk_score = prior_outputs.get("risk_review", {}).get("risk_score")
        if not isinstance(value, (int, float)):
            return ValuationView(
                item_id=item_id,
                value_trap_score=item.risk_score,
                notes="估值数据暂不可用",
            )
        base_range = (round(value * 0.9, 2), round(value * 1.1, 2))
        pessimistic = (round(value * 0.7, 2), round(value * 0.9, 2))
        return ValuationView(
            item_id=item_id,
            base_valuation_range=base_range,
            pessimistic_range=pessimistic,
            margin_of_safety=None,
            value_trap_score=(
                float(risk_score)
                if isinstance(risk_score, (int, float))
                else item.risk_score
            ),
            method="pe",
            notes="估值区间来自模块 06 valuation_tool 输出",
        )


class FeedbackService:
    """Append feedback without mutating immutable research items."""

    def __init__(self, repository: DashboardRepository) -> None:
        """Initialize the feedback service.

        Args:
            repository: Dashboard repository used to store feedback records.
        """
        self._repository = repository

    def record_feedback(
        self,
        item_id: str,
        feedback_type: FeedbackType,
        comment: str = "",
    ) -> FeedbackRecord:
        """Record feedback for a research item.

        Args:
            item_id: Identifier of the research item.
            feedback_type: Type of feedback action.
            comment: Optional textual comment.

        Returns:
            The persisted feedback record.

        Raises:
            KeyError: If the item does not exist.
        """
        _must_get_item(self._repository, item_id)
        feedback = FeedbackRecord(
            item_id=item_id,
            feedback_type=feedback_type,
            comment=comment,
        )
        self._repository.add_feedback(feedback)
        return feedback


class AuditService:
    """Return module 06 snapshot audit metadata for a dashboard item."""

    def __init__(
        self,
        repository: DashboardRepository,
        research_repository: ResearchRepository,
    ) -> None:
        """Initialize the audit service.

        Args:
            repository: Dashboard repository for items.
            research_repository: Repository for module 06 research snapshots.
        """
        self._repository = repository
        self._research_repository = research_repository

    def get_audit_view(self, item_id: str) -> AuditView:
        """Build an audit view for a research item.

        Args:
            item_id: Unique identifier of the research item.

        Returns:
            An audit view populated from the item's snapshot when available.

        Raises:
            KeyError: If the item does not exist.
        """
        item = _must_get_item(self._repository, item_id)
        snapshot = (
            self._research_repository.get_snapshot(item.snapshot_id)
            if item.snapshot_id
            else None
        )
        if snapshot is None:
            return AuditView(
                item_id=item_id,
                workflow_run_id=item.workflow_run_id,
                snapshot_id=item.snapshot_id,
                error="snapshot unavailable",
            )
        return AuditView(
            item_id=item_id,
            workflow_run_id=item.workflow_run_id,
            snapshot_id=snapshot.snapshot_id,
            workflow_state=snapshot.workflow_state.value,
            input_hash=snapshot.input_hash,
            output_hash=snapshot.output_hash,
            trace_count=len(snapshot.traces),
            tool_call_ids=list(snapshot.tool_call_ids),
            error=snapshot.error,
        )


class ReportRenderer:
    """Render a dashboard item into an auditable research report."""

    def __init__(
        self,
        repository: DashboardRepository,
        research_repository: ResearchRepository,
    ) -> None:
        """Initialize the report renderer.

        Args:
            repository: Dashboard repository for runs and items.
            research_repository: Repository for module 06 research snapshots.
        """
        self._repository = repository
        self._research_repository = research_repository

    def render_report(self, item_id: str) -> ResearchReport:
        """Render a full research report for an item.

        Args:
            item_id: Unique identifier of the research item.

        Returns:
            A rendered research report including valuation, evidence, and audit.

        Raises:
            KeyError: If the item does not exist.
        """
        item = _must_get_item(self._repository, item_id)
        run = self._repository.get_run(item.run_id)
        evidence = EvidenceViewService(
            self._repository,
            self._research_repository,
        ).get_evidence_view(item_id)
        valuation = ValuationViewService(
            self._repository,
            self._research_repository,
        ).get_valuation_view(item_id)
        audit = AuditService(
            self._repository,
            self._research_repository,
        ).get_audit_view(item_id)
        sections = {
            "summary": {
                "symbol": item.symbol,
                "statement": item.statement,
                "signal_type": item.signal_type,
                "status": item.status.value,
                "confidence": item.confidence,
                "decision_at": run.decision_at.isoformat() if run else None,
                "strategy_version": run.version_id if run else "",
                "disclaimer": CandidateCard.model_fields[
                    "disclaimer"
                ].default,
            },
            "valuation": valuation.model_dump(mode="json"),
            "evidence": evidence.model_dump(mode="json"),
            "counter_arguments": list(item.counter_arguments),
            "rejection_reasons": list(item.rejection_reasons),
            "portfolio_constraint_violations": list(
                item.portfolio_constraint_violations
            ),
            "audit": audit.model_dump(mode="json"),
        }
        title = f"{item.symbol} 研究报告"
        return ResearchReport(
            item_id=item.item_id,
            run_id=item.run_id,
            symbol=item.symbol,
            title=title,
            content=_render_markdown_report(title, sections),
            sections=sections,
        )


class ExportService:
    """Export rendered dashboard reports in lightweight MVP formats."""

    def __init__(self, renderer: ReportRenderer) -> None:
        """Initialize the export service.

        Args:
            renderer: Report renderer used to produce report content.
        """
        self._renderer = renderer

    def export_report(
        self,
        item_id: str,
        report_format: str | ReportFormat = ReportFormat.MARKDOWN,
    ) -> ReportExport:
        """Export a research report in the requested format.

        Args:
            item_id: Unique identifier of the research item.
            report_format: Desired export format; defaults to Markdown.

        Returns:
            An export payload containing content, filename, and MIME type.

        Raises:
            ValueError: If the requested report format is not supported.
        """
        resolved_format = _coerce_report_format(report_format)
        report = self._renderer.render_report(item_id)
        if resolved_format == ReportFormat.JSON:
            content = json.dumps(
                report.model_dump(mode="json"),
                ensure_ascii=False,
                sort_keys=True,
            )
            extension = "json"
            mime_type = "application/json"
        else:
            content = report.content
            extension = "md"
            mime_type = "text/markdown"
        return ReportExport(
            item_id=report.item_id,
            format=resolved_format,
            filename=f"{report.symbol}_{report.item_id}_research_report.{extension}",
            mime_type=mime_type,
            content=content,
        )


class ProviderStatusService:
    """Provider health service for the dashboard BFF."""

    def __init__(self, providers: list[Any] | None = None) -> None:
        """Initialize the provider status service.

        Args:
            providers: Optional list of providers exposing a healthcheck method.
        """
        self._providers = list(providers or [])

    def list_status(self) -> list[ProviderStatus]:
        """List the health status of configured providers.

        Returns:
            A list of provider statuses. Falls back to a healthy dashboard status
            when no providers are configured.
        """
        if self._providers:
            statuses: list[ProviderStatus] = []
            for provider in self._providers:
                try:
                    health = provider.healthcheck()
                    statuses.append(
                        ProviderStatus(
                            provider=health.provider_name,
                            status=health.status.value,
                            message=health.message or "",
                        )
                    )
                except Exception as exc:  # noqa: BLE001
                    descriptor = getattr(provider, "descriptor", None)
                    statuses.append(
                        ProviderStatus(
                            provider=getattr(descriptor, "name", "unknown"),
                            status="unhealthy",
                            message=f"{type(exc).__name__}: {exc}",
                        )
                    )
            return statuses
        return [
            ProviderStatus(
                provider="dashboard",
                status="healthy",
                message="dashboard BFF ready",
            )
        ]


class JobService:
    """Synchronous job registry for v0.1 nightly run endpoints."""

    def __init__(self) -> None:
        """Initialize an empty job registry."""
        self._jobs: dict[str, JobRun] = {}

    def record_completed_job(self, run_id: str) -> JobRun:
        """Record a completed nightly job for a research run.

        Args:
            run_id: Identifier of the research run associated with the job.

        Returns:
            The recorded job run.
        """
        job = JobRun(run_id=run_id, payload_json=json.dumps({"run_id": run_id}))
        self._jobs[job.job_run_id] = job
        return job

    def get_job(self, job_run_id: str) -> JobRun:
        """Fetch a job run by identifier.

        Args:
            job_run_id: Unique identifier of the job run.

        Returns:
            The requested job run.

        Raises:
            KeyError: If the job run does not exist.
        """
        job = self._jobs.get(job_run_id)
        if job is None:
            raise KeyError(f"job run '{job_run_id}' not found")
        return job


@dataclass(frozen=True)
class DashboardServiceBundle:
    """Container for FastAPI dependency injection."""

    research: DashboardResearchService
    query: DashboardQueryService
    evidence: EvidenceViewService
    valuation: ValuationViewService
    feedback: FeedbackService
    audit: AuditService
    reports: ReportRenderer
    exports: ExportService
    providers: ProviderStatusService
    jobs: JobService

    @classmethod
    def in_memory(
        cls,
        *,
        dashboard_repository: MemoryDashboardRepository | None = None,
        research_repository: MemoryResearchRepository | None = None,
        research_service: Any | None = None,
    ) -> DashboardServiceBundle:
        """Create a service bundle backed by in-memory repositories.

        Args:
            dashboard_repository: Optional dashboard repository instance.
            research_repository: Optional research repository instance.
            research_service: Optional research service instance.

        Returns:
            A fully wired in-memory service bundle.
        """
        dashboard_repository = dashboard_repository or MemoryDashboardRepository()
        research_repository = research_repository or MemoryResearchRepository()
        research_service = research_service or ResearchService(
            repository=research_repository
        )
        return cls.from_repositories(
            dashboard_repository=dashboard_repository,
            research_repository=research_repository,
            research_service=research_service,
        )

    @classmethod
    def from_repositories(
        cls,
        *,
        dashboard_repository: DashboardRepository,
        research_repository: ResearchRepository,
        research_service: Any,
        providers: list[Any] | None = None,
    ) -> DashboardServiceBundle:
        """Create a service bundle from existing repositories.

        Args:
            dashboard_repository: Dashboard repository implementation.
            research_repository: Research repository implementation.
            research_service: Service capable of running symbol research workflows.
            providers: Optional list of providers to health-check.

        Returns:
            A fully wired service bundle.
        """
        reports = ReportRenderer(dashboard_repository, research_repository)
        return cls(
            research=DashboardResearchService(research_service, dashboard_repository),
            query=DashboardQueryService(dashboard_repository, research_repository),
            evidence=EvidenceViewService(dashboard_repository, research_repository),
            valuation=ValuationViewService(dashboard_repository, research_repository),
            feedback=FeedbackService(dashboard_repository),
            audit=AuditService(dashboard_repository, research_repository),
            reports=reports,
            exports=ExportService(reports),
            providers=ProviderStatusService(providers),
            jobs=JobService(),
        )


def _item_status(
    state: WorkflowState,
    signal_type: SignalType | None,
) -> ItemStatus:
    if state == WorkflowState.ABORTED:
        return ItemStatus.ABORTED
    if state == WorkflowState.ABSTAINED or signal_type == SignalType.ABSTAINED:
        return ItemStatus.ABSTAINED
    if state == WorkflowState.PUBLISHED:
        return ItemStatus.PUBLISHED
    return ItemStatus.DATA_MISSING


def _run_status(
    published_count: int,
    abstained_count: int,
    aborted_count: int,
    total: int,
) -> RunStatus:
    if total == 0 or aborted_count == total:
        return RunStatus.ABORTED
    if abstained_count == total:
        return RunStatus.ABSTAINED
    if published_count == total:
        return RunStatus.PUBLISHED
    return RunStatus.PARTIAL


def _must_get_item(
    repository: DashboardRepository,
    item_id: str,
) -> ResearchItem:
    item = repository.get_item(item_id)
    if item is None:
        raise KeyError(f"research item '{item_id}' not found")
    return item


def _snapshot_prior_outputs(snapshot: Any | None) -> dict[str, Any]:
    if snapshot is None:
        return {}
    try:
        data = json.loads(snapshot.agent_outputs_json)
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


def _coerce_report_format(report_format: str | ReportFormat) -> ReportFormat:
    if isinstance(report_format, ReportFormat):
        return report_format
    try:
        return ReportFormat(report_format)
    except ValueError as exc:
        raise ValueError(f"unsupported report format: {report_format}") from exc


def _render_markdown_report(title: str, sections: dict[str, Any]) -> str:
    summary = sections["summary"]
    valuation = sections["valuation"]
    evidence = sections["evidence"]
    counter_arguments = sections["counter_arguments"]
    rejection_reasons = sections["rejection_reasons"]
    audit = sections["audit"]
    lines = [
        f"# {title}",
        "",
        str(summary["disclaimer"]),
        "",
        "## 研究结论",
        f"- 标的：{summary['symbol']}",
        f"- 状态：{summary['status']}",
        f"- 置信度：{summary['confidence']:.0%}",
        f"- 结论：{summary['statement'] or '暂无结论'}",
        "",
        "## 估值",
        f"- 基准估值区间：{valuation.get('base_valuation_range') or '暂无'}",
        f"- 悲观估值区间：{valuation.get('pessimistic_range') or '暂无'}",
        f"- 价值陷阱风险：{valuation.get('value_trap_score')}",
        "",
        "## 证据",
        f"- Claim 数：{len(evidence.get('claims', []))}",
        f"- 来源分布：{evidence.get('source_distribution', {})}",
        f"- 原文定位：{evidence.get('locators_available', False)}",
        "",
        "## 反方与拒绝原因",
        f"- 反方理由：{counter_arguments or ['暂无']}",
        f"- 拒绝原因：{rejection_reasons or ['暂无']}",
        "",
        "## 审计追溯",
        f"- snapshot_id：{audit.get('snapshot_id') or '--'}",
        f"- workflow_run_id：{audit.get('workflow_run_id') or '--'}",
        f"- input_hash：{audit.get('input_hash') or '--'}",
        f"- output_hash：{audit.get('output_hash') or '--'}",
    ]
    return "\n".join(lines)
