"""Quant screening result models."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from margin.valuation_discovery.models import DataStatus


@dataclass(frozen=True)
class FilterReason:
    """Structured hard-filter reason.."""

    code: str
    severity: str
    message: str
    observed: Any | None = None
    threshold: Any | None = None
    indicator_id: str | None = None
    indicator_version: str | None = None


@dataclass(frozen=True)
class SecurityFilterResult:
    """Hard-filter result for one security.."""

    security_id: str
    allowed_for_scoring: bool
    data_status: DataStatus
    reasons: tuple[FilterReason, ...]

    def reason_by_code(self, code: str) -> FilterReason | None:
        """Return the first reason with the supplied code.

        Args:
            code: str: .

        Returns:
            FilterReason | None: .
        """
        return next((reason for reason in self.reasons if reason.code == code), None)


@dataclass(frozen=True)
class HardFilterResult:
    """Hard-filter result for a full cross section.."""

    by_security: dict[str, SecurityFilterResult]
