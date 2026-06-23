"""Versioned tool definitions exposed to scoped graph sessions."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from pydantic import BaseModel


class ToolCapability(StrEnum):
    """Capabilities used by graph tool policy."""

    CONTEXT_READ = "context_read"
    QUANT_READ = "quant_read"
    FINANCIAL_READ = "financial_read"
    NEWS_READ = "news_read"
    FILING_READ = "filing_read"
    EVIDENCE_RETRIEVE = "evidence_retrieve"
    DETERMINISTIC_VALUATION = "deterministic_valuation"
    RESTRICTED_CALCULATION = "restricted_calculation"
    CITATION_VALIDATION = "citation_validation"
    REALTIME_WEBSEARCH = "realtime_websearch"
    PROVIDER_SYNC = "provider_sync"
    ORDER_WRITE = "order_write"
    ALERT_WRITE = "alert_write"
    FILE_NETWORK_PYTHON = "file_network_python"


ToolHandler = Callable[[dict[str, Any]], Any]


@dataclass(frozen=True)
class ToolDefinition:
    """Versioned executable definition registered before graph execution."""

    name: str
    capability: ToolCapability
    version: str
    description: str
    input_model: type[BaseModel]
    handler: ToolHandler
    estimated_result_bytes: int = 0

    @property
    def input_schema(self) -> dict[str, Any]:
        """Return the JSON schema shown in the node ToolManifest."""
        return self.input_model.model_json_schema()

    def validate_args(self, args: dict[str, Any]) -> dict[str, Any]:
        """Validate and normalize tool arguments before execution."""
        return self.input_model.model_validate(args).model_dump(mode="python")


class ToolDefinitionRegistry:
    """In-memory registry of immutable v0.2 tool definitions."""

    def __init__(self) -> None:
        """Initialize the instance."""
        self._definitions: dict[str, ToolDefinition] = {}

    def register(self, definition: ToolDefinition) -> None:
        """Register a definition, rejecting incompatible replacement."""
        current = self._definitions.get(definition.name)
        if current is not None and current != definition:
            raise ValueError(f"tool definition '{definition.name}' is immutable")
        self._definitions[definition.name] = definition

    def get(self, name: str) -> ToolDefinition | None:
        """Return a definition by name."""
        return self._definitions.get(name)

    def list_definitions(self) -> tuple[ToolDefinition, ...]:
        """Return definitions in stable name order."""
        return tuple(self._definitions[name] for name in sorted(self._definitions))
