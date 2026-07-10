"""Audited ToolGateway for v1 WorkerAgent tools."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from hashlib import sha256
from threading import RLock
from typing import Any, Protocol

from margin.agents.security.capability import CapabilityAuthority
from margin.agents.tools.authz import capability_allows_tool
from margin.agents.tools.catalog import ToolCatalog
from margin.agents.tools.schema_registry import NoopToolSchemaRegistry, ToolSchemaRegistry
from margin.agents.tools.specs import ToolCallRequest, ToolCallResult, ToolCallStatus
from margin.news.models import ensure_utc

_SENSITIVE_KEYS = {
    "access_token",
    "api_key",
    "authorization",
    "client_secret",
    "cookie",
    "password",
    "private_key",
    "provider_token",
    "raw_payload",
    "raw_text",
    "refresh_token",
    "secret",
    "session_cookie",
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

    def get_record(self, audit_ref: str) -> Any | None:
        """Return one immutable audit record by reference."""


class InMemoryToolRateLimiter:
    """Simple per-tool call counter used by deterministic tests."""

    def __init__(self, *, limit_per_tool: int) -> None:
        """Initialize a fixed per-tool limit."""
        self._limit_per_tool = limit_per_tool
        self._used_by_tool: dict[str, int] = {}
        self._lock = RLock()

    def allow(self, tool_name: str) -> bool:
        """Return whether another call is allowed for a tool."""
        with self._lock:
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
        capability_authority: CapabilityAuthority | None = None,
    ) -> None:
        """Initialize the gateway with catalog, audit store, and optional rate limit."""
        self._catalog = catalog
        self._audit_store = audit_store
        self._schema_registry = schema_registry or NoopToolSchemaRegistry()
        self._rate_limiter = rate_limiter
        self._capability_authority = capability_authority
        self._idempotency_cache: dict[str, ToolCallResult] = {}
        self._idempotency_fingerprints: dict[str, str] = {}
        self._idempotency_locks: dict[str, RLock] = {}
        self._tool_call_fingerprints: dict[str, str] = {}
        self._tool_call_results: dict[str, ToolCallResult] = {}
        self._tool_call_locks: dict[str, RLock] = {}
        self._tool_calls_by_token: dict[str, int] = {}
        self._lock = RLock()

    def call(self, request: ToolCallRequest) -> ToolCallResult:
        """Authorize, execute, audit, and optionally replay one tool call."""
        with self._tool_call_lock(request.tool_call_id):
            registered = self._catalog.get(request.tool_name, request.tool_version)
            if registered is None or not registered.spec.idempotent:
                return self._call_once(request)
            with self._idempotency_lock(request.idempotency_key):
                return self._call_once(request)

    def _call_once(self, request: ToolCallRequest) -> ToolCallResult:
        """Execute one call while any per-key idempotency lock is held."""
        fingerprint = _request_fingerprint(request)
        registered = self._catalog.get(request.tool_name, request.tool_version)
        input_redacted = _redact_for_audit(request.input_json)
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
        identity_error = self._capability_identity_error(request)
        if identity_error is not None:
            return self._blocked(
                request,
                input_redacted_json=input_redacted,
                error_code=identity_error,
            )
        if not capability_allows_tool(request.capability_token, registered.spec):
            return self._blocked(
                request,
                input_redacted_json=input_redacted,
                error_code="capability_denied",
            )
        if (
            registered.spec.mutates_state
            and registered.spec.max_output_bytes
            > request.capability_token.max_result_bytes
        ):
            return self._blocked(
                request,
                input_redacted_json=input_redacted,
                error_code="capability_result_limit_too_small",
            )
        with self._lock:
            existing_call_fingerprint = self._tool_call_fingerprints.get(
                request.tool_call_id
            )
            existing_call_result = self._tool_call_results.get(request.tool_call_id)
        if existing_call_fingerprint is not None:
            if existing_call_fingerprint != fingerprint:
                return self._blocked(
                    request,
                    input_redacted_json=input_redacted,
                    error_code="tool_call_id_conflict",
                    audit_tool_call_id=(
                        f"{request.tool_call_id}_conflict_{fingerprint[:12]}"
                    ),
                    remember=False,
                )
            if existing_call_result is not None:
                return existing_call_result
        with self._lock:
            cached = self._idempotency_cache.get(request.idempotency_key)
            cached_fingerprint = self._idempotency_fingerprints.get(
                request.idempotency_key
            )
        if cached is not None:
            if cached_fingerprint != fingerprint:
                return self._blocked(
                    request,
                    input_redacted_json=input_redacted,
                    error_code="idempotency_conflict",
                )
            return cached
        if not self._reserve_tool_call_budget(request):
            return self._blocked(
                request,
                input_redacted_json=input_redacted,
                error_code="max_tool_calls_exceeded",
            )
        if not _matches_inline_schema(
            registered.spec.input_schema,
            request.input_json,
        ) or not self._schema_registry.validate(
            registered.spec.input_schema_ref,
            request.input_json,
        ):
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
        try:
            output = registered.handler(request)
        except Exception as exc:  # noqa: BLE001
            return self._failed(
                request,
                input_redacted_json=input_redacted,
                error_code=f"tool_execution_failed:{type(exc).__name__}",
            )
        output_safe = _redact(output)
        if output_safe.get("ok") is False:
            error = output_safe.get("error")
            error_code = (
                str(error.get("code") or "tool_rejected")
                if isinstance(error, dict)
                else "tool_rejected"
            )
            return self._blocked(
                request,
                input_redacted_json=input_redacted,
                output_redacted_json=_redact_for_audit(output_safe),
                error_code=error_code,
            )
        if not _matches_inline_schema(
            registered.spec.output_schema,
            output_safe,
        ) or not self._schema_registry.validate(
            registered.spec.output_schema_ref,
            output_safe,
        ):
            return self._blocked(
                request,
                input_redacted_json=input_redacted,
                output_redacted_json=_redact_for_audit(output_safe),
                error_code="output_schema_invalid",
            )
        if _json_size(output_safe) > registered.spec.max_output_bytes:
            return self._blocked(
                request,
                input_redacted_json=input_redacted,
                output_redacted_json=None,
                error_code="tool_output_too_large",
            )
        if _json_size(output_safe) > request.capability_token.max_result_bytes:
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
            output_redacted_json=_redact_for_audit(output_safe),
            error_code=None,
        )
        result = ToolCallResult(
            tool_call_id=request.tool_call_id,
            status=ToolCallStatus.SUCCEEDED,
            output_json=output_safe,
            audit_ref=audit.audit_ref,
        )
        self._remember_tool_call(request, result)
        if registered.spec.idempotent:
            with self._lock:
                self._idempotency_cache[request.idempotency_key] = result
                self._idempotency_fingerprints[request.idempotency_key] = fingerprint
        return result

    def _idempotency_lock(self, idempotency_key: str) -> RLock:
        with self._lock:
            return self._idempotency_locks.setdefault(idempotency_key, RLock())

    def _tool_call_lock(self, tool_call_id: str) -> RLock:
        with self._lock:
            return self._tool_call_locks.setdefault(tool_call_id, RLock())

    def _remember_tool_call(
        self,
        request: ToolCallRequest,
        result: ToolCallResult,
    ) -> None:
        with self._lock:
            self._tool_call_fingerprints[request.tool_call_id] = _request_fingerprint(
                request
            )
            self._tool_call_results[request.tool_call_id] = result

    def _capability_identity_error(self, request: ToolCallRequest) -> str | None:
        token = request.capability_token
        if token.run_id != request.run_id:
            return "capability_run_mismatch"
        if token.issued_to != request.caller_agent:
            return "capability_agent_mismatch"
        if token.bound_task_id is not None and token.bound_task_id != request.task_id:
            return "capability_task_mismatch"
        if (
            token.bound_context_pack_id is not None
            and token.bound_context_pack_id != request.context_pack_id
        ):
            return "capability_context_mismatch"
        if (
            token.bound_context_pack_hash is not None
            and token.bound_context_pack_hash != request.context_pack_hash
        ):
            return "capability_context_hash_mismatch"
        if self._capability_authority is None:
            return None
        try:
            issued = self._capability_authority.resolve(
                token.token_id,
                run_id=request.run_id,
                issued_to=request.caller_agent,
                task_id=request.task_id,
                context_pack_id=request.context_pack_id,
                context_pack_hash=request.context_pack_hash,
            )
        except ValueError:
            return "capability_not_issued"
        if issued != token:
            return "capability_payload_mismatch"
        return None

    def _reserve_tool_call_budget(self, request: ToolCallRequest) -> bool:
        """Increment the per-token call counter if under the token limit."""
        token_id = request.capability_token.token_id
        with self._lock:
            used = self._tool_calls_by_token.get(token_id, 0)
            if used >= request.capability_token.max_tool_calls:
                return False
            self._tool_calls_by_token[token_id] = used + 1
            return True

    def _release_tool_call_budget(self, request: ToolCallRequest) -> None:
        """Roll back a reserved call when execution is blocked before the handler."""
        token_id = request.capability_token.token_id
        with self._lock:
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
        audit_tool_call_id: str | None = None,
        remember: bool = True,
    ) -> ToolCallResult:
        """Write a blocked audit record and return a blocked result."""
        audit_request = (
            request
            if audit_tool_call_id is None
            else request.model_copy(update={"tool_call_id": audit_tool_call_id})
        )
        try:
            audit = self._audit_store.write(
                request=audit_request,
                status=ToolCallStatus.BLOCKED,
                input_redacted_json=input_redacted_json,
                output_redacted_json=output_redacted_json,
                error_code=error_code,
            )
        except ValueError:
            variant_hash = sha256(
                f"{error_code}:{_request_fingerprint(request)}".encode()
            ).hexdigest()[:12]
            audit = self._audit_store.write(
                request=request.model_copy(
                    update={
                        "tool_call_id": (
                            f"{request.tool_call_id}_blocked_{variant_hash}"
                        )
                    }
                ),
                status=ToolCallStatus.BLOCKED,
                input_redacted_json=input_redacted_json,
                output_redacted_json=output_redacted_json,
                error_code=error_code,
            )
        result = ToolCallResult(
            tool_call_id=request.tool_call_id,
            status=ToolCallStatus.BLOCKED,
            output_json=output_redacted_json,
            audit_ref=audit.audit_ref,
            error_code=error_code,
            retryable=False,
        )
        if remember:
            self._remember_tool_call(request, result)
        return result

    def _failed(
        self,
        request: ToolCallRequest,
        *,
        input_redacted_json: dict[str, Any],
        error_code: str,
    ) -> ToolCallResult:
        audit = self._audit_store.write(
            request=request,
            status=ToolCallStatus.FAILED,
            input_redacted_json=input_redacted_json,
            output_redacted_json=None,
            error_code=error_code,
        )
        result = ToolCallResult(
            tool_call_id=request.tool_call_id,
            status=ToolCallStatus.FAILED,
            audit_ref=audit.audit_ref,
            error_code=error_code,
            retryable=True,
        )
        self._remember_tool_call(request, result)
        return result


def _token_expired(request: ToolCallRequest) -> bool:
    """Return whether the capability token is past its expiry."""
    expires_at = ensure_utc(request.capability_token.expires_at)
    return expires_at <= datetime.now(UTC)


def _redact(value: Any) -> Any:
    """Recursively redact sensitive keys from tool payloads."""
    if isinstance(value, dict):
        return {
            key: "[redacted]" if _is_sensitive_key(key) else _redact(item)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [_redact(item) for item in value]
    return value


def _redact_for_audit(value: Any) -> Any:
    if isinstance(value, list):
        return [_redact_for_audit(item) for item in value]
    redacted = _redact(value)
    if not isinstance(redacted, dict):
        return redacted
    return {
        key: _audit_value_summary(item)
        if key.lower() in {"content", "stdout", "stderr", "unified"}
        else _redact_for_audit(item)
        for key, item in redacted.items()
    }


def _is_sensitive_key(key: object) -> bool:
    normalized = str(key).strip().casefold().replace("-", "_")
    if normalized in _SENSITIVE_KEYS:
        return True
    return normalized.endswith(("_access_token", "_refresh_token", "_client_secret"))


def _audit_value_summary(value: Any) -> dict[str, Any]:
    encoded = json.dumps(value, ensure_ascii=False, default=str).encode("utf-8")
    return {
        "redacted": True,
        "sha256": sha256(encoded).hexdigest(),
        "size_bytes": len(encoded),
    }


def _json_size(value: dict[str, Any]) -> int:
    """Return UTF-8 byte size of a JSON-serializable mapping."""
    return len(json.dumps(value, ensure_ascii=False, sort_keys=True).encode("utf-8"))


def _request_fingerprint(request: ToolCallRequest) -> str:
    payload = {
        "run_id": request.run_id,
        "task_id": request.task_id,
        "caller_agent": request.caller_agent,
        "tool_name": request.tool_name,
        "tool_version": request.tool_version,
        "input_json": request.input_json,
        "capability_token_ref": request.capability_token.token_id,
        "context_pack_id": request.context_pack_id,
        "context_pack_hash": request.context_pack_hash,
        "idempotency_key": request.idempotency_key,
    }
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str).encode()
    return sha256(encoded).hexdigest()


def _matches_inline_schema(schema: dict[str, Any], value: Any) -> bool:
    if not schema:
        return True
    enum_values = schema.get("enum")
    if isinstance(enum_values, list | tuple) and value not in enum_values:
        return False
    expected_type = schema.get("type")
    if expected_type == "object":
        if not isinstance(value, dict):
            return False
        required = schema.get("required", ())
        if isinstance(required, list | tuple) and any(key not in value for key in required):
            return False
        properties = schema.get("properties", {})
        if isinstance(properties, dict):
            if schema.get("additionalProperties") is False and any(
                key not in properties for key in value
            ):
                return False
            return all(
                key not in value
                or not isinstance(child_schema, dict)
                or _matches_inline_schema(child_schema, value[key])
                for key, child_schema in properties.items()
            )
        return True
    if expected_type == "array":
        if not isinstance(value, list):
            return False
        if isinstance(schema.get("minItems"), int) and len(value) < schema["minItems"]:
            return False
        if isinstance(schema.get("maxItems"), int) and len(value) > schema["maxItems"]:
            return False
        item_schema = schema.get("items")
        return not isinstance(item_schema, dict) or all(
            _matches_inline_schema(item_schema, item) for item in value
        )
    if expected_type == "string":
        if not isinstance(value, str):
            return False
        if isinstance(schema.get("minLength"), int) and len(value) < schema["minLength"]:
            return False
        return not (
            isinstance(schema.get("maxLength"), int) and len(value) > schema["maxLength"]
        )
    if expected_type == "integer":
        if not isinstance(value, int) or isinstance(value, bool):
            return False
        return _number_in_schema_bounds(schema, value)
    if expected_type == "number":
        if not isinstance(value, int | float) or isinstance(value, bool):
            return False
        return _number_in_schema_bounds(schema, value)
    if expected_type == "boolean":
        return isinstance(value, bool)
    return True


def _number_in_schema_bounds(schema: dict[str, Any], value: int | float) -> bool:
    minimum = schema.get("minimum")
    maximum = schema.get("maximum")
    if isinstance(minimum, int | float) and value < minimum:
        return False
    return not (isinstance(maximum, int | float) and value > maximum)
