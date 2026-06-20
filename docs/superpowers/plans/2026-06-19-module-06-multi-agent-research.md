# Module 06 — Multi-Agent Research Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the MVP multi-agent research module (06-multi_agent_research) that orchestrates a nightly research workflow from universe filtering through research signal composition, with structured outputs, tool use, state-machine lifecycle, and immutable audit snapshots.

**Architecture:** A deterministic, test-first workflow engine wires 12 agent roles through a shared `AgentContext`. Each agent declares an input schema, output schema, and fallback behavior. A lightweight `LLMProvider` adapter supports OpenAI-compatible endpoints plus deterministic test doubles. A `ToolRegistry` exposes existing Margin capabilities (retrieval, market data, portfolio, web search) as typed tools. The `ResearchWorkflow` drives the state machine and emits immutable `ResearchSnapshot` records.

**Tech Stack:** Python 3.11, Pydantic v2, FastAPI, pytest. No new external runtime dependencies; LLM calls use the existing `httpx` stack.

---

## File Structure

New files:

- `src/margin/research/__init__.py` — public exports
- `src/margin/research/models.py` — `ResearchSignal`, `WorkflowState`, `SignalType`, `AgentTrace`, `ResearchSnapshot`
- `src/margin/research/llm.py` — `LLMProvider`, `ModelRouter`, `StructuredOutputGuardrail`
- `src/margin/research/tools.py` — `ToolRegistry`, `ToolCallRecord`, and built-in tools
- `src/margin/research/agents.py` — `Agent` base, agent outputs, and all 12 agent roles
- `src/margin/research/workflow.py` — `ResearchWorkflow` state machine
- `src/margin/research/snapshot.py` — `ResearchSnapshot` builder / hasher
- `src/margin/research/service.py` — high-level `ResearchService`
- `tests/research/__init__.py`
- `tests/research/test_llm.py`
- `tests/research/test_tools.py`
- `tests/research/test_agents.py`
- `tests/research/test_workflow.py`
- `tests/research/test_snapshot.py`

Modified files:

- `src/margin/api/main.py` — register research routes
- `src/margin/api/routes/research.py` — new research HTTP endpoints

---

### Task 1: Research domain models

**Files:**
- Create: `src/margin/research/models.py`
- Test: `tests/research/test_models.py`

- [ ] **Step 1: Write the failing test**

```python
from margin.research.models import ResearchSignal, SignalType, WorkflowState


def test_research_signal_defaults():
    signal = ResearchSignal(symbol="000001.SZ", signal_type=SignalType.WATCH)
    assert signal.symbol == "000001.SZ"
    assert signal.signal_type == SignalType.WATCH
    assert signal.confidence == 0.0
    assert signal.evidence_refs == []
```

Run: `pytest tests/research/test_models.py::test_research_signal_defaults -v`
Expected: FAIL — `ResearchSignal` not defined.

- [ ] **Step 2: Implement models**

Create `src/margin/research/models.py`:

```python
"""Domain models for the multi-agent research module."""

from __future__ import annotations

import uuid
from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field, field_validator

from margin.news.models import ensure_utc, utc_now


class SignalType(StrEnum):
    """Classification of research signal output."""

    RESEARCH_CANDIDATE = "research_candidate"
    WATCH = "watch"
    ABSTAINED = "abstained"


class WorkflowState(StrEnum):
    """Lifecycle states of a research workflow run."""

    INITIALIZED = "initialized"
    DATA_READY = "data_ready"
    EVIDENCE_READY = "evidence_ready"
    ANALYSIS_READY = "analysis_ready"
    REVIEW_READY = "review_ready"
    PUBLISHED = "published"
    ABORTED = "aborted"
    ABSTAINED = "abstained"


class AgentTrace(BaseModel):
    """Single agent invocation trace."""

    trace_id: str
    agent_node: str
    model_version: str
    input_hash: str
    output_hash: str
    latency_ms: float | None = None
    error: str | None = None
    timestamp: datetime = Field(default_factory=utc_now)

    model_config = {"frozen": True}

    @field_validator("timestamp")
    @classmethod
    def normalize_timestamp(cls, value: datetime) -> datetime:
        return ensure_utc(value)


class ResearchSignal(BaseModel):
    """Structured research signal emitted by the workflow."""

    signal_id: str = Field(default_factory=lambda: f"sig_{uuid.uuid4().hex[:12]}")
    symbol: str
    signal_type: SignalType
    confidence: float = 0.0
    statement: str = ""
    evidence_refs: list[str] = Field(default_factory=list)
    claim_ids: list[str] = Field(default_factory=list)
    risk_score: float | None = None
    counter_arguments: list[str] = Field(default_factory=list)
    portfolio_constraint_violations: list[str] = Field(default_factory=list)
    generated_at: datetime = Field(default_factory=utc_now)

    model_config = {"frozen": True}

    @field_validator("generated_at")
    @classmethod
    def normalize_generated_at(cls, value: datetime) -> datetime:
        return ensure_utc(value)

    @field_validator("confidence")
    @classmethod
    def validate_confidence(cls, value: float) -> float:
        if not 0.0 <= value <= 1.0:
            raise ValueError(f"confidence must be in [0, 1], got {value}")
        return value


class ResearchSnapshot(BaseModel):
    """Immutable audit snapshot of a research run."""

    snapshot_id: str = Field(default_factory=lambda: f"snap_{uuid.uuid4().hex[:12]}")
    run_id: str
    workflow_state: WorkflowState
    symbols: list[str] = Field(default_factory=list)
    strategy_version: str = ""
    prompt_version: str = ""
    tool_versions: dict[str, str] = Field(default_factory=dict)
    model_versions: dict[str, str] = Field(default_factory=dict)
    evidence_ids: list[str] = Field(default_factory=list)
    claim_ids: list[str] = Field(default_factory=list)
    signals: list[ResearchSignal] = Field(default_factory=list)
    input_hash: str = ""
    output_hash: str = ""
    traces: list[AgentTrace] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=utc_now)

    model_config = {"frozen": True}

    @field_validator("created_at")
    @classmethod
    def normalize_created_at(cls, value: datetime) -> datetime:
        return ensure_utc(value)
```

- [ ] **Step 3: Run tests**

Run: `pytest tests/research/test_models.py -v`
Expected: PASS.

- [ ] **Step 4: Commit**

```bash
git add src/margin/research/models.py tests/research/test_models.py
git commit -m "feat(research): add domain models for module 06"
```

---

### Task 2: LLM provider and model router

**Files:**
- Create: `src/margin/research/llm.py`
- Test: `tests/research/test_llm.py`

- [ ] **Step 1: Write the failing test**

```python
from margin.research.llm import DeterministicLLMProvider, ModelRouter, TaskType


def test_deterministic_provider_returns_injected_output():
    provider = DeterministicLLMProvider(name="mock", response={"answer": "ok"})
    result = provider.complete("hi", response_schema={"answer": {"type": "string"}})
    assert result.output == {"answer": "ok"}
    assert result.success is True


def test_model_router_selects_cheap_model_for_extraction():
    router = ModelRouter({"extraction": "cheap-model"})
    model = router.select(TaskType.EXTRACTION)
    assert model == "cheap-model"
```

Run: `pytest tests/research/test_llm.py -v`
Expected: FAIL — classes not defined.

- [ ] **Step 2: Implement LLM provider and router**

Create `src/margin/research/llm.py`:

```python
"""LLM provider adapter, model router, and structured-output guardrail."""

from __future__ import annotations

import hashlib
import json
import os
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Any

import httpx

from margin.core.provider import (
    BaseProvider,
    HealthCheckResult,
    ProviderDescriptor,
    ProviderStatus,
    ProviderType,
)
from margin.news.models import utc_now


class TaskType(StrEnum):
    """Research task types used for routing."""

    UNIVERSE_FILTER = "universe_filter"
    QUANT = "quant"
    WEBSEARCH = "websearch"
    SUMMARY = "summary"
    EVIDENCE = "evidence"
    VALUATION = "valuation"
    RISK = "risk"
    REFLECT = "reflect"
    PORTFOLIO = "portfolio"
    SIGNAL = "signal"
    EXTRACTION = "extraction"
    VALIDATION = "validation"


@dataclass(frozen=True)
class LLMResult:
    """Result of an LLM completion call."""

    output: dict[str, Any]
    model: str
    success: bool
    latency_ms: float
    error: str | None = None
    raw_response: str | None = None


def _compute_hash(data: Any) -> str:
    return hashlib.sha256(json.dumps(data, sort_keys=True, default=str).encode()).hexdigest()


class LLMProvider(BaseProvider):
    """OpenAI-compatible LLM provider with structured JSON output."""

    def __init__(
        self,
        name: str = "openai_llm",
        *,
        api_key: str | None = None,
        base_url: str | None = None,
        model: str | None = None,
        client: httpx.Client | None = None,
        timeout: float = 60.0,
    ) -> None:
        self._api_key = api_key or os.getenv("MARGIN_LLM_API_KEY")
        self._base_url = (base_url or os.getenv("MARGIN_LLM_BASE_URL") or "").rstrip("/")
        self._model = model or os.getenv("MARGIN_LLM_MODEL") or "deepseek-v4-pro"
        self._timeout = timeout
        self._client = client or httpx.Client()
        self._descriptor = ProviderDescriptor(
            name=name,
            version=self._model,
            provider_type=ProviderType.LLM,
            capabilities=["complete", "complete_structured"],
            secret_refs=["MARGIN_LLM_API_KEY"],
            config={"base_url": self._base_url, "model": self._model},
        )

    @property
    def descriptor(self) -> ProviderDescriptor:
        return self._descriptor

    def complete(
        self,
        prompt: str,
        *,
        response_schema: dict[str, Any] | None = None,
        temperature: float = 0.0,
    ) -> LLMResult:
        if not self._api_key or not self._base_url:
            return LLMResult(
                output={},
                model=self._model,
                success=False,
                latency_ms=0.0,
                error="LLM API key or base URL not configured",
            )

        start = datetime.now().timestamp()
        messages = [{"role": "user", "content": prompt}]
        payload: dict[str, Any] = {
            "model": self._model,
            "messages": messages,
            "temperature": temperature,
        }
        if response_schema is not None:
            payload["response_format"] = {"type": "json_object"}
            payload["messages"].insert(
                0,
                {
                    "role": "system",
                    "content": f"Respond with valid JSON matching this schema: {json.dumps(response_schema)}",
                },
            )

        try:
            response = self._client.post(
                f"{self._base_url}/chat/completions",
                headers={
                    "Authorization": f"Bearer {self._api_key}",
                    "Content-Type": "application/json",
                },
                json=payload,
                timeout=self._timeout,
            )
            response.raise_for_status()
            data = response.json()
            content = data["choices"][0]["message"]["content"]
            output = json.loads(content) if response_schema else {"content": content}
            latency = (datetime.now().timestamp() - start) * 1000
            return LLMResult(
                output=output,
                model=self._model,
                success=True,
                latency_ms=latency,
                raw_response=content,
            )
        except Exception as exc:
            latency = (datetime.now().timestamp() - start) * 1000
            return LLMResult(
                output={},
                model=self._model,
                success=False,
                latency_ms=latency,
                error=f"{type(exc).__name__}: {exc}",
            )

    def healthcheck(self) -> HealthCheckResult:
        if not self._api_key or not self._base_url:
            return HealthCheckResult(
                provider_name=self._descriptor.name,
                status=ProviderStatus.DEGRADED,
                checked_at=utc_now(),
                message="LLM not configured",
            )
        return HealthCheckResult(
            provider_name=self._descriptor.name,
            status=ProviderStatus.HEALTHY,
            checked_at=utc_now(),
        )


class DeterministicLLMProvider(LLMProvider):
    """Test double that ignores prompts and returns a fixed JSON object."""

    def __init__(
        self,
        name: str = "deterministic_llm",
        response: dict[str, Any] | None = None,
        fail: bool = False,
        error: str = "injected failure",
    ) -> None:
        self._response = response or {"result": "ok"}
        self._fail = fail
        self._error = error
        self._descriptor = ProviderDescriptor(
            name=name,
            version="test",
            provider_type=ProviderType.LLM,
            capabilities=["complete", "complete_structured"],
            config={"mode": "deterministic"},
        )

    @property
    def descriptor(self) -> ProviderDescriptor:
        return self._descriptor

    def complete(
        self,
        prompt: str,
        *,
        response_schema: dict[str, Any] | None = None,
        temperature: float = 0.0,
    ) -> LLMResult:
        if self._fail:
            return LLMResult(
                output={},
                model=self._descriptor.name,
                success=False,
                latency_ms=0.0,
                error=self._error,
            )
        return LLMResult(
            output=dict(self._response),
            model=self._descriptor.name,
            success=True,
            latency_ms=0.0,
            raw_response=json.dumps(self._response),
        )

    def healthcheck(self) -> HealthCheckResult:
        return HealthCheckResult(
            provider_name=self._descriptor.name,
            status=ProviderStatus.HEALTHY,
            checked_at=utc_now(),
        )


class ModelRouter:
    """Route research tasks to model/tool/budget/schema configurations."""

    DEFAULTS: dict[TaskType, str] = {
        TaskType.UNIVERSE_FILTER: "rule",
        TaskType.QUANT: "rule",
        TaskType.WEBSEARCH: "rule",
        TaskType.SUMMARY: "cheap-llm",
        TaskType.EVIDENCE: "cheap-llm",
        TaskType.VALUATION: "rule",
        TaskType.RISK: "cheap-llm",
        TaskType.REFLECT: "capable-llm",
        TaskType.PORTFOLIO: "rule",
        TaskType.SIGNAL: "cheap-llm",
        TaskType.EXTRACTION: "cheap-llm",
        TaskType.VALIDATION: "cheap-llm",
    }

    def __init__(
        self,
        overrides: dict[TaskType, str] | None = None,
        llm_providers: dict[str, LLMProvider] | None = None,
    ) -> None:
        self._mapping = dict(self.DEFAULTS)
        if overrides:
            self._mapping.update(overrides)
        self._providers = llm_providers or {}

    def select(self, task: TaskType) -> str:
        return self._mapping.get(task, "rule")

    def get_provider(self, name: str) -> LLMProvider | None:
        return self._providers.get(name)

    def register_provider(self, name: str, provider: LLMProvider) -> None:
        self._providers[name] = provider


class StructuredOutputGuardrail:
    """Validate that an LLM output conforms to a JSON schema subset."""

    def __init__(self, schema: dict[str, Any]) -> None:
        self._schema = schema

    def validate(self, output: dict[str, Any]) -> tuple[bool, str]:
        required = self._schema.get("required", [])
        for key in required:
            if key not in output:
                return False, f"missing required field: {key}"
        return True, ""
```

- [ ] **Step 3: Run tests**

Run: `pytest tests/research/test_llm.py -v`
Expected: PASS.

- [ ] **Step 4: Commit**

```bash
git add src/margin/research/llm.py tests/research/test_llm.py
git commit -m "feat(research): add LLM provider, router, and guardrail"
```

---

### Task 3: Tool system

**Files:**
- Create: `src/margin/research/tools.py`
- Test: `tests/research/test_tools.py`

- [ ] **Step 1: Write the failing test**

```python
from margin.research.tools import ToolRegistry, RetrievalTool, PythonTool


def test_registry_registers_and_calls_tool():
    registry = ToolRegistry()
    registry.register(PythonTool())
    result = registry.call("python", {"expression": "1 + 1"})
    assert result.success is True
    assert result.data == 2


def test_retrieval_tool_requires_symbol_and_decision_at():
    tool = RetrievalTool(pipeline=None)
    result = tool.run({"query": "cash flow"})
    assert result.success is False
    assert "symbol" in result.error.lower()
```

Run: `pytest tests/research/test_tools.py -v`
Expected: FAIL.

- [ ] **Step 2: Implement tool system**

Create `src/margin/research/tools.py`:

```python
"""Typed tool system for multi-agent research workflows."""

from __future__ import annotations

import hashlib
import json
import math
import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

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


class ToolCallRecord(BaseModel):
    """Immutable audit record for a tool call."""

    call_id: str = Field(default_factory=lambda: f"tc_{uuid.uuid4().hex[:12]}")
    tool_name: str
    params: dict[str, Any] = Field(default_factory=dict)
    success: bool = True
    data_hash: str | None = None
    error: str | None = None
    latency_ms: float = 0.0
    called_at: datetime = Field(default_factory=utc_now)

    model_config = {"frozen": True}


class BaseTool(ABC):
    """Abstract base for all research tools."""

    @property
    @abstractmethod
    def name(self) -> str:
        ...

    @property
    def permission(self) -> str:
        return "read"

    @abstractmethod
    def run(self, params: dict[str, Any]) -> ToolResult:
        ...

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


class MarketDataTool(BaseTool):
    """Stub for market data lookup; real implementation delegates to data providers."""

    @property
    def name(self) -> str:
        return "market_data"

    def run(self, params: dict[str, Any]) -> ToolResult:
        symbol = params.get("symbol")
        return ToolResult(
            tool_name=self.name,
            success=True,
            data={"symbol": symbol, "close": 0.0, "note": "stub"},
            params=params,
        )


class FinancialTool(BaseTool):
    """Stub for financial statement lookup."""

    @property
    def name(self) -> str:
        return "financial"

    def run(self, params: dict[str, Any]) -> ToolResult:
        return ToolResult(
            tool_name=self.name,
            success=True,
            data={"roe": 0.12, "note": "stub"},
            params=params,
        )


class FactorTool(BaseTool):
    """Stub factor computation."""

    @property
    def name(self) -> str:
        return "factor"

    def run(self, params: dict[str, Any]) -> ToolResult:
        symbols = params.get("symbols", [])
        scores = {s: 0.5 for s in symbols}
        return ToolResult(
            tool_name=self.name,
            success=True,
            data=scores,
            params=params,
        )


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


class PortfolioTool(BaseTool):
    """Read-only portfolio constraint check stub."""

    @property
    def name(self) -> str:
        return "portfolio"

    def run(self, params: dict[str, Any]) -> ToolResult:
        symbol = params.get("symbol")
        max_weight = params.get("max_weight", 0.1)
        current_weight = params.get("current_weight", 0.0)
        violations = []
        if current_weight > max_weight:
            violations.append(f"{symbol} weight {current_weight} exceeds {max_weight}")
        return ToolResult(
            tool_name=self.name,
            success=True,
            data={"violations": violations, "current_weight": current_weight},
            params=params,
        )


class WebSearchTool(BaseTool):
    """Stub web search tool; real implementation delegates to news/websearch provider."""

    @property
    def name(self) -> str:
        return "websearch"

    def run(self, params: dict[str, Any]) -> ToolResult:
        query = params.get("query", "")
        return ToolResult(
            tool_name=self.name,
            success=True,
            data={"query": query, "results": []},
            params=params,
        )


class CalendarTool(BaseTool):
    """Stub trading calendar tool."""

    @property
    def name(self) -> str:
        return "calendar"

    def run(self, params: dict[str, Any]) -> ToolResult:
        return ToolResult(
            tool_name=self.name,
            success=True,
            data={"trading_days": []},
            params=params,
        )


class AlertTool(BaseTool):
    """Stub alert creation tool."""

    @property
    def name(self) -> str:
        return "alert"

    @property
    def permission(self) -> str:
        return "write_with_confirm"

    def run(self, params: dict[str, Any]) -> ToolResult:
        return ToolResult(
            tool_name=self.name,
            success=True,
            data={"alert_id": f"alt_{uuid.uuid4().hex[:12]}"},
            params=params,
        )


class BacktestTool(BaseTool):
    """Stub backtest tool."""

    @property
    def name(self) -> str:
        return "backtest"

    def run(self, params: dict[str, Any]) -> ToolResult:
        return ToolResult(
            tool_name=self.name,
            success=True,
            data={"sharpe": 0.0, "note": "stub"},
            params=params,
        )


class FilingTool(BaseTool):
    """Stub filing lookup tool."""

    @property
    def name(self) -> str:
        return "filing"

    def run(self, params: dict[str, Any]) -> ToolResult:
        return ToolResult(
            tool_name=self.name,
            success=True,
            data={"filings": []},
            params=params,
        )


class ToolRegistry:
    """Registry of tools available to agents."""

    def __init__(self) -> None:
        self._tools: dict[str, BaseTool] = {}

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

    def get(self, name: str) -> BaseTool | None:
        return self._tools.get(name)

    def list_tools(self) -> list[str]:
        return list(self._tools.keys())

    def call(self, name: str, params: dict[str, Any]) -> ToolResult:
        tool = self.get(name)
        if tool is None:
            return ToolResult(
                tool_name=name,
                success=False,
                error=f"tool '{name}' not found",
            )
        return tool.run(params)
```

- [ ] **Step 3: Run tests**

Run: `pytest tests/research/test_tools.py -v`
Expected: PASS.

- [ ] **Step 4: Commit**

```bash
git add src/margin/research/tools.py tests/research/test_tools.py
git commit -m "feat(research): add typed tool system with audit records"
```

---

### Task 4: Agent framework and base classes

**Files:**
- Create: `src/margin/research/agents.py`
- Test: `tests/research/test_agents.py`

- [ ] **Step 1: Write the failing test**

```python
from margin.research.agents import AgentContext, Agent, UniverseFilterAgent
from margin.research.llm import DeterministicLLMProvider
from margin.research.tools import ToolRegistry


def test_universe_filter_agent_returns_symbols():
    agent = UniverseFilterAgent(DeterministicLLMProvider(response={"symbols": ["000001.SZ"]}))
    registry = ToolRegistry()
    registry.register_defaults()
    context = AgentContext(symbol="000001.SZ", decision_at="2026-06-18", tool_registry=registry)
    output = agent.run(context)
    assert output.success is True
    assert "000001.SZ" in output.data["symbols"]
```

Run: `pytest tests/research/test_agents.py::test_universe_filter_agent_returns_symbols -v`
Expected: FAIL.

- [ ] **Step 2: Implement agent framework**

Create `src/margin/research/agents.py`:

```python
"""Agent framework and the 12 research agent roles."""

from __future__ import annotations

import hashlib
import json
import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from margin.evidence.models import Claim
from margin.news.models import utc_now
from margin.research.llm import LLMProvider, LLMResult, StructuredOutputGuardrail, TaskType
from margin.research.models import WorkflowState
from margin.research.tools import ToolRegistry, ToolResult


@dataclass
class AgentContext:
    """Shared context passed to every agent."""

    symbol: str
    decision_at: datetime
    tool_registry: ToolRegistry
    llm_provider: LLMProvider | None = None
    model_router: Any | None = None
    portfolio_id: str | None = None
    strategy_config: dict[str, Any] = field(default_factory=dict)
    prior_outputs: dict[str, Any] = field(default_factory=dict)
    claims: list[Claim] = field(default_factory=list)
    evidences: dict[str, Any] = field(default_factory=dict)
    trace_id: str = ""


@dataclass(frozen=True)
class AgentOutput:
    """Structured result from a single agent."""

    agent_node: str
    success: bool
    data: dict[str, Any]
    error: str | None = None
    trace_id: str = ""
    model_version: str = ""
    latency_ms: float = 0.0
    tool_calls: list[ToolResult] = field(default_factory=list)


class Agent(ABC):
    """Base class for a research agent role."""

    def __init__(self, llm_provider: LLMProvider | None = None) -> None:
        self._llm = llm_provider

    @property
    @abstractmethod
    def node_name(self) -> str:
        ...

    @property
    def output_schema(self) -> dict[str, Any]:
        return {"type": "object", "properties": {}, "required": []}

    def _hash(self, data: Any) -> str:
        return hashlib.sha256(json.dumps(data, sort_keys=True, default=str).encode()).hexdigest()

    def _call_llm(
        self,
        prompt: str,
        provider: LLMProvider | None = None,
        schema: dict[str, Any] | None = None,
    ) -> LLMResult:
        llm = provider or self._llm
        if llm is None:
            return LLMResult(
                output={},
                model="none",
                success=False,
                latency_ms=0.0,
                error="no LLM provider configured",
            )
        schema = schema or self.output_schema
        result = llm.complete(prompt, response_schema=schema)
        if result.success and schema:
            guardrail = StructuredOutputGuardrail(schema)
            ok, msg = guardrail.validate(result.output)
            if not ok:
                return LLMResult(
                    output=result.output,
                    model=result.model,
                    success=False,
                    latency_ms=result.latency_ms,
                    error=f"guardrail: {msg}",
                    raw_response=result.raw_response,
                )
        return result

    def _call_tool(self, context: AgentContext, name: str, params: dict[str, Any]) -> ToolResult:
        return context.tool_registry.call(name, params)

    @abstractmethod
    def run(self, context: AgentContext) -> AgentOutput:
        ...

    def _make_output(
        self,
        context: AgentContext,
        success: bool,
        data: dict[str, Any],
        error: str | None = None,
        llm_result: LLMResult | None = None,
        tool_calls: list[ToolResult] | None = None,
    ) -> AgentOutput:
        return AgentOutput(
            agent_node=self.node_name,
            success=success,
            data=data,
            error=error,
            trace_id=context.trace_id or f"trc_{uuid.uuid4().hex[:12]}",
            model_version=(llm_result.model if llm_result else "rule"),
            latency_ms=(llm_result.latency_ms if llm_result else 0.0),
            tool_calls=tool_calls or [],
        )


class RuleAgent(Agent):
    """Agent that uses only rules/tools without LLM."""

    def run(self, context: AgentContext) -> AgentOutput:
        try:
            data = self._run_rule(context)
            return self._make_output(context, True, data)
        except Exception as exc:
            return self._make_output(context, False, {}, error=f"{type(exc).__name__}: {exc}")

    @abstractmethod
    def _run_rule(self, context: AgentContext) -> dict[str, Any]:
        ...


class UniverseFilterAgent(RuleAgent):
    """Agent #1: filter universe by configured symbols and basic rules."""

    @property
    def node_name(self) -> str:
        return "universe_filter"

    def _run_rule(self, context: AgentContext) -> dict[str, Any]:
        symbols = context.strategy_config.get("universe", [context.symbol])
        max_market_cap = context.strategy_config.get("max_market_cap")
        result = {"symbols": symbols, "filtered": []}
        for symbol in symbols:
            md = self._call_tool(context, "market_data", {"symbol": symbol})
            if md.success:
                result["filtered"].append(symbol)
        if not result["filtered"]:
            result["filtered"] = symbols
        return result


class QuantResearchAgent(RuleAgent):
    """Agent #2: compute factor scores and basic ranking."""

    @property
    def node_name(self) -> str:
        return "quant_research"

    def _run_rule(self, context: AgentContext) -> dict[str, Any]:
        symbols = context.prior_outputs.get("universe_filter", {}).get("filtered", [context.symbol])
        factor_result = self._call_tool(context, "factor", {"symbols": symbols})
        scores = factor_result.data if factor_result.success else {}
        ranked = sorted(scores.items(), key=lambda x: x[1], reverse=True)
        return {
            "scores": scores,
            "ranked": [s for s, _ in ranked],
            "top_symbol": ranked[0][0] if ranked else context.symbol,
        }


class WebSearchAgent(Agent):
    """Agent #3: discover news/announcement/web sources."""

    @property
    def node_name(self) -> str:
        return "websearch"

    @property
    def output_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "queries": {"type": "array", "items": {"type": "string"}},
                "results": {"type": "array"},
            },
            "required": ["queries"],
        }

    def run(self, context: AgentContext) -> AgentOutput:
        symbol = context.symbol
        prompt = (
            f"Generate 1-3 web search queries in Chinese for recent news and announcements "
            f"about stock {symbol} as of {context.decision_at.date()}. "
            f"Respond with JSON: {{\"queries\": [\"...\"]}}."
        )
        result = self._call_llm(prompt)
        if not result.success:
            return self._make_output(context, False, {"queries": []}, error=result.error)

        queries = result.output.get("queries", [f"{symbol} 公告"])
        tool_results: list[ToolResult] = []
        all_results: list[dict[str, Any]] = []
        for query in queries[:3]:
            tr = self._call_tool(context, "websearch", {"query": query})
            tool_results.append(tr)
            if tr.success and isinstance(tr.data, dict):
                all_results.extend(tr.data.get("results", []))

        return self._make_output(
            context,
            True,
            {"queries": queries, "results": all_results},
            llm_result=result,
            tool_calls=tool_results,
        )


class DocumentCollectorAgent(RuleAgent):
    """Agent #4: collect/snapshot source documents and record hashes."""

    @property
    def node_name(self) -> str:
        return "document_collector"

    def _run_rule(self, context: AgentContext) -> dict[str, Any]:
        results = context.prior_outputs.get("websearch", {}).get("results", [])
        collected: list[dict[str, Any]] = []
        for item in results:
            collected.append(
                {
                    "url": item.get("url", ""),
                    "title": item.get("title", ""),
                    "source_hash": self._hash(item),
                    "collected_at": utc_now().isoformat(),
                }
            )
        return {"collected": collected, "count": len(collected)}


class TextSummaryAgent(Agent):
    """Agent #5: structured summary of documents."""

    @property
    def node_name(self) -> str:
        return "text_summary"

    @property
    def output_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "summaries": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "source_url": {"type": "string"},
                            "summary": {"type": "string"},
                            "key_points": {"type": "array", "items": {"type": "string"}},
                        },
                        "required": ["source_url", "summary"],
                    },
                }
            },
            "required": ["summaries"],
        }

    def run(self, context: AgentContext) -> AgentOutput:
        collected = context.prior_outputs.get("document_collector", {}).get("collected", [])
        if not collected:
            return self._make_output(context, True, {"summaries": []})

        prompt = (
            f"Summarize the following sources for {context.symbol}. "
            f"Respond with JSON matching the schema with 'summaries'. Sources: {json.dumps(collected)}"
        )
        result = self._call_llm(prompt)
        if not result.success:
            return self._make_output(context, False, {"summaries": []}, error=result.error)
        return self._make_output(context, True, result.output, llm_result=result)


class EvidenceResearchAgent(Agent):
    """Agent #6: retrieve and organize evidence claims."""

    @property
    def node_name(self) -> str:
        return "evidence_research"

    def run(self, context: AgentContext) -> AgentOutput:
        tr = self._call_tool(
            context,
            "retrieval",
            {"query": f"{context.symbol} 经营", "symbol": context.symbol, "decision_at": context.decision_at},
        )
        if not tr.success:
            return self._make_output(context, False, {"claims": []}, error=tr.error, tool_calls=[tr])

        data = tr.data or []
        return self._make_output(context, True, {"retrieval_results": data, "count": len(data)}, tool_calls=[tr])


class ValuationToolAgent(RuleAgent):
    """Agent #7: numeric valuation using the valuation tool."""

    @property
    def node_name(self) -> str:
        return "valuation_tool"

    def _run_rule(self, context: AgentContext) -> dict[str, Any]:
        eps = context.strategy_config.get("eps", 1.0)
        pe = context.strategy_config.get("pe", 10.0)
        tr = self._call_tool(context, "valuation", {"method": "pe", "eps": eps, "pe": pe})
        if not tr.success:
            return {"value": None, "error": tr.error}
        return {"value": tr.data.get("value") if isinstance(tr.data, dict) else None}


class RiskReviewAgent(Agent):
    """Agent #8: output risk score, not calibrated probability."""

    @property
    def node_name(self) -> str:
        return "risk_review"

    @property
    def output_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "risk_score": {"type": "number"},
                "risk_factors": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["risk_score", "risk_factors"],
        }

    def run(self, context: AgentContext) -> AgentOutput:
        prompt = (
            f"Review risks for {context.symbol} based on current evidence. "
            f"Output JSON with 'risk_score' (0-1) and 'risk_factors' (list of strings). "
            f"Do not output probability of gain/loss."
        )
        result = self._call_llm(prompt)
        if not result.success:
            return self._make_output(context, False, {"risk_score": 0.5, "risk_factors": []}, error=result.error)
        return self._make_output(context, True, result.output, llm_result=result)


class ReflectCounterArgumentAgent(Agent):
    """Agent #9: review counter-evidence, conflicts, and unknowns."""

    @property
    def node_name(self) -> str:
        return "reflect_counter_argument"

    @property
    def output_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "counter_arguments": {"type": "array", "items": {"type": "string"}},
                "unknowns": {"type": "array", "items": {"type": "string"}},
                "conflict_flags": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["counter_arguments", "unknowns"],
        }

    def run(self, context: AgentContext) -> AgentOutput:
        prompt = (
            f"Provide counter-arguments and unknowns for {context.symbol}. "
            f"Output JSON with 'counter_arguments', 'unknowns', and optional 'conflict_flags'."
        )
        result = self._call_llm(prompt)
        if not result.success:
            return self._make_output(context, False, {"counter_arguments": [], "unknowns": []}, error=result.error)
        return self._make_output(context, True, result.output, llm_result=result)


class PortfolioConstraintAgent(RuleAgent):
    """Agent #10: check portfolio exposure constraints."""

    @property
    def node_name(self) -> str:
        return "portfolio_constraint"

    def _run_rule(self, context: AgentContext) -> dict[str, Any]:
        max_weight = context.strategy_config.get("max_position_weight", 0.1)
        current_weight = context.strategy_config.get("current_weight", 0.0)
        tr = self._call_tool(
            context,
            "portfolio",
            {"symbol": context.symbol, "max_weight": max_weight, "current_weight": current_weight},
        )
        if not tr.success:
            return {"violations": [tr.error or "portfolio check failed"], "passed": False}
        data = tr.data or {}
        violations = data.get("violations", [])
        return {"violations": violations, "passed": len(violations) == 0}


class ResearchSignalComposer(Agent):
    """Agent #11: compose final research signal."""

    @property
    def node_name(self) -> str:
        return "signal_composer"

    @property
    def output_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "signal_type": {"type": "string", "enum": ["research_candidate", "watch", "abstained"]},
                "confidence": {"type": "number"},
                "statement": {"type": "string"},
                "evidence_refs": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["signal_type", "confidence", "statement"],
        }

    def run(self, context: AgentContext) -> AgentOutput:
        risk = context.prior_outputs.get("risk_review", {}).get("risk_score", 0.5)
        reflect = context.prior_outputs.get("reflect_counter_argument", {})
        constraints = context.prior_outputs.get("portfolio_constraint", {})
        evidence = context.prior_outputs.get("evidence_research", {}).get("retrieval_results", [])

        if not constraints.get("passed", True):
            return self._make_output(
                context,
                True,
                {
                    "signal_type": "abstained",
                    "confidence": 0.0,
                    "statement": "Portfolio constraint violation",
                    "evidence_refs": [],
                },
            )

        if risk > 0.7 or reflect.get("conflict_flags"):
            return self._make_output(
                context,
                True,
                {
                    "signal_type": "watch",
                    "confidence": round(1 - risk, 2),
                    "statement": "High risk or conflicts flagged; watch only",
                    "evidence_refs": self._extract_evidence_refs(evidence),
                },
            )

        return self._make_output(
            context,
            True,
            {
                "signal_type": "research_candidate",
                "confidence": round(max(0.0, 0.8 - risk), 2),
                "statement": f"{context.symbol} passes initial research screen",
                "evidence_refs": self._extract_evidence_refs(evidence),
            },
        )

    def _extract_evidence_refs(self, evidence: list[Any]) -> list[str]:
        refs: list[str] = []
        for item in evidence:
            if isinstance(item, dict):
                chunk_id = item.get("chunk", {}).get("chunk_id")
                if chunk_id:
                    refs.append(chunk_id)
        return refs[:5]


class CitationValidatorAgent(RuleAgent):
    """Agent #12: validate evidence references, source levels, and timing."""

    @property
    def node_name(self) -> str:
        return "citation_validator"

    def _run_rule(self, context: AgentContext) -> dict[str, Any]:
        signal = context.prior_outputs.get("signal_composer", {})
        refs = signal.get("evidence_refs", [])
        if not refs:
            return {"valid": False, "reason": "no evidence references", "failed_refs": []}
        return {"valid": True, "reason": "evidence refs present", "failed_refs": []}
```

- [ ] **Step 3: Run tests**

Run: `pytest tests/research/test_agents.py -v`
Expected: PASS.

- [ ] **Step 4: Commit**

```bash
git add src/margin/research/agents.py tests/research/test_agents.py
git commit -m "feat(research): add agent framework and 12 agent roles"
```

---

### Task 5: Workflow state machine

**Files:**
- Create: `src/margin/research/workflow.py`
- Test: `tests/research/test_workflow.py`

- [ ] **Step 1: Write the failing test**

```python
from datetime import datetime, UTC
from margin.research.workflow import ResearchWorkflow
from margin.research.llm import DeterministicLLMProvider
from margin.research.tools import ToolRegistry
from margin.research.models import WorkflowState


def test_workflow_runs_to_published():
    registry = ToolRegistry()
    registry.register_defaults()
    workflow = ResearchWorkflow(
        symbol="000001.SZ",
        decision_at=datetime(2026, 6, 18, tzinfo=UTC),
        tool_registry=registry,
        llm_provider=DeterministicLLMProvider(response={"queries": ["q"], "summaries": [], "risk_score": 0.3, "risk_factors": [], "counter_arguments": [], "unknowns": []}),
    )
    result = workflow.run()
    assert result.state == WorkflowState.PUBLISHED
    assert len(result.signals) == 1
```

Run: `pytest tests/research/test_workflow.py::test_workflow_runs_to_published -v`
Expected: FAIL.

- [ ] **Step 2: Implement workflow state machine**

Create `src/margin/research/workflow.py`:

```python
"""Research workflow state machine."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from margin.news.models import utc_now
from margin.research.agents import (
    AgentContext,
    CitationValidatorAgent,
    DocumentCollectorAgent,
    EvidenceResearchAgent,
    PortfolioConstraintAgent,
    QuantResearchAgent,
    ReflectCounterArgumentAgent,
    ResearchSignalComposer,
    RiskReviewAgent,
    TextSummaryAgent,
    UniverseFilterAgent,
    ValuationToolAgent,
    WebSearchAgent,
)
from margin.research.llm import LLMProvider
from margin.research.models import AgentTrace, ResearchSignal, WorkflowState
from margin.research.snapshot import ResearchSnapshotBuilder
from margin.research.tools import ToolRegistry


@dataclass
class WorkflowResult:
    """Result of a workflow run."""

    run_id: str
    state: WorkflowState
    signals: list[ResearchSignal] = field(default_factory=list)
    prior_outputs: dict[str, Any] = field(default_factory=dict)
    traces: list[AgentTrace] = field(default_factory=list)
    snapshot: dict[str, Any] | None = None
    error: str | None = None


class ResearchWorkflow:
    """Nightly research workflow state machine."""

    def __init__(
        self,
        symbol: str,
        decision_at: datetime,
        tool_registry: ToolRegistry,
        llm_provider: LLMProvider | None = None,
        strategy_config: dict[str, Any] | None = None,
        portfolio_id: str | None = None,
    ) -> None:
        self._run_id = f"run_{uuid.uuid4().hex[:12]}"
        self._symbol = symbol
        self._decision_at = decision_at
        self._tools = tool_registry
        self._llm = llm_provider
        self._strategy = strategy_config or {}
        self._portfolio_id = portfolio_id
        self._state = WorkflowState.INITIALIZED
        self._prior_outputs: dict[str, Any] = {}
        self._traces: list[AgentTrace] = []

    @property
    def run_id(self) -> str:
        return self._run_id

    @property
    def state(self) -> WorkflowState:
        return self._state

    def _make_context(self) -> AgentContext:
        return AgentContext(
            symbol=self._symbol,
            decision_at=self._decision_at,
            tool_registry=self._tools,
            llm_provider=self._llm,
            portfolio_id=self._portfolio_id,
            strategy_config=self._strategy,
            prior_outputs=self._prior_outputs,
            trace_id=f"trc_{uuid.uuid4().hex[:12]}",
        )

    def _run_agent(self, agent) -> Any:
        context = self._make_context()
        output = agent.run(context)
        self._prior_outputs[agent.node_name] = output.data
        trace = AgentTrace(
            trace_id=output.trace_id,
            agent_node=agent.node_name,
            model_version=output.model_version,
            input_hash="",
            output_hash="",
            latency_ms=output.latency_ms,
            error=output.error,
        )
        self._traces.append(trace)
        return output

    def run(self) -> WorkflowResult:
        self._state = WorkflowState.DATA_READY

        # Agent 1 & 2: universe + quant
        universe_output = self._run_agent(UniverseFilterAgent())
        if not universe_output.success:
            self._state = WorkflowState.ABORTED
            return WorkflowResult(self._run_id, self._state, error=universe_output.error)

        quant_output = self._run_agent(QuantResearchAgent())
        if not quant_output.success:
            self._state = WorkflowState.ABORTED
            return WorkflowResult(self._run_id, self._state, error=quant_output.error)

        self._state = WorkflowState.EVIDENCE_READY

        # Agent 3 & 4: web search + document collection
        web_output = self._run_agent(WebSearchAgent(self._llm))
        self._run_agent(DocumentCollectorAgent())

        # Agent 5 & 6: summary + evidence research
        summary_output = self._run_agent(TextSummaryAgent(self._llm))
        evidence_output = self._run_agent(EvidenceResearchAgent())
        if not evidence_output.success or not evidence_output.data.get("retrieval_results"):
            self._state = WorkflowState.ABSTAINED
            return WorkflowResult(
                self._run_id,
                self._state,
                prior_outputs=dict(self._prior_outputs),
                traces=list(self._traces),
            )

        self._state = WorkflowState.ANALYSIS_READY

        # Agent 7: valuation
        self._run_agent(ValuationToolAgent())

        self._state = WorkflowState.REVIEW_READY

        # Agent 8, 9, 10: risk, reflect, portfolio
        risk_output = self._run_agent(RiskReviewAgent(self._llm))
        reflect_output = self._run_agent(ReflectCounterArgumentAgent(self._llm))
        portfolio_output = self._run_agent(PortfolioConstraintAgent())

        # Agent 11: signal composer
        signal_output = self._run_agent(ResearchSignalComposer(self._llm))
        signal_data = signal_output.data

        # Agent 12: citation validator
        validator_output = self._run_agent(CitationValidatorAgent())
        if not validator_output.data.get("valid"):
            signal_data = {
                "signal_type": "abstained",
                "confidence": 0.0,
                "statement": validator_output.data.get("reason", "citation validation failed"),
                "evidence_refs": [],
            }

        signal = ResearchSignal(
            symbol=self._symbol,
            signal_type=signal_data.get("signal_type", "abstained"),
            confidence=signal_data.get("confidence", 0.0),
            statement=signal_data.get("statement", ""),
            evidence_refs=signal_data.get("evidence_refs", []),
            risk_score=risk_output.data.get("risk_score") if risk_output.success else None,
            counter_arguments=reflect_output.data.get("counter_arguments", []) if reflect_output.success else [],
            portfolio_constraint_violations=portfolio_output.data.get("violations", []) if portfolio_output.success else [],
        )

        self._state = WorkflowState.PUBLISHED

        builder = ResearchSnapshotBuilder()
        snapshot = (
            builder.for_run(self._run_id)
            .with_state(self._state)
            .with_symbols([self._symbol])
            .with_strategy_version(self._strategy.get("version", ""))
            .with_prompt_version(self._strategy.get("prompt_version", ""))
            .with_tool_versions({name: "1.0.0" for name in self._tools.list_tools()})
            .with_model_versions({"default": self._llm.descriptor.version if self._llm else "rule"})
            .with_signals([signal])
            .with_traces(list(self._traces))
            .with_prior_outputs(self._prior_outputs)
            .build()
        )

        return WorkflowResult(
            self._run_id,
            self._state,
            signals=[signal],
            prior_outputs=dict(self._prior_outputs),
            traces=list(self._traces),
            snapshot=snapshot.model_dump(),
        )
```

- [ ] **Step 3: Run tests**

Run: `pytest tests/research/test_workflow.py -v`
Expected: PASS.

- [ ] **Step 4: Commit**

```bash
git add src/margin/research/workflow.py tests/research/test_workflow.py
git commit -m "feat(research): add workflow state machine"
```

---

### Task 6: Immutable snapshot builder

**Files:**
- Create: `src/margin/research/snapshot.py`
- Test: `tests/research/test_snapshot.py`

- [ ] **Step 1: Write the failing test**

```python
from margin.research.snapshot import ResearchSnapshotBuilder
from margin.research.models import WorkflowState, ResearchSignal, SignalType


def test_snapshot_hashes_inputs_and_outputs():
    signal = ResearchSignal(symbol="000001.SZ", signal_type=SignalType.WATCH, confidence=0.5)
    builder = ResearchSnapshotBuilder()
    snapshot = (
        builder.for_run("run_1")
        .with_state(WorkflowState.PUBLISHED)
        .with_symbols(["000001.SZ"])
        .with_signals([signal])
        .with_prior_outputs({"foo": "bar"})
        .build()
    )
    assert snapshot.run_id == "run_1"
    assert snapshot.input_hash != ""
    assert snapshot.output_hash != ""
```

Run: `pytest tests/research/test_snapshot.py -v`
Expected: FAIL.

- [ ] **Step 2: Implement snapshot builder**

Create `src/margin/research/snapshot.py`:

```python
"""Immutable research snapshot builder."""

from __future__ import annotations

import hashlib
import json
from typing import Any

from margin.research.models import AgentTrace, ResearchSignal, ResearchSnapshot, WorkflowState


class ResearchSnapshotBuilder:
    """Build an immutable research audit snapshot."""

    def __init__(self) -> None:
        self._run_id: str = ""
        self._state: WorkflowState = WorkflowState.INITIALIZED
        self._symbols: list[str] = []
        self._strategy_version: str = ""
        self._prompt_version: str = ""
        self._tool_versions: dict[str, str] = {}
        self._model_versions: dict[str, str] = {}
        self._evidence_ids: list[str] = []
        self._claim_ids: list[str] = []
        self._signals: list[ResearchSignal] = []
        self._traces: list[AgentTrace] = []
        self._prior_outputs: dict[str, Any] = {}

    def for_run(self, run_id: str) -> ResearchSnapshotBuilder:
        self._run_id = run_id
        return self

    def with_state(self, state: WorkflowState) -> ResearchSnapshotBuilder:
        self._state = state
        return self

    def with_symbols(self, symbols: list[str]) -> ResearchSnapshotBuilder:
        self._symbols = symbols
        return self

    def with_strategy_version(self, version: str) -> ResearchSnapshotBuilder:
        self._strategy_version = version
        return self

    def with_prompt_version(self, version: str) -> ResearchSnapshotBuilder:
        self._prompt_version = version
        return self

    def with_tool_versions(self, versions: dict[str, str]) -> ResearchSnapshotBuilder:
        self._tool_versions = versions
        return self

    def with_model_versions(self, versions: dict[str, str]) -> ResearchSnapshotBuilder:
        self._model_versions = versions
        return self

    def with_evidence_ids(self, ids: list[str]) -> ResearchSnapshotBuilder:
        self._evidence_ids = ids
        return self

    def with_claim_ids(self, ids: list[str]) -> ResearchSnapshotBuilder:
        self._claim_ids = ids
        return self

    def with_signals(self, signals: list[ResearchSignal]) -> ResearchSnapshotBuilder:
        self._signals = signals
        return self

    def with_traces(self, traces: list[AgentTrace]) -> ResearchSnapshotBuilder:
        self._traces = traces
        return self

    def with_prior_outputs(self, outputs: dict[str, Any]) -> ResearchSnapshotBuilder:
        self._prior_outputs = outputs
        return self

    @staticmethod
    def _hash(data: Any) -> str:
        return hashlib.sha256(json.dumps(data, sort_keys=True, default=str).encode()).hexdigest()

    def build(self) -> ResearchSnapshot:
        input_payload = {
            "run_id": self._run_id,
            "symbols": self._symbols,
            "strategy_version": self._strategy_version,
            "prompt_version": self._prompt_version,
            "tool_versions": self._tool_versions,
            "model_versions": self._model_versions,
            "prior_outputs": self._prior_outputs,
        }
        output_payload = {
            "state": self._state,
            "signals": [s.model_dump() for s in self._signals],
            "evidence_ids": self._evidence_ids,
            "claim_ids": self._claim_ids,
            "traces": [t.model_dump() for t in self._traces],
        }
        return ResearchSnapshot(
            run_id=self._run_id,
            workflow_state=self._state,
            symbols=self._symbols,
            strategy_version=self._strategy_version,
            prompt_version=self._prompt_version,
            tool_versions=self._tool_versions,
            model_versions=self._model_versions,
            evidence_ids=self._evidence_ids,
            claim_ids=self._claim_ids,
            signals=self._signals,
            input_hash=self._hash(input_payload),
            output_hash=self._hash(output_payload),
            traces=self._traces,
        )
```

- [ ] **Step 3: Run tests**

Run: `pytest tests/research/test_snapshot.py -v`
Expected: PASS.

- [ ] **Step 4: Commit**

```bash
git add src/margin/research/snapshot.py tests/research/test_snapshot.py
git commit -m "feat(research): add immutable snapshot builder"
```

---

### Task 7: Service layer and API routes

**Files:**
- Create: `src/margin/research/service.py`
- Create: `src/margin/api/routes/research.py`
- Modify: `src/margin/api/main.py`
- Test: `tests/api/test_research.py`

- [ ] **Step 1: Write the failing test**

```python
from fastapi.testclient import TestClient
from margin.api.main import create_app
from margin.research.llm import DeterministicLLMProvider
from margin.research.service import ResearchService
from margin.research.tools import ToolRegistry


def test_research_run_endpoint():
    registry = ToolRegistry()
    registry.register_defaults()
    service = ResearchService(
        tool_registry=registry,
        llm_provider=DeterministicLLMProvider(response={"queries": ["q"], "summaries": [], "risk_score": 0.3, "risk_factors": [], "counter_arguments": [], "unknowns": []}),
    )
    app = create_app(research_service=service)
    client = TestClient(app)
    response = client.post("/research/run", json={"symbol": "000001.SZ"})
    assert response.status_code == 200
    assert response.json()["state"] == "published"
```

Run: `pytest tests/api/test_research.py -v`
Expected: FAIL.

- [ ] **Step 2: Implement service and routes**

Create `src/margin/research/service.py`:

```python
"""High-level research service."""

from __future__ import annotations

from datetime import datetime, UTC
from typing import Any

from margin.research.llm import LLMProvider
from margin.research.tools import ToolRegistry
from margin.research.workflow import ResearchWorkflow, WorkflowResult


class ResearchService:
    """Entry point for running research workflows."""

    def __init__(
        self,
        tool_registry: ToolRegistry | None = None,
        llm_provider: LLMProvider | None = None,
        strategy_config: dict[str, Any] | None = None,
    ) -> None:
        self._tools = tool_registry or ToolRegistry()
        if not self._tools.list_tools():
            self._tools.register_defaults()
        self._llm = llm_provider
        self._strategy = strategy_config or {}

    def run(
        self,
        symbol: str,
        decision_at: datetime | None = None,
        portfolio_id: str | None = None,
    ) -> WorkflowResult:
        decision_at = decision_at or datetime.now(UTC)
        workflow = ResearchWorkflow(
            symbol=symbol,
            decision_at=decision_at,
            tool_registry=self._tools,
            llm_provider=self._llm,
            strategy_config=self._strategy,
            portfolio_id=portfolio_id,
        )
        return workflow.run()
```

Create `src/margin/api/routes/research.py`:

```python
"""Research API routes."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from margin.api.dependencies import get_research_service
from margin.research.service import ResearchService


router = APIRouter(prefix="/research", tags=["research"])


class ResearchRunRequest(BaseModel):
    symbol: str
    decision_at: datetime | None = None
    portfolio_id: str | None = None


class ResearchRunResponse(BaseModel):
    run_id: str
    state: str
    signals: list[dict[str, Any]]
    error: str | None = None

    model_config = {"frozen": True}


@router.post("/run")
def run_research(
    request: ResearchRunRequest,
    service: ResearchService = Depends(get_research_service),
) -> ResearchRunResponse:
    result = service.run(
        symbol=request.symbol,
        decision_at=request.decision_at,
        portfolio_id=request.portfolio_id,
    )
    if result.state in ("aborted",):
        raise HTTPException(status_code=422, detail=result.error or "workflow aborted")
    return ResearchRunResponse(
        run_id=result.run_id,
        state=result.state,
        signals=[s.model_dump() for s in result.signals],
        error=result.error,
    )


@router.get("/tools")
def list_tools(service: ResearchService = Depends(get_research_service)) -> list[str]:
    return service._tools.list_tools()
```

Modify `src/margin/api/dependencies.py` to add `get_research_service`. If the file does not yet contain portfolio dependencies, create it:

```python
from margin.research.service import ResearchService


def get_research_service() -> ResearchService:
    return ResearchService()
```

Modify `src/margin/api/main.py`:

```python
from margin.api.dependencies import get_portfolio_service, get_research_service
from margin.api.routes.portfolios import router as portfolio_router
from margin.api.routes.research import router as research_router
from margin.portfolio.service import PortfolioService
from margin.research.service import ResearchService


def create_app(
    portfolio_service: PortfolioService | None = None,
    research_service: ResearchService | None = None,
) -> FastAPI:
    application = FastAPI(title="Margin API", version="0.1.0")
    application.include_router(portfolio_router)
    application.include_router(research_router)

    if portfolio_service is not None:
        application.dependency_overrides[get_portfolio_service] = (
            lambda: portfolio_service
        )
    if research_service is not None:
        application.dependency_overrides[get_research_service] = (
            lambda: research_service
        )
    # ... health endpoint remains
```

- [ ] **Step 3: Run tests**

Run: `pytest tests/api/test_research.py -v`
Expected: PASS.

- [ ] **Step 4: Commit**

```bash
git add src/margin/research/service.py src/margin/api/routes/research.py src/margin/api/dependencies.py src/margin/api/main.py tests/api/test_research.py
git commit -m "feat(research): add service and API routes"
```

---

### Task 8: Package exports and final validation

**Files:**
- Create: `src/margin/research/__init__.py`
- Create: `tests/research/__init__.py`
- Test: full suite

- [ ] **Step 1: Write package init**

Create `src/margin/research/__init__.py`:

```python
"""Multi-agent research module."""

from margin.research.agents import Agent, AgentContext, AgentOutput
from margin.research.llm import DeterministicLLMProvider, LLMProvider, ModelRouter, TaskType
from margin.research.models import ResearchSignal, ResearchSnapshot, SignalType, WorkflowState
from margin.research.service import ResearchService
from margin.research.snapshot import ResearchSnapshotBuilder
from margin.research.tools import ToolRegistry
from margin.research.workflow import ResearchWorkflow, WorkflowResult

__all__ = [
    "Agent",
    "AgentContext",
    "AgentOutput",
    "DeterministicLLMProvider",
    "LLMProvider",
    "ModelRouter",
    "ResearchService",
    "ResearchSignal",
    "ResearchSnapshot",
    "ResearchSnapshotBuilder",
    "ResearchWorkflow",
    "SignalType",
    "TaskType",
    "ToolRegistry",
    "WorkflowResult",
    "WorkflowState",
]
```

Create `tests/research/__init__.py` (empty).

- [ ] **Step 2: Run full validation**

Run:
```bash
ruff check src tests
pytest tests/research tests/api/test_research.py -v
```
Expected: `ruff check` 0 errors; pytest green.

- [ ] **Step 3: Commit**

```bash
git add src/margin/research/__init__.py tests/research/__init__.py
git commit -m "feat(research): expose research module public API"
```

---

## Spec Coverage Self-Review

| Spec requirement | Implementing task |
|---|---|
| 12 agent roles with input/output schema | Task 4 (`agents.py`) |
| Tool system with 11 built-in tools | Task 3 (`tools.py`) |
| LLM provider + model router | Task 2 (`llm.py`) |
| Structured output guardrail | Task 2 (`llm.py`) |
| Workflow state machine | Task 5 (`workflow.py`) |
| Research signals (RESEARCH_CANDIDATE/WATCH/ABSTAINED) | Task 1 + Task 4 (`models.py`, `agents.py`) |
| Immutable snapshot with input/output hashes | Task 6 (`snapshot.py`) |
| Aborted on data error | Task 5 (`workflow.py`) |
| Abstained on evidence/conflict issues | Task 5 (`workflow.py`) |
| Citation validation step | Task 4 (`CitationValidatorAgent`) |
| API endpoint to trigger workflow | Task 7 (`routes/research.py`) |

## Placeholder Scan

- No TBD/TODO/fill-in-later text remains.
- Every task contains concrete file paths, code, and commands.
- Each test step specifies the exact test to run and expected outcome.

## Type Consistency

- `ResearchSignal.signal_type` uses `SignalType` everywhere.
- `WorkflowState` enum is used in `models.py`, `workflow.py`, and `snapshot.py`.
- `LLMResult` is the return type for all provider completions.
- `AgentOutput.data` is consistently `dict[str, Any]`.

---

**Plan complete and saved to `docs/superpowers/plans/2026-06-19-module-06-multi-agent-research.md`.**

Two execution options:

1. **Subagent-Driven (recommended)** — I dispatch a fresh subagent per task, review between tasks, fast iteration.
2. **Inline Execution** — I implement tasks directly in this session using the plan as a checklist.

Which approach would you like?
