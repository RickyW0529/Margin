"""Immutable audit logging for every Provider call.

Each call records a parameter summary and the result status. Audit records are
append-only and must not be modified after writing.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from pathlib import Path
from typing import Any, ClassVar

from pydantic import BaseModel, Field

from margin.core.provider import CallResult


class SecretRedactingProcessor:
    """Recursively redact sensitive fields and known secret values.

    The callable signature is compatible with structlog processors, while the
    implementation is also reusable for audit payloads and structured errors.
    """

    sensitive_fragments: ClassVar[tuple[str, ...]] = (
        "token",
        "api_key",
        "authorization",
        "password",
        "secret",
        "cookie",
    )

    def __init__(self, secret_values: tuple[str, ...] = ()) -> None:
        """Initialize the redactor with known secret values to scrub.

        Args:
            secret_values: Tuple of plaintext secret values to redact from
                strings. Values are sorted longest-first for greedy matching.
        """
        self._secret_values = tuple(
            sorted(
                {value for value in secret_values if value},
                key=len,
                reverse=True,
            )
        )

    def __call__(
        self,
        logger: object,
        method_name: str,
        event_dict: dict[str, Any],
    ) -> dict[str, Any]:
        """Redact sensitive fields and known secret values from an event dict.

        Args:
            logger: Logger instance (unused, required by structlog protocol).
            method_name: Method name (unused, required by structlog protocol).
            event_dict: Event dictionary to redact in place.

        Returns:
            A new dictionary with sensitive fields and secret values redacted.
        """
        del logger, method_name
        return self._redact_mapping(event_dict)

    def _redact_mapping(self, value: dict[Any, Any]) -> dict[str, Any]:
        """redact mapping."""
        redacted: dict[str, Any] = {}
        for raw_key, raw_value in value.items():
            key = str(raw_key)
            normalized = key.lower().replace("-", "_")
            if any(fragment in normalized for fragment in self.sensitive_fragments):
                redacted[key] = "[REDACTED]"
            else:
                redacted[key] = self._redact_value(raw_value)
        return redacted

    def _redact_value(self, value: Any) -> Any:
        """redact value."""
        if isinstance(value, dict):
            return self._redact_mapping(value)
        if isinstance(value, list):
            return [self._redact_value(item) for item in value]
        if isinstance(value, tuple):
            return tuple(self._redact_value(item) for item in value)
        if isinstance(value, BaseException):
            return self._redact_string(f"{type(value).__name__}: {value}")
        if isinstance(value, str):
            return self._redact_string(value)
        return value

    def _redact_string(self, value: str) -> str:
        """redact string."""
        redacted = value
        for secret in self._secret_values:
            redacted = redacted.replace(secret, "[REDACTED]")
        return redacted


class AuditRecord(BaseModel):
    """A single immutable audit record describing a Provider call.

    Attributes:
        provider_name: Name of the Provider that was called.
        provider_version: Version of the Provider.
        method: Method name that was invoked.
        params_summary: Sanitized summary of call parameters.
        success: Whether the call succeeded.
        error: Error message when the call failed.
        fetched_at: Timestamp when the call was attempted.
        available_at: Timestamp when the data becomes available, if known.
        response_hash: SHA-256 hash of the response payload.
        cost: Estimated monetary or quota cost of the call.
        latency_ms: Round-trip latency in milliseconds.
        attempt_count: Number of attempts made before the final result.
        from_fallback: Whether the result came from a fallback Provider.
        trace_id: Optional trace identifier.
    """

    provider_name: str
    provider_version: str
    method: str
    params_summary: dict[str, Any]
    success: bool
    error: str | None = None
    fetched_at: datetime
    available_at: datetime | None = None
    response_hash: str | None = None
    cost: float = 0.0
    latency_ms: float | None = None
    attempt_count: int = 1
    from_fallback: bool = False
    trace_id: str = Field(default_factory=lambda: "")

    model_config = {"frozen": True}


def compute_hash(data: Any) -> str:
    """Compute a deterministic SHA256 hash for arbitrary data.

    Args:
        data: Any JSON-serializable value. ``None`` is handled explicitly.

    Returns:
        A string of the form ``sha256:<hex_digest>`` or ``sha256:none``.
    """
    if data is None:
        return "sha256:none"
    serialized = json.dumps(data, sort_keys=True, default=str, ensure_ascii=False)
    return "sha256:" + hashlib.sha256(serialized.encode("utf-8")).hexdigest()


class AuditLogger:
    """Append-only audit log writer.

    The MVP implementation writes JSON Lines to a local file. Future iterations
    will migrate to an immutable PostgreSQL audit table.

    Attributes:
        _log_path: Path to the JSONL audit log file.
    """

    def __init__(self, log_path: Path | None = None) -> None:
        """Initialize the audit logger.

        Args:
            log_path: Path to the JSONL log file. Defaults to
                ``.margin/audit/provider_calls.jsonl``.
        """
        self._log_path = log_path or Path(".margin") / "audit" / "provider_calls.jsonl"
        self._log_path.parent.mkdir(parents=True, exist_ok=True)

    def log_call(
        self,
        provider_name: str,
        provider_version: str,
        method: str,
        params: dict[str, Any],
        result: CallResult,
        trace_id: str = "",
    ) -> AuditRecord:
        """Log a single Provider call and return the immutable record.

        Args:
            provider_name: Name of the Provider that was called.
            provider_version: Version of the Provider.
            method: Method name that was invoked.
            params: Original call parameters; sensitive values are redacted.
            result: Call result containing status, timing, and cost metadata.
            trace_id: Optional trace identifier for observability.

        Returns:
            The immutable ``AuditRecord`` that was appended to the log.
        """
        params_summary = _summarize_params(params)

        record = AuditRecord(
            provider_name=provider_name,
            provider_version=provider_version,
            method=method,
            params_summary=params_summary,
            success=result.success,
            error=result.error,
            fetched_at=result.fetched_at,
            available_at=result.available_at,
            response_hash=result.response_hash,
            cost=result.cost,
            latency_ms=result.latency_ms,
            attempt_count=result.attempt_count,
            from_fallback=result.from_fallback,
            trace_id=trace_id,
        )

        self._append(record)
        return record

    def _append(self, record: AuditRecord) -> None:
        """Append a JSON-encoded record to the log file.

        Args:
            record: The audit record to append.
        """
        line = record.model_dump_json() + "\n"
        with open(self._log_path, "a", encoding="utf-8") as f:
            f.write(line)

    def read_all(self) -> list[AuditRecord]:
        """Read all audit records from the log file.

        Returns:
            List of parsed ``AuditRecord`` objects. Returns an empty list when
            the log file does not exist.
        """
        if not self._log_path.is_file():
            return []
        records: list[AuditRecord] = []
        for line in self._log_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line:
                records.append(AuditRecord.model_validate_json(line))
        return records


def _summarize_params(params: dict[str, Any]) -> dict[str, Any]:
    """Summarize call parameters for audit logging.

    Sensitive keys are redacted, long strings are truncated, and long sequences
    are replaced by a length summary.

    Args:
        params: Original call parameters.

    Returns:
        A sanitized copy suitable for persistent audit logs.
    """
    redacted_params = SecretRedactingProcessor()(None, "audit", params)
    summary: dict[str, Any] = {}
    for key, value in redacted_params.items():
        if value == "[REDACTED]":
            summary[key] = "***REDACTED***"
        elif isinstance(value, (list, tuple)) and len(value) > 10:
            summary[key] = f"{type(value).__name__}[len={len(value)}]"
        elif isinstance(value, str) and len(value) > 200:
            summary[key] = value[:200] + "..."
        else:
            summary[key] = value
    return summary
