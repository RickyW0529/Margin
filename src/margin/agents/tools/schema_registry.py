"""Schema validation registry for ToolGateway calls."""

from __future__ import annotations

from typing import Any, Protocol


class ToolSchemaRegistry(Protocol):
    """Validation boundary for tool input and output schema refs."""

    def validate(self, schema_ref: str, payload: dict[str, Any]) -> bool:
        """Return whether a payload conforms to a schema ref."""


class NoopToolSchemaRegistry:
    """Schema registry that accepts every payload."""

    def validate(self, schema_ref: str, payload: dict[str, Any]) -> bool:
        """Accept all payloads.

        Args:
            schema_ref: Schema reference.
            payload: JSON-compatible payload.

        Returns:
            Always ``True``.
        """
        del schema_ref, payload
        return True


class InMemoryToolSchemaRegistry:
    """Simple deterministic schema registry for required-key contracts."""

    def __init__(self) -> None:
        """Initialize an empty schema registry."""
        self._required_keys: dict[str, tuple[str, ...]] = {}

    def register_required_keys(self, schema_ref: str, required_keys: tuple[str, ...]) -> None:
        """Register a schema ref that requires top-level keys.

        Args:
            schema_ref: Schema reference.
            required_keys: Required top-level payload keys.
        """
        self._required_keys[schema_ref] = required_keys

    def validate(self, schema_ref: str, payload: dict[str, Any]) -> bool:
        """Validate a payload by top-level required keys.

        Args:
            schema_ref: Schema reference.
            payload: JSON-compatible payload.

        Returns:
            ``True`` if all registered required keys are present.
        """
        return all(key in payload for key in self._required_keys.get(schema_ref, ()))
