"""Tests for v1 context routing, capsules, and final audit."""

from __future__ import annotations

from margin.agent_runtime.context_store import make_context_artifact
from margin.agents.context.compressor import DeterministicDomainCompressor
from margin.agents.context.router import ContextRouter
from margin.agents.protocol.models import AgentExecutionStatus, DomainTaskRequest
from margin.agents.runtime.audit import FinalAuditor


def test_context_pack_omits_raw_payload_by_default() -> None:
    artifact = make_context_artifact(
        artifact_id="ctx_raw_doc",
        run_id="ar_1",
        artifact_type="raw_document",
        producer_agent="NewsFetchWorker",
        payload_json={
            "title": "公告",
            "raw_text": "这是一段很长的原始公告正文，不应该直接进入 ContextPack。",
            "api_key": "secret-token",
        },
        source_refs=("source:announcement:1",),
        evidence_refs=("ev_1",),
    )

    pack = ContextRouter().build_context_pack(
        run_id="ar_1",
        requester_agent="MainAgent",
        target_agent="EvidenceRagExpertAgent",
        purpose="evidence planning",
        token_budget=256,
        artifacts=(artifact,),
    )

    serialized = pack.model_dump_json()
    assert "secret-token" not in serialized
    assert "原始公告正文" not in serialized
    assert pack.included_artifact_refs == ("ctx_raw_doc",)
    assert pack.evidence_refs == ("ev_1",)
    assert pack.source_refs == ("source:announcement:1",)


def test_domain_capsule_preserves_refs_from_worker_artifacts() -> None:
    artifact = make_context_artifact(
        artifact_id="ctx_quant",
        run_id="ar_1",
        artifact_type="quant_result",
        producer_agent="QuantScreenWorker",
        payload_json={"top": ["000001.SZ"]},
        source_refs=("analysis_snapshot:as_1",),
        evidence_refs=("ev_quant",),
    )
    domain_task = DomainTaskRequest(
        run_id="ar_1",
        domain_task_id="dt_quant",
        to_domain_agent="QuantExpertAgent",
        domain="quant",
        user_intent_summary="scheduled research",
        task_goal="screen candidates",
        required_output_types=("quant_result",),
        input_context_pack_ref="ctxpack_1",
        capability_token_ref="cap_1",
        token_budget=1024,
        deadline_ms=30_000,
        idempotency_key="dt_quant:1",
    )

    capsule = DeterministicDomainCompressor().compress(
        domain_task=domain_task,
        worker_artifacts=(artifact,),
        token_budget=512,
    )

    assert capsule.artifact_refs == ("ctx_quant",)
    assert capsule.evidence_refs == ("ev_quant",)
    assert capsule.source_refs == ("analysis_snapshot:as_1",)
    assert capsule.status == AgentExecutionStatus.SUCCEEDED


def test_final_auditor_rejects_unapproved_answer_refs() -> None:
    auditor = FinalAuditor()

    report = auditor.audit_answer_refs(
        run_id="ar_1",
        required_domain_task_ids=("dt_quant",),
        completed_domain_task_ids=("dt_quant",),
        approved_artifact_refs=("ctx_quant",),
        approved_capsule_refs=("ctx_capsule_quant",),
        used_artifact_refs=("ctx_quant", "ctx_unapproved"),
        used_capsule_refs=("ctx_capsule_quant",),
        evidence_refs=("ev_1",),
        source_refs=("source:1",),
    )

    assert report.decision == "blocked"
    assert "unapproved artifact refs" in report.blocking_reasons[0]
