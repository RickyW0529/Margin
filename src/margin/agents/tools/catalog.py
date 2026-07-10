"""In-memory ToolCatalog for v1 tools."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from margin.agents.security.capability import CapabilityToken
from margin.agents.security.policies import DataAccessPolicy, ToolPolicy
from margin.agents.tools.authz import capability_allows_tool
from margin.agents.tools.specs import ToolCallRequest, ToolSpec
from margin.agents.tools.warehouse_tools import WarehouseReadTools
from margin.dashboard.models import DashboardFilters, DashboardSort

ToolHandler = Callable[[ToolCallRequest], dict[str, Any]]


@dataclass(frozen=True)
class RegisteredTool:
    """RegisteredTool.."""

    spec: ToolSpec
    handler: ToolHandler


class ToolCatalog:
    """ToolCatalog.."""

    def __init__(self) -> None:
        """Init .

        Returns:
            None: .
        """
        self._tools: dict[tuple[str, str], RegisteredTool] = {}

    def register(self, spec: ToolSpec, handler: ToolHandler) -> None:
        """Register.

        Args:
            spec: ToolSpec: .
            handler: ToolHandler: .

        Returns:
            None: .
        """
        self._tools[(spec.tool_name, spec.tool_version)] = RegisteredTool(
            spec=spec,
            handler=handler,
        )

    def get(self, tool_name: str, tool_version: str) -> RegisteredTool | None:
        """Get.

        Args:
            tool_name: str: .
            tool_version: str: .

        Returns:
            RegisteredTool | None: .
        """
        return self._tools.get((tool_name, tool_version))

    def has(self, tool_name: str, tool_version: str | None = None) -> bool:
        """Return whether a tool name/version is registered."""
        if tool_version is not None:
            return (tool_name, tool_version) in self._tools
        return any(name == tool_name for name, _version in self._tools)

    def list_specs(self) -> tuple[ToolSpec, ...]:
        """Return all registered tool specs."""
        return tuple(registered.spec for registered in self._tools.values())

    def specs_for_name(self, tool_name: str) -> tuple[ToolSpec, ...]:
        """Return registered specs for a tool name across versions."""
        return tuple(
            registered.spec
            for (name, _version), registered in self._tools.items()
            if name == tool_name
        )

    def visible_specs(self, token: CapabilityToken) -> tuple[ToolSpec, ...]:
        """Return tools allowed by the supplied capability token."""
        return tuple(spec for spec in self.list_specs() if capability_allows_tool(token, spec))

    def explain_missing(self, tool_name: str) -> str:
        """Return a stable missing-tool explanation."""
        if self.has(tool_name):
            return ""
        return f"tool not registered: {tool_name}"


def default_tool_catalog(
    *,
    warehouse_repository: object | None = None,
    dashboard_services: object | None = None,
    firecrawl_adapter: object | None = None,
) -> ToolCatalog:
    """Return the default executable tool catalog for configured dependencies."""
    catalog = ToolCatalog()
    if dashboard_services is not None:
        catalog.register(
            _read_only_dashboard_tool_spec("dashboard.read_candidates"),
            _dashboard_read_candidates_handler(dashboard_services),
        )
    if warehouse_repository is not None:
        warehouse_tools = WarehouseReadTools(warehouse_repository)
        handlers = {
            "warehouse.describe_schema": _warehouse_describe_schema_handler(warehouse_tools),
            "warehouse.resolve_security": _warehouse_resolve_security_handler(warehouse_tools),
            "warehouse.discover_indicators": _warehouse_discover_indicators_handler(
                warehouse_tools
            ),
            "warehouse.query_indicator_history": _warehouse_query_indicator_history_handler(
                warehouse_tools
            ),
            "warehouse.query_data_freshness": _warehouse_query_data_freshness_handler(
                warehouse_tools
            ),
        }
        for tool_name in handlers:
            catalog.register(_read_only_warehouse_tool_spec(tool_name), handlers[tool_name])
    if firecrawl_adapter is not None:
        from margin.agents.tools.firecrawl_tools import register_firecrawl_tools

        register_firecrawl_tools(catalog, firecrawl_adapter)
    return catalog


def _dashboard_read_candidates_handler(dashboard_services: object) -> ToolHandler:
    def handler(request: ToolCallRequest) -> dict[str, Any]:
        page = dashboard_services.query.list_research_candidates_v2(
            scope_version_id=str(request.input_json.get("scope_version_id") or ""),
            universe_code=str(request.input_json.get("universe") or "ALL_A"),
            filters=DashboardFilters(),
            sort=DashboardSort(field="final_score", direction="desc"),
            cursor=None,
            limit=int(request.input_json.get("limit") or 10),
        )
        rows = [
            {
                "security_id": item.security_id,
                "symbol": item.symbol,
                "final_score": item.final_score,
                "confidence": item.confidence,
                "screening_status": item.screening_status,
            }
            for item in page.items
        ]
        return _json_safe(
            {
                "scope_version_id": page.scope_version_id,
                "universe": request.input_json.get("universe") or "ALL_A",
                "status": "ready" if rows else "empty",
                "as_of": page.as_of,
                "row_count": len(rows),
                "facets": page.facets,
                "rows": rows,
                "safe_summary": (
                    f"Dashboard candidate source has {len(rows)} rows."
                    if rows
                    else "Dashboard candidate source is empty for current scope."
                ),
            }
        )

    return handler


def _warehouse_describe_schema_handler(tools: WarehouseReadTools) -> ToolHandler:
    def handler(_request: ToolCallRequest) -> dict[str, Any]:
        return _json_safe(tools.describe_schema().output)

    return handler


def _warehouse_resolve_security_handler(tools: WarehouseReadTools) -> ToolHandler:
    def handler(request: ToolCallRequest) -> dict[str, Any]:
        result = tools.resolve_security(
            query_text=str(request.input_json.get("query_text") or ""),
            decision_at=_datetime_input(request.input_json.get("decision_at")),
            limit=int(request.input_json.get("limit") or 5),
        )
        profiles = result.output.get("raw_profiles") or result.output.get("profiles") or ()
        return {
            "profiles": [_security_profile_json(profile) for profile in profiles],
        }

    return handler


def _warehouse_discover_indicators_handler(tools: WarehouseReadTools) -> ToolHandler:
    def handler(request: ToolCallRequest) -> dict[str, Any]:
        result = tools.discover_indicators(
            security_ids=_string_tuple(request.input_json.get("security_ids")),
            query_text=str(request.input_json.get("query_text") or ""),
            decision_at=_datetime_input(request.input_json.get("decision_at")),
            limit=int(request.input_json.get("limit") or 200),
        )
        return _json_safe(result.output)

    return handler


def _warehouse_query_indicator_history_handler(tools: WarehouseReadTools) -> ToolHandler:
    def handler(request: ToolCallRequest) -> dict[str, Any]:
        result = tools.query_indicator_history(
            security_ids=_string_tuple(request.input_json.get("security_ids")),
            indicator_ids=_string_tuple(request.input_json.get("indicator_ids")),
            decision_at=_datetime_input(request.input_json.get("decision_at")),
            years=int(request.input_json.get("years") or 4),
            max_points_per_indicator=int(
                request.input_json.get("max_points_per_indicator") or 12
            ),
        )
        return {
            "history": [
                _indicator_history_json(value)
                for value in result.output.get("history", ())
            ],
        }

    return handler


def _warehouse_query_data_freshness_handler(tools: WarehouseReadTools) -> ToolHandler:
    def handler(request: ToolCallRequest) -> dict[str, Any]:
        result = tools.query_data_freshness(
            domains=_string_tuple(request.input_json.get("domains")),
            dataset=(
                str(request.input_json.get("dataset")).strip()
                if request.input_json.get("dataset") is not None
                else None
            ),
        )
        return _json_safe(result.output)

    return handler


def _datetime_input(value: object) -> datetime:
    if isinstance(value, datetime):
        return value if value.tzinfo is not None else value.replace(tzinfo=UTC)
    if isinstance(value, str) and value:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=UTC)
    return datetime.now(UTC)


def _string_tuple(value: object) -> tuple[str, ...]:
    if isinstance(value, str):
        return (value,) if value else ()
    if isinstance(value, list | tuple):
        return tuple(str(item) for item in value if str(item))
    return ()


def _security_profile_json(profile: object) -> dict[str, Any]:
    if isinstance(profile, dict):
        data = dict(profile)
    else:
        data = {
            "security_id": getattr(profile, "security_id", ""),
            "symbol": getattr(profile, "symbol", ""),
            "name": getattr(profile, "name", ""),
            "exchange": getattr(profile, "exchange", ""),
            "listed_at": getattr(profile, "listed_at", None),
            "delisted_at": getattr(profile, "delisted_at", None),
            "is_st": getattr(profile, "is_st", False),
        }
    return _json_safe(data)


def _indicator_history_json(value: object) -> dict[str, Any]:
    if isinstance(value, dict):
        data = dict(value)
    else:
        data = {
            "fact_id": getattr(value, "fact_id", ""),
            "provider": getattr(value, "provider", ""),
            "security_id": getattr(value, "security_id", ""),
            "indicator_id": getattr(value, "indicator_id", ""),
            "event_at": getattr(value, "event_at", None),
            "available_at": getattr(value, "available_at", None),
            "fetched_at": getattr(value, "fetched_at", None),
            "numeric_value": getattr(value, "numeric_value", None),
            "quality_score": getattr(value, "quality_score", None),
            "raw_snapshot_id": getattr(value, "raw_snapshot_id", None),
        }
    return _json_safe(data)


def _json_safe(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, list | tuple):
        return [_json_safe(item) for item in value]
    if isinstance(value, datetime):
        return value.isoformat()
    if hasattr(value, "isoformat"):
        return value.isoformat()
    if isinstance(value, Decimal):
        return float(value)
    return value


def _read_only_warehouse_tool_spec(tool_name: str) -> ToolSpec:
    return ToolSpec(
        tool_name=tool_name,
        tool_version="v1",
        description=f"{tool_name} read-only warehouse tool",
        owner_domain="data",
        input_schema_ref=f"{tool_name}.input",
        output_schema_ref=f"{tool_name}.output",
        input_schema=_warehouse_input_schema(tool_name),
        output_schema=_warehouse_output_schema(tool_name),
        required_data_access=(DataAccessPolicy.READ_ANALYSIS_MART,),
        required_write_policy=(),
        required_tool_policy=(ToolPolicy.READ_ONLY_TOOLS,),
        idempotent=True,
        mutates_state=False,
        timeout_ms=30_000,
        max_output_bytes=64_000,
        returns_raw_payload=False,
        allowed_runtimes=("langgraph",),
    )


def _read_only_dashboard_tool_spec(tool_name: str) -> ToolSpec:
    return ToolSpec(
        tool_name=tool_name,
        tool_version="v1",
        description=f"{tool_name} read-only dashboard tool",
        owner_domain="general",
        input_schema_ref=f"{tool_name}.input",
        output_schema_ref=f"{tool_name}.output",
        input_schema={
            "type": "object",
            "properties": {
                "scope_version_id": {"type": "string"},
                "universe": {"type": "string"},
                "limit": {"type": "integer", "minimum": 1, "maximum": 100},
            },
            "additionalProperties": False,
        },
        output_schema={
            "type": "object",
            "required": ["scope_version_id", "universe", "status", "row_count", "rows"],
            "properties": {
                "scope_version_id": {"type": "string"},
                "universe": {"type": "string"},
                "status": {"type": "string"},
                "row_count": {"type": "integer"},
                "rows": {"type": "array", "items": {"type": "object"}},
            },
        },
        required_data_access=(DataAccessPolicy.READ_DASHBOARD,),
        required_write_policy=(),
        required_tool_policy=(ToolPolicy.READ_ONLY_TOOLS,),
        idempotent=True,
        mutates_state=False,
        timeout_ms=30_000,
        max_output_bytes=64_000,
        returns_raw_payload=False,
        allowed_runtimes=("langgraph",),
    )


def _warehouse_input_schema(tool_name: str) -> dict[str, Any]:
    schemas: dict[str, dict[str, Any]] = {
        "warehouse.describe_schema": {"type": "object", "additionalProperties": False},
        "warehouse.resolve_security": {
            "type": "object",
            "required": ["query_text"],
            "properties": {
                "query_text": {"type": "string", "minLength": 1},
                "decision_at": {"type": "string"},
                "limit": {"type": "integer", "minimum": 1, "maximum": 20},
            },
            "additionalProperties": False,
        },
        "warehouse.discover_indicators": {
            "type": "object",
            "required": ["security_ids", "query_text"],
            "properties": {
                "security_ids": {"type": "array", "items": {"type": "string"}},
                "query_text": {"type": "string", "minLength": 1},
                "decision_at": {"type": "string"},
                "limit": {"type": "integer", "minimum": 1, "maximum": 500},
            },
            "additionalProperties": False,
        },
        "warehouse.query_indicator_history": {
            "type": "object",
            "required": ["security_ids", "indicator_ids"],
            "properties": {
                "security_ids": {"type": "array", "items": {"type": "string"}},
                "indicator_ids": {"type": "array", "items": {"type": "string"}},
                "decision_at": {"type": "string"},
                "years": {"type": "integer", "minimum": 1, "maximum": 20},
                "max_points_per_indicator": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 200,
                },
            },
            "additionalProperties": False,
        },
        "warehouse.query_data_freshness": {
            "type": "object",
            "properties": {
                "domains": {"type": "array", "items": {"type": "string"}},
                "dataset": {"type": "string"},
            },
            "additionalProperties": False,
        },
    }
    return schemas[tool_name]


def _warehouse_output_schema(tool_name: str) -> dict[str, Any]:
    if tool_name == "warehouse.resolve_security":
        return {
            "type": "object",
            "required": ["profiles"],
            "properties": {"profiles": {"type": "array", "items": {"type": "object"}}},
        }
    if tool_name == "warehouse.query_indicator_history":
        return {
            "type": "object",
            "required": ["history"],
            "properties": {"history": {"type": "array", "items": {"type": "object"}}},
        }
    return {"type": "object"}
