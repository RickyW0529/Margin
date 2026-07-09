"""Audited ToolGateway for v1 WorkerAgent tools."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any, Protocol

from margin.agents.tools.authz import capability_allows_tool
from margin.agents.tools.catalog import ToolCatalog
from margin.agents.tools.schema_registry import NoopToolSchemaRegistry, ToolSchemaRegistry
from margin.agents.tools.specs import ToolCallRequest, ToolCallResult, ToolCallStatus
from margin.news.models import ensure_utc

_SENSITIVE_KEYS = {
    "api_key",
    "authorization",
    "password",
    "provider_token",
    "raw_payload",
    "raw_text",
    "secret",
    "system_prompt",
    "token",
}


class ToolAuditStore(Protocol):
    """Minimal protocol satisfied by in-memory and SQL audit stores."""

    def write(
        self,
        *,
        request: ToolCallRequest,
        status: ToolCallStatus,
        input_redacted_json: dict[str, Any],
        output_redacted_json: dict[str, Any] | None,
        error_code: str | None,
    ) -> Any:
        """Persist one audit record."""


class InMemoryToolRateLimiter:
    """Simple per-tool call counter used by deterministic tests."""

    def __init__(self, *, limit_per_tool: int) -> None:
        """Initialize a fixed per-tool limit."""
        self._limit_per_tool = limit_per_tool
        self._used_by_tool: dict[str, int] = {}

    def allow(self, tool_name: str) -> bool:
        """Return whether another call is allowed for a tool."""
        used = self._used_by_tool.get(tool_name, 0)
        if used >= self._limit_per_tool:
            return False
        self._used_by_tool[tool_name] = used + 1
        return True


class ToolGateway:
    """Policy-enforcing gateway for WorkerAgent tool calls."""

    def __init__(
        self,
        *,
        catalog: ToolCatalog,
        audit_store: ToolAuditStore,
        schema_registry: ToolSchemaRegistry | None = None,
        rate_limiter: InMemoryToolRateLimiter | None = None,
    ) -> None:
        """Initialize the gateway with catalog, audit store, and optional rate limit."""
        self._catalog = catalog
        self._audit_store = audit_store
        self._schema_registry = schema_registry or NoopToolSchemaRegistry()
        self._rate_limiter = rate_limiter
        self._idempotency_cache: dict[str, ToolCallResult] = {}
        self._tool_calls_by_token: dict[str, int] = {}

    def call(self, request: ToolCallRequest) -> ToolCallResult:
        """Authorize, execute, audit, and optionally replay one tool call."""
        cached = self._idempotency_cache.get(request.idempotency_key)
        if cached is not None:
            return cached
        registered = self._catalog.get(request.tool_name, request.tool_version)
        input_redacted = _redact(request.input_json)
        if registered is None:
            return self._blocked(
                request,
                input_redacted_json=input_redacted,
                error_code="tool_not_registered",
            )
        if registered.spec.returns_raw_payload:
            return self._blocked(
                request,
                input_redacted_json=input_redacted,
                error_code="raw_payload_tool_forbidden",
            )
        if _token_expired(request):
            return self._blocked(
                request,
                input_redacted_json=input_redacted,
                error_code="capability_expired",
            )
        if not capability_allows_tool(request.capability_token, registered.spec):
            return self._blocked(
                request,
                input_redacted_json=input_redacted,
                error_code="capability_denied",
            )
        if not self._reserve_tool_call_budget(request):
            return self._blocked(
                request,
                input_redacted_json=input_redacted,
                error_code="max_tool_calls_exceeded",
            )
        if not self._schema_registry.validate(registered.spec.input_schema_ref, request.input_json):
            self._release_tool_call_budget(request)
            return self._blocked(
                request,
                input_redacted_json=input_redacted,
                error_code="input_schema_invalid",
            )
        if self._rate_limiter is not None and not self._rate_limiter.allow(request.tool_name):
            self._release_tool_call_budget(request)
            return self._blocked(
                request,
                input_redacted_json=input_redacted,
                error_code="rate_limited",
            )
        output = registered.handler(request)
        output_redacted = _redact(output)
        if not self._schema_registry.validate(registered.spec.output_schema_ref, output_redacted):
            return self._blocked(
                request,
                input_redacted_json=input_redacted,
                output_redacted_json=output_redacted,
                error_code="output_schema_invalid",
            )
        if _json_size(output_redacted) > registered.spec.max_output_bytes:
            return self._blocked(
                request,
                input_redacted_json=input_redacted,
                output_redacted_json=None,
                error_code="tool_output_too_large",
            )
        if _json_size(output_redacted) > request.capability_token.max_result_bytes:
            return self._blocked(
                request,
                input_redacted_json=input_redacted,
                output_redacted_json=None,
                error_code="capability_result_too_large",
            )
        audit = self._audit_store.write(
            request=request,
            status=ToolCallStatus.SUCCEEDED,
            input_redacted_json=input_redacted,
            output_redacted_json=output_redacted,
            error_code=None,
        )
        result = ToolCallResult(
            tool_call_id=request.tool_call_id,
            status=ToolCallStatus.SUCCEEDED,
            output_json=output_redacted,
            audit_ref=audit.audit_ref,
        )
        if registered.spec.idempotent:
            self._idempotency_cache[request.idempotency_key] = result
        return result

    def _reserve_tool_call_budget(self, request: ToolCallRequest) -> bool:
        """Increment the per-token call counter if under the token limit."""
        token_id = request.capability_token.token_id
        used = self._tool_calls_by_token.get(token_id, 0)
        if used >= request.capability_token.max_tool_calls:
            return False
        self._tool_calls_by_token[token_id] = used + 1
        return True

    def _release_tool_call_budget(self, request: ToolCallRequest) -> None:
        """Roll back a reserved call when execution is blocked before the handler."""
        token_id = request.capability_token.token_id
        used = self._tool_calls_by_token.get(token_id, 0)
        if used <= 1:
            self._tool_calls_by_token.pop(token_id, None)
        else:
            self._tool_calls_by_token[token_id] = used - 1

    def _blocked(
        self,
        request: ToolCallRequest,
        *,
        input_redacted_json: dict[str, Any],
        error_code: str,
        output_redacted_json: dict[str, Any] | None = None,
    ) -> ToolCallResult:
        """Write a blocked audit record and return a blocked result."""
        audit = self._audit_store.write(
            request=request,
            status=ToolCallStatus.BLOCKED,
            input_redacted_json=input_redacted_json,
            output_redacted_json=output_redacted_json,
            error_code=error_code,
        )
        return ToolCallResult(
            tool_call_id=request.tool_call_id,
            status=ToolCallStatus.BLOCKED,
            output_json=output_redacted_json,
            audit_ref=audit.audit_ref,
            error_code=error_code,
            retryable=False,
        )


def _token_expired(request: ToolCallRequest) -> bool:
    """Return whether the capability token is past its expiry."""
    expires_at = ensure_utc(request.capability_token.expires_at)
    return expires_at <= datetime.now(UTC)


def _redact(value: Any) -> Any:
    """Recursively redact sensitive keys from tool payloads."""
    if isinstance(value, dict):
        return {
            key: "[redacted]" if key.lower() in _SENSITIVE_KEYS else _redact(item)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [_redact(item) for item in value]
    return value


def _json_size(value: dict[str, Any]) -> int:
    """Return UTF-8 byte size of a JSON-serializable mapping."""
    return len(json.dumps(value, ensure_ascii=False, sort_keys=True).encode("utf-8"))
