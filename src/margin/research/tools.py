"""Typed tool system for multi-agent research workflows."""

from __future__ import annotations

import hashlib
import json
import math
import uuid
from abc import ABC, abstractmethod
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import AliasChoices, BaseModel, Field, field_validator

from margin.news.models import utc_now


@dataclass(frozen=True)
class ToolResult:
    """Result of a single tool invocation."""

    tool_name: str
    success: bool
    data: Any = None
    error: str | None = None
    latency_ms: float = 0.0
    params: dict[str, Any] | None = None
    call_id: str | None = None


class ToolPermission(StrEnum):
    """Permission level enforced by :class:`ToolRegistry`."""

    READ = "read"
    WRITE_WITH_CONFIRM = "write_with_confirm"
    FORBIDDEN = "forbidden"


class ToolCallRecord(BaseModel):
    """Immutable audit record for a tool call."""

    call_id: str = Field(default_factory=lambda: f"tc_{uuid.uuid4().hex[:12]}")
    trace_id: str = ""
    tool_name: str
    params_json: str = Field(
        default="{}",
        validation_alias=AliasChoices("params_json", "params"),
    )
    permission: ToolPermission = ToolPermission.READ
    success: bool = True
    data_hash: str | None = None
    data_json: str | None = None
    error: str | None = None
    latency_ms: float = 0.0
    called_at: datetime = Field(default_factory=utc_now)

    model_config = {"frozen": True}

    @field_validator("params_json", mode="before")
    @classmethod
    def serialize_params(cls, value: Any) -> str:
        if isinstance(value, str):
            return value
        return json.dumps(value or {}, sort_keys=True, default=str)

    @property
    def params(self) -> dict[str, Any]:
        """Return a defensive copy of the redacted parameters."""
        return json.loads(self.params_json)

    @property
    def data(self) -> Any:
        """Return a defensive copy of the redacted result payload."""
        return json.loads(self.data_json) if self.data_json is not None else None


class BaseTool(ABC):
    """Abstract base for all research tools."""

    @property
    @abstractmethod
    def name(self) -> str:
        """Return the tool name."""

    @property
    def permission(self) -> ToolPermission:
        return ToolPermission.READ

    @abstractmethod
    def run(self, params: dict[str, Any]) -> ToolResult:
        """Execute the tool with the given parameters."""

    def _hash(self, data: Any) -> str:
        return hashlib.sha256(json.dumps(data, sort_keys=True, default=str).encode()).hexdigest()


class PythonTool(BaseTool):
    """Controlled numeric computation; no shell, no imports."""

    @property
    def name(self) -> str:
        return "python"

    def run(self, params: dict[str, Any]) -> ToolResult:
        start = datetime.now().timestamp()
        expression = params.get("expression", "")
        allowed_names = {
            "abs": abs,
            "round": round,
            "max": max,
            "min": min,
            "sum": sum,
            "pow": pow,
            "math": math,
        }
        try:
            code = compile(expression, "<tool>", "eval")
            if code.co_names:
                for name in code.co_names:
                    if name not in allowed_names:
                        raise ValueError(f"disallowed name: {name}")
            value = eval(code, {"__builtins__": {}}, allowed_names)
            latency = (datetime.now().timestamp() - start) * 1000
            return ToolResult(
                tool_name=self.name,
                success=True,
                data=value,
                latency_ms=latency,
                params=params,
            )
        except Exception as exc:
            latency = (datetime.now().timestamp() - start) * 1000
            return ToolResult(
                tool_name=self.name,
                success=False,
                error=f"{type(exc).__name__}: {exc}",
                latency_ms=latency,
                params=params,
            )


class RetrievalTool(BaseTool):
    """Wrap ``margin.vector.retrieval.RetrievalTool`` when a pipeline is available."""

    def __init__(self, pipeline: Any | None = None) -> None:
        self._pipeline = pipeline

    @property
    def name(self) -> str:
        return "retrieval"

    def run(self, params: dict[str, Any]) -> ToolResult:
        start = datetime.now().timestamp()
        symbol = params.get("symbol")
        query = params.get("query", "")
        decision_at = params.get("decision_at")
        if not symbol:
            return ToolResult(
                tool_name=self.name,
                success=False,
                error="symbol is required",
                latency_ms=(datetime.now().timestamp() - start) * 1000,
                params=params,
            )
        if decision_at is None:
            return ToolResult(
                tool_name=self.name,
                success=False,
                error="decision_at is required",
                latency_ms=(datetime.now().timestamp() - start) * 1000,
                params=params,
            )
        if self._pipeline is None:
            return ToolResult(
                tool_name=self.name,
                success=False,
                error="retrieval pipeline not configured",
                latency_ms=(datetime.now().timestamp() - start) * 1000,
                params=params,
            )
        try:
            from margin.vector.retrieval import RetrievalTool as VectorRetrievalTool

            tool = VectorRetrievalTool(self._pipeline)
            results = tool.search(query=query, symbol=symbol, decision_at=decision_at)
            latency = (datetime.now().timestamp() - start) * 1000
            return ToolResult(
                tool_name=self.name,
                success=True,
                data=[r.model_dump() for r in results],
                latency_ms=latency,
                params=params,
            )
        except Exception as exc:
            latency = (datetime.now().timestamp() - start) * 1000
            return ToolResult(
                tool_name=self.name,
                success=False,
                error=f"{type(exc).__name__}: {exc}",
                latency_ms=latency,
                params=params,
            )


class _AdapterTool(BaseTool):
    """Typed adapter that fails closed when no handler is configured."""

    tool_name = ""

    def __init__(self, handler: Callable[[dict[str, Any]], Any] | None = None) -> None:
        self._handler = handler

    @property
    def name(self) -> str:
        return self.tool_name

    def run(self, params: dict[str, Any]) -> ToolResult:
        start = datetime.now().timestamp()
        if self._handler is None:
            return ToolResult(
                tool_name=self.name,
                success=False,
                error=f"{self.name} adapter not configured",
                latency_ms=(datetime.now().timestamp() - start) * 1000,
                params=params,
            )
        try:
            data = self._handler(params)
            return ToolResult(
                tool_name=self.name,
                success=True,
                data=data,
                latency_ms=(datetime.now().timestamp() - start) * 1000,
                params=params,
            )
        except Exception as exc:
            return ToolResult(
                tool_name=self.name,
                success=False,
                error=f"{type(exc).__name__}: {exc}",
                latency_ms=(datetime.now().timestamp() - start) * 1000,
                params=params,
            )


class MarketDataTool(_AdapterTool):
    """Market data adapter."""

    tool_name = "market_data"


class FinancialTool(_AdapterTool):
    """Financial statement adapter."""

    tool_name = "financial"


class FactorTool(_AdapterTool):
    """Factor computation adapter."""

    tool_name = "factor"


class ValuationTool(BaseTool):
    """Simple DCF/relative valuation stub using PythonTool for calculations."""

    def __init__(self) -> None:
        self._python = PythonTool()

    @property
    def name(self) -> str:
        return "valuation"

    def run(self, params: dict[str, Any]) -> ToolResult:
        method = params.get("method", "pe")
        eps = params.get("eps", 1.0)
        pe = params.get("pe", 10.0)
        result = self._python.run({"expression": f"{eps} * {pe}"})
        return ToolResult(
            tool_name=self.name,
            success=result.success,
            data={"method": method, "value": result.data},
            error=result.error,
            latency_ms=result.latency_ms,
            params=params,
        )


class PortfolioTool(_AdapterTool):
    """Read-only portfolio constraint adapter."""

    tool_name = "portfolio"


class WebSearchTool(_AdapterTool):
    """Web search adapter."""

    tool_name = "websearch"


class CalendarTool(_AdapterTool):
    """Trading calendar adapter."""

    tool_name = "calendar"


class AlertTool(_AdapterTool):
    """Alert creation adapter requiring explicit confirmation."""

    tool_name = "alert"

    @property
    def permission(self) -> ToolPermission:
        return ToolPermission.WRITE_WITH_CONFIRM


class BacktestTool(_AdapterTool):
    """Backtest adapter."""

    tool_name = "backtest"


class FilingTool(_AdapterTool):
    """Filing lookup adapter."""

    tool_name = "filing"


class DocumentCollectorTool(_AdapterTool):
    """Compliant document acquisition/snapshot adapter."""

    tool_name = "document_collector"


class ToolRegistry:
    """Registry of tools available to agents."""

    def __init__(self) -> None:
        self._tools: dict[str, BaseTool] = {}
        self._audit_records: list[ToolCallRecord] = []

    def register(self, tool: BaseTool) -> None:
        self._tools[tool.name] = tool

    def register_defaults(self, pipeline: Any | None = None) -> None:
        self.register(PythonTool())
        self.register(RetrievalTool(pipeline))
        self.register(MarketDataTool())
        self.register(FinancialTool())
        self.register(FactorTool())
        self.register(ValuationTool())
        self.register(PortfolioTool())
        self.register(WebSearchTool())
        self.register(CalendarTool())
        self.register(AlertTool())
        self.register(BacktestTool())
        self.register(FilingTool())
        self.register(DocumentCollectorTool())

    def get(self, name: str) -> BaseTool | None:
        return self._tools.get(name)

    def list_tools(self) -> list[str]:
        return list(self._tools.keys())

    def describe_tools(self) -> list[dict[str, str]]:
        """Return public tool metadata without exposing handlers."""
        return [
            {
                "name": name,
                "permission": ToolPermission(tool.permission).value,
            }
            for name, tool in sorted(self._tools.items())
        ]

    @property
    def audit_records(self) -> tuple[ToolCallRecord, ...]:
        """Return immutable tool-call audit records."""
        return tuple(self._audit_records)

    def call(
        self,
        name: str,
        params: dict[str, Any],
        *,
        trace_id: str = "",
        confirmed: bool = False,
    ) -> ToolResult:
        tool = self.get(name)
        if tool is None:
            return self._record(
                ToolResult(
                    tool_name=name,
                    success=False,
                    error=f"tool '{name}' not found",
                    params=params,
                ),
                permission=ToolPermission.FORBIDDEN,
                trace_id=trace_id,
            )

        permission = ToolPermission(tool.permission)
        if permission == ToolPermission.FORBIDDEN:
            return self._record(
                ToolResult(
                    tool_name=name,
                    success=False,
                    error="tool forbidden",
                    params=params,
                ),
                permission=permission,
                trace_id=trace_id,
            )
        if permission == ToolPermission.WRITE_WITH_CONFIRM and not confirmed:
            return self._record(
                ToolResult(
                    tool_name=name,
                    success=False,
                    error="confirmation required",
                    params=params,
                ),
                permission=permission,
                trace_id=trace_id,
            )

        return self._record(
            tool.run(params),
            permission=permission,
            trace_id=trace_id,
        )

    def _record(
        self,
        result: ToolResult,
        *,
        permission: ToolPermission,
        trace_id: str,
    ) -> ToolResult:
        call_id = f"tc_{uuid.uuid4().hex[:12]}"
        record = ToolCallRecord(
            call_id=call_id,
            trace_id=trace_id,
            tool_name=result.tool_name,
            params=_redact(result.params or {}),
            permission=permission,
            success=result.success,
            data_hash=(
                hashlib.sha256(
                    json.dumps(result.data, sort_keys=True, default=str).encode()
                ).hexdigest()
                if result.data is not None
                else None
            ),
            data_json=(
                json.dumps(
                    _redact(result.data),
                    sort_keys=True,
                    default=str,
                )
                if result.data is not None
                else None
            ),
            error=result.error,
            latency_ms=result.latency_ms,
        )
        self._audit_records.append(record)
        return ToolResult(
            tool_name=result.tool_name,
            success=result.success,
            data=result.data,
            error=result.error,
            latency_ms=result.latency_ms,
            params=result.params,
            call_id=call_id,
        )


def _redact(value: Any, key: str = "") -> Any:
    sensitive = {"api_key", "token", "password", "secret", "authorization"}
    if any(part in key.lower() for part in sensitive):
        return "***"
    if isinstance(value, dict):
        return {k: _redact(v, k) for k, v in value.items()}
    if isinstance(value, list):
        return [_redact(item, key) for item in value]
    if isinstance(value, tuple):
        return tuple(_redact(item, key) for item in value)
    return value
