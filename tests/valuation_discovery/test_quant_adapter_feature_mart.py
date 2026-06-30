"""Quant adapter wiring tests for fourth-layer feature mart reads.

This module validates that the quant adapter persists feature-bound input
snapshots and that the SQLAlchemy feature mart ETL pipeline writes bound
input and feature rows atomically in one transaction.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

import pandas as pd
from sqlalchemy import text

from margin.storage.base import Base
from margin.storage.database import (
    DatabaseSettings,
    create_database_engine,
    create_session_factory,
)
from margin.valuation_discovery.analysis_mart import (
    MemoryAnalysisMartRepository,
    SQLAlchemyAnalysisMartRepository,
)
from margin.valuation_discovery.db_models import (
    QuantFeatureRowRow,
    QuantFeatureSnapshotRow,
    QuantInputSnapshotRow,
)
from margin.valuation_discovery.etl import (
    QuantFeatureMartETLPipeline,
    SQLAlchemyQuantFeatureMartETLPipeline,
)
from margin.valuation_discovery.models import UniverseCode, UniverseSnapshot
from margin.valuation_discovery.quant.repository import MemoryQuantRepository
from margin.valuation_discovery.quant.service import QuantService
from margin.valuation_discovery.quant_adapter import QuantAdapter
from margin.valuation_discovery.quant_input import (
    CanonicalFactRef,
    QuantInputSnapshotBuilder,
)
from margin.valuation_discovery.repository import (
    MemoryValuationDiscoveryRepository,
    SQLAlchemyValuationDiscoveryRepository,
)
from margin.valuation_discovery.scope import (
    QuantFeatureSet,
    ScopeBinding,
    UserIndicatorView,
)

DECISION_AT = datetime(2026, 6, 24, 8, 0, tzinfo=UTC)


def test_quant_adapter_persists_feature_bound_input_snapshot() -> None:
    """Verify the production adapter path binds quant input to fourth-layer features.

    Returns:
        None.
    """
    valuation_repository = MemoryValuationDiscoveryRepository()
    analysis_repository = MemoryAnalysisMartRepository()
    snapshot_builder = QuantInputSnapshotBuilder(
        valuation_repository,
        _FactWarehouse(),
    )
    feature_pipeline = QuantFeatureMartETLPipeline(
        repository=analysis_repository,
        source_loader=_feature_frame,
        snapshot_persister=snapshot_builder.persist,
    )
    quant_repository = MemoryQuantRepository()
    adapter = QuantAdapter(
        quant_service=QuantService(quant_repository),
        snapshot_builder=snapshot_builder,
        scope_provider=_ScopeProvider(_scope()),
        quant_repository=quant_repository,
        feature_mart_pipeline=feature_pipeline,
    )

    snapshot = adapter.build_input(
        scope_version_id="scope-v1",
        decision_at=DECISION_AT,
    )

    assert snapshot.feature_snapshot_id is not None
    assert valuation_repository.get_quant_input_snapshot(snapshot.snapshot_id) == snapshot
    assert analysis_repository.get_feature_snapshot(snapshot.feature_snapshot_id)


def test_sqlalchemy_quant_feature_mart_etl_persists_atomically(
    database_url: str,
) -> None:
    """Verify SQL ETL writes bound input and feature rows in one transaction.

    Args:
        database_url: PostgreSQL connection URL for the isolated test database.

    Returns:
        None.
    """
    engine = create_database_engine(DatabaseSettings(url=database_url))
    Base.metadata.create_all(engine)
    with engine.begin() as connection:
        connection.execute(
            text(
                "ALTER TABLE quant_input_snapshots "
                "ADD COLUMN IF NOT EXISTS feature_snapshot_id VARCHAR(64)"
            )
        )
    session_factory = create_session_factory(engine)
    snapshot = QuantInputSnapshotBuilder(
        MemoryValuationDiscoveryRepository(),
        _FactWarehouse(),
    ).build(
        scope=_scope(),
        decision_at=DECISION_AT,
        market_window_days=260,
        persist=False,
    )
    pipeline = SQLAlchemyQuantFeatureMartETLPipeline(
        session_factory,
        source_loader=_feature_frame,
    )

    result = None
    try:
        result = pipeline.materialize(snapshot)

        stored_input = SQLAlchemyValuationDiscoveryRepository(
            session_factory
        ).get_quant_input_snapshot(snapshot.snapshot_id)
        assert stored_input is not None
        assert stored_input.feature_snapshot_id == (
            result.feature_snapshot.feature_snapshot_id
        )
        assert stored_input.input_hash == result.input_snapshot.input_hash
        assert _fact_ref_keys(stored_input.fact_refs) == _fact_ref_keys(
            result.input_snapshot.fact_refs
        )
        assert (
            SQLAlchemyAnalysisMartRepository(session_factory).get_feature_snapshot(
                result.feature_snapshot.feature_snapshot_id
            )
            == result.feature_snapshot
        )
    finally:
        with session_factory.begin() as session:
            if result is not None:
                session.query(QuantFeatureRowRow).filter_by(
                    feature_snapshot_id=result.feature_snapshot.feature_snapshot_id
                ).delete()
                session.query(QuantFeatureSnapshotRow).filter_by(
                    feature_snapshot_id=result.feature_snapshot.feature_snapshot_id
                ).delete()
            session.query(QuantInputSnapshotRow).filter_by(
                snapshot_id=snapshot.snapshot_id
            ).delete()
        engine.dispose()


@dataclass(frozen=True)
class _ScopeProvider:
    """Fake scope binding provider returning a single frozen scope."""

    scope: ScopeBinding

    def get_scope_binding(self, scope_version_id: str) -> ScopeBinding:
        """Return the frozen scope, asserting the expected version ID."""
        assert scope_version_id == self.scope.scope_version_id
        return self.scope


class _FactWarehouse:
    """Fake fact warehouse returning deterministic canonical fact references."""

    def get_latest_facts(
        self,
        *,
        security_ids: tuple[str, ...],
        indicator_ids: tuple[str, ...],
        known_at: datetime,
    ) -> tuple[CanonicalFactRef, ...]:
        """Return deterministic canonical fact refs for all security-indicator pairs."""
        return tuple(
            CanonicalFactRef(
                fact_id=f"fact-{security_id}-{indicator_id}",
                security_id=security_id,
                indicator_id=indicator_id,
                available_at=known_at,
                payload_hash=f"sha256:{security_id}:{indicator_id}",
            )
            for security_id in security_ids
            for indicator_id in indicator_ids
        )


def _scope() -> ScopeBinding:
    """Build a deterministic scope binding with an ALL_A universe and feature set."""
    universe = UniverseSnapshot(
        universe_code=UniverseCode.ALL_A,
        universe_version_id="univ-v1",
        business_at=DECISION_AT,
        known_at=DECISION_AT,
        security_ids=("000001.SZ", "000002.SZ"),
    )
    return ScopeBinding(
        scope_version_id="scope-v1",
        universe_snapshot=universe,
        quant_feature_set=QuantFeatureSet(
            version_id="qfs-v1",
            required_indicators=("pe_ttm",),
            optional_indicators=("roe_ttm",),
        ),
        user_indicator_view=UserIndicatorView(
            version_id="view-v1",
            visible_indicator_ids=("pe_ttm", "roe_ttm"),
        ),
        corporate_action_adjustment_version="adj-v1",
        industry_snapshot_id="industry-v1",
    )


def _feature_frame(_snapshot) -> pd.DataFrame:
    """Build a deterministic two-row feature DataFrame for ETL tests."""
    return pd.DataFrame.from_records(
        [
            {
                "security_id": "000001.SZ",
                "symbol": "000001.SZ",
                "name": "平安银行",
                "industry_id": "bank",
                "pe_ttm": 8.2,
                "roe_ttm": 0.15,
                "is_st": False,
            },
            {
                "security_id": "000002.SZ",
                "symbol": "000002.SZ",
                "name": "万科A",
                "industry_id": "real_estate",
                "pe_ttm": 12.5,
                "roe_ttm": 0.09,
                "is_st": False,
            },
        ]
    )


def _fact_ref_keys(fact_refs: tuple[dict, ...]) -> tuple[tuple[str, str, str], ...]:
    """Extract and sort fact reference keys for equality comparison."""
    return tuple(
        sorted(
            (
                str(fact["security_id"]),
                str(fact["indicator_id"]),
                str(fact["fact_id"]),
            )
            for fact in fact_refs
        )
    )
