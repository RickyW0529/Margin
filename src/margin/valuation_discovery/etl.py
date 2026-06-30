"""Managed ETL pipelines for valuation-discovery mart layers."""

from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any

import pandas as pd
from sqlalchemy import select
from sqlalchemy.orm import Session

from margin.valuation_discovery.analysis_mart import (
    AnalysisMartPublisher,
    AnalysisMartRepository,
    AnalysisSnapshot,
    QuantFeatureRow,
    QuantFeatureSnapshot,
    _feature_row_from_row,
    _feature_row_to_row,
    _feature_snapshot_from_row,
    _feature_snapshot_to_row,
    _validate_feature_snapshot,
)
from margin.valuation_discovery.db_models import (
    QuantFeatureRowRow,
    QuantFeatureSnapshotRow,
    QuantInputSnapshotFactRow,
    QuantInputSnapshotRow,
)
from margin.valuation_discovery.models import QuantInputSnapshot, QuantResult
from margin.valuation_discovery.repository import (
    _quant_input_fact_to_row,
    _quant_input_snapshot_from_row,
    _quant_input_snapshot_to_row,
)

SessionFactory = Callable[[], Session]


@dataclass(frozen=True)
class QuantFeatureMartETLResult:
    """Atomic output from the third-layer to fourth-layer feature ETL."""

    input_snapshot: QuantInputSnapshot
    feature_snapshot: QuantFeatureSnapshot


class QuantFeatureMartETLPipeline:
    """Materialize third-layer warehouse data into fourth-layer quant features."""

    def __init__(
        self,
        *,
        repository: AnalysisMartRepository,
        source_loader: Callable[[QuantInputSnapshot], pd.DataFrame],
        snapshot_persister: Callable[[QuantInputSnapshot], None] | None = None,
    ) -> None:
        """Initialize the ETL pipeline with repository, loader, and persister.

        Args:
            repository: Persistence boundary for feature snapshots and rows.
            source_loader: Callable that loads a PIT-safe cross-section.
            snapshot_persister: Optional callable to persist the bound snapshot.
        """
        self._repository = repository
        self._source_loader = source_loader
        self._snapshot_persister = snapshot_persister

    def materialize(self, snapshot: QuantInputSnapshot) -> QuantFeatureMartETLResult:
        """Publish one feature snapshot and return an input bound to it."""
        frame = self._source_loader(snapshot)
        feature_snapshot, rows = build_quant_feature_payload(
            snapshot=snapshot,
            frame=frame,
        )
        bound_snapshot = bind_feature_snapshot(
            snapshot,
            feature_snapshot.feature_snapshot_id,
        )
        self._repository.upsert_feature_snapshot(feature_snapshot, rows)
        if self._snapshot_persister is not None:
            self._snapshot_persister(bound_snapshot)
        return QuantFeatureMartETLResult(
            input_snapshot=bound_snapshot,
            feature_snapshot=feature_snapshot,
        )


class SQLAlchemyQuantFeatureMartETLPipeline:
    """SQLAlchemy ETL pipeline with one transaction for input and feature rows."""

    def __init__(
        self,
        session_factory: SessionFactory,
        *,
        source_loader: Callable[[QuantInputSnapshot], pd.DataFrame],
    ) -> None:
        """Initialize the SQLAlchemy ETL pipeline with a session factory.

        Args:
            session_factory: Callable that returns a SQLAlchemy ``Session``.
            source_loader: Callable that loads a PIT-safe cross-section.
        """
        self._session_factory = session_factory
        self._source_loader = source_loader

    def materialize(self, snapshot: QuantInputSnapshot) -> QuantFeatureMartETLResult:
        """Publish quant input and feature rows in one database transaction."""
        frame = self._source_loader(snapshot)
        feature_snapshot, rows = build_quant_feature_payload(
            snapshot=snapshot,
            frame=frame,
        )
        bound_snapshot = bind_feature_snapshot(
            snapshot,
            feature_snapshot.feature_snapshot_id,
        )
        _validate_feature_snapshot(feature_snapshot, rows)
        with self._session_factory.begin() as session:
            _upsert_quant_input_snapshot(session, bound_snapshot)
            _upsert_sqlalchemy_row(
                session,
                QuantFeatureSnapshotRow,
                feature_snapshot.feature_snapshot_id,
                _feature_snapshot_to_row(feature_snapshot),
                _feature_snapshot_from_row,
                "quant feature snapshot",
            )
            for row in rows:
                _upsert_sqlalchemy_row(
                    session,
                    QuantFeatureRowRow,
                    row.row_id,
                    _feature_row_to_row(row),
                    _feature_row_from_row,
                    "quant feature row",
                )
        return QuantFeatureMartETLResult(
            input_snapshot=bound_snapshot,
            feature_snapshot=feature_snapshot,
        )


class AnalysisResultMartETLPipeline:
    """Managed ETL entry point for quant results written to Analysis Mart."""

    def __init__(
        self,
        repository: AnalysisMartRepository,
        *,
        analysis_version: str = "analysis-mart-v0.3.0",
    ) -> None:
        """Initialize the ETL entry point with a repository and version.

        Args:
            repository: Persistence boundary for Analysis Mart bundles.
            analysis_version: Version label for published analysis snapshots.
        """
        self._publisher = AnalysisMartPublisher(
            repository,
            analysis_version=analysis_version,
        )

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
        """Publish one quant result through the fourth-layer ETL boundary."""
        return self._publisher.publish_quant_result(
            scope_version_id=scope_version_id,
            decision_at=decision_at,
            trading_date=trading_date,
            quant_result=quant_result,
            input_snapshot_id=input_snapshot_id,
            strategy_version_id=strategy_version_id,
            config_hash=config_hash,
            input_hash=input_hash,
            evidence_ids=evidence_ids,
        )


def publish_quant_feature_snapshot(
    *,
    repository: AnalysisMartRepository,
    snapshot: QuantInputSnapshot,
    frame: pd.DataFrame,
) -> QuantFeatureSnapshot:
    """Materialize a quant cross-section into fourth-layer feature rows.

    Args:
        repository: Persistence boundary for feature snapshots and rows.
        snapshot: Frozen quant input snapshot with lineage metadata.
        frame: PIT-safe cross-section DataFrame.

    Returns:
        The persisted ``QuantFeatureSnapshot``.
    """
    feature_snapshot, rows = build_quant_feature_payload(
        snapshot=snapshot,
        frame=frame,
    )
    repository.upsert_feature_snapshot(feature_snapshot, rows)
    return feature_snapshot


def build_quant_feature_payload(
    *,
    snapshot: QuantInputSnapshot,
    frame: pd.DataFrame,
) -> tuple[QuantFeatureSnapshot, tuple[QuantFeatureRow, ...]]:
    """Build the atomic fourth-layer feature snapshot payload.

    Args:
        snapshot: Frozen quant input snapshot with lineage metadata.
        frame: PIT-safe cross-section DataFrame.

    Returns:
        A tuple of (feature snapshot, feature rows).
    """
    normalized = frame.copy(deep=True)
    if "security_id" not in normalized.columns:
        normalized["security_id"] = normalized.index.astype(str)
    normalized["security_id"] = normalized["security_id"].astype(str)
    normalized = normalized.set_index("security_id", drop=False)
    feature_columns = tuple(
        str(column)
        for column in normalized.columns
        if str(column) not in {"security_id"}
    )
    lineage_summary = {
        "quant_input_snapshot_id": snapshot.snapshot_id,
        "quant_input_hash": snapshot.input_hash,
        "fact_count": snapshot.fact_count,
        "required_indicators": list(snapshot.required_indicators),
        "optional_indicators": list(snapshot.optional_indicators),
        "market_window_start": (
            snapshot.market_window_start.isoformat()
            if snapshot.market_window_start is not None
            else None
        ),
        "market_window_end": (
            snapshot.market_window_end.isoformat()
            if snapshot.market_window_end is not None
            else None
        ),
    }
    input_hash = _hash_feature_payload(
        {
            "snapshot_input_hash": snapshot.input_hash,
            "security_ids": list(snapshot.security_ids),
            "feature_columns": list(feature_columns),
            "lineage_summary": lineage_summary,
        }
    )
    feature_snapshot_id = "qfsnap_" + input_hash.removeprefix("sha256:")[:24]
    feature_snapshot = QuantFeatureSnapshot(
        feature_snapshot_id=feature_snapshot_id,
        scope_version_id=snapshot.scope_version_id,
        universe_snapshot_id=snapshot.universe_snapshot_id,
        decision_at=snapshot.decision_at,
        known_at=snapshot.known_at,
        trading_date=snapshot.decision_at.date(),
        feature_set_version_id=getattr(snapshot.quant_feature_set, "version_id", None),
        feature_schema_version="quant-feature-mart-v0.3.0",
        source_layer="third_layer",
        input_hash=input_hash,
        row_count=len(normalized.index),
        feature_columns=feature_columns,
        lineage_summary=lineage_summary,
        quality_flags=snapshot.quality_flags,
        created_at=snapshot.created_at,
    )
    refs_by_security = _fact_refs_by_security(snapshot)
    rows = tuple(
        QuantFeatureRow(
            row_id="qfrow_"
            + _hash_feature_payload(
                {
                    "feature_snapshot_id": feature_snapshot_id,
                    "security_id": security_id,
                }
            ).removeprefix("sha256:")[:24],
            feature_snapshot_id=feature_snapshot_id,
            security_id=security_id,
            symbol=_optional_text(row.get("symbol")) or security_id,
            name=_optional_text(row.get("name")),
            industry_id=_optional_text(row.get("industry_id")),
            features={
                str(column): _jsonable_feature(row.get(column))
                for column in normalized.columns
                if str(column) != "security_id"
            },
            source_refs=refs_by_security.get(security_id, ()),
            quality_flags=_row_quality_flags(row),
            created_at=snapshot.created_at,
        )
        for security_id, row in normalized.iterrows()
    )
    return feature_snapshot, rows


def bind_feature_snapshot(
    snapshot: QuantInputSnapshot,
    feature_snapshot_id: str,
) -> QuantInputSnapshot:
    """Return a quant input snapshot bound to its fourth-layer feature snapshot.

    Args:
        snapshot: The original frozen quant input snapshot.
        feature_snapshot_id: The feature snapshot ID to bind.

    Returns:
        A new ``QuantInputSnapshot`` with the feature snapshot ID set.
    """
    payload = snapshot.model_dump()
    payload["feature_snapshot_id"] = feature_snapshot_id
    payload.pop("input_hash", None)
    return QuantInputSnapshot(**payload)


def build_feature_mart_cross_section_loader(
    repository: AnalysisMartRepository,
) -> Callable[[QuantInputSnapshot], pd.DataFrame]:
    """Return a cross-section loader backed by fourth-layer feature rows.

    Args:
        repository: Persistence boundary for feature snapshots and rows.

    Returns:
        A callable that loads a PIT-safe cross-section from QuantFeatureMart.
    """

    def loader(snapshot: QuantInputSnapshot) -> pd.DataFrame:
        """Load a materialized PIT-safe cross-section from QuantFeatureMart."""
        if not snapshot.feature_snapshot_id:
            raise RuntimeError("QuantInputSnapshot is missing feature_snapshot_id")
        feature_snapshot = repository.get_feature_snapshot(snapshot.feature_snapshot_id)
        if feature_snapshot is None:
            raise KeyError(f"quant feature snapshot not found: {snapshot.feature_snapshot_id}")
        rows = repository.list_feature_rows(feature_snapshot.feature_snapshot_id)
        records: list[dict[str, Any]] = []
        for row in rows:
            record = {
                "security_id": row.security_id,
                "symbol": row.symbol or row.security_id,
                "name": row.name,
                "industry_id": row.industry_id,
                **row.features,
            }
            records.append(record)
        if not records:
            return pd.DataFrame({"security_id": list(snapshot.security_ids)}).set_index(
                "security_id",
                drop=False,
            )
        frame = pd.DataFrame.from_records(records)
        frame["security_id"] = frame["security_id"].astype(str)
        return frame.set_index("security_id", drop=False)

    return loader


def _upsert_quant_input_snapshot(
    session: Session,
    snapshot: QuantInputSnapshot,
) -> None:
    """Insert a quant input snapshot idempotently or reject conflicting replays."""
    existing = session.get(QuantInputSnapshotRow, snapshot.snapshot_id)
    if existing is not None:
        fact_rows = session.scalars(
            select(QuantInputSnapshotFactRow)
            .where(QuantInputSnapshotFactRow.snapshot_id == snapshot.snapshot_id)
            .order_by(
                QuantInputSnapshotFactRow.security_id,
                QuantInputSnapshotFactRow.indicator_code,
                QuantInputSnapshotFactRow.fact_ref_id,
            )
        ).all()
        if _quant_input_snapshot_from_row(
            existing,
            list(fact_rows),
        ) != _persisted_quant_input_projection(snapshot):
            raise ValueError("conflicting quant input snapshot")
        return
    session.add(_quant_input_snapshot_to_row(snapshot))
    for index, fact_ref in enumerate(snapshot.fact_refs):
        session.add(_quant_input_fact_to_row(snapshot.snapshot_id, index, fact_ref))


def _persisted_quant_input_projection(
    snapshot: QuantInputSnapshot,
) -> QuantInputSnapshot:
    """Return a projection of a snapshot with non-persisted fields cleared."""
    payload = snapshot.model_dump()
    payload["quant_feature_set"] = None
    payload["user_indicator_view"] = None
    return QuantInputSnapshot(**payload)


def _upsert_sqlalchemy_row(
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


def _hash_feature_payload(payload: dict[str, Any]) -> str:
    """Hash a payload dict to a deterministic SHA-256 digest string."""
    encoded = json.dumps(
        payload,
        sort_keys=True,
        default=str,
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def _fact_refs_by_security(
    snapshot: QuantInputSnapshot,
) -> dict[str, tuple[dict[str, Any], ...]]:
    """Group fact references by security_id for feature row lineage."""
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for ref in snapshot.fact_refs:
        security_id = ref.get("security_id")
        if security_id is not None:
            grouped[str(security_id)].append(
                {str(key): _jsonable_feature(value) for key, value in ref.items()}
            )
    return {key: tuple(value) for key, value in grouped.items()}


def _optional_text(value: Any) -> str | None:
    """Convert a value to a stripped string, returning None for empty or NaN."""
    if value is None:
        return None
    if isinstance(value, float) and pd.isna(value):
        return None
    text = str(value).strip()
    return text or None


def _jsonable_feature(value: Any) -> Any:
    """Convert a value to a JSON-serializable form, handling pandas and dates."""
    if value is None:
        return None
    if isinstance(value, float) and pd.isna(value):
        return None
    if isinstance(value, (pd.Timestamp, datetime, date)):
        return value.isoformat()
    if hasattr(value, "item"):
        return _jsonable_feature(value.item())
    if isinstance(value, dict):
        return {str(key): _jsonable_feature(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable_feature(item) for item in value]
    return value


def _row_quality_flags(row: pd.Series) -> tuple[str, ...]:
    """Build quality flag tags from ST and suspension indicators in a row."""
    flags: list[str] = []
    if _truthy_feature(row.get("is_st")):
        flags.append("st_security")
    if _truthy_feature(row.get("is_suspended")):
        flags.append("suspended_or_stale_market")
    return tuple(flags)


def _truthy_feature(value: Any) -> bool:
    """Return whether a feature value is truthy, handling None and NaN."""
    if value is None:
        return False
    if isinstance(value, float) and pd.isna(value):
        return False
    return bool(value)
