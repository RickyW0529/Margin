"""Tests for unified ContextPack persistence (no dual-write of packs)."""

from __future__ import annotations

from margin.agent_runtime.context_store import MemoryAgentContextStore, make_context_artifact
from margin.agents.context.persistence import ContextPersistence
from margin.agents.context.repository import MemoryContextRepository
from margin.agents.protocol.models import ContextFact, ContextPack


def test_persist_context_pack_writes_repo_not_runtime_artifact() -> None:
    """Structured packs are stored once in ContextRepository only."""
    store = MemoryAgentContextStore()
    repo = MemoryContextRepository()
    persistence = ContextPersistence(context_store=store, context_repository=repo)

    readiness = make_context_artifact(
        artifact_id="ready_1",
        run_id="run_1",
        artifact_type="data_readiness",
        producer_agent="DataReadinessBuilder",
        payload_json={"status": "ok"},
    )
    pack = ContextPack(
        context_pack_id="ctxpack_1",
        run_id="run_1",
        requester_agent="MainAgent",
        target_agent="MainAgent",
        purpose="user_qna_planning",
        token_budget=1000,
        facts=(
            ContextFact(
                fact_id="f1",
                statement="hello",
                confidence=1.0,
                fact_type="user_constraint",
            ),
        ),
        compression_policy_version="test",
        included_chat_summary_ref="chat_summary:abc",
    )

    persistence.persist_context_pack(pack, readiness_artifact=readiness)

    assert repo.get_context_pack("ctxpack_1") is not None
    assert store.get_artifact("ready_1") is not None
    # Pack payload must not be dual-written into the runtime artifact table.
    assert store.get_artifact("ctxpack_1") is None
    # Readers can still reconstruct the pack as an artifact view.
    reconstructed = persistence.get_runtime_artifact("ctxpack_1")
    assert reconstructed is not None
    assert reconstructed.artifact_type == "context_pack"
    assert reconstructed.payload_json["context_pack_id"] == "ctxpack_1"
    edges = repo.list_lineage_edges("run_1")
    assert {edge.to_ref for edge in edges} >= {"ready_1", "chat_summary:abc"}
