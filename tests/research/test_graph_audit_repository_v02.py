"""DB-backed graph LLM/tool audit repository tests."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import delete, select

from margin.research.db_models import (
    AIGraphRunRow,
    LLMCallRecordRow,
    ToolCallRecordRow,
)
from margin.research.execution.llm_service import LLMCallAuditRecord
from margin.research.graph.state import ReviewMode
from margin.research.graph_audit_repository import (
    SQLAlchemyLLMCallAuditRepository,
    SQLAlchemyToolCallAuditRepository,
)
from margin.research.tools.executor import ToolCallAuditRecord
from margin.storage.base import Base
from margin.storage.database import (
    DatabaseSettings,
    create_database_engine,
    create_session_factory,
)

DECISION_AT = datetime(2026, 6, 23, tzinfo=UTC)


def test_llm_audit_repository_is_hash_only_and_idempotent(database_url: str) -> None:
    """LLM audit persists metadata, not prompt/response text."""
    session_factory = _session_factory(database_url)
    graph_run_id = "graph-audit-llm"
    _cleanup(session_factory, graph_run_id)
    _seed_graph_run(session_factory, graph_run_id)
    repository = SQLAlchemyLLMCallAuditRepository(session_factory)
    record = LLMCallAuditRecord(
        call_id="llm-audit-1",
        billing_key="sha256:billing",
        graph_run_id=graph_run_id,
        node_name="delta_decision",
        task_type="draft",
        provider_name="openai_llm",
        model_name="glm",
        model_version="glm-4.5",
        prompt_version="prompt-v0.2.0:draft",
        prompt_hash="sha256:prompt",
        schema_hash="sha256:schema",
        request_hash="sha256:request",
        response_hash="sha256:response",
        latency_ms=12.0,
        input_tokens=10,
        output_tokens=20,
        success=True,
        created_at=DECISION_AT,
    )

    repository.add(record)
    repository.add(record)

    with session_factory() as session:
        rows = session.scalars(
            select(LLMCallRecordRow).where(
                LLMCallRecordRow.graph_run_id == graph_run_id
            )
        ).all()
    assert len(rows) == 1
    assert rows[0].billing_key == "sha256:billing"
    assert rows[0].prompt_hash == "sha256:prompt"
    assert "prompt" not in rows[0].__table__.columns
    assert "response" not in rows[0].__table__.columns
    _cleanup(session_factory, graph_run_id)


def test_tool_audit_repository_is_idempotent(database_url: str) -> None:
    """Scoped tool audit rows are immutable and replay-safe."""
    session_factory = _session_factory(database_url)
    graph_run_id = "graph-audit-tool"
    _cleanup(session_factory, graph_run_id)
    _seed_graph_run(session_factory, graph_run_id)
    repository = SQLAlchemyToolCallAuditRepository(session_factory)
    record = ToolCallAuditRecord(
        call_id="tool-audit-1",
        graph_run_id=graph_run_id,
        node_name="retrieve_evidence",
        tool_name="evidence_retrieve",
        tool_version="evidence-retrieve-v0.2.0",
        capability="evidence_retrieve",
        policy_version="tool-policy-v0.2.0",
        allowed=True,
        success=True,
        request_hash="sha256:request",
        response_hash="sha256:response",
        request_metadata={"keys": ["security_id"]},
        response_metadata={"type": "dict"},
        result_bytes=64,
        latency_ms=1.0,
        created_at=DECISION_AT,
    )

    repository.add(record)
    repository.add(record)

    with session_factory() as session:
        rows = session.scalars(
            select(ToolCallRecordRow).where(
                ToolCallRecordRow.graph_run_id == graph_run_id
            )
        ).all()
    assert len(rows) == 1
    assert rows[0].request_hash == "sha256:request"
    _cleanup(session_factory, graph_run_id)


def _session_factory(database_url: str):
    engine = create_database_engine(DatabaseSettings(url=database_url))
    Base.metadata.create_all(engine)
    return create_session_factory(engine)


def _seed_graph_run(session_factory, graph_run_id: str) -> None:
    with session_factory.begin() as session:
        session.add(
            AIGraphRunRow(
                graph_run_id=graph_run_id,
                graph_version="ai-delta-review-v0.2.0",
                context_snapshot_id=f"context-{graph_run_id}",
                context_input_hash="sha256:context",
                identity_hash="sha256:identity",
                state_hash="sha256:state",
                scope_version_id="scope-1",
                security_id="000001.SZ",
                decision_at=DECISION_AT,
                status="running",
                review_mode=ReviewMode.DELTA_REVIEW.value,
                llm_call_count=0,
                tool_call_count=0,
                retrieval_count=0,
                repair_count=0,
                started_at=DECISION_AT,
                created_at=DECISION_AT,
                updated_at=DECISION_AT,
            )
        )


def _cleanup(session_factory, graph_run_id: str) -> None:
    with session_factory.begin() as session:
        session.execute(
            delete(LLMCallRecordRow).where(
                LLMCallRecordRow.graph_run_id == graph_run_id
            )
        )
        session.execute(
            delete(ToolCallRecordRow).where(
                ToolCallRecordRow.graph_run_id == graph_run_id
            )
        )
        session.execute(
            delete(AIGraphRunRow).where(
                AIGraphRunRow.graph_run_id == graph_run_id
            )
        )
