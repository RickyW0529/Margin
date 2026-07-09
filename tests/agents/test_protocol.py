"""Tests for v1 three-layer Agent protocol and capability rules."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError

from margin.agents.protocol.models import (
    AgentExecutionStatus,
    ContextPack,
    DomainTaskResult,
    WorkerTaskResult,
)
from margin.agents.security.capability import CapabilityToken, derive_capability_token
from margin.agents.security.policies import (
    DataAccessPolicy,
    ProductionWritePolicy,
    ToolPolicy,
)


def test_capability_token_can_only_be_narrowed() -> None:
    """Test capability_token_can_only_be_narrowed.

    Returns:
        None: .
    """
    parent = _token(
        data_access=(
            DataAccessPolicy.READ_CHAT_SUMMARY,
            DataAccessPolicy.READ_DASHBOARD,
            DataAccessPolicy.READ_EVIDENCE,
        ),
        production_write=(ProductionWritePolicy.WRITE_CONTEXT_ONLY,),
        tool_policy=(ToolPolicy.READ_ONLY_TOOLS, ToolPolicy.RETRIEVAL_TOOLS),
        can_delegate=True,
        delegation_depth_remaining=1,
    )

    child = derive_capability_token(
        parent,
        token_id="cap_child",
        issued_to="RetrieverWorker",
        data_access=(DataAccessPolicy.READ_EVIDENCE,),
        production_write=(ProductionWritePolicy.WRITE_CONTEXT_ONLY,),
        tool_policy=(ToolPolicy.RETRIEVAL_TOOLS,),
    )

    assert child.issued_by == parent.issued_to
    assert child.data_access == (DataAccessPolicy.READ_EVIDENCE,)
    assert child.can_delegate is False
    assert child.delegation_depth_remaining == 0

    with pytest.raises(ValueError, match="expand data_access"):
        derive_capability_token(
            parent,
            token_id="cap_bad",
            issued_to="ProviderSyncWorker",
            data_access=(DataAccessPolicy.READ_ANALYSIS_MART,),
            production_write=(ProductionWritePolicy.WRITE_CONTEXT_ONLY,),
            tool_policy=(ToolPolicy.RETRIEVAL_TOOLS,),
        )


def test_worker_success_result_requires_artifact_refs() -> None:
    """Test worker_success_result_requires_artifact_refs.

    Returns:
        None: .
    """
    with pytest.raises(ValidationError, match="output_artifact_refs"):
        WorkerTaskResult(
            run_id="ar_1",
            domain_task_id="dt_1",
            worker_task_id="wt_1",
            worker_agent="RetrieverWorker",
            skill_id="retrieve_evidence",
            status=AgentExecutionStatus.SUCCEEDED,
            output_artifact_refs=(),
            safe_summary="done",
        )


def test_domain_result_requires_capsule_and_audit_refs() -> None:
    """Test domain_result_requires_capsule_and_audit_refs.

    Returns:
        None: .
    """
    result = DomainTaskResult(
        run_id="ar_1",
        domain_task_id="dt_quant",
        domain_agent="QuantExpertAgent",
        domain="quant",
        status=AgentExecutionStatus.SUCCEEDED,
        produced_artifact_refs=("ctx_quant",),
        domain_context_capsule_ref="ctx_capsule_quant",
        domain_audit_report_ref="ctx_audit_quant",
        safe_user_summary="quant domain completed",
    )

    assert result.domain_context_capsule_ref == "ctx_capsule_quant"
    assert result.domain_audit_report_ref == "ctx_audit_quant"


def test_context_pack_requires_token_budget() -> None:
    """Test context_pack_requires_token_budget.

    Returns:
        None: .
    """
    with pytest.raises(ValidationError, match="token_budget"):
        ContextPack(
            context_pack_id="ctxpack_1",
            run_id="ar_1",
            requester_agent="MainAgent",
            target_agent="DataExpertAgent",
            purpose="planning",
            facts=(),
            compression_policy_version="context-pack-v1",
        )


def _token(
    *,
    data_access: tuple[DataAccessPolicy, ...],
    production_write: tuple[ProductionWritePolicy, ...],
    tool_policy: tuple[ToolPolicy, ...],
    can_delegate: bool,
    delegation_depth_remaining: int,
) -> CapabilityToken:
    """Helper token.

    Args:
        data_access: tuple[DataAccessPolicy, ...]: .
        production_write: tuple[ProductionWritePolicy, ...]: .
        tool_policy: tuple[ToolPolicy, ...]: .
        can_delegate: bool: .
        delegation_depth_remaining: int: .

    Returns:
        CapabilityToken: .
    """
    return CapabilityToken(
        token_id="cap_parent",
        run_id="ar_1",
        issued_by="MainAgent",
        issued_to="EvidenceRagExpertAgent",
        domain="evidence",
        data_access=data_access,
        production_write=production_write,
        tool_policy=tool_policy,
        allowed_artifact_types=("evidence_package", "citation_validation_report"),
        allowed_tool_names=("retrieve_evidence",),
        expires_at=datetime.now(UTC) + timedelta(minutes=10),
        max_tool_calls=8,
        max_result_bytes=100_000,
        can_delegate=can_delegate,
        delegation_depth_remaining=delegation_depth_remaining,
    )
