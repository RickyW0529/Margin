"""Tests for the v0.4 Shared Context Store."""

from __future__ import annotations

import pytest

from margin.agent_runtime.context_store import (
    MemoryAgentContextStore,
    SQLAlchemyAgentContextStore,
    make_context_artifact,
    stable_json_hash,
)
from margin.agent_runtime.db_models import (
    AgentRuntimeArtifactRow,
    AgentRuntimeGuardrailDecisionRow,
    AgentRuntimeRunRow,
    AgentRuntimeStepRow,
)
from margin.agent_runtime.models import (
    AgentExecutionStatus,
    AgentPermissionMode,
    AgentRun,
    AgentRunType,
    AgentStep,
    GuardrailDecision,
    GuardrailStage,
)
from margin.storage.base import Base
from margin.storage.database import (
    DatabaseSettings,
    create_database_engine,
    create_session_factory,
)


def _run(run_id: str = "ar_test") -> AgentRun:
    return AgentRun(
        run_id=run_id,
        run_type=AgentRunType.SCHEDULED_STOCK_ANALYSIS,
        status=AgentExecutionStatus.RUNNING,
        permission_mode=AgentPermissionMode.WRITE_ALLOWED,
        trigger_source="scheduled",
        user_intent_summary="daily stock analysis",
    )


def test_memory_context_store_hashes_and_filters_artifacts() -> None:
    store = MemoryAgentContextStore()
    run = _run()
    store.add_run(run)
    artifact = make_context_artifact(
        artifact_id="ctx_quant",
        run_id=run.run_id,
        artifact_type="quant_result",
        producer_agent="QuantAgent",
        payload_json={"passed": ["000001.SZ"], "near_threshold": []},
        source_refs=("analysis_snapshot:as_1",),
        evidence_refs=("ev_1",),
    )

    store.add_artifact(artifact)

    assert artifact.payload_hash == stable_json_hash(artifact.payload_json)
    assert store.get_run(run.run_id) == run
    assert store.get_artifact("ctx_quant") == artifact
    assert store.list_artifacts(run.run_id, artifact_type="quant_result") == [artifact]
    assert store.list_artifacts(run.run_id, artifact_type="news_context_bundle") == []


def test_memory_context_store_rejects_artifact_mutation() -> None:
    store = MemoryAgentContextStore()
    artifact = make_context_artifact(
        artifact_id="ctx_immutable",
        run_id="ar_test",
        artifact_type="explanation",
        producer_agent="StockAnalystAgent",
        payload_json={"summary": "first"},
    )
    store.add_artifact(artifact)
    changed = make_context_artifact(
        artifact_id=artifact.artifact_id,
        run_id=artifact.run_id,
        artifact_type=artifact.artifact_type,
        producer_agent=artifact.producer_agent,
        payload_json={"summary": "changed"},
    )

    with pytest.raises(ValueError, match="immutable"):
        store.add_artifact(changed)


def test_postgres_context_store_round_trips_runtime_records(database_url: str) -> None:
    engine = create_database_engine(DatabaseSettings(url=database_url))
    Base.metadata.create_all(engine)
    session_factory = create_session_factory(engine)
    with session_factory.begin() as session:
        for row in (
            AgentRuntimeGuardrailDecisionRow,
            AgentRuntimeArtifactRow,
            AgentRuntimeStepRow,
            AgentRuntimeRunRow,
        ):
            session.query(row).delete()

    store = SQLAlchemyAgentContextStore(session_factory)
    run = _run("ar_pg")
    step = AgentStep(
        step_id="quant_analysis",
        run_id=run.run_id,
        expert_agent_name="QuantAgent",
        skill_id="run_ml_lifecycle_quant_analysis",
        status=AgentExecutionStatus.SUCCEEDED,
        input_artifact_refs=("ctx_data",),
        output_artifact_refs=("ctx_quant",),
    )
    artifact = make_context_artifact(
        artifact_id="ctx_pg_quant",
        run_id=run.run_id,
        artifact_type="quant_result",
        producer_agent="QuantAgent",
        payload_json={"snapshot_id": "as_pg"},
    )
    decision = GuardrailDecision(
        decision_id="gd_pg",
        run_id=run.run_id,
        stage=GuardrailStage.OUTPUT,
        allowed=True,
        evaluation_summary="quant output passed policy checks",
    )

    try:
        store.add_run(run)
        store.add_step(step)
        store.add_artifact(artifact)
        store.add_guardrail_decision(decision)
        fresh = SQLAlchemyAgentContextStore(session_factory)

        assert fresh.get_run(run.run_id) == run
        assert fresh.list_steps(run.run_id) == [step]
        assert fresh.get_artifact(artifact.artifact_id) == artifact
        assert fresh.list_artifacts(run.run_id) == [artifact]
        assert fresh.list_guardrail_decisions(run.run_id) == [decision]
    finally:
        with session_factory.begin() as session:
            for row in (
                AgentRuntimeGuardrailDecisionRow,
                AgentRuntimeArtifactRow,
                AgentRuntimeStepRow,
                AgentRuntimeRunRow,
            ):
                session.query(row).delete()
        engine.dispose()
