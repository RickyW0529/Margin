"""Source schema discovery and field lifecycle tracking."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import UTC, datetime
from typing import Any


@dataclass(frozen=True)
class SourceFieldState:
    """Lifecycle state for one observed source field.."""

    endpoint_code: str
    field_name: str
    inferred_type: str
    status: str
    first_seen_at: datetime
    last_seen_at: datetime
    consecutive_missing_count: int = 0
    type_change_count: int = 0


class SchemaDiscoveryService:
    """Track source fields, type changes, and consecutive missing observations.."""

    def __init__(self, *, missing_threshold: int = 3) -> None:
        """Initialize the service.

        Args:
            missing_threshold: int: .

        Returns:
            None: .
        """
        if missing_threshold < 1:
            raise ValueError("missing_threshold must be positive")
        self._missing_threshold = missing_threshold
        self._fields: dict[tuple[str, str], SourceFieldState] = {}

    def observe(
        self,
        endpoint_code: str,
        payload: dict[str, Any],
        *,
        observed_at: datetime | None = None,
    ) -> None:
        """Observe a provider payload and update field lifecycle state.

        Args:
            endpoint_code: str: .
            payload: dict[str, Any]: .
            observed_at: datetime | None: .

        Returns:
            None: .
        """
        timestamp = observed_at or datetime.now(UTC)
        endpoint = endpoint_code.strip().lower()
        observed_fields = set(payload)

        for key, value in payload.items():
            field_key = (endpoint, key)
            inferred_type = _infer_type(value)
            current = self._fields.get(field_key)
            if current is None:
                self._fields[field_key] = SourceFieldState(
                    endpoint_code=endpoint,
                    field_name=key,
                    inferred_type=inferred_type,
                    status="active",
                    first_seen_at=timestamp,
                    last_seen_at=timestamp,
                )
                continue
            type_changed = current.inferred_type != inferred_type and value is not None
            self._fields[field_key] = replace(
                current,
                inferred_type=inferred_type if type_changed else current.inferred_type,
                status="active",
                last_seen_at=timestamp,
                consecutive_missing_count=0,
                type_change_count=current.type_change_count + int(type_changed),
            )

        for field_key, current in list(self._fields.items()):
            current_endpoint, field_name = field_key
            if current_endpoint != endpoint or field_name in observed_fields:
                continue
            missing_count = current.consecutive_missing_count + 1
            status = "missing" if missing_count >= self._missing_threshold else current.status
            self._fields[field_key] = replace(
                current,
                status=status,
                consecutive_missing_count=missing_count,
            )

    def field(self, endpoint_code: str, field_name: str) -> SourceFieldState:
        """Return current lifecycle state for an endpoint field.

        Args:
            endpoint_code: str: .
            field_name: str: .

        Returns:
            SourceFieldState: .
        """
        key = (endpoint_code.strip().lower(), field_name)
        try:
            return self._fields[key]
        except KeyError as exc:
            raise KeyError(f"unknown source field: {endpoint_code}/{field_name}") from exc


def _infer_type(value: Any) -> str:
    """Infer a coarse type name from a single observed value.

    Args:
        value: Any: .

    Returns:
        str: .
    """
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "bool"
    if isinstance(value, int) and not isinstance(value, bool):
        return "int"
    if isinstance(value, float):
        return "float"
    if isinstance(value, str):
        return "str"
    if isinstance(value, list):
        return "list"
    if isinstance(value, dict):
        return "dict"
    return type(value).__name__
