"""Quant screening service.

The service is provider-free. It consumes a frozen ``QuantInputSnapshot`` and a
PIT-safe cross-section supplied by a repository/adapter, then writes append-only
quant runs and results.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict
from datetime import datetime
from typing import Any

import pandas as pd

from margin.valuation_discovery.models import (
    DataStatus,
    QuantInputSnapshot,
    QuantResult,
    QuantRun,
    ResearchGuardrail,
    ScreeningStatus,
)
from margin.valuation_discovery.quant.config import QuantConfig
from margin.valuation_discovery.quant.factors.growth import GrowthFactorCalculator
from margin.valuation_discovery.quant.factors.momentum import MomentumFactorCalculator
from margin.valuation_discovery.quant.factors.quality import QualityFactorCalculator
from margin.valuation_discovery.quant.factors.risk import RiskFactorCalculator
from margin.valuation_discovery.quant.filters import HardFilterEngine
from margin.valuation_discovery.quant.manual_all_a import (
    ManualAllAConfig,
    build_ai_quant_profile,
    score_manual_all_a,
)
from margin.valuation_discovery.quant.models import SecurityFilterResult
from margin.valuation_discovery.quant.repository import QuantRepository
from margin.valuation_discovery.quant.scoring import (
    CombinedFactorScore,
    FactorGroupScores,
    FactorScorer,
)


class QuantService:
    """Run a single-day multi-factor quant screen."""

    def __init__(
        self,
        repository: QuantRepository,
        *,
        config: QuantConfig | None = None,
        strategy_version_id: str = "quant-v0.2",
    ) -> None:
        """Initialize the quant service with repository and configuration.

        Args:
            repository: Persistence boundary for quant runs and results.
            config: Optional hard-filter and scoring thresholds.
            strategy_version_id: Default strategy version identifier.
        """
        self._repository = repository
        self._config = config or QuantConfig()
        self._strategy_version_id = strategy_version_id
        self._filter_engine = HardFilterEngine(self._config)
        self._quality_calculator = QualityFactorCalculator()
        self._growth_calculator = GrowthFactorCalculator()
        self._momentum_calculator = MomentumFactorCalculator()
        self._risk_calculator = RiskFactorCalculator()
        self._scorer = FactorScorer()
        self._manual_config = ManualAllAConfig(
            score_threshold=52.0,
            min_avg_amount_20d=self._config.min_avg_amount_20d,
        )

    def run(self, snapshot: QuantInputSnapshot, *, decision_at: datetime) -> QuantRun:
        """Run quant screening for a frozen input snapshot and persist results.

        Args:
            snapshot: Frozen PIT-safe quant input snapshot.
            decision_at: Timezone-aware decision timestamp.

        Returns:
            The persisted ``QuantRun`` with completed status.

        Raises:
            ValueError: If the snapshot is not valid for publishable results.
        """
        if not snapshot.is_valid:
            raise ValueError("invalid quant input snapshot")

        cross_section = self._prepare_cross_section(
            self._repository.load_cross_section(snapshot),
            snapshot=snapshot,
            decision_at=decision_at,
        )
        filter_result = self._filter_engine.apply(cross_section)
        strategy_metadata = _strategy_metadata(snapshot)
        manual_config = _manual_config_from_strategy_metadata(
            strategy_metadata,
            fallback=self._manual_config,
        )
        manual_final_enabled = _manual_final_score_enabled(strategy_metadata)
        scored_by_security = self._score_allowed(
            cross_section,
            filter_result,
            manual_config=manual_config,
            manual_final_enabled=manual_final_enabled,
        )
        quant_run = QuantRun(
            input_snapshot_id=snapshot.snapshot_id,
            scope_version_id=snapshot.scope_version_id,
            strategy_version_id=str(
                strategy_metadata.get("quant_strategy_version_id")
                or self._strategy_version_id
            ),
            decision_at=decision_at,
            config_hash=self._config_hash(),
            status="completed",
        )
        results = tuple(
            self._build_result(
                quant_run=quant_run,
                security_id=security_id,
                filter_result=filter_result.by_security[security_id],
                scored_row=scored_by_security.get(security_id),
            )
            for security_id in _ordered_security_ids(snapshot, cross_section)
        )
        results = _assign_ranks(results, cross_section)
        self._repository.add_run(quant_run)
        self._repository.add_results(quant_run.quant_run_id, results)
        return quant_run

    def _prepare_cross_section(
        self,
        frame: pd.DataFrame,
        *,
        snapshot: QuantInputSnapshot,
        decision_at: datetime,
    ) -> pd.DataFrame:
        """Prepare a cross-section DataFrame with security_id index and missing rows."""
        prepared = frame.copy(deep=True)
        if prepared.empty:
            prepared = pd.DataFrame({"security_id": list(snapshot.security_ids)})
        if "security_id" not in prepared.columns:
            prepared["security_id"] = prepared.index.astype(str)
        prepared["security_id"] = prepared["security_id"].astype(str)
        if "decision_at" not in prepared.columns:
            prepared["decision_at"] = decision_at
        missing = [
            security_id
            for security_id in snapshot.security_ids
            if security_id not in set(prepared["security_id"])
        ]
        if missing:
            prepared = pd.concat(
                [
                    prepared,
                    pd.DataFrame(
                        {
                            "security_id": missing,
                            "decision_at": [decision_at] * len(missing),
                            "__missing_cross_section": [True] * len(missing),
                        }
                    ),
                ],
                ignore_index=True,
            )
        if "__missing_cross_section" not in prepared.columns:
            prepared["__missing_cross_section"] = False
        return prepared.set_index("security_id", drop=False)

    def _score_allowed(
        self,
        cross_section: pd.DataFrame,
        filter_result: Any,
        *,
        manual_config: ManualAllAConfig,
        manual_final_enabled: bool,
    ) -> dict[str, pd.Series]:
        """Score all filter-allowed securities and return scored rows by ID."""
        allowed_ids = [
            security_id
            for security_id, result in filter_result.by_security.items()
            if result.allowed_for_scoring
        ]
        if not allowed_ids:
            return {}
        allowed = cross_section.loc[allowed_ids].copy()
        scored = self._quality_calculator.calculate(allowed)
        scored = self._scorer.score_value(scored)
        scored = self._growth_calculator.calculate(scored)
        scored = self._momentum_calculator.calculate(scored)
        scored = self._risk_calculator.calculate(scored)
        scored = score_manual_all_a(scored, config=manual_config)
        scored["__use_manual_all_a_final_score"] = manual_final_enabled
        return {
            str(row["security_id"]): row
            for _, row in scored.iterrows()
        }

    def _build_result(
        self,
        *,
        quant_run: QuantRun,
        security_id: str,
        filter_result: SecurityFilterResult,
        scored_row: pd.Series | None,
    ) -> QuantResult:
        """Build a ``QuantResult`` from filter and scored row data."""
        if not filter_result.allowed_for_scoring or scored_row is None:
            return self._blocked_result(
                quant_run=quant_run,
                security_id=security_id,
                filter_result=filter_result,
            )

        risk_flags = _reason_codes(filter_result, severity="risk")
        review_reasons = _reason_codes(filter_result, severity="review")
        group_scores = FactorGroupScores(
            security_id=security_id,
            quality_score=_float(scored_row.get("quality_score")),
            value_score=_float(scored_row.get("value_score")),
            growth_score=_float(scored_row.get("growth_score")),
            momentum_score=_float(scored_row.get("momentum_score")),
            risk_score=_float(scored_row.get("risk_score")),
        )
        combined = self._scorer.combine(group_scores)
        combined = _combined_with_manual_final_score(combined, scored_row)
        decision = self._scorer.determine_status(
            combined,
            data_status=filter_result.data_status,
            risk_flags=risk_flags,
            short_term_overheat=_is_short_term_overheated(scored_row),
        )
        merged_review_reasons = _dedupe(decision.review_reasons + review_reasons)
        ai_quant_profile = build_ai_quant_profile(scored_row)
        manual_scores = ai_quant_profile["scores"]
        return QuantResult(
            quant_run_id=quant_run.quant_run_id,
            security_id=security_id,
            final_score=combined.final_score,
            quality_score=combined.quality_score,
            value_score=combined.value_score,
            growth_score=combined.growth_score,
            momentum_score=combined.momentum_score,
            risk_score=combined.risk_score,
            screening_status=decision.screening_status,
            data_status=filter_result.data_status,
            risk_flags=risk_flags,
            review_required=decision.review_required or bool(review_reasons),
            review_reasons=merged_review_reasons,
            research_guardrail=decision.research_guardrail,
            reason_summary=_score_reason_summary(combined, decision.screening_status),
            factor_details={
                "name": scored_row.get("name"),
                "symbol": scored_row.get("security_id"),
                "industry_id": scored_row.get("industry_id"),
                "filter_reasons": [asdict(reason) for reason in filter_result.reasons],
                "scores": {
                    "quality": combined.quality_score,
                    "value": combined.value_score,
                    "growth": combined.growth_score,
                    "momentum": combined.momentum_score,
                    "risk": combined.risk_score,
                    "final": combined.final_score,
                    "manual_all_a": manual_scores.get("manual_all_a_score"),
                    "theme_hotness": manual_scores.get("theme_hotness"),
                },
                "ai_quant_profile": ai_quant_profile,
            },
        )

    def _blocked_result(
        self,
        *,
        quant_run: QuantRun,
        security_id: str,
        filter_result: SecurityFilterResult,
    ) -> QuantResult:
        """Build a rejected ``QuantResult`` for blocked or missing securities."""
        blocker_codes = _reason_codes(filter_result, severity="blocker")
        review_reasons = _dedupe(
            blocker_codes
            + _reason_codes(filter_result, severity="review")
            + _reason_codes(filter_result, severity="risk")
        )
        data_status = (
            DataStatus.INSUFFICIENT
            if filter_result.data_status == DataStatus.INSUFFICIENT
            or any(code == "missing_cross_section" for code in blocker_codes)
            else filter_result.data_status
        )
        return QuantResult(
            quant_run_id=quant_run.quant_run_id,
            security_id=security_id,
            final_score=0.0,
            screening_status=ScreeningStatus.REJECT,
            data_status=data_status,
            risk_flags=_reason_codes(filter_result, severity="risk"),
            review_required=bool(review_reasons) or data_status != DataStatus.OK,
            review_reasons=review_reasons,
            research_guardrail=ResearchGuardrail.RESEARCH_BLOCKED,
            reason_summary=_blocked_reason_summary(filter_result),
            factor_details={
                "filter_reasons": [asdict(reason) for reason in filter_result.reasons],
            },
        )

    def _config_hash(self) -> str:
        """Return a deterministic SHA-256 hash of the quant configuration."""
        rendered = json.dumps(
            self._config.model_dump(mode="json"),
            ensure_ascii=False,
            sort_keys=True,
        )
        return "sha256:" + hashlib.sha256(rendered.encode("utf-8")).hexdigest()


def _ordered_security_ids(
    snapshot: QuantInputSnapshot,
    cross_section: pd.DataFrame,
) -> tuple[str, ...]:
    """Return snapshot security IDs followed by any cross-section extras."""
    snapshot_ids = tuple(str(security_id) for security_id in snapshot.security_ids)
    extras = tuple(
        security_id
        for security_id in cross_section["security_id"].astype(str).tolist()
        if security_id not in set(snapshot_ids)
    )
    return snapshot_ids + extras


def _strategy_metadata(snapshot: QuantInputSnapshot) -> dict[str, Any]:
    """Return quant strategy metadata embedded in the feature-set binding."""
    feature_set = snapshot.quant_feature_set
    metadata = getattr(feature_set, "metadata", None)
    if isinstance(metadata, dict):
        strategy = metadata.get("quant_strategy")
        if isinstance(strategy, dict):
            return strategy
    return {}


def _manual_config_from_strategy_metadata(
    metadata: dict[str, Any],
    *,
    fallback: ManualAllAConfig,
) -> ManualAllAConfig:
    """Build manual strategy config from a versioned strategy payload."""
    thresholds = metadata.get("thresholds")
    factor_weights = metadata.get("factor_weights")
    if not isinstance(thresholds, dict):
        thresholds = {}
    if not isinstance(factor_weights, dict):
        factor_weights = {}

    default_universe = str(thresholds.get("default_universe") or "ALL_A")
    presets = thresholds.get("presets")
    preset = (
        presets.get(default_universe)
        if isinstance(presets, dict)
        and isinstance(presets.get(default_universe), dict)
        else {}
    )
    weights = preset.get("factor_weights") if isinstance(preset, dict) else None
    if not isinstance(weights, dict) or not weights:
        weights = factor_weights or fallback.weights
    threshold = _number_or_fallback(
        preset.get("buy_threshold") if isinstance(preset, dict) else None,
        fallback.score_threshold,
    )
    min_amount = _number_or_fallback(
        preset.get("min_avg_amount_20d") if isinstance(preset, dict) else None,
        fallback.min_avg_amount_20d,
    )
    return ManualAllAConfig(
        score_threshold=threshold,
        min_avg_amount_20d=min_amount,
        weights={str(key): float(value) for key, value in weights.items()},
    )


def _manual_final_score_enabled(metadata: dict[str, Any]) -> bool:
    """Return whether versioned strategy metadata should own final score."""
    thresholds = metadata.get("thresholds")
    if not isinstance(thresholds, dict):
        return False
    presets = thresholds.get("presets")
    default_universe = str(thresholds.get("default_universe") or "ALL_A")
    preset = (
        presets.get(default_universe)
        if isinstance(presets, dict)
        and isinstance(presets.get(default_universe), dict)
        else None
    )
    if not isinstance(preset, dict):
        return False
    weights = preset.get("factor_weights")
    return isinstance(weights, dict) and bool(weights)


def _combined_with_manual_final_score(
    combined: CombinedFactorScore,
    scored_row: pd.Series,
) -> CombinedFactorScore:
    """Use manual strategy score as final score when strategy metadata asks for it."""
    if not _bool_value(scored_row.get("__use_manual_all_a_final_score")):
        return combined
    manual_score = _optional_score(scored_row.get("manual_all_a_score"))
    if manual_score is None:
        return combined
    return CombinedFactorScore(
        security_id=combined.security_id,
        quality_score=combined.quality_score,
        value_score=combined.value_score,
        growth_score=combined.growth_score,
        momentum_score=combined.momentum_score,
        risk_score=combined.risk_score,
        final_score=manual_score,
    )


def _optional_score(value: Any) -> float | None:
    """Convert a value to a clamped 0-100 float, returning None for NaN."""
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return None
    if pd.isna(numeric):
        return None
    return min(100.0, max(0.0, numeric))


def _number_or_fallback(value: Any, fallback: float) -> float:
    """Convert a value to float, returning the fallback for NaN or non-numeric."""
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return fallback
    if pd.isna(numeric):
        return fallback
    return numeric


def _reason_codes(
    filter_result: SecurityFilterResult,
    *,
    severity: str,
) -> tuple[str, ...]:
    """Return reason codes of a specific severity from a filter result."""
    return tuple(
        reason.code for reason in filter_result.reasons if reason.severity == severity
    )


def _dedupe(values: tuple[str, ...]) -> tuple[str, ...]:
    """Remove duplicate strings while preserving order."""
    return tuple(dict.fromkeys(values))


def _float(value: Any) -> float:
    """Convert a value to float, returning 0.0 for None or NaN."""
    if value is None or bool(pd.isna(value)):
        return 0.0
    return float(value)


def _bool_value(value: Any) -> bool:
    """Convert a value to bool, returning False for None or NaN."""
    if value is None or bool(pd.isna(value)):
        return False
    return bool(value)


def _is_short_term_overheated(row: pd.Series) -> bool:
    """Return whether a scored row indicates short-term price overheat."""
    if bool(row.get("short_term_overheat", False)):
        return True
    value = row.get("return_20d")
    if value is None or bool(pd.isna(value)):
        return False
    return float(value) > 0.35


def _score_reason_summary(
    scores: Any,
    status: ScreeningStatus,
) -> str:
    """Build a human-readable score and status summary string."""
    return (
        f"Quant screen {status.value}: final_score={scores.final_score:.2f}, "
        f"quality={scores.quality_score:.2f}, value={scores.value_score:.2f}, "
        f"growth={scores.growth_score:.2f}, momentum={scores.momentum_score:.2f}, "
        f"risk={scores.risk_score:.2f}."
    )


def _blocked_reason_summary(filter_result: SecurityFilterResult) -> str:
    """Build a human-readable rejection summary from filter reasons."""
    if not filter_result.reasons:
        return "Rejected before scoring because required cross-section data is unavailable."
    codes = ", ".join(reason.code for reason in filter_result.reasons)
    return f"Rejected before scoring: {codes}."


def _assign_ranks(
    results: tuple[QuantResult, ...],
    cross_section: pd.DataFrame,
) -> tuple[QuantResult, ...]:
    """Assign overall and industry ranks to quant results."""
    overall = {
        result.security_id: rank
        for rank, result in enumerate(
            sorted(results, key=lambda item: (-item.final_score, item.security_id)),
            start=1,
        )
    }
    industry_by_security = _industry_by_security(cross_section)
    industry_ranks: dict[str, int] = {}
    for industry_id in sorted(set(industry_by_security.values())):
        industry_results = [
            result
            for result in results
            if industry_by_security.get(result.security_id, "") == industry_id
        ]
        for rank, result in enumerate(
            sorted(industry_results, key=lambda item: (-item.final_score, item.security_id)),
            start=1,
        ):
            industry_ranks[result.security_id] = rank
    ranked: list[QuantResult] = []
    for result in results:
        rank_overall = overall.get(result.security_id)
        rank_in_industry = industry_ranks.get(result.security_id)
        factor_details = {
            **result.factor_details,
            "rank_overall": rank_overall,
            "rank_in_industry": rank_in_industry,
        }
        ranked.append(
            result.model_copy(
                update={
                    "rank_overall": rank_overall,
                    "rank_in_industry": rank_in_industry,
                    "factor_details": factor_details,
                }
            )
        )
    return tuple(ranked)


def _industry_by_security(cross_section: pd.DataFrame) -> dict[str, str]:
    """Build a security_id to industry_id mapping from a cross-section."""
    mapping: dict[str, str] = {}
    for _, row in cross_section.iterrows():
        security_id = str(row.get("security_id", ""))
        industry_id = row.get("industry_id")
        mapping[security_id] = (
            "" if industry_id is None or bool(pd.isna(industry_id)) else str(industry_id)
        )
    return mapping
