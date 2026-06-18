"""Immutable audit logging for every Provider call.

Each call records a parameter summary and the result status. Audit records are
append-only and must not be modified after writing.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from margin.core.provider import CallResult


class AuditRecord(BaseModel):
    """A single immutable audit record describing a Provider call."""

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
                ``~/.margin/audit/provider_calls.jsonl``.
        """
        self._log_path = log_path or Path.home() / ".margin" / "audit" / "provider_calls.jsonl"
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
    sensitive_keys = {"token", "api_key", "password", "secret"}
    summary: dict[str, Any] = {}
    for key, value in params.items():
        if key.lower() in sensitive_keys:
            summary[key] = "***REDACTED***"
        elif isinstance(value, (list, tuple)) and len(value) > 10:
            summary[key] = f"{type(value).__name__}[len={len(value)}]"
        elif isinstance(value, str) and len(value) > 200:
            summary[key] = value[:200] + "..."
        else:
            summary[key] = value
    return summary
