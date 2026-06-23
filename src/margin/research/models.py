"""Domain models for the multi-agent research module."""

from __future__ import annotations

import uuid
from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, Field, field_validator

from margin.news.models import ensure_utc, utc_now


class SignalType(StrEnum):
    """Classification of research signal output."""

    RESEARCH_CANDIDATE = "research_candidate"
    WATCH = "watch"
    ABSTAINED = "abstained"


class WorkflowState(StrEnum):
    """Lifecycle states of a research workflow run."""

    INITIALIZED = "initialized"
    DATA_READY = "data_ready"
    EVIDENCE_READY = "evidence_ready"
    ANALYSIS_READY = "analysis_ready"
    REVIEW_READY = "review_ready"
    PUBLISHED = "published"
    ABORTED = "aborted"
    ABSTAINED = "abstained"


class AgentTrace(BaseModel):
    """Single agent invocation trace."""

    trace_id: str
    agent_node: str
    model_version: str
    input_hash: str
    output_hash: str
    latency_ms: float | None = None
    error: str | None = None
    tool_call_ids: tuple[str, ...] = ()
    timestamp: datetime = Field(default_factory=utc_now)

    model_config = {"frozen": True}

    @field_validator("timestamp")
    @classmethod
    def normalize_timestamp(cls, value: datetime) -> datetime:
        """Ensure the timestamp is UTC."""
        return ensure_utc(value)


class ResearchSignal(BaseModel):
    """Structured research signal emitted by the workflow."""

    signal_id: str = Field(default_factory=lambda: f"sig_{uuid.uuid4().hex[:12]}")
    symbol: str
    signal_type: SignalType
    confidence: float = 0.0
    statement: str = ""
    evidence_refs: tuple[str, ...] = ()
    claim_ids: tuple[str, ...] = ()
    risk_score: float | None = None
    counter_arguments: tuple[str, ...] = ()
    generated_at: datetime = Field(default_factory=utc_now)

    model_config = {"frozen": True}

    @field_validator("generated_at")
    @classmethod
    def normalize_generated_at(cls, value: datetime) -> datetime:
        """Ensure the generated timestamp is UTC."""
        return ensure_utc(value)

    @field_validator("confidence")
    @classmethod
    def validate_confidence(cls, value: float) -> float:
        """Validate that confidence is within [0, 1].

        Args:
            value: Confidence value to validate.

        Returns:
            The validated confidence value.

        Raises:
            ValueError: If confidence is outside [0, 1].
        """
        if not 0.0 <= value <= 1.0:
            raise ValueError(f"confidence must be in [0, 1], got {value}")
        return value


class VersionRef(BaseModel):
    """Immutable component version captured in a research snapshot."""

    name: str
    version: str

    model_config = {"frozen": True}


class ResearchSnapshot(BaseModel):
    """Immutable audit snapshot of a research run."""

    snapshot_id: str = Field(default_factory=lambda: f"snap_{uuid.uuid4().hex[:12]}")
    run_id: str
    workflow_state: WorkflowState
    decision_at: datetime = Field(default_factory=utc_now)
    symbols: tuple[str, ...] = ()
    strategy_version: str = ""
    prompt_version: str = ""
    tool_versions: tuple[VersionRef, ...] = ()
    model_versions: tuple[VersionRef, ...] = ()
    evidence_ids: tuple[str, ...] = ()
    claim_ids: tuple[str, ...] = ()
    signals: tuple[ResearchSignal, ...] = ()
    input_hash: str = ""
    output_hash: str = ""
    traces: tuple[AgentTrace, ...] = ()
    tool_call_ids: tuple[str, ...] = ()
    agent_outputs_json: str = "{}"
    tool_calls_json: str = "[]"
    error: str | None = None
    created_at: datetime = Field(default_factory=utc_now)

    model_config = {"frozen": True}

    @field_validator("decision_at", "created_at")
    @classmethod
    def normalize_created_at(cls, value: datetime) -> datetime:
        """Ensure decision and created timestamps are UTC."""
        return ensure_utc(value)
