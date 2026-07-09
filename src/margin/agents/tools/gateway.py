"""Audited ToolGateway for v1 WorkerAgent tools."""

from __future__ import annotations

import json
from typing import Any

from margin.agents.tools.audit import InMemoryToolAuditStore
from margin.agents.tools.authz import capability_allows_tool
from margin.agents.tools.catalog import ToolCatalog
from margin.agents.tools.schema_registry import NoopToolSchemaRegistry, ToolSchemaRegistry
from margin.agents.tools.specs import ToolCallRequest, ToolCallResult, ToolCallStatus

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


class InMemoryToolRateLimiter:
    """Simple per-tool call counter used by deterministic tests."""

    def __init__(self, *, limit_per_tool: int) -> None:
        """Initialize a fixed per-tool limit."""
        self._limit_per_tool = limit_per_tool
        self._used_by_tool: dict[str, int] = {}

    def allow(self, tool_name: str) -> bool:
        """Return whether another call is allowed for a tool.

        Args:
            tool_name: Registered tool name.

        Returns:
            ``True`` until the configured per-tool limit is reached.
        """
        used = self._used_by_tool.get(tool_name, 0)
        if used >= self._limit_per_tool:
            return False
        self._used_by_tool[tool_name] = used + 1
        return True


class ToolGateway:
    """ToolGateway.."""

    def __init__(
        self,
        *,
        catalog: ToolCatalog,
        audit_store: InMemoryToolAuditStore,
        schema_registry: ToolSchemaRegistry | None = None,
        rate_limiter: InMemoryToolRateLimiter | None = None,
    ) -> None:
        """Init .

        Args:
            catalog: ToolCatalog: .
            audit_store: InMemoryToolAuditStore: .

        Returns:
            None: .
        """
        self._catalog = catalog
        self._audit_store = audit_store
        self._schema_registry = schema_registry or NoopToolSchemaRegistry()
        self._rate_limiter = rate_limiter
        self._idempotency_cache: dict[str, ToolCallResult] = {}

    def call(self, request: ToolCallRequest) -> ToolCallResult:
        """Call.

        Args:
            request: ToolCallRequest: .

        Returns:
            ToolCallResult: .
        """
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
        if not capability_allows_tool(request.capability_token, registered.spec):
            return self._blocked(
                request,
                input_redacted_json=input_redacted,
                error_code="capability_denied",
            )
        if not self._schema_registry.validate(registered.spec.input_schema_ref, request.input_json):
            return self._blocked(
                request,
                input_redacted_json=input_redacted,
                error_code="input_schema_invalid",
            )
        if self._rate_limiter is not None and not self._rate_limiter.allow(request.tool_name):
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

    def _blocked(
        self,
        request: ToolCallRequest,
        *,
        input_redacted_json: dict[str, Any],
        error_code: str,
        output_redacted_json: dict[str, Any] | None = None,
    ) -> ToolCallResult:
        """Blocked.

        Args:
            request: ToolCallRequest: .
            input_redacted_json: dict[str, Any]: .
            error_code: str: .
            output_redacted_json: dict[str, Any] | None: .

        Returns:
            ToolCallResult: .
        """
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


def _redact(value: Any) -> Any:
    """Redact.

    Args:
        value: Any: .

    Returns:
        Any: .
    """
    if isinstance(value, dict):
        return {
            key: "[redacted]" if key.lower() in _SENSITIVE_KEYS else _redact(item)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [_redact(item) for item in value]
    return value


def _json_size(value: dict[str, Any]) -> int:
    """Json size.

    Args:
        value: dict[str, Any]: .

    Returns:
        int: .
    """
    return len(json.dumps(value, ensure_ascii=False, sort_keys=True).encode("utf-8"))
