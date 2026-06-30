"""Fourth-layer Analysis Mart for quant and research-facing data products."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import UTC, date, datetime
from typing import Any, Protocol

from sqlalchemy.orm import Session

from margin.sql.valuation_queries import (
    analysis_evidence_links_by_snapshot,
    analysis_findings_by_snapshot,
    analysis_metrics_by_snapshot,
    latest_analysis_snapshot,
    latest_quant_feature_snapshot,
    quant_feature_rows_by_snapshot,
)
from margin.valuation_discovery.db_models import (
    AnalysisEvidenceLinkRow,
    AnalysisFindingRow,
    AnalysisMetricRow,
    AnalysisSnapshotRow,
    QuantFeatureRowRow,
    QuantFeatureSnapshotRow,
)
from margin.valuation_discovery.models import QuantResult

SessionFactory = Callable[[], Session]


@dataclass(frozen=True)
class QuantFeatureSnapshot:
    """Fourth-layer quant input feature snapshot materialized from layer 3."""

    feature_snapshot_id: str
    scope_version_id: str
    universe_snapshot_id: str
    decision_at: datetime
    known_at: datetime
    trading_date: date
    feature_set_version_id: str | None
    feature_schema_version: str
    source_layer: str
    input_hash: str
    row_count: int
    feature_columns: tuple[str, ...]
    lineage_summary: dict[str, Any]
    quality_flags: tuple[str, ...] = ()
    created_at: datetime | None = None


@dataclass(frozen=True)
class QuantFeatureRow:
    """One materialized feature row consumed by the quant layer."""

    row_id: str
    feature_snapshot_id: str
    security_id: str
    symbol: str | None
    name: str | None
    industry_id: str | None
    features: dict[str, Any]
    source_refs: tuple[dict[str, Any], ...] = ()
    quality_flags: tuple[str, ...] = ()
    created_at: datetime | None = None


@dataclass(frozen=True)
class AnalysisSnapshot:
    """One immutable fourth-layer snapshot for a security and decision time."""

    analysis_snapshot_id: str
    security_id: str
    scope_version_id: str
    decision_at: datetime
    trading_date: date
    analysis_version: str
    analysis_kind: str
    quant_run_id: str | None
    quant_result_id: str | None
    input_snapshot_id: str | None
    strategy_version_id: str | None
    config_hash: str | None
    input_hash: str
    result_hash: str
    summary: dict[str, Any]
    quality_flags: tuple[str, ...] = ()
    created_at: datetime | None = None

    def with_result_hash(self, result_hash: str) -> AnalysisSnapshot:
        """Return a copy with a different result hash for conflict tests."""
        return replace(self, result_hash=result_hash)


@dataclass(frozen=True)
class AnalysisMetric:
    """Structured metric exposed to dashboards and AI read tools."""

    metric_id: str
    analysis_snapshot_id: str
    metric_code: str
    metric_name: str
    metric_group: str
    numeric_value: float | None
    unit: str | None
    direction: str
    percentile_market: float | None = None
    percentile_industry: float | None = None
    rank_market: int | None = None
    rank_industry: int | None = None
    source_refs: tuple[dict[str, Any], ...] = ()
    detail: dict[str, Any] | None = None
    created_at: datetime | None = None


@dataclass(frozen=True)
class AnalysisFinding:
    """Human/AI-readable finding derived from quant and canonical inputs."""

    finding_id: str
    analysis_snapshot_id: str
    finding_type: str
    severity: str
    title: str
    description: str
    confidence: float
    evidence_ids: tuple[str, ...] = ()
    source_refs: tuple[dict[str, Any], ...] = ()
    detail: dict[str, Any] | None = None
    created_at: datetime | None = None


@dataclass(frozen=True)
class AnalysisEvidenceLink:
    """Lineage edge from an analysis snapshot to evidence or source rows."""

    link_id: str
    analysis_snapshot_id: str
    finding_id: str | None
    metric_id: str | None
    evidence_id: str | None
    source_type: str
    source_id: str
    role: str
    detail: dict[str, Any] | None = None
    created_at: datetime | None = None


@dataclass(frozen=True)
class AnalysisMartBundle:
    """Atomic write unit for one analysis snapshot and its child rows."""

    snapshot: AnalysisSnapshot
    metrics: tuple[AnalysisMetric, ...] = ()
    findings: tuple[AnalysisFinding, ...] = ()
    evidence_links: tuple[AnalysisEvidenceLink, ...] = ()


class AnalysisMartRepository(Protocol):
    """Persistence contract for fourth-layer analysis results."""

    def upsert_feature_snapshot(
        self,
        snapshot: QuantFeatureSnapshot,
        rows: tuple[QuantFeatureRow, ...],
    ) -> None:
        """Persist one QuantFeatureMart snapshot idempotently."""

    def get_feature_snapshot(
        self,
        feature_snapshot_id: str,
    ) -> QuantFeatureSnapshot | None:
        """Return one feature snapshot by ID."""

    def latest_feature_snapshot(
        self,
        *,
        scope_version_id: str,
        as_of: datetime,
    ) -> QuantFeatureSnapshot | None:
        """Return the latest feature snapshot visible at or before ``as_of``."""

    def list_feature_rows(self, feature_snapshot_id: str) -> list[QuantFeatureRow]:
        """Return materialized feature rows for one snapshot."""

    def upsert_bundle(self, bundle: AnalysisMartBundle) -> None:
        """Persist one bundle idempotently and reject conflicting replays."""

    def get_snapshot(self, analysis_snapshot_id: str) -> AnalysisSnapshot | None:
        """Return one snapshot by ID."""

    def latest_snapshot(
        self,
        *,
        security_id: str,
        scope_version_id: str | None = None,
        as_of: datetime,
    ) -> AnalysisSnapshot | None:
        """Return the latest snapshot visible at or before ``as_of``.

        When ``scope_version_id`` is None, returns the latest snapshot across
        all scopes for the given security.
        """

    def list_metrics(self, analysis_snapshot_id: str) -> list[AnalysisMetric]:
        """Return metrics for a snapshot."""

    def list_findings(self, analysis_snapshot_id: str) -> list[AnalysisFinding]:
        """Return findings for a snapshot."""

    def list_evidence_links(self, analysis_snapshot_id: str) -> list[AnalysisEvidenceLink]:
        """Return evidence and lineage links for a snapshot."""


class MemoryAnalysisMartRepository:
    """In-memory Analysis Mart repository for unit tests."""

    def __init__(self) -> None:
        """Initialize an empty in-memory Analysis Mart repository."""
        self._feature_snapshots: dict[str, QuantFeatureSnapshot] = {}
        self._feature_rows: dict[str, QuantFeatureRow] = {}
        self._snapshots: dict[str, AnalysisSnapshot] = {}
        self._metrics: dict[str, AnalysisMetric] = {}
        self._findings: dict[str, AnalysisFinding] = {}
        self._links: dict[str, AnalysisEvidenceLink] = {}

    def upsert_feature_snapshot(
        self,
        snapshot: QuantFeatureSnapshot,
        rows: tuple[QuantFeatureRow, ...],
    ) -> None:
        """Persist one feature snapshot idempotently."""
        _validate_feature_snapshot(snapshot, rows)
        _ensure_same_or_absent(
            self._feature_snapshots,
            snapshot.feature_snapshot_id,
            snapshot,
            "quant feature snapshot",
        )
        for row in rows:
            _ensure_same_or_absent(
                self._feature_rows,
                row.row_id,
                row,
                "quant feature row",
            )
        self._feature_snapshots.setdefault(snapshot.feature_snapshot_id, snapshot)
        for row in rows:
            self._feature_rows.setdefault(row.row_id, row)

    def get_feature_snapshot(
        self,
        feature_snapshot_id: str,
    ) -> QuantFeatureSnapshot | None:
        """Return one feature snapshot by ID."""
        return self._feature_snapshots.get(feature_snapshot_id)

    def latest_feature_snapshot(
        self,
        *,
        scope_version_id: str,
        as_of: datetime,
    ) -> QuantFeatureSnapshot | None:
        """Return the latest visible feature snapshot."""
        candidates = [
            snapshot
            for snapshot in self._feature_snapshots.values()
            if snapshot.scope_version_id == scope_version_id
            and snapshot.decision_at <= as_of
        ]
        return max(
            candidates,
            key=lambda item: (item.decision_at, item.created_at or item.decision_at),
            default=None,
        )

    def list_feature_rows(self, feature_snapshot_id: str) -> list[QuantFeatureRow]:
        """Return feature rows for one snapshot."""
        return sorted(
            (
                row
                for row in self._feature_rows.values()
                if row.feature_snapshot_id == feature_snapshot_id
            ),
            key=lambda item: (item.security_id, item.row_id),
        )

    def upsert_bundle(self, bundle: AnalysisMartBundle) -> None:
        """Persist one bundle idempotently."""
        _validate_bundle(bundle)
        _ensure_same_or_absent(
            self._snapshots,
            bundle.snapshot.analysis_snapshot_id,
            bundle.snapshot,
            "analysis snapshot",
        )
        for metric in bundle.metrics:
            _ensure_same_or_absent(self._metrics, metric.metric_id, metric, "analysis metric")
        for finding in bundle.findings:
            _ensure_same_or_absent(
                self._findings,
                finding.finding_id,
                finding,
                "analysis finding",
            )
        for link in bundle.evidence_links:
            _ensure_same_or_absent(self._links, link.link_id, link, "analysis evidence link")
        self._snapshots.setdefault(bundle.snapshot.analysis_snapshot_id, bundle.snapshot)
        for metric in bundle.metrics:
            self._metrics.setdefault(metric.metric_id, metric)
        for finding in bundle.findings:
            self._findings.setdefault(finding.finding_id, finding)
        for link in bundle.evidence_links:
            self._links.setdefault(link.link_id, link)

    def get_snapshot(self, analysis_snapshot_id: str) -> AnalysisSnapshot | None:
        """Return one snapshot by ID."""
        return self._snapshots.get(analysis_snapshot_id)

    def latest_snapshot(
        self,
        *,
        security_id: str,
        scope_version_id: str | None = None,
        as_of: datetime,
    ) -> AnalysisSnapshot | None:
        """Return the latest visible snapshot.

        When ``scope_version_id`` is None, returns the latest snapshot across
        all scopes for the given security.
        """
        candidates = [
            snapshot
            for snapshot in self._snapshots.values()
            if snapshot.security_id == security_id
            and snapshot.decision_at <= as_of
            and (
                scope_version_id is None
                or snapshot.scope_version_id == scope_version_id
            )
        ]
        return max(
            candidates,
            key=lambda item: (item.decision_at, item.created_at or item.decision_at),
            default=None,
        )

    def list_metrics(self, analysis_snapshot_id: str) -> list[AnalysisMetric]:
        """Return metrics for one snapshot."""
        return sorted(
            (
                metric
                for metric in self._metrics.values()
                if metric.analysis_snapshot_id == analysis_snapshot_id
            ),
            key=lambda item: item.metric_id,
        )

    def list_findings(self, analysis_snapshot_id: str) -> list[AnalysisFinding]:
        """Return findings for one snapshot."""
        return sorted(
            (
                finding
                for finding in self._findings.values()
                if finding.analysis_snapshot_id == analysis_snapshot_id
            ),
            key=lambda item: item.finding_id,
        )

    def list_evidence_links(self, analysis_snapshot_id: str) -> list[AnalysisEvidenceLink]:
        """Return links for one snapshot."""
        return sorted(
            (
                link
                for link in self._links.values()
                if link.analysis_snapshot_id == analysis_snapshot_id
            ),
            key=lambda item: item.link_id,
        )


class SQLAlchemyAnalysisMartRepository:
    """SQLAlchemy-backed Analysis Mart repository."""

    def __init__(self, session_factory: SessionFactory) -> None:
        """Initialize the repository with a SQLAlchemy session factory."""
        self._session_factory = session_factory

    def upsert_feature_snapshot(
        self,
        snapshot: QuantFeatureSnapshot,
        rows: tuple[QuantFeatureRow, ...],
    ) -> None:
        """Persist one feature snapshot idempotently in one transaction."""
        _validate_feature_snapshot(snapshot, rows)
        with self._session_factory.begin() as session:
            self._upsert_row(
                session,
                QuantFeatureSnapshotRow,
                snapshot.feature_snapshot_id,
                _feature_snapshot_to_row(snapshot),
                _feature_snapshot_from_row,
                "quant feature snapshot",
            )
            for row in rows:
                self._upsert_row(
                    session,
                    QuantFeatureRowRow,
                    row.row_id,
                    _feature_row_to_row(row),
                    _feature_row_from_row,
                    "quant feature row",
                )

    def get_feature_snapshot(
        self,
        feature_snapshot_id: str,
    ) -> QuantFeatureSnapshot | None:
        """Return one feature snapshot by ID."""
        with self._session_factory() as session:
            row = session.get(QuantFeatureSnapshotRow, feature_snapshot_id)
        return _feature_snapshot_from_row(row) if row is not None else None

    def latest_feature_snapshot(
        self,
        *,
        scope_version_id: str,
        as_of: datetime,
    ) -> QuantFeatureSnapshot | None:
        """Return the latest visible feature snapshot."""
        with self._session_factory() as session:
            row = session.scalar(
                latest_quant_feature_snapshot(
                    scope_version_id=scope_version_id,
                    as_of=as_of,
                )
            )
        return _feature_snapshot_from_row(row) if row is not None else None

    def list_feature_rows(self, feature_snapshot_id: str) -> list[QuantFeatureRow]:
        """Return rows for one feature snapshot."""
        with self._session_factory() as session:
            rows = session.scalars(quant_feature_rows_by_snapshot(feature_snapshot_id)).all()
        return [_feature_row_from_row(row) for row in rows]

    def upsert_bundle(self, bundle: AnalysisMartBundle) -> None:
        """Persist one bundle idempotently in one transaction."""
        _validate_bundle(bundle)
        with self._session_factory.begin() as session:
            self._upsert_row(
                session,
                AnalysisSnapshotRow,
                bundle.snapshot.analysis_snapshot_id,
                _snapshot_to_row(bundle.snapshot),
                _snapshot_from_row,
                "analysis snapshot",
            )
            for metric in bundle.metrics:
                self._upsert_row(
                    session,
                    AnalysisMetricRow,
                    metric.metric_id,
                    _metric_to_row(metric),
                    _metric_from_row,
                    "analysis metric",
                )
            for finding in bundle.findings:
                self._upsert_row(
                    session,
                    AnalysisFindingRow,
                    finding.finding_id,
                    _finding_to_row(finding),
                    _finding_from_row,
                    "analysis finding",
                )
            for link in bundle.evidence_links:
                self._upsert_row(
                    session,
                    AnalysisEvidenceLinkRow,
                    link.link_id,
                    _link_to_row(link),
                    _link_from_row,
                    "analysis evidence link",
                )

    def get_snapshot(self, analysis_snapshot_id: str) -> AnalysisSnapshot | None:
        """Return one snapshot by ID."""
        with self._session_factory() as session:
            row = session.get(AnalysisSnapshotRow, analysis_snapshot_id)
        return _snapshot_from_row(row) if row is not None else None

    def latest_snapshot(
        self,
        *,
        security_id: str,
        scope_version_id: str | None = None,
        as_of: datetime,
    ) -> AnalysisSnapshot | None:
        """Return the latest visible snapshot.

        When ``scope_version_id`` is None, returns the latest snapshot across
        all scopes for the given security.
        """
        with self._session_factory() as session:
            row = session.scalar(
                latest_analysis_snapshot(
                    security_id=security_id,
                    scope_version_id=scope_version_id,
                    as_of=as_of,
                )
            )
        return _snapshot_from_row(row) if row is not None else None

    def list_metrics(self, analysis_snapshot_id: str) -> list[AnalysisMetric]:
        """Return metrics for one snapshot."""
        with self._session_factory() as session:
            rows = session.scalars(analysis_metrics_by_snapshot(analysis_snapshot_id)).all()
        return [_metric_from_row(row) for row in rows]

    def list_findings(self, analysis_snapshot_id: str) -> list[AnalysisFinding]:
        """Return findings for one snapshot."""
        with self._session_factory() as session:
            rows = session.scalars(analysis_findings_by_snapshot(analysis_snapshot_id)).all()
        return [_finding_from_row(row) for row in rows]

    def list_evidence_links(self, analysis_snapshot_id: str) -> list[AnalysisEvidenceLink]:
        """Return links for one snapshot."""
        with self._session_factory() as session:
            rows = session.scalars(
                analysis_evidence_links_by_snapshot(analysis_snapshot_id)
            ).all()
        return [_link_from_row(row) for row in rows]

    def _upsert_row(
        self,
        session: Session,
        row_type: type,
        row_id: str,
        row: Any,
        mapper: Callable[[Any], Any],
        label: str,
    ) -> None:
        """Insert a row idempotently or reject conflicting replays."""
        existing = session.get(row_type, row_id)
        if existing is not None:
            if mapper(existing) != mapper(row):
                raise ValueError(f"conflicting {label}")
            return
        session.add(row)


class AnalysisMartPublisher:
    """Materialize quant and derived analysis outputs into Analysis Mart."""

    def __init__(
        self,
        repository: AnalysisMartRepository,
        *,
        analysis_version: str = "analysis-mart-v0.3.0",
    ) -> None:
        """Initialize the publisher with a repository and analysis version.

        Args:
            repository: Persistence boundary for Analysis Mart bundles.
            analysis_version: Version label for published analysis snapshots.
        """
        self._repository = repository
        self._analysis_version = analysis_version

    def publish_quant_result(
        self,
        *,
        scope_version_id: str,
        decision_at: datetime,
        trading_date: date,
        quant_result: QuantResult,
        input_snapshot_id: str | None,
        strategy_version_id: str | None,
        config_hash: str | None,
        input_hash: str,
        evidence_ids: tuple[str, ...] = (),
    ) -> AnalysisSnapshot:
        """Publish one quant result as a fourth-layer analysis snapshot."""
        ai_profile = dict(quant_result.factor_details.get("ai_quant_profile", {}))
        scores = _dict(ai_profile.get("scores"))
        raw_factors = _dict(ai_profile.get("raw_factors"))
        summary = {
            "security_id": quant_result.security_id,
            "name": quant_result.factor_details.get("name"),
            "industry_id": quant_result.factor_details.get("industry_id"),
            "screening_status": quant_result.screening_status.value,
            "data_status": quant_result.data_status.value,
            "final_score": quant_result.final_score,
            "rank_overall": quant_result.rank_overall,
            "rank_in_industry": quant_result.rank_in_industry,
            "risk_flags": list(quant_result.risk_flags),
            "review_required": quant_result.review_required,
            "review_reasons": list(quant_result.review_reasons),
            "research_guardrail": quant_result.research_guardrail.value,
            "reason_summary": quant_result.reason_summary,
            "strategy_profile": ai_profile.get("strategy_profile"),
            "candidate": ai_profile.get("candidate"),
            "research_hints": list(ai_profile.get("research_hints", ())),
        }
        result_hash = _hash_payload(
            {
                "quant_result_id": quant_result.result_id,
                "summary": summary,
                "scores": scores,
                "raw_factors": raw_factors,
                "evidence_ids": evidence_ids,
            }
        )
        snapshot_id = "asnap_" + _hash_payload(
            {
                "security_id": quant_result.security_id,
                "scope_version_id": scope_version_id,
                "decision_at": decision_at.isoformat(),
                "quant_result_id": quant_result.result_id,
                "analysis_version": self._analysis_version,
                "result_hash": result_hash,
            }
        ).removeprefix("sha256:")[:24]
        snapshot = AnalysisSnapshot(
            analysis_snapshot_id=snapshot_id,
            security_id=quant_result.security_id,
            scope_version_id=scope_version_id,
            decision_at=decision_at,
            trading_date=trading_date,
            analysis_version=self._analysis_version,
            analysis_kind="quant_snapshot",
            quant_run_id=quant_result.quant_run_id,
            quant_result_id=quant_result.result_id,
            input_snapshot_id=input_snapshot_id,
            strategy_version_id=strategy_version_id,
            config_hash=config_hash,
            input_hash=input_hash,
            result_hash=result_hash,
            summary=summary,
            quality_flags=_quality_flags(quant_result),
            created_at=quant_result.created_at,
        )
        metrics = tuple(
            _metric(
                snapshot=snapshot,
                code=code,
                name=name,
                group=group,
                value=value,
                source_type="quant_result",
                source_id=quant_result.result_id,
                detail=detail,
            )
            for code, name, group, value, detail in _metric_specs(
                quant_result,
                scores,
                raw_factors,
            )
        )
        finding = _quant_finding(
            snapshot=snapshot,
            quant_result=quant_result,
            evidence_ids=evidence_ids,
        )
        links = _lineage_links(
            snapshot=snapshot,
            finding=finding,
            metrics=metrics,
            quant_result=quant_result,
            input_snapshot_id=input_snapshot_id,
            evidence_ids=evidence_ids,
        )
        self._repository.upsert_bundle(
            AnalysisMartBundle(
                snapshot=snapshot,
                metrics=metrics,
                findings=(finding,),
                evidence_links=links,
            )
        )
        return snapshot


def _validate_bundle(bundle: AnalysisMartBundle) -> None:
    """Validate that all child rows reference the bundle's snapshot ID."""
    snapshot_id = bundle.snapshot.analysis_snapshot_id
    for metric in bundle.metrics:
        if metric.analysis_snapshot_id != snapshot_id:
            raise ValueError("analysis metric snapshot mismatch")
    for finding in bundle.findings:
        if finding.analysis_snapshot_id != snapshot_id:
            raise ValueError("analysis finding snapshot mismatch")
    for link in bundle.evidence_links:
        if link.analysis_snapshot_id != snapshot_id:
            raise ValueError("analysis evidence link snapshot mismatch")


def _metric_specs(
    quant_result: QuantResult,
    scores: dict[str, Any],
    raw_factors: dict[str, Any],
) -> tuple[tuple[str, str, str, float | None, dict[str, Any]], ...]:
    """Build metric specification tuples from quant scores and raw factors."""
    specs: list[tuple[str, str, str, float | None, dict[str, Any]]] = [
        ("final_score", "Final Score", "quant_score", quant_result.final_score, {}),
        ("quality_score", "Quality Score", "factor_group", quant_result.quality_score, {}),
        ("value_score", "Value Score", "factor_group", quant_result.value_score, {}),
        ("growth_score", "Growth Score", "factor_group", quant_result.growth_score, {}),
        ("momentum_score", "Momentum Score", "factor_group", quant_result.momentum_score, {}),
        ("risk_score", "Risk Score", "factor_group", quant_result.risk_score, {}),
    ]
    for key, value in sorted(scores.items()):
        specs.append(
            (
                f"score_{key}",
                f"Score {key}",
                "ai_quant_profile",
                _optional_float(value),
                {"profile_section": "scores"},
            )
        )
    for key, value in sorted(raw_factors.items()):
        specs.append(
            (
                f"raw_{key}",
                f"Raw {key}",
                "raw_factor",
                _optional_float(value),
                {"profile_section": "raw_factors"},
            )
        )
    return tuple(spec for spec in specs if spec[3] is not None)


def _metric(
    *,
    snapshot: AnalysisSnapshot,
    code: str,
    name: str,
    group: str,
    value: float | None,
    source_type: str,
    source_id: str,
    detail: dict[str, Any],
) -> AnalysisMetric:
    """Build an ``AnalysisMetric`` with a deterministic metric ID."""
    metric_id = "am_" + _hash_payload(
        {
            "snapshot_id": snapshot.analysis_snapshot_id,
            "metric_code": code,
        }
    ).removeprefix("sha256:")[:28]
    return AnalysisMetric(
        metric_id=metric_id,
        analysis_snapshot_id=snapshot.analysis_snapshot_id,
        metric_code=code,
        metric_name=name,
        metric_group=group,
        numeric_value=value,
        unit=None,
        direction=_metric_direction(code),
        source_refs=(
            {
                "source_type": source_type,
                "source_id": source_id,
            },
        ),
        detail=detail,
        created_at=snapshot.created_at,
    )


def _quant_finding(
    *,
    snapshot: AnalysisSnapshot,
    quant_result: QuantResult,
    evidence_ids: tuple[str, ...],
) -> AnalysisFinding:
    """Build a quant screening ``AnalysisFinding`` with a deterministic ID."""
    finding_id = "af_" + _hash_payload(
        {
            "snapshot_id": snapshot.analysis_snapshot_id,
            "finding_type": "quant_screening",
            "quant_result_id": quant_result.result_id,
        }
    ).removeprefix("sha256:")[:28]
    severity = (
        "positive"
        if quant_result.screening_status.value == "pass"
        else "watch"
        if quant_result.review_required
        else "neutral"
    )
    description = quant_result.reason_summary or (
        f"Quant screening status is {quant_result.screening_status.value} "
        f"with final score {quant_result.final_score:.2f}."
    )
    return AnalysisFinding(
        finding_id=finding_id,
        analysis_snapshot_id=snapshot.analysis_snapshot_id,
        finding_type="quant_screening",
        severity=severity,
        title=f"Quant screening: {quant_result.screening_status.value}",
        description=description,
        confidence=_finding_confidence(quant_result),
        evidence_ids=evidence_ids,
        source_refs=(
            {
                "source_type": "quant_result",
                "source_id": quant_result.result_id,
            },
        ),
        detail={
            "review_reasons": list(quant_result.review_reasons),
            "risk_flags": list(quant_result.risk_flags),
            "research_guardrail": quant_result.research_guardrail.value,
        },
        created_at=snapshot.created_at,
    )


def _lineage_links(
    *,
    snapshot: AnalysisSnapshot,
    finding: AnalysisFinding,
    metrics: tuple[AnalysisMetric, ...],
    quant_result: QuantResult,
    input_snapshot_id: str | None,
    evidence_ids: tuple[str, ...],
) -> tuple[AnalysisEvidenceLink, ...]:
    """Build lineage and evidence link rows for one analysis snapshot."""
    links: list[AnalysisEvidenceLink] = [
        _link(
            snapshot=snapshot,
            finding_id=finding.finding_id,
            metric_id=None,
            evidence_id=None,
            source_type="quant_result",
            source_id=quant_result.result_id,
            role="derived_from",
        )
    ]
    if input_snapshot_id is not None:
        links.append(
            _link(
                snapshot=snapshot,
                finding_id=finding.finding_id,
                metric_id=None,
                evidence_id=None,
                source_type="quant_input_snapshot",
                source_id=input_snapshot_id,
                role="derived_from",
            )
        )
    for metric in metrics:
        links.append(
            _link(
                snapshot=snapshot,
                finding_id=None,
                metric_id=metric.metric_id,
                evidence_id=None,
                source_type="quant_result",
                source_id=quant_result.result_id,
                role="metric_source",
            )
        )
    for evidence_id in evidence_ids:
        links.append(
            _link(
                snapshot=snapshot,
                finding_id=finding.finding_id,
                metric_id=None,
                evidence_id=evidence_id,
                source_type="evidence",
                source_id=evidence_id,
                role="supports",
            )
        )
    return tuple(links)


def _link(
    *,
    snapshot: AnalysisSnapshot,
    finding_id: str | None,
    metric_id: str | None,
    evidence_id: str | None,
    source_type: str,
    source_id: str,
    role: str,
) -> AnalysisEvidenceLink:
    """Build an ``AnalysisEvidenceLink`` with a deterministic link ID."""
    link_id = "al_" + _hash_payload(
        {
            "snapshot_id": snapshot.analysis_snapshot_id,
            "finding_id": finding_id,
            "metric_id": metric_id,
            "evidence_id": evidence_id,
            "source_type": source_type,
            "source_id": source_id,
            "role": role,
        }
    ).removeprefix("sha256:")[:28]
    return AnalysisEvidenceLink(
        link_id=link_id,
        analysis_snapshot_id=snapshot.analysis_snapshot_id,
        finding_id=finding_id,
        metric_id=metric_id,
        evidence_id=evidence_id,
        source_type=source_type,
        source_id=source_id,
        role=role,
        detail={},
        created_at=snapshot.created_at,
    )


def _quality_flags(quant_result: QuantResult) -> tuple[str, ...]:
    """Build quality flag tags from a quant result's data and risk state."""
    flags = ["data_status:" + quant_result.data_status.value]
    flags.extend(f"risk:{flag}" for flag in quant_result.risk_flags)
    if quant_result.review_required:
        flags.append("review_required")
    return tuple(flags)


def _metric_direction(code: str) -> str:
    """Return whether a metric code is lower or higher is better."""
    if code.startswith(("raw_pe", "raw_pb", "raw_ps")):
        return "lower_is_better"
    if code.startswith("raw_volatility") or code.startswith("raw_max_drawdown"):
        return "lower_is_better"
    return "higher_is_better"


def _finding_confidence(quant_result: QuantResult) -> float:
    """Return a clamped 0-1 confidence value from a quant result."""
    base = min(max(quant_result.final_score / 100.0, 0.0), 1.0)
    if quant_result.data_status.value != "ok":
        return min(base, 0.4)
    if quant_result.research_guardrail.value != "research_allowed":
        return min(base, 0.6)
    return base


def _dict(value: Any) -> dict[str, Any]:
    """Return a dict copy or an empty dict for non-dict values."""
    return dict(value) if isinstance(value, dict) else {}


def _optional_float(value: Any) -> float | None:
    """Convert a value to float, returning None for bool, NaN, or non-numeric."""
    if value is None or isinstance(value, bool):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _hash_payload(payload: dict[str, Any]) -> str:
    """Hash a payload dict to a deterministic SHA-256 digest string."""
    encoded = json.dumps(
        payload,
        sort_keys=True,
        default=str,
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def _ensure_same_or_absent(
    store: dict[str, Any],
    key: str,
    value: Any,
    label: str,
) -> None:
    """Reject conflicting replays when a key already holds a different value."""
    current = store.get(key)
    if current is not None and current != value:
        raise ValueError(f"conflicting {label}")


def _validate_feature_snapshot(
    snapshot: QuantFeatureSnapshot,
    rows: tuple[QuantFeatureRow, ...],
) -> None:
    """Validate that feature rows match the snapshot's row count and ID."""
    if snapshot.row_count != len(rows):
        raise ValueError("feature snapshot row_count does not match rows")
    for row in rows:
        if row.feature_snapshot_id != snapshot.feature_snapshot_id:
            raise ValueError("feature row references a different feature snapshot")


def _feature_snapshot_to_row(snapshot: QuantFeatureSnapshot) -> QuantFeatureSnapshotRow:
    """Convert a ``QuantFeatureSnapshot`` to its database row."""
    return QuantFeatureSnapshotRow(
        feature_snapshot_id=snapshot.feature_snapshot_id,
        scope_version_id=snapshot.scope_version_id,
        universe_snapshot_id=snapshot.universe_snapshot_id,
        decision_at=snapshot.decision_at,
        known_at=snapshot.known_at,
        trading_date=snapshot.trading_date,
        feature_set_version_id=snapshot.feature_set_version_id,
        feature_schema_version=snapshot.feature_schema_version,
        source_layer=snapshot.source_layer,
        input_hash=snapshot.input_hash,
        row_count=snapshot.row_count,
        feature_columns=list(snapshot.feature_columns),
        lineage_summary=snapshot.lineage_summary,
        quality_flags=list(snapshot.quality_flags),
        created_at=snapshot.created_at or snapshot.decision_at,
    )


def _feature_snapshot_from_row(row: QuantFeatureSnapshotRow) -> QuantFeatureSnapshot:
    """Convert a feature snapshot row to the immutable domain model."""
    return QuantFeatureSnapshot(
        feature_snapshot_id=row.feature_snapshot_id,
        scope_version_id=row.scope_version_id,
        universe_snapshot_id=row.universe_snapshot_id,
        decision_at=row.decision_at,
        known_at=row.known_at,
        trading_date=row.trading_date,
        feature_set_version_id=row.feature_set_version_id,
        feature_schema_version=row.feature_schema_version,
        source_layer=row.source_layer,
        input_hash=row.input_hash,
        row_count=row.row_count,
        feature_columns=tuple(row.feature_columns),
        lineage_summary=dict(row.lineage_summary),
        quality_flags=tuple(row.quality_flags),
        created_at=row.created_at,
    )


def _feature_row_to_row(row: QuantFeatureRow) -> QuantFeatureRowRow:
    """Convert a ``QuantFeatureRow`` to its database row."""
    return QuantFeatureRowRow(
        row_id=row.row_id,
        feature_snapshot_id=row.feature_snapshot_id,
        security_id=row.security_id,
        symbol=row.symbol,
        name=row.name,
        industry_id=row.industry_id,
        features_json=row.features,
        source_refs=list(row.source_refs),
        quality_flags=list(row.quality_flags),
        created_at=row.created_at or datetime.now(UTC),
    )


def _feature_row_from_row(row: QuantFeatureRowRow) -> QuantFeatureRow:
    """Convert a feature row row to the immutable domain model."""
    return QuantFeatureRow(
        row_id=row.row_id,
        feature_snapshot_id=row.feature_snapshot_id,
        security_id=row.security_id,
        symbol=row.symbol,
        name=row.name,
        industry_id=row.industry_id,
        features=dict(row.features_json),
        source_refs=tuple(dict(ref) for ref in row.source_refs),
        quality_flags=tuple(row.quality_flags),
        created_at=row.created_at,
    )


def _snapshot_to_row(snapshot: AnalysisSnapshot) -> AnalysisSnapshotRow:
    """Convert an ``AnalysisSnapshot`` to its database row."""
    return AnalysisSnapshotRow(
        analysis_snapshot_id=snapshot.analysis_snapshot_id,
        security_id=snapshot.security_id,
        scope_version_id=snapshot.scope_version_id,
        decision_at=snapshot.decision_at,
        trading_date=snapshot.trading_date,
        analysis_version=snapshot.analysis_version,
        analysis_kind=snapshot.analysis_kind,
        quant_run_id=snapshot.quant_run_id,
        quant_result_id=snapshot.quant_result_id,
        input_snapshot_id=snapshot.input_snapshot_id,
        strategy_version_id=snapshot.strategy_version_id,
        config_hash=snapshot.config_hash,
        input_hash=snapshot.input_hash,
        result_hash=snapshot.result_hash,
        summary_json=snapshot.summary,
        quality_flags=list(snapshot.quality_flags),
        created_at=snapshot.created_at or snapshot.decision_at,
    )


def _snapshot_from_row(row: AnalysisSnapshotRow) -> AnalysisSnapshot:
    """Convert an analysis snapshot row to the immutable domain model."""
    return AnalysisSnapshot(
        analysis_snapshot_id=row.analysis_snapshot_id,
        security_id=row.security_id,
        scope_version_id=row.scope_version_id,
        decision_at=row.decision_at,
        trading_date=row.trading_date,
        analysis_version=row.analysis_version,
        analysis_kind=row.analysis_kind,
        quant_run_id=row.quant_run_id,
        quant_result_id=row.quant_result_id,
        input_snapshot_id=row.input_snapshot_id,
        strategy_version_id=row.strategy_version_id,
        config_hash=row.config_hash,
        input_hash=row.input_hash,
        result_hash=row.result_hash,
        summary=dict(row.summary_json),
        quality_flags=tuple(row.quality_flags),
        created_at=row.created_at,
    )


def _metric_to_row(metric: AnalysisMetric) -> AnalysisMetricRow:
    """Convert an ``AnalysisMetric`` to its database row."""
    return AnalysisMetricRow(
        metric_id=metric.metric_id,
        analysis_snapshot_id=metric.analysis_snapshot_id,
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
        source_refs=list(metric.source_refs),
        detail_json=metric.detail or {},
        created_at=metric.created_at or datetime.now(UTC),
    )


def _metric_from_row(row: AnalysisMetricRow) -> AnalysisMetric:
    """Convert an analysis metric row to the immutable domain model."""
    return AnalysisMetric(
        metric_id=row.metric_id,
        analysis_snapshot_id=row.analysis_snapshot_id,
        metric_code=row.metric_code,
        metric_name=row.metric_name,
        metric_group=row.metric_group,
        numeric_value=row.numeric_value,
        unit=row.unit,
        direction=row.direction,
        percentile_market=row.percentile_market,
        percentile_industry=row.percentile_industry,
        rank_market=row.rank_market,
        rank_industry=row.rank_industry,
        source_refs=tuple(dict(ref) for ref in row.source_refs),
        detail=dict(row.detail_json),
        created_at=row.created_at,
    )


def _finding_to_row(finding: AnalysisFinding) -> AnalysisFindingRow:
    """Convert an ``AnalysisFinding`` to its database row."""
    return AnalysisFindingRow(
        finding_id=finding.finding_id,
        analysis_snapshot_id=finding.analysis_snapshot_id,
        finding_type=finding.finding_type,
        severity=finding.severity,
        title=finding.title,
        description=finding.description,
        confidence=finding.confidence,
        evidence_ids=list(finding.evidence_ids),
        source_refs=list(finding.source_refs),
        detail_json=finding.detail or {},
        created_at=finding.created_at or datetime.now(UTC),
    )


def _finding_from_row(row: AnalysisFindingRow) -> AnalysisFinding:
    """Convert an analysis finding row to the immutable domain model."""
    return AnalysisFinding(
        finding_id=row.finding_id,
        analysis_snapshot_id=row.analysis_snapshot_id,
        finding_type=row.finding_type,
        severity=row.severity,
        title=row.title,
        description=row.description,
        confidence=row.confidence,
        evidence_ids=tuple(row.evidence_ids),
        source_refs=tuple(dict(ref) for ref in row.source_refs),
        detail=dict(row.detail_json),
        created_at=row.created_at,
    )


def _link_to_row(link: AnalysisEvidenceLink) -> AnalysisEvidenceLinkRow:
    """Convert an ``AnalysisEvidenceLink`` to its database row."""
    return AnalysisEvidenceLinkRow(
        link_id=link.link_id,
        analysis_snapshot_id=link.analysis_snapshot_id,
        finding_id=link.finding_id,
        metric_id=link.metric_id,
        evidence_id=link.evidence_id,
        source_type=link.source_type,
        source_id=link.source_id,
        role=link.role,
        detail_json=link.detail or {},
        created_at=link.created_at or datetime.now(UTC),
    )


def _link_from_row(row: AnalysisEvidenceLinkRow) -> AnalysisEvidenceLink:
    """Convert an analysis evidence link row to the immutable domain model."""
    return AnalysisEvidenceLink(
        link_id=row.link_id,
        analysis_snapshot_id=row.analysis_snapshot_id,
        finding_id=row.finding_id,
        metric_id=row.metric_id,
        evidence_id=row.evidence_id,
        source_type=row.source_type,
        source_id=row.source_id,
        role=row.role,
        detail=dict(row.detail_json),
        created_at=row.created_at,
    )
