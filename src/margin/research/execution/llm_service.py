"""Structured LLM service adapter for graph node execution."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from typing import Any, Protocol

from pydantic import BaseModel, Field

from margin.news.models import utc_now
from margin.research.llm import (
    LLMProvider,
    ModelRouter,
    StructuredOutputGuardrail,
    TaskType,
)
from margin.research.prompts.models import RenderedPrompt


class StructuredLLMResponse(BaseModel):
    """Sanitized structured completion returned to node code."""

    call_id: str
    output: dict[str, Any]
    model: str
    success: bool
    latency_ms: float
    task_type: str
    input_tokens: int = 0
    output_tokens: int = 0
    error_code: str | None = None

    model_config = {"frozen": True}


class LLMCallAuditRecord(BaseModel):
    """Hash-only audit metadata for a structured LLM call."""

    call_id: str
    billing_key: str
    graph_run_id: str
    node_name: str
    task_type: str
    model: str = ""
    provider_name: str | None = None
    model_name: str | None = None
    model_version: str | None = None
    prompt_version: str = ""
    prompt_hash: str
    schema_hash: str
    request_hash: str = ""
    response_hash: str | None = None
    latency_ms: float
    input_tokens: int
    output_tokens: int
    total_tokens: int = 0
    cost_usd: float = 0.0
    success: bool
    error_code: str | None = None
    request_metadata: dict[str, Any] = Field(default_factory=dict)
    response_metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime

    model_config = {"frozen": True}


class LLMCallAuditRepository(Protocol):
    """Persistence boundary for LLM call metadata."""

    def add(self, record: LLMCallAuditRecord) -> None:
        """Persist one immutable call audit.

        Args:
            record: Hash-only audit record to persist.
        """


class MemoryLLMCallAuditRepository:
    """Append-only in-memory LLM call audit repository."""

    def __init__(self) -> None:
        """Initialize the instance."""
        self._records: dict[str, LLMCallAuditRecord] = {}

    def add(self, record: LLMCallAuditRecord) -> None:
        """Persist one immutable LLM call audit record.

        Args:
            record: Hash-only audit record to persist.

        Raises:
            ValueError: If a conflicting record with the same call ID exists.
        """
        current = self._records.get(record.call_id)
        if current is not None and current != record:
            raise ValueError(f"LLM call audit '{record.call_id}' is immutable")
        self._records[record.call_id] = record

    @property
    def records(self) -> tuple[LLMCallAuditRecord, ...]:
        """Return call audits in insertion order."""
        return tuple(self._records.values())


class LLMService:
    """Call existing providers/routers and validate structured output."""

    def __init__(
        self,
        provider: LLMProvider | ModelRouter,
        *,
        audit_repository: LLMCallAuditRepository | None = None,
    ) -> None:
        """Initialize the LLM service.

        Args:
            provider: LLM provider or model router for completions.
            audit_repository: Optional audit repository for call metadata.
        """
        self._provider = provider
        self._audit = audit_repository or MemoryLLMCallAuditRepository()

    def complete_structured(
        self,
        *,
        prompt: RenderedPrompt,
        output_schema: dict[str, Any],
        task_type: str,
        node_name: str,
        graph_run_id: str,
        deadline: datetime | None = None,
    ) -> StructuredLLMResponse:
        """Complete and validate one structured graph-node request.

        Args:
            prompt: Rendered prompt to send to the LLM.
            output_schema: JSON schema used to validate the response.
            task_type: Node task type for routing and audit.
            node_name: Name of the calling graph node.
            graph_run_id: Identifier of the parent graph run.
            deadline: Optional deadline; returns a failure if already exceeded.

        Returns:
            A ``StructuredLLMResponse`` with validated output or error details.
        """
        prompt_hash = prompt.prompt_hash
        schema_hash = _hash_json(output_schema)
        request_hash = _hash_json(
            {
                "graph_run_id": graph_run_id,
                "node_name": node_name,
                "task_type": task_type,
                "prompt_hash": prompt_hash,
                "schema_hash": schema_hash,
            }
        )
        call_id = "llm_" + request_hash.removeprefix("sha256:")[:24]
        if deadline is not None and datetime.now(UTC) >= deadline.astimezone(UTC):
            response = StructuredLLMResponse(
                call_id=call_id,
                output={},
                model="none",
                success=False,
                latency_ms=0.0,
                task_type=task_type,
                error_code="deadline_exceeded",
            )
            self._record(
                response,
                graph_run_id=graph_run_id,
                node_name=node_name,
                prompt_hash=prompt_hash,
                schema_hash=schema_hash,
                request_hash=request_hash,
                prompt_version=prompt.prompt_version,
            )
            return response
        rendered = prompt.render()
        if isinstance(self._provider, ModelRouter):
            routed_task = _task_type(task_type)
            result = self._provider.complete(
                routed_task,
                rendered,
                response_schema=output_schema,
                trace_id=graph_run_id,
            )
        else:
            result = self._provider.complete(
                rendered,
                response_schema=output_schema,
            )
        if not result.success:
            response = StructuredLLMResponse(
                call_id=call_id,
                output={},
                model=result.model,
                success=False,
                latency_ms=result.latency_ms,
                task_type=task_type,
                error_code="llm_call_failed",
            )
            self._record(
                response,
                graph_run_id=graph_run_id,
                node_name=node_name,
                prompt_hash=prompt_hash,
                schema_hash=schema_hash,
                request_hash=request_hash,
                prompt_version=prompt.prompt_version,
            )
            return response
        valid, _ = StructuredOutputGuardrail(output_schema).validate(result.output)
        response = StructuredLLMResponse(
            call_id=call_id,
            output=result.output if valid else {},
            model=result.model,
            success=valid,
            latency_ms=result.latency_ms,
            task_type=task_type,
            error_code=None if valid else "structured_output_invalid",
        )
        self._record(
            response,
            graph_run_id=graph_run_id,
            node_name=node_name,
            prompt_hash=prompt_hash,
            schema_hash=schema_hash,
            request_hash=request_hash,
            prompt_version=prompt.prompt_version,
        )
        return response

    def _record(
        self,
        response: StructuredLLMResponse,
        *,
        graph_run_id: str,
        node_name: str,
        prompt_hash: str,
        schema_hash: str,
        request_hash: str,
        prompt_version: str,
    ) -> None:
        """Record one LLM call audit entry with hash-only metadata."""
        billing_key = request_hash
        provider_name, model_name, model_version = _provider_identity(
            self._provider,
            response.model,
        )
        self._audit.add(
            LLMCallAuditRecord(
                call_id=response.call_id,
                billing_key=billing_key,
                graph_run_id=graph_run_id,
                node_name=node_name,
                task_type=response.task_type,
                model=response.model,
                provider_name=provider_name,
                model_name=model_name,
                model_version=model_version,
                prompt_version=prompt_version,
                prompt_hash=prompt_hash,
                schema_hash=schema_hash,
                request_hash=request_hash,
                response_hash=(
                    _hash_json(response.output)
                    if response.output
                    else None
                ),
                latency_ms=response.latency_ms,
                input_tokens=response.input_tokens,
                output_tokens=response.output_tokens,
                total_tokens=response.input_tokens + response.output_tokens,
                success=response.success,
                error_code=response.error_code,
                request_metadata={
                    "graph_run_id": graph_run_id,
                    "node_name": node_name,
                    "task_type": response.task_type,
                },
                response_metadata={"model": response.model},
                created_at=utc_now(),
            )
        )


def _task_type(value: str) -> TaskType:
    """Map a node task type string to a ModelRouter TaskType."""
    mapping = {
        "draft": TaskType.EVIDENCE,
        "reflection": TaskType.REFLECT,
        "revision": TaskType.REFLECT,
    }
    return mapping.get(value, TaskType.EVIDENCE)


def _provider_identity(
    provider: LLMProvider | ModelRouter,
    fallback_model: str,
) -> tuple[str, str, str]:
    """Return safe provider/model labels for audit rows."""
    descriptor = getattr(provider, "descriptor", None)
    if descriptor is not None:
        name = str(getattr(descriptor, "name", "unknown"))
        version = str(getattr(descriptor, "version", fallback_model or "unknown"))
        return name, version, version
    return "model_router", fallback_model or "unknown", fallback_model or "unknown"


def _hash_json(value: Any) -> str:
    """Return a deterministic SHA-256 hash for a JSON-serializable value."""
    encoded = json.dumps(
        value,
        sort_keys=True,
        default=str,
        separators=(",", ":"),
    ).encode("utf-8")
    return "sha256:" + hashlib.sha256(encoded).hexdigest()
