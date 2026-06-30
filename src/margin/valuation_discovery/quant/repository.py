"""Persistence boundary for quant screening runs and results."""

from __future__ import annotations

import hashlib
from collections.abc import Callable, Iterable
from typing import Protocol

import pandas as pd
from sqlalchemy import select
from sqlalchemy.orm import Session

from margin.valuation_discovery.db_models import (
    QuantFactorValueRow,
    QuantScreenResultRow,
    QuantScreenRunRow,
)
from margin.valuation_discovery.models import (
    DataStatus,
    QuantInputSnapshot,
    QuantResult,
    QuantRun,
    ResearchGuardrail,
    ScreeningStatus,
)


class QuantRepository(Protocol):
    """Repository contract used by the quant service.

    Loading cross-section data is deliberately abstract. Production callers wire
    this to the PIT-safe warehouse adapter; the quant module never calls data
    providers directly.
    """

    def load_cross_section(self, snapshot: QuantInputSnapshot) -> pd.DataFrame:
        """Return the PIT-safe quant cross-section for a frozen input snapshot."""

    def add_run(self, quant_run: QuantRun) -> None:
        """Persist quant run metadata."""

    def add_results(self, quant_run_id: str, results: Iterable[QuantResult]) -> None:
        """Persist all results for a quant run."""

    def get_run(self, quant_run_id: str) -> QuantRun | None:
        """Return one persisted quant run."""

    def list_results(self, quant_run_id: str) -> tuple[QuantResult, ...]:
        """Return persisted results for a quant run."""


class MemoryQuantRepository:
    """In-memory quant repository for unit and local integration tests."""

    def __init__(self) -> None:
        """Initialize an empty in-memory quant repository."""
        self._cross_sections: dict[str, pd.DataFrame] = {}
        self._runs: dict[str, QuantRun] = {}
        self._results: dict[str, tuple[QuantResult, ...]] = {}

    def set_cross_section(self, snapshot_id: str, frame: pd.DataFrame) -> None:
        """Register a cross-section returned for a snapshot ID."""
        self._cross_sections[snapshot_id] = frame.copy(deep=True)

    def load_cross_section(self, snapshot: QuantInputSnapshot) -> pd.DataFrame:
        """Return the registered cross-section for the supplied snapshot."""
        if snapshot.snapshot_id not in self._cross_sections:
            raise KeyError(f"cross-section not found for snapshot {snapshot.snapshot_id}")
        return self._cross_sections[snapshot.snapshot_id].copy(deep=True)

    def add_run(self, quant_run: QuantRun) -> None:
        """Persist quant run metadata."""
        self._runs[quant_run.quant_run_id] = quant_run

    def add_results(self, quant_run_id: str, results: Iterable[QuantResult]) -> None:
        """Persist results for one run."""
        stored = tuple(results)
        _validate_result_run_ids(quant_run_id, stored)
        self._results[quant_run_id] = stored

    def get_run(self, quant_run_id: str) -> QuantRun | None:
        """Return one persisted quant run."""
        return self._runs.get(quant_run_id)

    def list_results(self, quant_run_id: str) -> tuple[QuantResult, ...]:
        """Return persisted results for one run."""
        return self._results.get(quant_run_id, ())


class SQLAlchemyQuantRepository:
    """PostgreSQL-backed quant run/result repository."""

    def __init__(
        self,
        session_factory: Callable[[], Session],
        *,
        cross_section_loader: Callable[[QuantInputSnapshot], pd.DataFrame] | None = None,
    ) -> None:
        """Initialize the repository with a session factory and optional loader.

        Args:
            session_factory: Callable that returns a SQLAlchemy ``Session``.
            cross_section_loader: Optional PIT-safe cross-section loader.
        """
        self._session_factory = session_factory
        self._cross_section_loader = cross_section_loader

    def load_cross_section(self, snapshot: QuantInputSnapshot) -> pd.DataFrame:
        """Load a cross-section through the caller-provided PIT-safe adapter."""
        if self._cross_section_loader is None:
            raise RuntimeError("SQLAlchemyQuantRepository requires a cross_section_loader")
        return self._cross_section_loader(snapshot).copy(deep=True)

    def add_run(self, quant_run: QuantRun) -> None:
        """Persist quant run metadata append-only."""
        with self._session_factory.begin() as session:  # type: ignore[attr-defined]
            session.add(_quant_run_to_row(quant_run))

    def add_results(self, quant_run_id: str, results: Iterable[QuantResult]) -> None:
        """Persist quant results append-only."""
        stored = tuple(results)
        _validate_result_run_ids(quant_run_id, stored)
        with self._session_factory.begin() as session:  # type: ignore[attr-defined]
            for result in stored:
                session.add(_quant_result_to_row(result))
                for factor_row in _factor_rows_from_result(result):
                    session.add(factor_row)

    def get_run(self, quant_run_id: str) -> QuantRun | None:
        """Return one persisted quant run."""
        with self._session_factory() as session:
            row = session.get(QuantScreenRunRow, quant_run_id)
        return _quant_run_from_row(row) if row is not None else None

    def list_results(self, quant_run_id: str) -> tuple[QuantResult, ...]:
        """Return persisted results for one run ordered by creation time."""
        with self._session_factory() as session:
            rows = session.scalars(
                select(QuantScreenResultRow)
                .where(QuantScreenResultRow.quant_run_id == quant_run_id)
                .order_by(QuantScreenResultRow.created_at, QuantScreenResultRow.result_id)
            ).all()
        return tuple(_quant_result_from_row(row) for row in rows)


def _validate_result_run_ids(
    quant_run_id: str,
    results: tuple[QuantResult, ...],
) -> None:
    """Validate that all results belong to the supplied quant run ID."""
    mismatches = [
        result.result_id for result in results if result.quant_run_id != quant_run_id
    ]
    if mismatches:
        raise ValueError(f"quant result run mismatch: {mismatches[0]}")


def _quant_run_to_row(quant_run: QuantRun) -> QuantScreenRunRow:
    """Convert a ``QuantRun`` to its database row."""
    return QuantScreenRunRow(
        quant_run_id=quant_run.quant_run_id,
        input_snapshot_id=quant_run.input_snapshot_id,
        scope_version_id=quant_run.scope_version_id,
        strategy_version_id=quant_run.strategy_version_id,
        decision_at=quant_run.decision_at,
        config_hash=quant_run.config_hash,
        status=quant_run.status,
        created_at=quant_run.created_at,
    )


def _quant_run_from_row(row: QuantScreenRunRow) -> QuantRun:
    """Convert one persisted run row to the immutable domain model."""
    return QuantRun(
        quant_run_id=row.quant_run_id,
        input_snapshot_id=row.input_snapshot_id,
        scope_version_id=row.scope_version_id,
        strategy_version_id=row.strategy_version_id,
        decision_at=row.decision_at,
        config_hash=row.config_hash,
        status=row.status,
        created_at=row.created_at,
    )


def _quant_result_to_row(result: QuantResult) -> QuantScreenResultRow:
    """Convert a ``QuantResult`` to its database row."""
    return QuantScreenResultRow(
        result_id=result.result_id,
        quant_run_id=result.quant_run_id,
        security_id=result.security_id,
        final_score=result.final_score,
        quality_score=result.quality_score,
        value_score=result.value_score,
        growth_score=result.growth_score,
        momentum_score=result.momentum_score,
        risk_score=result.risk_score,
        rank_overall=result.rank_overall,
        rank_in_industry=result.rank_in_industry,
        screening_status=result.screening_status.value,
        data_status=result.data_status.value,
        risk_flags=list(result.risk_flags),
        review_required=result.review_required,
        review_reasons=list(result.review_reasons),
        research_guardrail=result.research_guardrail.value,
        reason_summary=result.reason_summary,
        factor_details=result.factor_details,
        created_at=result.created_at,
    )


def _quant_result_from_row(row: QuantScreenResultRow) -> QuantResult:
    """Convert a result row to the immutable ``QuantResult`` model."""
    return QuantResult(
        result_id=row.result_id,
        quant_run_id=row.quant_run_id,
        security_id=row.security_id,
        final_score=row.final_score,
        quality_score=row.quality_score,
        value_score=row.value_score,
        growth_score=row.growth_score,
        momentum_score=row.momentum_score,
        risk_score=row.risk_score,
        rank_overall=row.rank_overall,
        rank_in_industry=row.rank_in_industry,
        screening_status=ScreeningStatus(row.screening_status),
        data_status=DataStatus(row.data_status),
        risk_flags=tuple(row.risk_flags),
        review_required=row.review_required,
        review_reasons=tuple(row.review_reasons),
        research_guardrail=ResearchGuardrail(row.research_guardrail),
        reason_summary=row.reason_summary,
        factor_details=row.factor_details,
        created_at=row.created_at,
    )


def _factor_rows_from_result(result: QuantResult) -> tuple[QuantFactorValueRow, ...]:
    """Build factor value rows from group scores in a quant result."""
    scores = {
        "final": result.final_score,
        "quality": result.quality_score,
        "value": result.value_score,
        "growth": result.growth_score,
        "momentum": result.momentum_score,
        "risk": result.risk_score,
    }
    rows: list[QuantFactorValueRow] = []
    for factor_name, score in scores.items():
        factor_value_id = _factor_value_id(result.result_id, factor_name)
        rows.append(
            QuantFactorValueRow(
                factor_value_id=factor_value_id,
                result_id=result.result_id,
                factor_group="group_score",
                factor_name=factor_name,
                raw_value=None,
                score=score,
                direction="higher",
                missing=score is None,
                detail_json={
                    "rank_overall": result.rank_overall,
                    "rank_in_industry": result.rank_in_industry,
                },
            )
        )
    return tuple(rows)


def _factor_value_id(result_id: str, factor_name: str) -> str:
    """Build a stable factor value ID from result ID and factor name."""
    material = f"{result_id}:{factor_name}"
    return "qfv_" + hashlib.sha256(material.encode("utf-8")).hexdigest()[:24]
