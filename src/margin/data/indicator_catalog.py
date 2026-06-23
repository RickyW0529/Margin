"""Canonical indicator definitions and provider field mappings."""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from pydantic import BaseModel, Field


class IndicatorDefinition(BaseModel):
    """Canonical indicator definition."""

    indicator_id: str
    version: str = "indicator-v0.2.0"
    domain: str
    name: str
    value_type: str
    unit: str | None = None
    direction: str | None = None
    required_for_quant: bool = False
    definition: dict[str, Any] = Field(default_factory=dict)

    model_config = {"frozen": True}


class ProviderIndicatorMapping(BaseModel):
    """Mapping from provider fields to canonical indicators."""

    provider: str
    endpoint_code: str
    source_field: str
    indicator_id: str
    indicator_version: str = "indicator-v0.2.0"
    mapping_version: str = "mapping-v0.2.0"
    multiplier: Decimal = Decimal("1")
    target_unit: str | None = None
    active: bool = True

    model_config = {"frozen": True}

    def convert_numeric(self, value: Decimal) -> Decimal:
        """Apply deterministic unit conversion for numeric provider values."""
        return value * self.multiplier


class IndicatorCatalog:
    """In-memory catalog of indicator definitions."""

    def __init__(self, definitions: tuple[IndicatorDefinition, ...] = ()) -> None:
        """Initialize the instance."""
        self._definitions = {
            (definition.indicator_id, definition.version): definition
            for definition in definitions
        }

    def add(self, definition: IndicatorDefinition) -> None:
        """Register a new indicator definition."""
        self._definitions[(definition.indicator_id, definition.version)] = definition

    def get(self, indicator_id: str, version: str = "indicator-v0.2.0") -> IndicatorDefinition:
        """Return an indicator definition by ID/version."""
        return self._definitions[(indicator_id, version)]
