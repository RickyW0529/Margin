"""High-level services for the research candidate dashboard module."""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from margin.dashboard.models import (
    DashboardFilters,
    DashboardSort,
    FeedbackRecord,
    FeedbackType,
    ItemStatus,
    JobRun,
    ProviderStatus,
    ResearchCandidateListItemV2,
    ResearchCandidateListResponse,
    ResearchItem,
    ResearchItemDetailV2,
    ResearchRun,
)
from margin.dashboard.repository import DashboardRepository, MemoryDashboardRepository

QuantProfileLoader = Callable[[str], dict[str, Any] | None]


class DashboardQueryService:
    """Read-only dashboard query service for v0.2 candidate data."""

    def __init__(
        self,
        repository: DashboardRepository,
        quant_profile_loader: QuantProfileLoader | None = None,
    ) -> None:
        """Initialize the query service.

        Args:
            repository: Dashboard repository for runs, items, and feedback.
            quant_profile_loader: Optional callable that returns a quant
                profile dict (with five factor scores) for a security id.
        """
        self._repository = repository
        self._quant_profile_loader = quant_profile_loader

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
        """Return one v0.2 paged candidate list."""
        return self._repository.list_research_candidates_v2(
            scope_version_id=scope_version_id,
            universe_code=universe_code,
            filters=filters,
            sort=sort,
            cursor=cursor,
            limit=limit,
        )
    def get_item_detail_v2(self, item_id: str) -> ResearchItemDetailV2:
        """Return the v0.2 company detail aggregate for a research item."""
        item = self.get_item(item_id)
        run = self.get_run(item.run_id)
        quant_factors = self._load_quant_factors(item.symbol)
        factors: dict[str, Any] = {
            "risk_score": item.risk_score,
            "confidence": item.confidence,
        }
        factors.update(quant_factors)
        return ResearchItemDetailV2(
            item=_candidate_item_from_research_item(item, run),
            current_review={
                "outcome": (
                    "update_assessment"
                    if item.status == ItemStatus.PUBLISHED
                    else "abstain"
                ),
                "reason": item.abstain_reason,
                "run_id": item.run_id,
                "workflow_run_id": item.workflow_run_id,
            },
            effective_assessment={
                "assessment_id": item.snapshot_id,
                "freshness": (
                    "current" if item.status == ItemStatus.PUBLISHED else "stale"
                ),
                "stale_reason": item.abstain_reason,
            },
            factors=factors,
            thesis={
                "statement": item.statement,
                "counter_arguments": tuple(item.counter_arguments),
                "rejection_reasons": tuple(item.rejection_reasons),
            },
            evidence=tuple(
                {
                    "evidence_id": evidence_id,
                    "source_level": "unknown",
                    "locator": "stored evidence reference",
                    "snapshot_id": item.snapshot_id,
                }
                for evidence_id in item.evidence_ids
            ),
            versions={
                "run_id": run.run_id,
                "strategy_id": run.strategy_id,
                "strategy_version_id": run.version_id,
                "scope_version_id": run.version_id,
                "workflow_run_id": item.workflow_run_id,
                "snapshot_id": item.snapshot_id or "",
            },
        )

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

    def _load_quant_factors(self, symbol: str) -> dict[str, Any]:
        """Load five-factor scores for a symbol via the optional loader.

        Returns an empty dict when no loader is configured or no quant result
        exists, so the detail page degrades gracefully without erroring.
        """
        if self._quant_profile_loader is None:
            return {}
        try:
            profile = self._quant_profile_loader(symbol)
        except Exception:
            return {}
        if not profile:
            return {}
        factor_scores = profile.get("factor_scores") or []
        result: dict[str, Any] = {}
        for item in factor_scores:
            key = item.get("factor_key")
            if key:
                result[key] = item.get("score")
        for extra_key in (
            "final_score",
            "rank_overall",
            "rank_in_industry",
            "screening_status",
            "research_guardrail",
            "reason_summary",
        ):
            value = profile.get(extra_key)
            if value is not None:
                result[extra_key] = value
        return result


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

    query: DashboardQueryService
    feedback: FeedbackService
    providers: ProviderStatusService
    jobs: JobService

    @classmethod
    def in_memory(
        cls,
        *,
        dashboard_repository: MemoryDashboardRepository | None = None,
    ) -> DashboardServiceBundle:
        """Create a service bundle backed by in-memory repositories.

        Args:
            dashboard_repository: Optional dashboard repository instance.

        Returns:
            A fully wired in-memory service bundle.
        """
        dashboard_repository = dashboard_repository or MemoryDashboardRepository()
        return cls.from_repositories(
            dashboard_repository=dashboard_repository,
        )

    @classmethod
    def from_repositories(
        cls,
        *,
        dashboard_repository: DashboardRepository,
        providers: list[Any] | None = None,
        quant_profile_loader: QuantProfileLoader | None = None,
    ) -> DashboardServiceBundle:
        """Create a service bundle from existing repositories.

        Args:
            dashboard_repository: Dashboard repository implementation.
            providers: Optional list of providers to health-check.
            quant_profile_loader: Optional callable returning a quant profile
                dict (with five factor scores) for a security id.

        Returns:
            A fully wired service bundle.
        """
        return cls(
            query=DashboardQueryService(dashboard_repository, quant_profile_loader),
            feedback=FeedbackService(dashboard_repository),
            providers=ProviderStatusService(providers),
            jobs=JobService(),
        )


def _must_get_item(
    repository: DashboardRepository,
    item_id: str,
) -> ResearchItem:
    """must get item."""
    item = repository.get_item(item_id)
    if item is None:
        raise KeyError(f"research item '{item_id}' not found")
    return item


def _candidate_item_from_research_item(
    item: ResearchItem,
    run: ResearchRun,
) -> ResearchCandidateListItemV2:
    """Build the list/detail item DTO without exposing internal prompts."""
    screening_status = (
        "pass" if item.status == ItemStatus.PUBLISHED else item.status.value
    )
    return ResearchCandidateListItemV2(
        item_id=item.item_id,
        security_id=item.symbol,
        symbol=item.symbol.split(".")[0],
        name=item.symbol,
        scope_version_id=run.version_id,
        screening_status=screening_status,
        data_status="complete" if item.status == ItemStatus.PUBLISHED else "partial",
        risk_flags=tuple(item.rejection_reasons),
        review_required=item.status != ItemStatus.PUBLISHED,
        research_guardrail=(
            "allow_research"
            if item.status == ItemStatus.PUBLISHED
            else "review_required"
        ),
        current_review_outcome=(
            "update_assessment" if item.status == ItemStatus.PUBLISHED else "abstain"
        ),
        effective_assessment_id=item.snapshot_id,
        assessment_freshness=(
            "current" if item.status == ItemStatus.PUBLISHED else "stale"
        ),
        stale_reason=item.abstain_reason,
        final_score=round(item.confidence * 100, 4),
        discount_rate=None,
        confidence=item.confidence,
        last_checked_at=item.created_at,
    )
