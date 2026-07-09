"""API tests for v1 Context Store read boundaries."""

from __future__ import annotations

import json

from fastapi.testclient import TestClient

from margin.agent_runtime.context_store import (
    MemoryAgentContextStore,
    make_context_artifact,
)
from margin.agents.context.repository import MemoryContextRepository
from margin.agents.protocol.models import ContextOmission, ContextPack
from margin.api.main import create_app


def test_safe_artifact_api_redacts_payload_and_preserves_lineage() -> None:
    """Safe artifact reads redact raw/sensitive fields without hiding lineage."""
    context_store = MemoryAgentContextStore()
    artifact = make_context_artifact(
        artifact_id="artifact_safe_1",
        run_id="run_context_1",
        artifact_type="analysis_table",
        producer_agent="QuantExpertAgent",
        payload_json={
            "summary": "可展示摘要",
            "raw_text": "不应返回给前端的原文",
            "nested": {"provider_token": "secret-token"},
        },
        source_refs=("mart.analysis_snapshot:snap_1",),
        evidence_refs=("ev_1",),
    )
    context_store.add_artifact(artifact)
    client = TestClient(create_app(agent_context_store=context_store))

    response = client.get("/api/v1/artifacts/artifact_safe_1/safe")

    assert response.status_code == 200
    body = response.json()
    assert body["artifact_id"] == "artifact_safe_1"
    assert body["payload_json"]["summary"] == "可展示摘要"
    assert body["payload_json"]["raw_text"] == "[redacted]"
    assert body["payload_json"]["nested"]["provider_token"] == "[redacted]"
    assert body["payload_hash"] == artifact.payload_hash
    assert body["source_refs"] == ["mart.analysis_snapshot:snap_1"]
    assert body["evidence_refs"] == ["ev_1"]


def test_context_pack_api_only_returns_context_pack_artifacts() -> None:
    """ContextPack endpoint reads the structured ContextRepository, not artifact payloads."""
    context_repository = MemoryContextRepository()
    context_repository.save_context_pack(
        ContextPack(
            context_pack_id="ctxpack_run_1",
            run_id="run_context_1",
            requester_agent="MainAgent",
            target_agent="QuantExpertAgent",
            purpose="domain_task",
            token_budget=8000,
            facts=(),
            source_refs=("artifact_safe_1",),
            omissions=(
                ContextOmission(
                    omitted_ref="artifact_raw_1",
                    reason="raw_payload_forbidden",
                    summary="raw payload removed",
                ),
            ),
            compression_policy_version="context-pack-v1",
        )
    )
    client = TestClient(create_app(agent_context_repository=context_repository))

    response = client.get("/api/v1/context-packs/ctxpack_run_1")
    wrong_type_response = client.get("/api/v1/context-packs/artifact_not_pack")

    assert response.status_code == 200
    body = response.json()
    assert body["context_pack_id"] == "ctxpack_run_1"
    assert body["pack_json"]["target_agent"] == "QuantExpertAgent"
    assert body["pack_hash"].startswith("sha256:")
    assert body["omissions"][0]["reason"] == "raw_payload_forbidden"
    assert wrong_type_response.status_code == 404
    assert wrong_type_response.json()["detail"]["code"] == "context_pack_not_found"


def test_run_context_graph_exposes_refs_without_raw_payloads() -> None:
    """Run context graph exposes artifact lineage without returning artifact payloads."""
    context_store = MemoryAgentContextStore()
    context_repository = MemoryContextRepository()
    context_store.add_artifact(
        make_context_artifact(
            artifact_id="ctxpack_run_1",
            run_id="run_context_1",
            artifact_type="context_pack",
            producer_agent="MainAgent",
            payload_json={"raw_text": "raw context must not leak"},
            source_refs=("mart.analysis_snapshot:snap_1",),
        )
    )
    context_store.add_artifact(
        make_context_artifact(
            artifact_id="capsule_quant_1",
            run_id="run_context_1",
            artifact_type="domain_context_capsule",
            producer_agent="QuantExpertAgent",
            payload_json={"summary": "量化 capsule", "provider_token": "hidden"},
            source_refs=("ctxpack_run_1",),
            evidence_refs=("ev_quant_1",),
        )
    )
    context_repository.record_lineage_edge(
        run_id="run_context_1",
        from_ref="ctxpack_run_1",
        to_ref="mart.analysis_snapshot:snap_1",
        edge_type="source_ref",
    )
    context_repository.record_lineage_edge(
        run_id="run_context_1",
        from_ref="capsule_quant_1",
        to_ref="ctxpack_run_1",
        edge_type="source_ref",
    )
    context_repository.record_lineage_edge(
        run_id="run_context_1",
        from_ref="capsule_quant_1",
        to_ref="ev_quant_1",
        edge_type="evidence_ref",
    )
    client = TestClient(
        create_app(
            agent_context_store=context_store,
            agent_context_repository=context_repository,
        )
    )

    response = client.get("/api/v1/runs/run_context_1/context-graph")

    assert response.status_code == 200
    body = response.json()
    serialized = json.dumps(body, ensure_ascii=False)
    assert "raw context must not leak" not in serialized
    assert "hidden" not in serialized
    assert {node["ref"] for node in body["nodes"]} >= {
        "ctxpack_run_1",
        "capsule_quant_1",
        "mart.analysis_snapshot:snap_1",
        "ev_quant_1",
    }
    assert {
        (edge["from_ref"], edge["to_ref"], edge["edge_type"])
        for edge in body["edges"]
    } >= {
        ("ctxpack_run_1", "mart.analysis_snapshot:snap_1", "source_ref"),
        ("capsule_quant_1", "ctxpack_run_1", "source_ref"),
        ("capsule_quant_1", "ev_quant_1", "evidence_ref"),
    }
