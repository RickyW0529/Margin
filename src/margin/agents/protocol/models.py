"""Typed protocol models for L1/L2/L3 Agent communication."""

from __future__ import annotations

from datetime import UTC, date, datetime
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from margin.core.hashing import stable_json_hash

PROTOCOL_VERSION = "margin-a2a-v1"


class AgentExecutionStatus(StrEnum):
    """Common execution status for the v1 Agent protocol.."""

    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    PARTIAL = "partial"
    BLOCKED = "blocked"
    FAILED = "failed"


class ContextFact(BaseModel):
    """One bounded fact carried through a ContextPack or capsule.."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    fact_id: str
    statement: str
    confidence: float = Field(ge=0.0, le=1.0)
    fact_type: Literal[
        "backtest_metric",
        "citation_status",
        "data_freshness",
        "user_constraint",
        "data_status",
        "factor_score",
        "financial_metric",
        "quant_signal",
        "quant_candidate",
        "evidence_claim",
        "market_metric",
        "platform_status",
        "risk_flag",
        "valuation_metric",
        "metric",
        "open_question",
        "decision",
    ]
    subject_type: Literal[
        "stock",
        "company",
        "industry",
        "run",
        "dataset",
        "tool",
        "user",
        "unknown",
    ] = "unknown"
    subject_id: str = ""
    value_json: dict[str, Any] | None = None
    as_of_date: date | None = None
    valid_from: datetime | None = None
    valid_to: datetime | None = None
    available_at: datetime | None = None
    artifact_refs: tuple[str, ...] = ()
    evidence_refs: tuple[str, ...] = ()
    source_refs: tuple[str, ...] = ()
    source_locators: tuple[str, ...] = ()
    freshness_status: Literal["fresh", "stale", "unknown"] = "unknown"
    pii_or_secret_risk: bool = False
    valid_at: datetime | None = None


class ContextOmission(BaseModel):
    """A context item deliberately omitted from a bounded pack.."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    omitted_ref: str
    reason: Literal[
        "token_budget",
        "low_relevance",
        "duplicate",
        "unsafe",
        "stale",
        "not_authorized",
        "permission_denied",
        "unsafe_key",
        "raw_payload_forbidden",
        "invalid_lineage",
    ]
    summary: str = ""


class ContextPack(BaseModel):
    """Bounded context envelope passed between Agent layers.."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    context_pack_id: str
    run_id: str
    requester_agent: str
    target_agent: str
    purpose: str
    token_budget: int = Field(ge=1)
    included_artifact_refs: tuple[str, ...] = ()
    included_capsule_refs: tuple[str, ...] = ()
    included_chat_summary_ref: str | None = None
    facts: tuple[ContextFact, ...]
    evidence_refs: tuple[str, ...] = ()
    source_refs: tuple[str, ...] = ()
    omissions: tuple[ContextOmission, ...] = ()
    compression_policy_version: str
    payload_hash: str = ""

    @model_validator(mode="before")
    @classmethod
    def fill_hash(cls, data: object) -> object:
        """Fill a stable hash when the caller did not provide one.

        Args:
            data: object: .

        Returns:
            object: .
        """
        if isinstance(data, dict) and not data.get("payload_hash"):
            payload = dict(data)
            payload.pop("payload_hash", None)
            data["payload_hash"] = stable_json_hash(payload)
        return data


class DomainTaskRequest(BaseModel):
    """L1 to L2 task envelope.."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    protocol_version: str = PROTOCOL_VERSION
    run_id: str
    domain_task_id: str
    from_agent: Literal["MainAgent"] = "MainAgent"
    to_domain_agent: str
    domain: str
    user_intent_summary: str
    task_goal: str
    required_output_types: tuple[str, ...]
    input_context_pack_ref: str
    input_artifact_refs: tuple[str, ...] = ()
    capability_token_ref: str
    constraints: dict[str, Any] = Field(default_factory=dict)
    token_budget: int = Field(ge=1)
    deadline_ms: int = Field(ge=1)
    idempotency_key: str


class WorkerTaskRequest(BaseModel):
    """L2 to L3 task envelope.."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    protocol_version: str = PROTOCOL_VERSION
    run_id: str
    domain_task_id: str
    worker_task_id: str
    parent_agent: str
    worker_agent: str
    skill_id: str
    task_goal: str
    input_context_pack_ref: str
    input_artifact_refs: tuple[str, ...] = ()
    required_output_types: tuple[str, ...]
    constraints: dict[str, Any] = Field(default_factory=dict)
    tool_policy_ref: str
    capability_token_ref: str
    token_budget: int = Field(ge=1)
    max_tool_calls: int = Field(ge=0)
    deadline_ms: int = Field(ge=1)
    idempotency_key: str


class WorkerTaskResult(BaseModel):
    """L3 to L2 task result envelope.."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    protocol_version: str = PROTOCOL_VERSION
    run_id: str
    domain_task_id: str
    worker_task_id: str
    worker_agent: str
    skill_id: str
    status: AgentExecutionStatus
    output_artifact_refs: tuple[str, ...] = ()
    audit_event_refs: tuple[str, ...] = ()
    guardrail_decision_refs: tuple[str, ...] = ()
    error_code: str | None = None
    retryable: bool = False
    safe_summary: str

    @model_validator(mode="after")
    def require_artifacts_for_success(self) -> WorkerTaskResult:
        """Require successful workers to return artifact references.

        Returns:
            WorkerTaskResult: .
        """
        if self.status is AgentExecutionStatus.SUCCEEDED and not self.output_artifact_refs:
            raise ValueError("output_artifact_refs are required for succeeded workers")
        return self


class RetrySuggestion(BaseModel):
    """One structured retry suggestion from a domain audit.."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    target_agent: str
    skill_id: str
    reason: str


class DomainTaskResult(BaseModel):
    """L2 to L1 task result envelope.."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    protocol_version: str = PROTOCOL_VERSION
    run_id: str
    domain_task_id: str
    domain_agent: str
    domain: str
    status: AgentExecutionStatus
    produced_artifact_refs: tuple[str, ...] = ()
    domain_context_capsule_ref: str
    domain_audit_report_ref: str
    missing_requirements: tuple[str, ...] = ()
    retry_suggestions: tuple[RetrySuggestion, ...] = ()
    safe_user_summary: str


class RiskFlag(BaseModel):
    """One risk flag carried by a domain capsule.."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    risk_id: str
    severity: Literal["low", "medium", "high", "critical"]
    statement: str
    artifact_refs: tuple[str, ...] = ()
    evidence_refs: tuple[str, ...] = ()
    source_refs: tuple[str, ...] = ()


class DomainContextCapsule(BaseModel):
    """Structured, auditable domain summary.."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    capsule_id: str
    run_id: str
    domain: str
    purpose: str
    status: AgentExecutionStatus
    summary: str
    key_facts: tuple[ContextFact, ...] = ()
    risk_flags: tuple[RiskFlag, ...] = ()
    evidence_refs: tuple[str, ...] = ()
    source_refs: tuple[str, ...] = ()
    artifact_refs: tuple[str, ...] = ()
    open_questions: tuple[str, ...] = ()
    conflicting_facts: tuple[dict[str, Any], ...] = ()
    recommended_next_steps: tuple[str, ...] = ()
    compression_policy_version: str
    input_hash: str
    payload_hash: str = ""

    @model_validator(mode="before")
    @classmethod
    def fill_hash(cls, data: object) -> object:
        """Fill a stable hash when absent.

        Args:
            data: object: .

        Returns:
            object: .
        """
        if isinstance(data, dict) and not data.get("payload_hash"):
            payload = dict(data)
            payload.pop("payload_hash", None)
            data["payload_hash"] = stable_json_hash(payload)
        return data


class DomainAuditReport(BaseModel):
    """L2 domain audit report.."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    audit_report_id: str
    run_id: str
    domain_task_id: str
    domain: str
    status: AgentExecutionStatus
    checked_artifact_refs: tuple[str, ...] = ()
    schema_valid: bool
    evidence_valid: bool
    source_refs_valid: bool
    context_budget_ok: bool
    guardrail_summary: tuple[str, ...] = ()
    missing_requirements: tuple[str, ...] = ()
    retry_suggestions: tuple[RetrySuggestion, ...] = ()
    safe_summary: str
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class FinalAuditReport(BaseModel):
    """Final L1 audit report.."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    audit_report_id: str
    run_id: str
    decision: Literal["complete", "blocked", "partial", "repair_required"]
    summary: str
    blocking_reasons: tuple[str, ...] = ()
    missing_artifacts: tuple[str, ...] = ()
    domain_to_retry: str | None = None
    final_answer_allowed: bool
    final_user_message_constraints: tuple[str, ...] = ()
    checked_artifact_refs: tuple[str, ...] = ()
    checked_capsule_refs: tuple[str, ...] = ()
    evidence_refs: tuple[str, ...] = ()
    source_refs: tuple[str, ...] = ()
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class FinalUserAnswerArtifact(BaseModel):
    """User-visible answer artifact based only on approved context.."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    artifact_id: str
    run_id: str
    answer_text: str
    language: Literal["zh", "en"]
    used_domain_capsule_refs: tuple[str, ...] = ()
    used_artifact_refs: tuple[str, ...] = ()
    evidence_refs: tuple[str, ...] = ()
    source_refs: tuple[str, ...] = ()
    disclaimers: tuple[str, ...] = ()
    limitations: tuple[str, ...] = ()
    final_audit_report_ref: str
    payload_hash: str = ""

    @model_validator(mode="before")
    @classmethod
    def fill_hash(cls, data: object) -> object:
        """Fill a stable hash when absent.

        Args:
            data: object: .

        Returns:
            object: .
        """
        if isinstance(data, dict) and not data.get("payload_hash"):
            payload = dict(data)
            payload.pop("payload_hash", None)
            data["payload_hash"] = stable_json_hash(payload)
        return data
