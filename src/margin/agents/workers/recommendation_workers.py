"""Durable workers for scheduled stock recommendation research.

The three workers in this module deliberately separate deterministic quant
serving, filing-catalyst research, and portfolio construction.  They exchange
frozen, JSON-serializable artifacts so the outer durable orchestrator can
resume each boundary after a process restart.
"""

from __future__ import annotations

import hashlib
import inspect
import json
from collections.abc import Callable, Mapping, Sequence
from datetime import date, datetime
from typing import Any, Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field, field_validator

from margin.valuation_discovery.models import (
    DataStatus,
    ResearchGuardrail,
    ScreeningStatus,
)


class RecommendationArtifactRepository(Protocol):
    """Persistence boundary shared by all recommendation workers."""

    def save(
        self,
        *,
        artifact_id: str,
        orchestration_run_id: str,
        worker_name: str,
        artifact_type: str,
        scope_version_id: str,
        decision_at: datetime,
        payload: dict[str, Any],
    ) -> None:
        """Persist an immutable worker artifact idempotently."""

    def load(self, artifact_id: str) -> dict[str, Any] | None:
        """Load one previously persisted worker artifact."""


class MemoryRecommendationArtifactRepository:
    """In-memory artifact repository used by unit tests and local composition."""

    def __init__(self) -> None:
        self._payloads: dict[str, dict[str, Any]] = {}

    def save(
        self,
        *,
        artifact_id: str,
        orchestration_run_id: str,
        worker_name: str,
        artifact_type: str,
        scope_version_id: str,
        decision_at: datetime,
        payload: dict[str, Any],
    ) -> None:
        del orchestration_run_id, worker_name, artifact_type, scope_version_id, decision_at
        existing = self._payloads.get(artifact_id)
        if existing is not None and existing != payload:
            raise ValueError(f"conflicting recommendation artifact: {artifact_id}")
        self._payloads[artifact_id] = dict(payload)

    def load(self, artifact_id: str) -> dict[str, Any] | None:
        payload = self._payloads.get(artifact_id)
        return dict(payload) if payload is not None else None


class FrozenWorkerModel(BaseModel):
    """Immutable JSON contract emitted by a recommendation worker."""

    model_config = ConfigDict(frozen=True, extra="forbid")


class RecommendationEvidenceRef(FrozenWorkerModel):
    """One auditable source used by quant, RAG, warehouse, or WebSearch."""

    source_type: str
    source_id: str
    title: str = ""
    url: str | None = None
    locator: dict[str, Any] = Field(default_factory=dict)
    excerpt: str = ""


class QuantRecommendationCandidate(FrozenWorkerModel):
    """A quant-passed candidate and its base portfolio weight."""

    security_id: str
    quant_result_id: str
    score: float
    screening_status: str
    target_weight: float
    risk_flags: tuple[str, ...] = ()
    review_required: bool = False
    reasons: tuple[str, ...] = ()
    evidence: tuple[RecommendationEvidenceRef, ...] = ()


class MLQuantWorkerResult(FrozenWorkerModel):
    """Frozen output of the deterministic MLQuantWorker serving boundary."""

    artifact_id: str
    orchestration_run_id: str
    quant_run_id: str
    profile_id: str
    strategy_family: str
    model_family: str
    implementation: str
    max_stock_exposure: float
    min_cash: float
    candidates: tuple[QuantRecommendationCandidate, ...] = ()


class CatalystResearchContext(FrozenWorkerModel):
    """Small, frozen view of one RAG context needed by the catalyst worker."""

    context_snapshot_id: str
    security_id: str
    previous_conclusion: str = ""
    previous_assessment_id: str | None = None
    evidence_ids: tuple[str, ...] = ()
    new_filing_document_ids: tuple[str, ...] = ()


class CatalystCandidate(FrozenWorkerModel):
    """Agent-reviewed filing catalyst for one security."""

    security_id: str
    context_snapshot_id: str
    review_id: str | None = None
    direction: Literal["positive", "neutral", "negative", "uncertain"] = "uncertain"
    confidence: float = 0.0
    conclusion: str = ""
    previous_conclusion: str = ""
    contradiction_status: Literal[
        "not_checked",
        "no_counter_evidence",
        "counter_evidence_found",
    ] = "not_checked"
    reasons: tuple[str, ...] = ()
    evidence: tuple[RecommendationEvidenceRef, ...] = ()

    @field_validator("confidence")
    @classmethod
    def validate_confidence(cls, value: float) -> float:
        return max(0.0, min(float(value), 1.0))


class EarningsCatalystWorkerResult(FrozenWorkerModel):
    """Frozen output of the filing-season/RAG catalyst worker."""

    artifact_id: str
    orchestration_run_id: str
    status: Literal["completed", "skipped_outside_reporting_window"]
    trigger_reasons: tuple[str, ...] = ()
    context_snapshot_ids: tuple[str, ...] = ()
    review_ids: tuple[str, ...] = ()
    candidates: tuple[CatalystCandidate, ...] = ()


class FusedRecommendation(FrozenWorkerModel):
    """One final recommendation exposed to Dashboard consumers."""

    security_id: str
    target_weight: float
    adjusted_weight: float
    quant_score: float | None = Field(default=None, ge=0.0, le=100.0)
    fusion_confidence: float = Field(default=0.70, ge=0.0, le=1.0)
    quant_contribution: float
    catalyst_contribution: float
    sources: tuple[str, ...]
    reasons: tuple[str, ...]
    risk_flags: tuple[str, ...] = ()
    evidence: tuple[RecommendationEvidenceRef, ...] = ()


class RecommendationFusionPolicy(FrozenWorkerModel):
    """Explicit conservative construction policy for the two research lines."""

    catalyst_only_max_weight: float = Field(default=0.02, ge=0.0, le=1.0)
    catalyst_only_min_confidence: float = Field(default=0.70, ge=0.0, le=1.0)
    require_catalyst_evidence: bool = True
    fill_remaining_quant_budget: bool = True


class RecommendationFusionResult(FrozenWorkerModel):
    """Cash-aware terminal portfolio produced before Dashboard publication."""

    artifact_id: str
    orchestration_run_id: str
    quant_run_id: str
    max_stock_exposure: float
    policy: RecommendationFusionPolicy
    stock_weight: float
    cash_weight: float
    recommendations: tuple[FusedRecommendation, ...] = ()
    excluded_security_ids: tuple[str, ...] = ()


class MLQuantWorker:
    """Freeze the selected profile and execute the actual quant serving route."""

    name = "MLQuantWorker"
    implementation = "deterministic_weighted_signal_formula_v1"

    def __init__(
        self,
        *,
        quant_service: Any,
        repository: RecommendationArtifactRepository,
    ) -> None:
        self._quant_service = quant_service
        self._repository = repository

    def run(
        self,
        *,
        orchestration_run_id: str,
        scope_version_id: str,
        decision_at: datetime,
        input_snapshot: Any,
        profile: Mapping[str, Any] | Any,
    ) -> MLQuantWorkerResult:
        """Run quant with the frozen profile and persist candidate weights."""
        _, strategy_metadata = _profile_metadata(profile)
        kwargs = {
            "scope_version_id": scope_version_id,
            "decision_at": decision_at,
            "input_snapshot": input_snapshot,
            "strategy_metadata": strategy_metadata,
        }
        quant_run = self._quant_service.run(**_supported_kwargs(self._quant_service.run, kwargs))
        return self.materialize_existing(
            orchestration_run_id=orchestration_run_id,
            scope_version_id=scope_version_id,
            decision_at=decision_at,
            quant_run=quant_run,
            profile=profile,
        )

    def materialize_existing(
        self,
        *,
        orchestration_run_id: str,
        scope_version_id: str,
        decision_at: datetime,
        quant_run: Any,
        profile: Mapping[str, Any] | Any,
    ) -> MLQuantWorkerResult:
        """Wrap a legacy persisted quant run without executing it a second time."""
        profile_metadata, strategy_metadata = _profile_metadata(profile)
        thresholds = strategy_metadata.get("thresholds")
        if not isinstance(thresholds, dict):
            thresholds = {}
        max_stock_exposure = _bounded_float(thresholds.get("max_stock_exposure"), default=0.8)
        min_cash = max(
            _bounded_float(thresholds.get("min_cash"), default=0.2),
            1.0 - max_stock_exposure,
        )
        candidates = tuple(
            candidate
            for result in tuple(getattr(quant_run, "results", ()) or ())
            if (candidate := _quant_candidate(result)) is not None
        )
        artifact_id = _artifact_id(orchestration_run_id, self.name)
        output = MLQuantWorkerResult(
            artifact_id=artifact_id,
            orchestration_run_id=orchestration_run_id,
            quant_run_id=str(getattr(quant_run, "quant_run_id", "")),
            profile_id=str(profile_metadata.get("profile_id") or "unversioned"),
            strategy_family=str(
                strategy_metadata.get("strategy_family")
                or profile_metadata.get("strategy_family")
                or "deterministic_weighted_signal_lifecycle"
            ),
            model_family=str(
                profile_metadata.get("model_family")
                or strategy_metadata.get("model_family")
                or "deterministic_weighted_signal"
            ),
            implementation=str(
                profile_metadata.get("implementation")
                or strategy_metadata.get("implementation")
                or self.implementation
            ),
            max_stock_exposure=max_stock_exposure,
            min_cash=min_cash,
            candidates=candidates,
        )
        self._save(output, scope_version_id=scope_version_id, decision_at=decision_at)
        return output

    def load(self, artifact_id: str) -> MLQuantWorkerResult:
        payload = self._repository.load(artifact_id)
        if payload is None:
            raise KeyError(f"ML quant artifact not found: {artifact_id}")
        return MLQuantWorkerResult.model_validate(payload)

    def _save(
        self,
        output: MLQuantWorkerResult,
        *,
        scope_version_id: str,
        decision_at: datetime,
    ) -> None:
        self._repository.save(
            artifact_id=output.artifact_id,
            orchestration_run_id=output.orchestration_run_id,
            worker_name=self.name,
            artifact_type="ml_quant_result",
            scope_version_id=scope_version_id,
            decision_at=decision_at,
            payload=output.model_dump(mode="json"),
        )


class EarningsCatalystWorker:
    """Review RAG filings in reporting windows and search for counter-evidence."""

    name = "EarningsCatalystWorker"

    def __init__(
        self,
        *,
        review_service: Any,
        repository: RecommendationArtifactRepository,
        context_loader: Callable[[Sequence[str]], Sequence[CatalystResearchContext]] | None = None,
        review_loader: Callable[[str], Any | None] | None = None,
        websearch_provider: Any | None = None,
    ) -> None:
        self._review_service = review_service
        self._repository = repository
        self._context_loader = context_loader
        self._review_loader = review_loader
        self._websearch = websearch_provider

    def run(
        self,
        *,
        orchestration_run_id: str,
        scope_version_id: str,
        decision_at: datetime,
        context_snapshot_ids: Sequence[str],
    ) -> EarningsCatalystWorkerResult:
        """Run only in a reporting window; newly indexed filings refine the trigger."""
        context_ids = tuple(str(value) for value in context_snapshot_ids)
        contexts = self._load_contexts(
            context_ids,
            scope_version_id=scope_version_id,
            decision_at=decision_at,
        )
        context_ids = tuple(context.context_snapshot_id for context in contexts)
        new_filing_ids = tuple(
            document_id for context in contexts for document_id in context.new_filing_document_ids
        )
        in_reporting_window = is_china_reporting_window(decision_at.date())
        trigger_reasons: list[str] = []
        if in_reporting_window:
            trigger_reasons.append("financial_reporting_window")
            if new_filing_ids:
                trigger_reasons.append("new_rag_filing_ingested")
        artifact_id = _artifact_id(orchestration_run_id, self.name)
        if not in_reporting_window:
            output = EarningsCatalystWorkerResult(
                artifact_id=artifact_id,
                orchestration_run_id=orchestration_run_id,
                status="skipped_outside_reporting_window",
                context_snapshot_ids=context_ids,
            )
            self._save(output, scope_version_id=scope_version_id, decision_at=decision_at)
            return output

        summary = self._review_service.review(
            context_snapshot_ids=context_ids,
            decision_at=decision_at,
        )
        review_ids = tuple(str(value) for value in getattr(summary, "review_ids", ()) or ())
        candidates = tuple(
            self._candidate_from_context(
                context,
                review_id=(review_ids[index] if index < len(review_ids) else None),
                decision_at=decision_at,
            )
            for index, context in enumerate(contexts)
        )
        output = EarningsCatalystWorkerResult(
            artifact_id=artifact_id,
            orchestration_run_id=orchestration_run_id,
            status="completed",
            trigger_reasons=tuple(trigger_reasons),
            context_snapshot_ids=context_ids,
            review_ids=review_ids,
            candidates=candidates,
        )
        self._save(output, scope_version_id=scope_version_id, decision_at=decision_at)
        return output

    def load(self, artifact_id: str) -> EarningsCatalystWorkerResult:
        payload = self._repository.load(artifact_id)
        if payload is None:
            raise KeyError(f"earnings catalyst artifact not found: {artifact_id}")
        return EarningsCatalystWorkerResult.model_validate(payload)

    def materialize_existing(
        self,
        *,
        orchestration_run_id: str,
        scope_version_id: str,
        decision_at: datetime,
        context_snapshot_ids: Sequence[str],
    ) -> EarningsCatalystWorkerResult:
        """Wrap reviews completed under the historical AI_DELTA_REVIEW step."""
        context_ids = tuple(str(value) for value in context_snapshot_ids)
        summary = self._review_service.load_summary(context_snapshot_ids=context_ids)
        review_ids = tuple(str(value) for value in getattr(summary, "review_ids", ()) or ())
        contexts = self._load_contexts(
            context_ids,
            scope_version_id=scope_version_id,
            decision_at=decision_at,
        )
        context_ids = tuple(context.context_snapshot_id for context in contexts)
        output = EarningsCatalystWorkerResult(
            artifact_id=_artifact_id(orchestration_run_id, self.name),
            orchestration_run_id=orchestration_run_id,
            status="completed",
            trigger_reasons=("legacy_ai_delta_review_recovered",),
            context_snapshot_ids=context_ids,
            review_ids=review_ids,
            candidates=tuple(
                self._candidate_from_context(
                    context,
                    review_id=(review_ids[index] if index < len(review_ids) else None),
                    decision_at=decision_at,
                )
                for index, context in enumerate(contexts)
            ),
        )
        self._save(output, scope_version_id=scope_version_id, decision_at=decision_at)
        return output

    def _load_contexts(
        self,
        context_ids: tuple[str, ...],
        *,
        scope_version_id: str,
        decision_at: datetime,
    ) -> tuple[CatalystResearchContext, ...]:
        if self._context_loader is None:
            return tuple(
                CatalystResearchContext(
                    context_snapshot_id=context_id,
                    security_id=context_id,
                )
                for context_id in context_ids
            )
        reporting_loader = getattr(self._context_loader, "load_reporting_contexts", None)
        if callable(reporting_loader):
            return tuple(
                reporting_loader(
                    scope_version_id=scope_version_id,
                    decision_at=decision_at,
                    seed_context_snapshot_ids=context_ids,
                )
            )
        return tuple(self._context_loader(context_ids))

    def _candidate_from_context(
        self,
        context: CatalystResearchContext,
        *,
        review_id: str | None,
        decision_at: datetime,
    ) -> CatalystCandidate:
        review = self._review_loader(review_id) if self._review_loader and review_id else None
        conclusion = str(getattr(review, "conclusion", "") or "")
        confidence = _bounded_float(getattr(review, "confidence", 0.0), default=0.0)
        direction = _review_direction(review)
        evidence = [
            RecommendationEvidenceRef(source_type="rag", source_id=evidence_id)
            for evidence_id in tuple(getattr(review, "evidence_ids", ()) or context.evidence_ids)
        ]
        contradiction_status: Literal[
            "not_checked", "no_counter_evidence", "counter_evidence_found"
        ] = "not_checked"
        reasons: list[str] = []
        if context.new_filing_document_ids:
            reasons.append("new_filing_reviewed_from_rag")
        if context.previous_conclusion and self._websearch is not None:
            query = _counter_evidence_query(context.security_id, context.previous_conclusion)
            raw_results = self._websearch.search(query, max_results=5)
            counter_evidence = tuple(_websearch_evidence(item) for item in raw_results)
            evidence.extend(counter_evidence)
            if any(_looks_like_counter_evidence(item) for item in raw_results):
                contradiction_status = "counter_evidence_found"
                direction = "negative"
                reasons.append("websearch_counter_evidence_requires_thesis_recheck")
            else:
                contradiction_status = "no_counter_evidence"
                reasons.append("websearch_did_not_find_obvious_counter_evidence")
        if review_id:
            reasons.append("rag_delta_review_completed")
        return CatalystCandidate(
            security_id=context.security_id,
            context_snapshot_id=context.context_snapshot_id,
            review_id=review_id,
            direction=direction,
            confidence=confidence,
            conclusion=conclusion,
            previous_conclusion=context.previous_conclusion,
            contradiction_status=contradiction_status,
            reasons=tuple(reasons),
            evidence=tuple(evidence),
        )

    def _save(
        self,
        output: EarningsCatalystWorkerResult,
        *,
        scope_version_id: str,
        decision_at: datetime,
    ) -> None:
        self._repository.save(
            artifact_id=output.artifact_id,
            orchestration_run_id=output.orchestration_run_id,
            worker_name=self.name,
            artifact_type="earnings_catalyst_result",
            scope_version_id=scope_version_id,
            decision_at=decision_at,
            payload=output.model_dump(mode="json"),
        )


class RecommendationFusionWorker:
    """Fuse quant and catalyst outputs, apply risk gates, and retain cash."""

    name = "RecommendationFusionWorker"

    def __init__(
        self,
        *,
        repository: RecommendationArtifactRepository,
        policy: RecommendationFusionPolicy | None = None,
    ) -> None:
        self._repository = repository
        self._policy = policy or RecommendationFusionPolicy()

    def run(
        self,
        *,
        orchestration_run_id: str,
        scope_version_id: str,
        decision_at: datetime,
        quant_result: MLQuantWorkerResult,
        catalyst_result: EarningsCatalystWorkerResult,
    ) -> RecommendationFusionResult:
        catalyst_by_security = {item.security_id: item for item in catalyst_result.candidates}
        quant_security_ids = {item.security_id for item in quant_result.candidates}
        staged: list[dict[str, Any]] = []
        excluded: list[str] = []
        for quant in quant_result.candidates:
            catalyst = catalyst_by_security.get(quant.security_id)
            gate_reasons = _fusion_gate_reasons(quant, catalyst)
            if gate_reasons:
                excluded.append(quant.security_id)
                continue
            catalyst_contribution = _catalyst_contribution(catalyst)
            multiplier = max(0.0, 1.0 + catalyst_contribution)
            staged.append(
                _quant_fusion_stage(
                    quant,
                    catalyst,
                    raw_weight=quant.target_weight * multiplier,
                    catalyst_contribution=catalyst_contribution,
                )
            )
        for catalyst in catalyst_result.candidates:
            if catalyst.security_id in quant_security_ids:
                continue
            gate_reasons = _catalyst_only_gate_reasons(catalyst, self._policy)
            if gate_reasons:
                excluded.append(catalyst.security_id)
                continue
            staged.append(_catalyst_only_fusion_stage(catalyst, self._policy))

        max_stock_exposure = min(
            quant_result.max_stock_exposure,
            max(0.0, 1.0 - quant_result.min_cash),
        )
        catalyst_only = [item for item in staged if item["catalyst_only"]]
        quant_staged = [item for item in staged if not item["catalyst_only"]]
        catalyst_raw_total = sum(float(item["raw_weight"]) for item in catalyst_only)
        catalyst_scale = (
            min(1.0, max_stock_exposure / catalyst_raw_total) if catalyst_raw_total > 0.0 else 0.0
        )
        catalyst_weight = catalyst_raw_total * catalyst_scale
        quant_budget = max(0.0, max_stock_exposure - catalyst_weight)
        quant_raw_total = sum(float(item["raw_weight"]) for item in quant_staged)
        quant_scale = (
            quant_budget / quant_raw_total
            if quant_raw_total > 0.0 and self._policy.fill_remaining_quant_budget
            else min(1.0, quant_budget / quant_raw_total)
            if quant_raw_total > 0.0
            else 0.0
        )
        recommendations = tuple(
            _fused_recommendation(
                item,
                scale=(catalyst_scale if item["catalyst_only"] else quant_scale),
            )
            for item in staged
            if float(item["raw_weight"]) > 0.0
        )
        stock_weight = round(sum(item.adjusted_weight for item in recommendations), 10)
        cash_weight = round(max(0.0, 1.0 - stock_weight), 10)
        artifact_id = _artifact_id(orchestration_run_id, self.name)
        output = RecommendationFusionResult(
            artifact_id=artifact_id,
            orchestration_run_id=orchestration_run_id,
            quant_run_id=quant_result.quant_run_id,
            max_stock_exposure=max_stock_exposure,
            policy=self._policy,
            stock_weight=stock_weight,
            cash_weight=cash_weight,
            recommendations=recommendations,
            excluded_security_ids=tuple(sorted(set(excluded))),
        )
        self._repository.save(
            artifact_id=output.artifact_id,
            orchestration_run_id=orchestration_run_id,
            worker_name=self.name,
            artifact_type="recommendation_fusion_result",
            scope_version_id=scope_version_id,
            decision_at=decision_at,
            payload=output.model_dump(mode="json"),
        )
        return output

    def load(self, artifact_id: str) -> RecommendationFusionResult:
        payload = self._repository.load(artifact_id)
        if payload is None:
            raise KeyError(f"recommendation fusion artifact not found: {artifact_id}")
        return RecommendationFusionResult.model_validate(payload)


def is_china_reporting_window(value: date) -> bool:
    """Return whether a date falls in a mainland periodic-report window."""
    month = value.month
    return month in {1, 2, 3, 4, 7, 8, 10}


def _profile_metadata(profile: Mapping[str, Any] | Any) -> tuple[dict[str, Any], dict[str, Any]]:
    if isinstance(profile, Mapping):
        raw = dict(profile)
        strategy = raw.get("quant_strategy")
        if isinstance(strategy, dict):
            return raw, dict(strategy)
        return raw, raw
    profile_metadata = (
        dict(profile.to_metadata()) if callable(getattr(profile, "to_metadata", None)) else {}
    )
    strategy_metadata = (
        dict(profile.to_quant_strategy_metadata())
        if callable(getattr(profile, "to_quant_strategy_metadata", None))
        else dict(profile_metadata)
    )
    return profile_metadata, strategy_metadata


def _supported_kwargs(callable_: Callable[..., Any], kwargs: dict[str, Any]) -> dict[str, Any]:
    """Keep compatibility with narrow fakes while production consumes the profile."""
    signature = inspect.signature(callable_)
    if any(
        parameter.kind is inspect.Parameter.VAR_KEYWORD
        for parameter in signature.parameters.values()
    ):
        return kwargs
    return {key: value for key, value in kwargs.items() if key in signature.parameters}


def _quant_candidate(result: Any) -> QuantRecommendationCandidate | None:
    status = getattr(result, "screening_status", "")
    status_value = str(getattr(status, "value", status))
    data_status = getattr(result, "data_status", "")
    guardrail = getattr(result, "research_guardrail", "")
    if status_value not in {
        ScreeningStatus.PASS.value,
        ScreeningStatus.NEAR_THRESHOLD.value,
        ScreeningStatus.WATCHLIST.value,
    }:
        return None
    if str(getattr(data_status, "value", data_status)) != DataStatus.OK.value:
        return None
    if str(getattr(guardrail, "value", guardrail)) == ResearchGuardrail.RESEARCH_BLOCKED.value:
        return None
    details = getattr(result, "factor_details", {})
    details = details if isinstance(details, dict) else {}
    strategy = details.get("ml_strategy")
    strategy = strategy if isinstance(strategy, dict) else {}
    target_weight = max(0.0, _float(strategy.get("target_weight"), default=0.0))
    result_id = str(getattr(result, "result_id", "") or "")
    evidence = (
        RecommendationEvidenceRef(
            source_type="warehouse_quant_result",
            source_id=result_id,
            locator={"quant_run_id": str(getattr(result, "quant_run_id", ""))},
        ),
    )
    reasons = tuple(
        dict.fromkeys(
            (
                str(getattr(result, "reason_summary", "") or status_value),
                *tuple(str(value) for value in getattr(result, "review_reasons", ()) or ()),
            )
        )
    )
    return QuantRecommendationCandidate(
        security_id=str(getattr(result, "security_id", "")),
        quant_result_id=result_id,
        score=_float(getattr(result, "final_score", 0.0), default=0.0),
        screening_status=status_value,
        target_weight=target_weight,
        risk_flags=tuple(str(value) for value in getattr(result, "risk_flags", ()) or ()),
        review_required=bool(getattr(result, "review_required", False)),
        reasons=reasons,
        evidence=evidence,
    )


def _review_direction(
    review: Any | None,
) -> Literal["positive", "neutral", "negative", "uncertain"]:
    if review is None:
        return "uncertain"
    outcome = str(getattr(getattr(review, "outcome", ""), "value", getattr(review, "outcome", "")))
    if outcome in {"invalidate", "downgrade_confidence", "abstain", "review_deferred"}:
        return "negative"
    view = str(getattr(review, "valuation_view", "") or "").lower()
    if any(
        marker in view
        for marker in (
            "positive",
            "bullish",
            "attractive",
            "undervalued",
            "看多",
            "低估",
        )
    ):
        return "positive"
    if any(marker in view for marker in ("negative", "bearish", "overvalued", "看空", "高估")):
        return "negative"
    if outcome == "carry_forward_verified":
        return "neutral"
    return "uncertain"


def _counter_evidence_query(security_id: str, previous_conclusion: str) -> str:
    bounded = " ".join(previous_conclusion.split())[:160]
    return f"{security_id} {bounded} 反面证据 需求下降 业绩不及预期 行业风险"


def _websearch_evidence(item: Any) -> RecommendationEvidenceRef:
    payload = dict(item) if isinstance(item, Mapping) else {}
    url = str(payload.get("url") or "")
    source_id = url or _stable_hash(payload)[:24]
    return RecommendationEvidenceRef(
        source_type="websearch",
        source_id=source_id,
        title=str(payload.get("title") or ""),
        url=url or None,
        excerpt=str(payload.get("snippet") or payload.get("content") or "")[:500],
    )


def _looks_like_counter_evidence(item: Any) -> bool:
    payload = dict(item) if isinstance(item, Mapping) else {}
    text = " ".join(str(payload.get(key) or "") for key in ("title", "snippet", "content")).lower()
    return any(
        marker in text
        for marker in (
            "不及预期",
            "下滑",
            "下降",
            "过剩",
            "供过于求",
            "取消订单",
            "需求疲软",
            "预警",
            "downgrade",
            "missed expectations",
            "demand decline",
            "oversupply",
        )
    )


def _fusion_gate_reasons(
    quant: QuantRecommendationCandidate,
    catalyst: CatalystCandidate | None,
) -> tuple[str, ...]:
    reasons: list[str] = []
    if quant.target_weight <= 0.0:
        reasons.append("zero_quant_target_weight")
    if "short_term_overheat" in quant.risk_flags:
        reasons.append("short_term_overheat")
    if quant.review_required and catalyst is None:
        reasons.append("required_catalyst_review_missing")
    if catalyst is not None and catalyst.direction == "negative":
        reasons.append("negative_catalyst_review")
    if catalyst is not None and catalyst.contradiction_status == "counter_evidence_found":
        reasons.append("counter_evidence_found")
    return tuple(reasons)


def _catalyst_contribution(catalyst: CatalystCandidate | None) -> float:
    if catalyst is None or catalyst.direction in {"neutral", "uncertain"}:
        return 0.0
    if catalyst.direction == "negative":
        return -1.0
    return min(0.25, 0.25 * catalyst.confidence)


def _catalyst_only_gate_reasons(
    catalyst: CatalystCandidate,
    policy: RecommendationFusionPolicy,
) -> tuple[str, ...]:
    reasons: list[str] = []
    if catalyst.direction != "positive":
        reasons.append("catalyst_only_direction_not_positive")
    if catalyst.confidence < policy.catalyst_only_min_confidence:
        reasons.append("catalyst_only_confidence_below_policy")
    if catalyst.contradiction_status == "counter_evidence_found":
        reasons.append("counter_evidence_found")
    if policy.require_catalyst_evidence and not catalyst.evidence:
        reasons.append("catalyst_only_evidence_missing")
    return tuple(reasons)


def _quant_fusion_stage(
    quant: QuantRecommendationCandidate,
    catalyst: CatalystCandidate | None,
    *,
    raw_weight: float,
    catalyst_contribution: float,
) -> dict[str, Any]:
    sources = ["ml_quant"]
    reasons = list(quant.reasons)
    evidence = list(quant.evidence)
    if catalyst is not None:
        sources.append("earnings_catalyst")
        reasons.extend(catalyst.reasons)
        if catalyst.conclusion:
            reasons.append(catalyst.conclusion)
        evidence.extend(catalyst.evidence)
    return {
        "security_id": quant.security_id,
        "target_weight": quant.target_weight,
        "quant_score": quant.score,
        # Preserve the existing confidence policy, but make it an explicit
        # fusion output instead of allowing Dashboard to reconstruct it.
        "fusion_confidence": max(0.0, min(1.0, 0.70 + catalyst_contribution)),
        "quant_contribution": quant.target_weight,
        "catalyst_contribution": catalyst_contribution,
        "sources": tuple(sources),
        "reasons": tuple(reasons),
        "risk_flags": quant.risk_flags,
        "evidence": tuple(evidence),
        "raw_weight": raw_weight,
        "catalyst_only": False,
    }


def _catalyst_only_fusion_stage(
    catalyst: CatalystCandidate,
    policy: RecommendationFusionPolicy,
) -> dict[str, Any]:
    target_weight = policy.catalyst_only_max_weight
    reasons = ["catalyst_only_conservative_weight", *catalyst.reasons]
    if catalyst.conclusion:
        reasons.append(catalyst.conclusion)
    return {
        "security_id": catalyst.security_id,
        "target_weight": target_weight,
        "quant_score": None,
        "fusion_confidence": catalyst.confidence,
        "quant_contribution": 0.0,
        "catalyst_contribution": catalyst.confidence,
        "sources": ("earnings_catalyst",),
        "reasons": tuple(reasons),
        "risk_flags": (),
        "evidence": catalyst.evidence,
        "raw_weight": target_weight,
        "catalyst_only": True,
    }


def _fused_recommendation(item: dict[str, Any], *, scale: float) -> FusedRecommendation:
    adjusted = round(float(item["raw_weight"]) * scale, 10)
    return FusedRecommendation(
        security_id=str(item["security_id"]),
        target_weight=float(item["target_weight"]),
        adjusted_weight=adjusted,
        quant_score=(float(item["quant_score"]) if item.get("quant_score") is not None else None),
        fusion_confidence=float(item["fusion_confidence"]),
        quant_contribution=float(item["quant_contribution"]),
        catalyst_contribution=float(item["catalyst_contribution"]),
        sources=tuple(item["sources"]),
        reasons=tuple(dict.fromkeys(reason for reason in item["reasons"] if reason)),
        risk_flags=tuple(item["risk_flags"]),
        evidence=tuple(_deduplicate_evidence(item["evidence"])),
    )


def _deduplicate_evidence(
    evidence: Sequence[RecommendationEvidenceRef],
) -> list[RecommendationEvidenceRef]:
    values: list[RecommendationEvidenceRef] = []
    seen: set[tuple[str, str]] = set()
    for item in evidence:
        key = (item.source_type, item.source_id)
        if key in seen:
            continue
        seen.add(key)
        values.append(item)
    return values


def _artifact_id(orchestration_run_id: str, worker_name: str) -> str:
    material = f"{orchestration_run_id}|{worker_name}"
    return "rec_" + hashlib.sha256(material.encode("utf-8")).hexdigest()[:24]


def _stable_hash(value: Any) -> str:
    rendered = json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha256(rendered.encode("utf-8")).hexdigest()


def _float(value: Any, *, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _bounded_float(value: Any, *, default: float) -> float:
    return max(0.0, min(_float(value, default=default), 1.0))


__all__ = [
    "CatalystCandidate",
    "CatalystResearchContext",
    "EarningsCatalystWorker",
    "EarningsCatalystWorkerResult",
    "FusedRecommendation",
    "MLQuantWorker",
    "MLQuantWorkerResult",
    "MemoryRecommendationArtifactRepository",
    "QuantRecommendationCandidate",
    "RecommendationArtifactRepository",
    "RecommendationEvidenceRef",
    "RecommendationFusionPolicy",
    "RecommendationFusionResult",
    "RecommendationFusionWorker",
    "is_china_reporting_window",
]
