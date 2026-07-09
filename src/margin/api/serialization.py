"""Shared API serialization helpers."""

from __future__ import annotations

from typing import Any

SENSITIVE_PAYLOAD_KEYS = (
    "api_key",
    "authorization",
    "password",
    "provider_token",
    "raw_text",
    "secret",
    "token",
)


def safe_artifact_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """Return a frontend-safe context artifact payload.

    Args:
        payload: Raw structured artifact payload.

    Returns:
        A recursively redacted payload that preserves displayable structure.
    """
    return {key: _redact_payload_value(key, value) for key, value in payload.items()}


def _redact_payload_value(key: str, value: Any) -> Any:
    """Redact one payload value using its parent key as sensitivity context.

    Args:
        key: Parent payload key.
        value: JSON-compatible payload value.

    Returns:
        Redacted or truncated payload value.
    """
    lowered = key.lower()
    if any(marker in lowered for marker in SENSITIVE_PAYLOAD_KEYS):
        return "[redacted]"
    if isinstance(value, dict):
        return safe_artifact_payload(value)
    if isinstance(value, list):
        return [_redact_payload_value(key, item) for item in value[:50]]
    if isinstance(value, str) and len(value) > 2000:
        return value[:2000] + "...[truncated]"
    return value
