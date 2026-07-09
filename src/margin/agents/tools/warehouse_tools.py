"""Read-only warehouse tools for WorkerAgent runtimes."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from margin.agents.tools.specs import ToolCallRequest
from margin.data.warehouse_repository import (
    IndicatorHistoryQuery,
    SecurityProfileSearchQuery,
)


@dataclass(frozen=True)
class WarehouseToolResult:
    """One deterministic read-only warehouse tool result."""

    tool_name: str
    output: dict[str, Any]


class WarehouseReadTools:
    """Hard-coded read-only tool facade over the PIT warehouse repository."""

    def __init__(self, repository: Any) -> None:
        """Initialize with a PIT-safe warehouse repository."""
        self._repository = repository

    def describe_schema(self) -> WarehouseToolResult:
        """Describe the warehouse surfaces available to data workers."""
        tables = (
            {
                "name": "securities",
                "role": "PIT/bitemporal security master",
                "query_tool": "warehouse.resolve_security",
            },
            {
                "name": "standardized_indicator_facts",
                "role": "append-only provider indicator facts",
                "query_tool": "warehouse.query_indicator_history",
                "pit_rule": "available_at <= decision_at",
            },
            {
                "name": "canonical_indicator_values",
                "role": "canonical serving values selected from provider facts",
                "pit_rule": "decision_at <= request.decision_at",
            },
        )
        return WarehouseToolResult(
            tool_name="warehouse.describe_schema",
            output={
                "tables": list(tables),
                "available_tools": [
                    "warehouse.describe_schema",
                    "warehouse.resolve_security",
                    "warehouse.discover_indicators",
                    "warehouse.query_indicator_history",
                    "warehouse.query_data_freshness",
                ],
            },
        )

    def resolve_security(
        self,
        *,
        query_text: str,
        decision_at: datetime,
        limit: int = 5,
    ) -> WarehouseToolResult:
        """Resolve a user-facing company/security string through warehouse metadata."""
        profiles = []
        security_ids = tuple(dict.fromkeys(_extract_security_codes(query_text)))
        if security_ids and hasattr(self._repository, "security_profiles"):
            profiles = self._repository.security_profiles(security_ids, system_as_of=decision_at)
        if not profiles and query_text and hasattr(self._repository, "search_security_profiles"):
            profiles = self._repository.search_security_profiles(
                SecurityProfileSearchQuery(
                    query_text=query_text,
                    system_as_of=decision_at,
                    limit=limit,
                )
            )
        return WarehouseToolResult(
            tool_name="warehouse.resolve_security",
            output={
                "profiles": [
                    {
                        "security_id": profile.security_id,
                        "symbol": profile.symbol,
                        "name": profile.name,
                        "exchange": profile.exchange,
                    }
                    for profile in profiles
                ],
                "raw_profiles": profiles,
            },
        )

    def discover_indicators(
        self,
        *,
        security_ids: tuple[str, ...],
        query_text: str,
        decision_at: datetime,
        limit: int = 200,
    ) -> WarehouseToolResult:
        """Discover indicator metadata from the current warehouse."""
        if hasattr(self._repository, "discover_indicators"):
            raw_items = self._repository.discover_indicators(
                security_ids=security_ids,
                query_text=query_text,
                decision_at=decision_at,
                limit=limit,
            )
        else:
            raw_items = ()
        indicators = [_indicator_catalog_item(item) for item in raw_items]
        return WarehouseToolResult(
            tool_name="warehouse.discover_indicators",
            output={"indicators": indicators},
        )

    def query_indicator_history(
        self,
        *,
        security_ids: tuple[str, ...],
        indicator_ids: tuple[str, ...],
        decision_at: datetime,
        years: int = 4,
        max_points_per_indicator: int = 12,
    ) -> WarehouseToolResult:
        """Query PIT-safe indicator history from the warehouse repository."""
        history = self._repository.indicator_history(
            IndicatorHistoryQuery(
                security_ids=security_ids,
                indicator_ids=indicator_ids,
                start_date=(decision_at - timedelta(days=365 * years)).date(),
                end_date=decision_at.date(),
                decision_at=decision_at,
                max_points_per_indicator=max_points_per_indicator,
            )
        )
        return WarehouseToolResult(
            tool_name="warehouse.query_indicator_history",
            output={"history": history},
        )

    def query_data_freshness(
        self,
        *,
        domains: tuple[str, ...] = (),
        dataset: str | None = None,
    ) -> WarehouseToolResult:
        """Return persisted warehouse freshness records for requested domains."""
        domain_set = set(domains) if domains else None
        if hasattr(self._repository, "freshness"):
            records = self._repository.freshness(domain_set)
        else:
            records = []
        rows = [_freshness_row(record) for record in records]
        if dataset:
            dataset_key = dataset.strip().lower()
            rows = [
                row
                for row in rows
                if dataset_key in str(row.get("endpoint_code", "")).lower()
                or dataset_key in str(row.get("provider", "")).lower()
            ]
        statuses = {str(row.get("status") or "unknown") for row in rows}
        if not rows:
            aggregate = "unknown"
        elif statuses == {"fresh"}:
            aggregate = "fresh"
        elif "failed" in statuses:
            aggregate = "failed"
        elif "stale" in statuses or "never_synced" in statuses:
            aggregate = "stale"
        elif "syncing" in statuses:
            aggregate = "syncing"
        else:
            aggregate = "mixed"
        return WarehouseToolResult(
            tool_name="warehouse.query_data_freshness",
            output={
                "dataset": dataset or "all",
                "status": aggregate,
                "domains": list(domains),
                "records": rows,
                "record_count": len(rows),
            },
        )


def query_data_freshness(request: ToolCallRequest) -> dict:
    """Module-level stub kept for import compatibility; prefer WarehouseReadTools."""
    return {"dataset": request.input_json.get("dataset", "unknown"), "status": "unknown"}


def _freshness_row(record: Any) -> dict[str, Any]:
    """Normalize one warehouse freshness record into tool JSON."""
    status = getattr(record, "status", None)
    status_value = getattr(status, "value", status)
    return {
        "provider": getattr(record, "provider", ""),
        "endpoint_code": getattr(record, "endpoint_code", ""),
        "as_of_date": getattr(record, "as_of_date", None),
        "expected_at": getattr(record, "expected_at", None),
        "observed_at": getattr(record, "observed_at", None),
        "status": status_value,
        "lag_seconds": getattr(record, "lag_seconds", None),
    }


def _indicator_catalog_item(item: Any) -> dict[str, Any]:
    """Normalize repository-specific indicator metadata into tool JSON."""
    if isinstance(item, dict):
        data = dict(item)
    else:
        data = {
            "indicator_id": getattr(item, "indicator_id", ""),
            "label": getattr(item, "label", None) or getattr(item, "name", None),
            "unit": getattr(item, "unit", None),
            "value_scale": getattr(item, "value_scale", None),
            "aliases": getattr(item, "aliases", ()),
            "coverage": getattr(item, "coverage", None),
            "source_fields": getattr(item, "source_fields", ()),
        }
    indicator_id = str(data.get("indicator_id") or "").strip()
    label = str(data.get("label") or _humanize_indicator_id(indicator_id)).strip()
    aliases = tuple(str(value) for value in data.get("aliases") or () if str(value).strip())
    source_fields = tuple(
        str(value) for value in data.get("source_fields") or () if str(value).strip()
    )
    return {
        "indicator_id": indicator_id,
        "label": label,
        "unit": data.get("unit") or "",
        "value_scale": data.get("value_scale"),
        "aliases": list(aliases),
        "coverage": data.get("coverage") or {},
        "source_fields": list(source_fields),
    }


def _humanize_indicator_id(indicator_id: str) -> str:
    """Return a readable fallback label from a warehouse indicator ID."""
    return indicator_id.replace("_", " ").strip() or "indicator"


def _extract_security_codes(value: str) -> list[str]:
    """Extract A-share style security IDs from free-form text."""
    codes: list[str] = []
    for match in re.finditer(r"\b(\d{6})(?:\.(SH|SZ|BJ))?\b", value, flags=re.IGNORECASE):
        raw_code = match.group(1)
        suffix = match.group(2)
        if suffix:
            codes.append(f"{raw_code}.{suffix.upper()}")
        elif raw_code.startswith(("6", "9")):
            codes.append(f"{raw_code}.SH")
        elif raw_code.startswith(("0", "2", "3")):
            codes.append(f"{raw_code}.SZ")
        else:
            codes.append(raw_code)
    return codes
