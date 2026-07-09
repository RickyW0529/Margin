"""Persistence tests for v1 Context Engineering tables."""

from __future__ import annotations

from datetime import UTC, datetime

from margin.agents.context.db_models import (
    ArtifactLineageEdgeRow,
    ContextFactRow,
    ContextOmissionRow,
    ContextPackRow,
    DomainContextCapsuleRow,
)
from margin.agents.context.repository import SQLAlchemyContextRepository
from margin.agents.protocol.models import (
    AgentExecutionStatus,
    ContextFact,
    ContextOmission,
    ContextPack,
    DomainContextCapsule,
)
from margin.storage.base import Base
from margin.storage.database import (
    DatabaseSettings,
    create_database_engine,
    create_session_factory,
)


def test_sqlalchemy_context_repository_round_trips_pack_facts_and_omissions(
    database_url: str,
) -> None:
    """ContextPack persistence keeps facts and omissions queryable by pack id."""
    repository = _repository(database_url)
    pack = ContextPack(
        context_pack_id="ctxpack_repo_1",
        run_id="run_repo_1",
        requester_agent="MainAgent",
        target_agent="QuantExpertAgent",
        purpose="domain_task",
        token_budget=8000,
        facts=(
            ContextFact(
                fact_id="fact_quant_1",
                fact_type="quant_candidate",
                subject_type="stock",
                subject_id="300502.SZ",
                statement="300502.SZ is ranked first in the quant snapshot.",
                value_json={"rank": 1, "score": 91.2},
                confidence=0.91,
                artifact_refs=("artifact_quant_1",),
                evidence_refs=("ev_quant_1",),
                source_refs=("mart.quant_feature_rows:ctxpack_repo_1",),
                source_locators=("row:300502.SZ",),
                freshness_status="fresh",
                available_at=datetime(2026, 7, 8, tzinfo=UTC),
            ),
        ),
        evidence_refs=("ev_quant_1",),
        source_refs=("mart.quant_feature_rows:ctxpack_repo_1",),
        omissions=(
            ContextOmission(
                omitted_ref="artifact_raw_1",
                reason="raw_payload_forbidden",
                summary="Raw provider payload is never loaded into prompt context.",
            ),
        ),
        compression_policy_version="context-pack-v1",
    )

    repository.save_context_pack(pack)
    repository.save_context_pack(pack)

    stored = repository.get_context_pack("ctxpack_repo_1")
    assert stored == pack
    assert repository.list_context_facts("ctxpack_repo_1") == list(pack.facts)
    assert repository.list_context_omissions("ctxpack_repo_1") == list(pack.omissions)


def test_context_fact_and_omission_models_declare_pack_foreign_keys() -> None:
    """ORM metadata must preserve flush ordering required by production DDL."""
    assert ContextFactRow.__table__.c.context_pack_id.foreign_keys
    assert ContextOmissionRow.__table__.c.context_pack_id.foreign_keys


def test_sqlalchemy_context_repository_round_trips_domain_capsule_and_lineage(
    database_url: str,
) -> None:
    """Domain capsule and artifact lineage edges are durable and idempotent."""
    repository = _repository(database_url)
    capsule = DomainContextCapsule(
        capsule_id="dcc_repo_1",
        run_id="run_repo_2",
        domain="quant",
        purpose="user_qna",
        status=AgentExecutionStatus.SUCCEEDED,
        summary="量化上下文已压缩。",
        artifact_refs=("artifact_quant_1",),
        evidence_refs=("ev_quant_1",),
        source_refs=("ctxpack_repo_2",),
        compression_policy_version="domain-capsule-v1",
        input_hash="sha256:input",
    )

    repository.save_domain_capsule(
        capsule,
        domain_task_id="dt_quant",
        expert_agent="QuantExpertAgent",
        output_artifact_refs=("artifact_quant_1",),
        audit_report_ref="da_quant",
        token_estimate=512,
    )
    repository.record_lineage_edge(
        run_id="run_repo_2",
        from_ref="dcc_repo_1",
        to_ref="ctxpack_repo_2",
        edge_type="source_ref",
    )
    repository.record_lineage_edge(
        run_id="run_repo_2",
        from_ref="dcc_repo_1",
        to_ref="ctxpack_repo_2",
        edge_type="source_ref",
    )

    assert repository.get_domain_capsule("dcc_repo_1") == capsule
    edges = repository.list_lineage_edges("run_repo_2")
    assert len(edges) == 1
    assert edges[0].from_ref == "dcc_repo_1"
    assert edges[0].to_ref == "ctxpack_repo_2"
    assert edges[0].edge_type == "source_ref"


def _repository(database_url: str) -> SQLAlchemyContextRepository:
    """Create a repository against the integration test database."""
    engine = create_database_engine(DatabaseSettings(url=database_url))
    with engine.begin() as connection:
        connection.exec_driver_sql("CREATE SCHEMA IF NOT EXISTS agent")
    Base.metadata.drop_all(engine, tables=_context_tables(), checkfirst=True)
    Base.metadata.create_all(engine)
    return SQLAlchemyContextRepository(create_session_factory(engine))


def _context_tables() -> list:
    """Return context tables in dependency-safe drop order."""
    return [
        ArtifactLineageEdgeRow.__table__,
        DomainContextCapsuleRow.__table__,
        ContextOmissionRow.__table__,
        ContextFactRow.__table__,
        ContextPackRow.__table__,
    ]
