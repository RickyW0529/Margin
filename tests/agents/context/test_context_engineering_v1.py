"""test_context_engineering_v1 module."""

from __future__ import annotations

from datetime import UTC, datetime

from margin.agent_runtime.context_store import stable_json_hash
from margin.agent_runtime.models import ContextArtifact
from margin.agents.context.capsule_builder import DomainContextCapsuleBuilder
from margin.agents.context.pack_builder import ContextPackBuilder
from margin.agents.context.validators import (
    NoRawPayloadValidator,
    SecretRedactionValidator,
)
from margin.agents.protocol.models import DomainTaskRequest
from margin.agents.security.capability import CapabilityToken
from margin.agents.security.policies import (
    DataAccessPolicy,
    ProductionWritePolicy,
    ToolPolicy,
)


def _artifact(
    artifact_id: str,
    artifact_type: str,
    payload: dict,
    *,
    evidence_refs: tuple[str, ...] = (),
    source_refs: tuple[str, ...] = (),
) -> ContextArtifact:
    """Helper artifact.

    Args:
        artifact_id: str: .
        artifact_type: str: .
        payload: dict: .
        evidence_refs: tuple[str, ...]: .
        source_refs: tuple[str, ...]: .

    Returns:
        ContextArtifact: .
    """
    return ContextArtifact(
        artifact_id=artifact_id,
        run_id="run_ctx",
        artifact_type=artifact_type,
        producer_agent="QuantAgent",
        payload_json=payload,
        payload_hash=stable_json_hash(payload),
        evidence_refs=evidence_refs,
        source_refs=source_refs,
        created_at=datetime(2026, 7, 8, tzinfo=UTC),
    )


def _token() -> CapabilityToken:
    """_token implementation.

    Returns:
        CapabilityToken: .
    """
    return CapabilityToken(
        token_id="cap_ctx",
        run_id="run_ctx",
        issued_by="MainAgent",
        issued_to="DataExpertAgent",
        domain="data",
        data_access=(DataAccessPolicy.READ_ANALYSIS_MART, DataAccessPolicy.READ_EVIDENCE),
        production_write=(ProductionWritePolicy.WRITE_CONTEXT_ONLY,),
        tool_policy=(ToolPolicy.READ_ONLY_TOOLS,),
        allowed_artifact_types=("quant_result", "evidence_package", "stock_analysis_result"),
        allowed_tool_names=("context.safe_read_artifact",),
        expires_at=datetime(2026, 7, 9, tzinfo=UTC),
        max_tool_calls=2,
        max_result_bytes=4096,
    )


def test_context_pack_builder_excludes_raw_payload_and_secret_keys() -> None:
    """test_context_pack_builder_excludes_raw_payload_and_secret_keys implementation.

    Returns:
        None: .
    """
    artifact = _artifact(
        "artifact_raw",
        "quant_result",
        {
            "summary": "top ranked candidates",
            "raw_text": "raw provider response must not enter prompt",
            "provider_token": "secret-token",
        },
    )

    pack = ContextPackBuilder().build(
        run_id="run_ctx",
        requester_agent="MainAgent",
        target_agent="QuantExpertAgent",
        purpose="domain_task",
        user_goal="summarize quant result",
        capability_token=_token(),
        artifacts=(artifact,),
        token_budget=800,
    )

    assert "raw provider response" not in pack.model_dump_json()
    assert "secret-token" not in pack.model_dump_json()
    assert {omission.reason for omission in pack.omissions} == {"unsafe"}
    assert NoRawPayloadValidator().validate(pack).valid
    assert SecretRedactionValidator().validate(pack).valid


def test_chat_memory_is_user_constraint_not_market_fact() -> None:
    """test_chat_memory_is_user_constraint_not_market_fact implementation.

    Returns:
        None: .
    """
    pack = ContextPackBuilder().build(
        run_id="run_ctx",
        requester_agent="MainAgent",
        target_agent="GeneralQnaExpertAgent",
        purpose="main_planning",
        user_goal="继续刚才的问题",
        capability_token=_token(),
        chat_memory_summary="用户说自己觉得某股票会涨。",
        token_budget=800,
    )

    assert len(pack.facts) == 1
    assert pack.facts[0].fact_type == "user_constraint"
    assert pack.facts[0].evidence_refs == ()


def test_quant_result_extractor_creates_quant_fact_with_refs() -> None:
    """test_quant_result_extractor_creates_quant_fact_with_refs implementation.

    Returns:
        None: .
    """
    artifact = _artifact(
        "artifact_quant",
        "quant_result",
        {"ts_code": "300502.SZ", "rank": 1, "composite_score": 91.2},
        evidence_refs=("ev_quant",),
        source_refs=("mart.quant_candidate_mart:run_ctx",),
    )

    pack = ContextPackBuilder().build(
        run_id="run_ctx",
        requester_agent="MainAgent",
        target_agent="QuantExpertAgent",
        purpose="domain_task",
        user_goal="解释量化结果",
        capability_token=_token(),
        artifacts=(artifact,),
        token_budget=800,
    )

    assert pack.facts[0].fact_type == "quant_signal"
    assert "300502.SZ" in pack.facts[0].statement
    assert pack.facts[0].evidence_refs == ("ev_quant",)
    assert pack.source_refs == ("mart.quant_candidate_mart:run_ctx",)


def test_context_pack_records_token_budget_omissions() -> None:
    """test_context_pack_records_token_budget_omissions implementation.

    Returns:
        None: .
    """
    artifacts = tuple(
        _artifact(
            f"artifact_{index}",
            "stock_analysis_result",
            {"summary": "long summary " * 20, "ts_code": f"00000{index}.SZ"},
        )
        for index in range(5)
    )

    pack = ContextPackBuilder().build(
        run_id="run_ctx",
        requester_agent="MainAgent",
        target_agent="StockResearchExpertAgent",
        purpose="domain_task",
        user_goal="压缩研究结论",
        capability_token=_token(),
        artifacts=artifacts,
        token_budget=10,
    )

    assert any(omission.reason == "token_budget" for omission in pack.omissions)
    assert len(pack.facts) < len(artifacts)


def test_domain_capsule_builder_preserves_evidence_gaps_and_conflicts() -> None:
    """test_domain_capsule_builder_preserves_evidence_gaps_and_conflicts implementation.

    Returns:
        None: .
    """
    domain_task = DomainTaskRequest(
        run_id="run_ctx",
        domain_task_id="dt_stock",
        to_domain_agent="StockResearchExpertAgent",
        domain="stock_research",
        user_intent_summary="研究股票",
        task_goal="融合基本面和情绪",
        required_output_types=("stock_analysis_result",),
        input_context_pack_ref="ctx_pack",
        capability_token_ref="cap_ctx",
        token_budget=1000,
        deadline_ms=1000,
        idempotency_key="idem",
    )
    artifact = _artifact(
        "artifact_stock",
        "stock_analysis_result",
        {
            "summary": "证据显示需求旺盛，但估值较高。",
            "gaps": ["缺少最新调研纪要"],
            "conflicts": [{"summary": "收入增长和现金流走弱同时存在"}],
        },
        evidence_refs=("ev_stock",),
        source_refs=("doc:annual_report:2025",),
    )

    capsule = DomainContextCapsuleBuilder().build(
        domain_task=domain_task,
        artifacts=(artifact,),
        token_budget=1000,
    )

    assert capsule.evidence_refs == ("ev_stock",)
    assert capsule.open_questions == ("缺少最新调研纪要",)
    assert capsule.conflicting_facts == ({"summary": "收入增长和现金流走弱同时存在"},)
