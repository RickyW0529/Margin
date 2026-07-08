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
DetailContextLoader = Callable[[ResearchItem, ResearchRun], dict[str, Any] | None]


class DashboardQueryService:
    """Read-only dashboard query service for v0.2 candidate data."""

    def __init__(
        self,
        repository: DashboardRepository,
        quant_profile_loader: QuantProfileLoader | None = None,
        detail_context_loader: DetailContextLoader | None = None,
    ) -> None:
        """Initialize the query service.

        Args:
            repository: Dashboard repository for runs, items, and feedback.
            quant_profile_loader: Optional callable that returns a quant
                profile dict (with five factor scores) for a security id.
        """
        self._repository = repository
        self._quant_profile_loader = quant_profile_loader
        self._detail_context_loader = detail_context_loader

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
        page = self._repository.list_research_candidates_v2(
            scope_version_id=scope_version_id,
            universe_code=universe_code,
            filters=filters,
            sort=sort,
            cursor=cursor,
            limit=limit,
        )
        return self._enrich_candidate_page(page)

    def get_item_detail_v2(self, item_id: str) -> ResearchItemDetailV2:
        """Return the v0.2 company detail aggregate for a research item."""
        item = self.get_item(item_id)
        run = self.get_run(item.run_id)
        profile = self._load_quant_profile(item.symbol)
        context = self._load_detail_context(item, run)
        quant_factors = self._quant_factors_from_profile(profile)
        factors: dict[str, Any] = {
            "risk_score": item.risk_score,
            "confidence": item.confidence,
        }
        factors.update(quant_factors)
        factors = _merge_dicts(factors, _dict_value(context, "factors"))
        current_review = _merge_dicts(
            {
                "outcome": (
                    "update_assessment"
                    if item.status == ItemStatus.PUBLISHED
                    else "abstain"
                ),
                "reason": item.abstain_reason,
                "run_id": item.run_id,
                "workflow_run_id": item.workflow_run_id,
            },
            _dict_value(context, "current_review"),
        )
        effective_assessment = _merge_dicts(
            {
                "assessment_id": item.snapshot_id,
                "freshness": (
                    "current" if item.status == ItemStatus.PUBLISHED else "stale"
                ),
                "stale_reason": item.abstain_reason,
            },
            _dict_value(context, "effective_assessment"),
        )
        thesis = _merge_dicts(
            {
                "statement": item.statement,
                "counter_arguments": tuple(item.counter_arguments),
                "rejection_reasons": tuple(item.rejection_reasons),
            },
            _dict_value(context, "thesis"),
        )
        context_evidence = context.get("evidence") if isinstance(context, dict) else None
        evidence = (
            tuple(context_evidence)
            if isinstance(context_evidence, list | tuple)
            else tuple(
                {
                    "evidence_id": evidence_id,
                    "source_level": "unknown",
                    "locator": "stored evidence reference",
                    "snapshot_id": item.snapshot_id,
                }
                for evidence_id in item.evidence_ids
            )
        )
        versions = _merge_dicts(
            {
                "run_id": run.run_id,
                "strategy_id": run.strategy_id,
                "strategy_version_id": run.version_id,
                "scope_version_id": run.version_id,
                "workflow_run_id": item.workflow_run_id,
                "snapshot_id": item.snapshot_id or "",
            },
            _dict_value(context, "versions"),
        )
        candidate = _candidate_item_from_research_item(item, run)
        candidate = self._enrich_candidate(candidate, profile=profile, context=context)
        return ResearchItemDetailV2(
            item=candidate,
            current_review=current_review,
            effective_assessment=effective_assessment,
            factors=factors,
            thesis=thesis,
            evidence=evidence,
            versions=versions,
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
        return self._quant_factors_from_profile(self._load_quant_profile(symbol))

    def _load_quant_profile(self, symbol: str) -> dict[str, Any]:
        """Load the optional quant profile, swallowing provider gaps."""
        if self._quant_profile_loader is None:
            return {}
        try:
            profile = self._quant_profile_loader(symbol)
        except Exception:
            return {}
        if not profile:
            return {}
        return dict(profile)

    def _quant_factors_from_profile(self, profile: dict[str, Any]) -> dict[str, Any]:
        """Extract numeric factor values from a quant profile dict."""
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

    def _load_detail_context(
        self,
        item: ResearchItem,
        run: ResearchRun,
    ) -> dict[str, Any]:
        """Load optional context data for one detail page."""
        if self._detail_context_loader is None:
            return {}
        try:
            context = self._detail_context_loader(item, run)
        except Exception:
            return {}
        return dict(context or {})

    def _enrich_candidate_page(
        self,
        page: ResearchCandidateListResponse,
    ) -> ResearchCandidateListResponse:
        """Apply profile-driven display fields to one candidate page."""
        if self._quant_profile_loader is None:
            return page
        items = tuple(
            self._enrich_candidate(
                item,
                profile=self._load_quant_profile(item.security_id),
                context={},
            )
            for item in page.items
        )
        return ResearchCandidateListResponse(
            items=items,
            page_info=page.page_info,
            facets=page.facets,
            as_of=page.as_of,
            scope_version_id=page.scope_version_id,
        )

    def _enrich_candidate(
        self,
        item: ResearchCandidateListItemV2,
        *,
        profile: dict[str, Any],
        context: dict[str, Any],
    ) -> ResearchCandidateListItemV2:
        """Return a candidate with display name and valuation overrides."""
        display_name = (
            _string_value(context, "display_name")
            or _string_value(profile, "display_name")
            or _string_value(profile.get("factor_details"), "name")
            or item.name
        )
        discount_rate = item.discount_rate
        valuation = _dict_value(context, "factors").get("valuation")
        if isinstance(valuation, dict):
            discount_rate = _optional_float(valuation.get("discount_rate"), discount_rate)
        discount_rate = _optional_float(profile.get("discount_rate"), discount_rate)
        return item.model_copy(
            update={
                "name": display_name,
                "discount_rate": discount_rate,
            }
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
        detail_context_loader: DetailContextLoader | None = None,
    ) -> DashboardServiceBundle:
        """Create a service bundle from existing repositories.

        Args:
            dashboard_repository: Dashboard repository implementation.
            providers: Optional list of providers to health-check.
            quant_profile_loader: Optional callable returning a quant profile
                dict (with five factor scores) for a security id.
            detail_context_loader: Optional callable returning AI/news/valuation
                context for a detail item.

        Returns:
            A fully wired service bundle.
        """
        return cls(
            query=DashboardQueryService(
                dashboard_repository,
                quant_profile_loader,
                detail_context_loader,
            ),
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
    screening_status = _screening_status_from_item(item)
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
        target_weight=item.target_weight,
        adjusted_weight=item.adjusted_weight,
        agent_adjustment=dict(item.agent_adjustment),
        discount_rate=None,
        confidence=item.confidence,
        last_checked_at=item.created_at,
    )


def _screening_status_from_item(item: ResearchItem) -> str:
    """Return the quant screening status carried by a dashboard item."""
    prefix = "quant_screen:"
    if item.signal_type.startswith(prefix):
        return item.signal_type.removeprefix(prefix)
    return "pass" if item.status == ItemStatus.PUBLISHED else item.status.value


def _merge_dicts(base: dict[str, Any], update: dict[str, Any]) -> dict[str, Any]:
    """Shallow merge two dicts while preserving base when update is empty."""
    if not update:
        return base
    merged = dict(base)
    merged.update(update)
    return merged


def _dict_value(value: Any, key: str | None = None) -> dict[str, Any]:
    """Return a nested dict or an empty dict."""
    candidate = value.get(key) if key is not None and isinstance(value, dict) else value
    return dict(candidate) if isinstance(candidate, dict) else {}


def _string_value(value: Any, key: str | None = None) -> str | None:
    """Return a non-empty string from a dict or raw value."""
    candidate = value.get(key) if key is not None and isinstance(value, dict) else value
    if isinstance(candidate, str) and candidate.strip():
        return candidate.strip()
    return None


def _optional_float(value: Any, fallback: float | None = None) -> float | None:
    """Return a float when conversion is possible."""
    if value is None:
        return fallback
    try:
        return float(value)
    except (TypeError, ValueError):
        return fallback
