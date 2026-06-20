# Module 06: Multi-Agent Research

## Table of Contents

1. [Module overview and responsibilities](#1-module-overview-and-responsibilities)
2. [File-level summaries](#2-file-level-summaries)
3. [Domain models](#3-domain-models)
4. [Workflow](#4-workflow)
5. [LLM layer](#5-llm-layer)
6. [Agents](#6-agents)
7. [Tools](#7-tools)
8. [Production tool adapters](#8-production-tool-adapters)
9. [Snapshot and repository](#9-snapshot-and-repository)
10. [Service and API](#10-service-and-api)
11. [Cross-module usage notes](#11-cross-module-usage-notes)

---

## 1. Module overview and responsibilities

The `06-multi_agent_research` module drives the current Margin implementation's nightly research pipeline. It coordinates a directed graph of specialized agents that screen a symbol universe, gather external evidence, evaluate risk, reflect on counter-arguments, check portfolio constraints, and emit an auditable `ResearchSignal`.

Core responsibilities:

- Orchestrate a reproducible multi-agent workflow with immutable snapshots.
- Provide an LLM abstraction, model routing, and structured-output guardrails.
- Define read-only research tools and a permission-aware tool registry.
- Compose final signals only when evidence references pass citation validation.
- Persist snapshots for audit, debugging, and downstream dashboards.

The module is intentionally read-only: no agent may write to the portfolio, and all side effects are confined to snapshot persistence, audit logs, and optional document snapshots sourced from external modules.

---

## 2. File-level summaries

| File | Responsibility |
|------|----------------|
| `src/margin/research/__init__.py` | Public API exports. Re-exports the main classes, enums, and protocols used by callers. |
| `src/margin/research/models.py` | Pydantic domain models: `ResearchSignal`, `ResearchSnapshot`, `AgentTrace`, `VersionRef`, plus enums `SignalType` and `WorkflowState`. |
| `src/margin/research/workflow.py` | `ResearchWorkflow` state machine and `WorkflowResult`. Executes the 12-agent pipeline. |
| `src/margin/research/llm.py` | LLM provider adapter, deterministic test provider, `ModelRouter`, and `StructuredOutputGuardrail`. |
| `src/margin/research/agents.py` | `Agent` framework, shared `AgentContext`/`AgentOutput`, and the 12 research agent implementations. |
| `src/margin/research/tools.py` | Typed research tool hierarchy, `ToolRegistry`, `ToolPermission`, and `ToolCallRecord` auditing. |
| `src/margin/research/production_tools.py` | `build_production_tool_registry` wires real market data, vector retrieval, web search, and document collection adapters into a `ToolRegistry`. |
| `src/margin/research/snapshot.py` | `ResearchSnapshotBuilder` constructs immutable audit snapshots. |
| `src/margin/research/repository.py` | `ResearchRepository` protocol plus in-memory and PostgreSQL implementations. |
| `src/margin/research/db_models.py` | SQLAlchemy `ResearchSnapshotRow` table definition. |
| `src/margin/research/service.py` | `ResearchService` entry point that wires dependencies and runs workflows. |
| `src/margin/api/routes/research.py` | FastAPI router exposing `POST /research/run` and `GET /research/tools`. |

---

## 3. Domain models

Source file: `src/margin/research/models.py`

### Enums

| Enum | Member | Meaning |
|------|--------|---------|
| `SignalType` | `RESEARCH_CANDIDATE` | Symbol passes the research screen. |
| `SignalType` | `WATCH` | Interesting but not a candidate; e.g., high risk or conflicts. |
| `SignalType` | `ABSTAINED` | No signal emitted, usually due to missing evidence or constraint violations. |
| `WorkflowState` | `INITIALIZED` | Workflow created but not yet executed. |
| `WorkflowState` | `DATA_READY` | Universe and quant data loaded. |
| `WorkflowState` | `EVIDENCE_READY` | Web sources, documents, and evidence retrieved. |
| `WorkflowState` | `ANALYSIS_READY` | Valuation computed. |
| `WorkflowState` | `REVIEW_READY` | Risk, reflection, and portfolio checks complete. |
| `WorkflowState` | `PUBLISHED` | Final signal emitted and snapshot persisted. |
| `WorkflowState` | `ABORTED` | Workflow failed unexpectedly. |
| `WorkflowState` | `ABSTAINED` | Workflow completed but chose not to publish a signal. |

### `AgentTrace`

Single agent invocation trace embedded in a snapshot.

| Field | Type | Description |
|-------|------|-------------|
| `trace_id` | `str` | Identifier grouping agent and tool calls. |
| `agent_node` | `str` | Agent node name, e.g., `risk_review`. |
| `model_version` | `str` | Model or rule version used. |
| `input_hash` | `str` | SHA-256 of canonical agent input. |
| `output_hash` | `str` | SHA-256 of canonical agent output. |
| `latency_ms` | `float \| None` | Wall-clock latency in milliseconds. |
| `error` | `str \| None` | Error message if the agent failed. |
| `tool_call_ids` | `tuple[str, ...]` | Tool-call IDs produced by this agent. |
| `timestamp` | `datetime` | UTC timestamp of the trace. |

| Method | Description |
|--------|-------------|
| `normalize_timestamp(cls, value: datetime) -> datetime` | Validator ensuring the timestamp is UTC. |

### `ResearchSignal`

Structured signal emitted at the end of a workflow run.

| Field | Type | Description |
|-------|------|-------------|
| `signal_id` | `str` | Unique signal identifier. |
| `symbol` | `str` | Ticker or symbol under research. |
| `signal_type` | `SignalType` | One of `research_candidate`, `watch`, or `abstained`. |
| `confidence` | `float` | Confidence in `[0.0, 1.0]`. |
| `statement` | `str` | Human-readable conclusion. |
| `evidence_refs` | `tuple[str, ...]` | Evidence IDs supporting the signal. |
| `claim_ids` | `tuple[str, ...]` | Claim IDs linked to the signal. |
| `risk_score` | `float \| None` | Optional risk score from the risk review agent. |
| `counter_arguments` | `tuple[str, ...]` | Counter-arguments identified by reflection. |
| `portfolio_constraint_violations` | `tuple[str, ...]` | Violation messages from portfolio checks. |
| `generated_at` | `datetime` | UTC generation timestamp. |

| Method | Description |
|--------|-------------|
| `normalize_generated_at(cls, value: datetime) -> datetime` | Validator ensuring `generated_at` is UTC. |
| `validate_confidence(cls, value: float) -> float` | Validator ensuring confidence is within `[0, 1]`. |

### `VersionRef`

Immutable component version captured in a snapshot.

| Field | Type | Description |
|-------|------|-------------|
| `name` | `str` | Component name, e.g., `market_data`. |
| `version` | `str` | Version string. |

### `ResearchSnapshot`

Immutable audit snapshot of a research run. This is the object persisted by `ResearchRepository` implementations.

| Field | Type | Description |
|-------|------|-------------|
| `snapshot_id` | `str` | Unique snapshot identifier. |
| `run_id` | `str` | Workflow run identifier. |
| `workflow_state` | `WorkflowState` | Terminal workflow state. |
| `decision_at` | `datetime` | UTC decision timestamp. |
| `symbols` | `tuple[str, ...]` | Symbols processed. |
| `strategy_version` | `str` | Strategy version string. |
| `prompt_version` | `str` | Prompt version string. |
| `tool_versions` | `tuple[VersionRef, ...]` | Tool versions used. |
| `model_versions` | `tuple[VersionRef, ...]` | Model versions used. |
| `evidence_ids` | `tuple[str, ...]` | Evidence IDs collected. |
| `claim_ids` | `tuple[str, ...]` | Claim IDs produced. |
| `signals` | `tuple[ResearchSignal, ...]` | Final emitted signals. |
| `input_hash` | `str` | SHA-256 of canonical workflow input. |
| `output_hash` | `str` | SHA-256 of canonical workflow output. |
| `traces` | `tuple[AgentTrace, ...]` | Agent execution traces. |
| `tool_call_ids` | `tuple[str, ...]` | IDs of all tool calls. |
| `agent_outputs_json` | `str` | JSON-serialized per-agent outputs. |
| `tool_calls_json` | `str` | JSON-serialized tool call audit records. |
| `error` | `str \| None` | Terminal error message, if any. |
| `created_at` | `datetime` | UTC persistence timestamp. |

| Method | Description |
|--------|-------------|
| `normalize_created_at(cls, value: datetime) -> datetime` | Validator ensuring `decision_at` and `created_at` are UTC. |

---

## 4. Workflow

Source file: `src/margin/research/workflow.py`

### `WorkflowResult`

Dataclass returned by `ResearchWorkflow.run()`.

| Field | Type | Description |
|-------|------|-------------|
| `run_id` | `str` | Workflow run identifier. |
| `state` | `WorkflowState` | Terminal state. |
| `signals` | `list[ResearchSignal]` | Emitted signals. |
| `prior_outputs` | `dict[str, Any]` | Per-agent outputs keyed by node name. |
| `traces` | `list[AgentTrace]` | Agent execution traces. |
| `snapshot` | `dict[str, Any] \| None` | JSON-serialized snapshot, if built. |
| `snapshot_persisted` | `bool` | Whether the snapshot was persisted successfully. |
| `error` | `str \| None` | Terminal error or abstention reason. |

### `ResearchWorkflow`

Nightly research workflow state machine. Runs 12 agents in order, captures traces, builds an immutable snapshot, and persists it through a `ResearchRepository`.

#### Constructor

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `symbol` | `str` | required | Primary symbol under research. |
| `decision_at` | `datetime` | required | UTC decision timestamp. |
| `tool_registry` | `ToolRegistry` | required | Registry of tools available to agents. |
| `llm_provider` | `LLMProvider \| None` | `None` | Optional LLM provider for agents that require reasoning. |
| `model_router` | `ModelRouter \| None` | `None` | Optional router for task-based model selection. |
| `strategy_config` | `dict[str, Any] \| None` | `{}` | Strategy parameters such as universe, EPS, PE, and position limits. |
| `portfolio_id` | `str \| None` | `None` | Optional portfolio context for constraint checks. |
| `claims` | `list[Claim] \| None` | `[]` | Pre-existing claims to carry through the workflow. |
| `evidences` | `dict[str, Evidence] \| None` | `{}` | Pre-existing evidence map. |
| `snapshot_resolver` | `Any \| None` | `None` | Resolver passed to citation validation. |
| `repository` | `ResearchRepository \| None` | `MemoryResearchRepository()` | Repository used to persist snapshots. |

#### Properties

| Property | Type | Description |
|----------|------|-------------|
| `run_id` | `str` | Unique run identifier generated at construction. |
| `state` | `WorkflowState` | Current workflow state. |

#### Methods

| Method | Parameters | Returns | Description |
|--------|------------|---------|-------------|
| `run()` | — | `WorkflowResult` | Entry point. Catches exceptions and returns an `ABORTED` result. |
| `_execute()` | — | `WorkflowResult` | Internal state-machine implementation. Advances through `DATA_READY`, `EVIDENCE_READY`, `ANALYSIS_READY`, and `REVIEW_READY`, then composes and validates the signal. |
| `_make_context()` | — | `AgentContext` | Builds a fresh context sharing the workflow's tools, LLM, model router, claims, and evidence. |
| `_run_agent(agent)` | `agent: Agent` | `AgentOutput` | Executes an agent, stores its output under `prior_outputs`, and appends a trace. |
| `_finish(state, *, signals, error)` | `state: WorkflowState`, `signals: list[ResearchSignal] \| None`, `error: str \| None` | `WorkflowResult` | Builds the terminal snapshot, persists it, and returns the workflow result. Falls back to `ABORTED` if persistence fails. |
| `_build_snapshot(state, signals, error)` | `state: WorkflowState`, `signals: list[ResearchSignal]`, `error: str \| None` | `ResearchSnapshot` | Populates a `ResearchSnapshotBuilder` with the workflow's accumulated state. |

#### Agent execution order

1. `UniverseFilterAgent`
2. `QuantResearchAgent`
3. `WebSearchAgent`
4. `DocumentCollectorAgent`
5. `TextSummaryAgent`
6. `EvidenceResearchAgent`
7. `ValuationToolAgent`
8. `RiskReviewAgent`
9. `ReflectCounterArgumentAgent`
10. `PortfolioConstraintAgent`
11. `ResearchSignalComposer`
12. `CitationValidatorAgent`

The workflow aborts if universe filtering or quant research fails. It abstains if evidence retrieval is empty or if required risk/reflection LLM calls fail. If citation validation fails, the signal is downgraded to `abstained`.

---

## 5. LLM layer

Source file: `src/margin/research/llm.py`

### `TaskType`

Research task types used for routing and logging.

| Member | Value |
|--------|-------|
| `UNIVERSE_FILTER` | `universe_filter` |
| `QUANT` | `quant` |
| `WEBSEARCH` | `websearch` |
| `SUMMARY` | `summary` |
| `EVIDENCE` | `evidence` |
| `VALUATION` | `valuation` |
| `RISK` | `risk` |
| `REFLECT` | `reflect` |
| `PORTFOLIO` | `portfolio` |
| `SIGNAL` | `signal` |
| `EXTRACTION` | `extraction` |
| `VALIDATION` | `validation` |

### `LLMResult`

Result of an LLM completion call.

| Field | Type | Description |
|-------|------|-------------|
| `output` | `dict[str, Any]` | Parsed JSON output. |
| `model` | `str` | Model or provider name. |
| `success` | `bool` | Whether the call succeeded and passed guardrails. |
| `latency_ms` | `float` | Wall-clock latency in milliseconds. |
| `error` | `str \| None` | Error message. |
| `raw_response` | `str \| None` | Raw model output, if available. |

### `LLMProvider`

OpenAI-compatible LLM provider with structured JSON output. Implements the Margin `BaseProvider` interface.

#### Constructor

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `name` | `str` | `"openai_llm"` | Provider name. |
| `api_key` | `str \| None` | `os.getenv("MARGIN_LLM_API_KEY")` | API key. |
| `base_url` | `str \| None` | `os.getenv("MARGIN_LLM_BASE_URL")` | Base URL with trailing slash removed. |
| `model` | `str \| None` | `os.getenv("MARGIN_LLM_MODEL")` or `"deepseek-v4-pro"` | Model name. |
| `client` | `httpx.Client \| None` | `httpx.Client()` | HTTP client. |
| `timeout` | `float` | `60.0` | Request timeout in seconds. |

#### Properties

| Property | Type | Description |
|----------|------|-------------|
| `descriptor` | `ProviderDescriptor` | Registry descriptor including name, version, type, capabilities, and config. |

#### Methods

| Method | Parameters | Returns | Description |
|--------|------------|---------|-------------|
| `complete(prompt, *, response_schema, temperature)` | `prompt: str`, `response_schema: dict[str, Any] \| None`, `temperature: float` | `LLMResult` | Calls `/chat/completions`. Injects a system message with the JSON schema when structured output is requested. |
| `complete_or_raise(prompt, *, response_schema, temperature)` | same as `complete` | `LLMResult` | Wrapper that raises `ProviderError` on failure so it can be invoked through `ProviderRegistry`. |
| `configure_secrets(secrets)` | `secrets: dict[str, str]` | `None` | Receives the LLM API key from `ProviderRegistry`. |
| `healthcheck()` | — | `HealthCheckResult` | Sends a minimal structured request and reports `HEALTHY`, `UNHEALTHY`, or `DEGRADED`. |

### `DeterministicLLMProvider`

Test double that ignores prompts and returns a fixed JSON object. Useful for deterministic unit tests and local development.

#### Constructor

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `name` | `str` | `"deterministic_llm"` | Provider name. |
| `response` | `dict[str, Any] \| None` | `{"result": "ok"}` | JSON object to return. |
| `fail` | `bool` | `False` | Whether to simulate a failure. |
| `error` | `str` | `"injected failure"` | Error message when `fail` is true. |

#### Methods

| Method | Parameters | Returns | Description |
|--------|------------|---------|-------------|
| `complete(prompt, *, response_schema, temperature)` | same as base | `LLMResult` | Returns the configured response or an injected error. Ignores prompt and schema. |
| `healthcheck()` | — | `HealthCheckResult` | Always reports healthy. |

### `ModelRouter`

Routes research tasks to model, tool, budget, or schema configurations. Integrates with the shared `ProviderRegistry` for fallback and call tracing.

#### Constructor

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `overrides` | `dict[TaskType, str] \| None` | `None` | Mapping overriding `DEFAULTS`. |
| `llm_providers` | `dict[str, LLMProvider] \| None` | `None` | Named LLM providers to register. |
| `provider_registry` | `ProviderRegistry \| None` | `ProviderRegistry()` | Shared registry for fallback routing. |

#### Class defaults

`ModelRouter.DEFAULTS` assigns `"rule"` to data/quant/valuation/portfolio tasks and `"cheap-llm"` to most reasoning tasks; `REFLECT` uses `"capable-llm"`.

#### Methods

| Method | Parameters | Returns | Description |
|--------|------------|---------|-------------|
| `select(task)` | `task: TaskType` | `str` | Returns the configured provider name for a task. |
| `get_provider(name)` | `name: str` | `LLMProvider \| None` | Returns a locally registered provider by name. |
| `register_provider(name, provider, *, fallback_names)` | `name: str`, `provider: LLMProvider`, `fallback_names: list[str] \| None` | `None` | Registers a provider locally and in the shared registry. |
| `complete(task, prompt, *, response_schema, trace_id)` | `task: TaskType`, `prompt: str`, `response_schema: dict[str, Any] \| None`, `trace_id: str` | `LLMResult` | Routes a completion through `ProviderRegistry.call`. Returns a rule error for `"rule"` tasks and wraps provider exceptions in an `LLMResult`. |

### `StructuredOutputGuardrail`

Validates that an LLM output conforms to a supported JSON Schema subset, including object/array/string/number/integer/boolean/null types, enums, minimum/maximum, required fields, properties, and array items.

#### Constructor

| Parameter | Type | Description |
|-----------|------|-------------|
| `schema` | `dict[str, Any]` | JSON Schema to enforce. |

#### Methods

| Method | Parameters | Returns | Description |
|--------|------------|---------|-------------|
| `validate(output)` | `output: dict[str, Any]` | `tuple[bool, str]` | Returns `(True, "")` on success or `(False, message)` on failure. |
| `_validate_value(value, schema, path)` | `value: Any`, `schema: dict[str, Any]`, `path: str` | `tuple[bool, str]` | Recursive validator used by `validate`. |

---

## 6. Agents

Source file: `src/margin/research/agents.py`

### `AgentContext`

Shared context passed to every agent.

| Field | Type | Description |
|-------|------|-------------|
| `symbol` | `str` | Symbol under research. |
| `decision_at` | `datetime` | UTC decision timestamp. |
| `tool_registry` | `ToolRegistry` | Tool registry for agent tool calls. |
| `llm_provider` | `LLMProvider \| None` | Optional direct LLM provider. |
| `model_router` | `ModelRouter \| None` | Optional model router. |
| `portfolio_id` | `str \| None` | Optional portfolio identifier. |
| `strategy_config` | `dict[str, Any]` | Strategy parameters. |
| `prior_outputs` | `dict[str, Any]` | Outputs from earlier agents. |
| `claims` | `list[Claim]` | Accumulated claims. |
| `evidences` | `dict[str, Evidence]` | Accumulated evidence map. |
| `snapshot_resolver` | `Any \| None` | Snapshot resolver for citation validation. |
| `trace_id` | `str` | Trace identifier for the current agent run. |

### `AgentOutput`

Structured result from a single agent.

| Field | Type | Description |
|-------|------|-------------|
| `agent_node` | `str` | Agent node name. |
| `success` | `bool` | Whether the agent succeeded. |
| `data` | `dict[str, Any]` | Agent-produced data. |
| `error` | `str \| None` | Error message. |
| `trace_id` | `str` | Trace identifier. |
| `model_version` | `str` | Model or rule version. |
| `latency_ms` | `float` | Latency in milliseconds. |
| `tool_calls` | `list[ToolResult]` | Tool results produced. |
| `input_hash` | `str` | SHA-256 of canonical input. |
| `output_hash` | `str` | SHA-256 of canonical output. |
| `tool_call_ids` | `tuple[str, ...]` | IDs of tool calls made during this run. |

### `Agent` (abstract base)

Base class for all research agent roles.

#### Constructor

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `llm_provider` | `LLMProvider \| None` | `None` | LLM provider used when no model router is configured. |

#### Abstract properties and methods

| Name | Type | Description |
|------|------|-------------|
| `node_name` | `str` | Agent node identifier. |
| `run(context)` | `AgentOutput` | Executes the agent. |

#### Concrete helpers

| Method | Parameters | Returns | Description |
|--------|------------|---------|-------------|
| `output_schema` | — | `dict[str, Any]` | JSON Schema expected from LLM calls. Defaults to an empty object schema. |
| `_hash(data)` | `data: Any` | `str` | SHA-256 of canonical JSON data. |
| `_call_llm(context, prompt, task, provider, schema)` | `context: AgentContext`, `prompt: str`, `task: TaskType`, `provider: LLMProvider \| None`, `schema: dict[str, Any] \| None` | `LLMResult` | Routes through `ModelRouter` if available, otherwise uses the direct provider, and applies `StructuredOutputGuardrail`. |
| `_call_tool(context, name, params)` | `context: AgentContext`, `name: str`, `params: dict[str, Any]` | `ToolResult` | Invokes a tool through the shared registry. |
| `_make_output(context, success, data, error, llm_result, tool_calls)` | `context: AgentContext`, `success: bool`, `data: dict[str, Any]`, `error: str \| None`, `llm_result: LLMResult \| None`, `tool_calls: list[ToolResult] \| None` | `AgentOutput` | Builds a canonical `AgentOutput` with hashes and tool-call IDs. |

### `RuleAgent` (abstract)

Agent that uses only rules and tools, with no LLM.

| Method | Parameters | Returns | Description |
|--------|------------|---------|-------------|
| `run(context)` | `context: AgentContext` | `AgentOutput` | Calls `_run_rule` and wraps the result. |
| `_run_rule(context)` | `context: AgentContext` | `dict[str, Any]` | Abstract rule implementation. |

### `UniverseFilterAgent`

Agent #1: filters the universe by configured symbols and verifies market data.

| Property | Value |
|----------|-------|
| `node_name` | `universe_filter` |

| Method | Description |
|--------|-------------|
| `_run_rule(context)` | Reads `strategy_config["universe"]` or defaults to the current symbol, calls `market_data` for each symbol, and returns `filtered`, `degraded`, and `symbols` lists. Fails if no symbol passes. |

### `QuantResearchAgent`

Agent #2: computes factor scores and ranks symbols.

| Property | Value |
|----------|-------|
| `node_name` | `quant_research` |

| Method | Description |
|--------|-------------|
| `_run_rule(context)` | Calls `factor` for the filtered universe, sorts scores descending, and returns `scores`, `ranked`, and `top_symbol`. |

### `WebSearchAgent`

Agent #3: discovers news, announcements, and web sources.

| Property | Value |
|----------|-------|
| `node_name` | `websearch` |
| `output_schema` | `{ "queries": ["string"], "results": [] }` |

| Method | Description |
|--------|-------------|
| `run(context)` | Asks the LLM for 1-3 Chinese search queries about the symbol, executes `websearch` for each query, and returns combined queries and results. |

### `DocumentCollectorAgent`

Agent #4: collects and snapshots source documents.

| Property | Value |
|----------|-------|
| `node_name` | `document_collector` |

| Method | Description |
|--------|-------------|
| `_run_rule(context)` | Iterates over `websearch.results`, calls `document_collector` for each source, verifies required fields (`url`, `content_hash`, `snapshot_id`, `snapshot_hash`), and returns the collected list. |

### `TextSummaryAgent`

Agent #5: produces structured summaries of collected documents.

| Property | Value |
|----------|-------|
| `node_name` | `text_summary` |
| `output_schema` | `{ "summaries": [{"source_url": "string", "summary": "string", "key_points": ["string"]}] }` |

| Method | Description |
|--------|-------------|
| `run(context)` | If no documents were collected, returns an empty summary list. Otherwise asks the LLM to summarize sources and returns the structured output. |

### `EvidenceResearchAgent`

Agent #6: retrieves vector evidence and converts it into `Claim`/`Evidence` records.

| Property | Value |
|----------|-------|
| `node_name` | `evidence_research` |

| Method | Description |
|--------|-------------|
| `run(context)` | Calls `retrieval` with a symbol-specific Chinese query, converts each result chunk into `Evidence` and a `Claim`, merges them into the shared context, and returns evidence/claim IDs and counts. Fails if no valid records are produced. |

### `ValuationToolAgent`

Agent #7: numeric valuation using the valuation tool.

| Property | Value |
|----------|-------|
| `node_name` | `valuation_tool` |

| Method | Description |
|--------|-------------|
| `_run_rule(context)` | Calls `valuation` with `method="pe"`, `eps` from strategy config, and `pe` from strategy config, returning the computed value or an error. |

### `RiskReviewAgent`

Agent #8: outputs a risk score and risk factors. The score is a research opinion, not a calibrated probability.

| Property | Value |
|----------|-------|
| `node_name` | `risk_review` |
| `output_schema` | `{ "risk_score": number in [0,1], "risk_factors": ["string"] }` |

| Method | Description |
|--------|-------------|
| `run(context)` | Prompts the LLM for a risk review based on current evidence and returns the structured output. On failure, returns a default risk score of `0.5` and an empty factor list. |

### `ReflectCounterArgumentAgent`

Agent #9: reviews counter-evidence, conflicts, and unknowns.

| Property | Value |
|----------|-------|
| `node_name` | `reflect_counter_argument` |
| `output_schema` | `{ "counter_arguments": ["string"], "unknowns": ["string"], "conflict_flags": ["string"] }` |

| Method | Description |
|--------|-------------|
| `run(context)` | Prompts the LLM for counter-arguments and unknowns. On failure, returns empty lists. |

### `PortfolioConstraintAgent`

Agent #10: checks portfolio exposure constraints.

| Property | Value |
|----------|-------|
| `node_name` | `portfolio_constraint` |

| Method | Description |
|--------|-------------|
| `_run_rule(context)` | Calls `portfolio` with `max_weight` and `current_weight` from strategy config and returns `violations` and `passed`. |

### `ResearchSignalComposer`

Agent #11: composes the final research signal.

| Property | Value |
|----------|-------|
| `node_name` | `signal_composer` |
| `output_schema` | `{ "signal_type": enum("research_candidate","watch","abstained"), "confidence": number in [0,1], "statement": "string", "evidence_refs": ["string"] }` |

| Method | Parameters | Returns | Description |
|--------|------------|---------|-------------|
| `run(context)` | `context: AgentContext` | `AgentOutput` | Abstains immediately if market data is degraded or portfolio constraints fail. Otherwise builds a prompt from prior outputs and asks the LLM for a signal. Falls back to rule-based signal composition if the LLM fails. |
| `_normalize_llm_signal(output, evidence_ids)` | `output: dict[str, Any]`, `evidence_ids: list[str]` | `dict[str, Any]` | Sanitizes signal type, clamps confidence, normalizes the statement, and filters `evidence_refs` to IDs that actually exist. |
| `_rule_signal(context, risk, reflect, evidence_ids)` | `context: AgentContext`, `risk: float`, `reflect: dict[str, Any]`, `evidence_ids: list[str]` | `dict[str, Any]` | Returns `watch` for high risk or conflicts, otherwise `research_candidate`. |

### `CitationValidatorAgent`

Agent #12: validates evidence references, source levels, and timing.

| Property | Value |
|----------|-------|
| `node_name` | `citation_validator` |

| Method | Description |
|--------|-------------|
| `_run_rule(context)` | Verifies that the composed signal references evidence IDs present in the context, that those IDs are backed by at least one `Claim`, and that `CitationValidator.validate_batch` passes. Returns `valid`, `reason`, `failed_refs`, `requires_counter_review`, and `capped_confidence`. |

---

## 7. Tools

Source file: `src/margin/research/tools.py`

### `ToolResult`

Result of a single tool invocation.

| Field | Type | Description |
|-------|------|-------------|
| `tool_name` | `str` | Tool name. |
| `success` | `bool` | Whether the call succeeded. |
| `data` | `Any` | Tool output payload. |
| `error` | `str \| None` | Error message. |
| `latency_ms` | `float` | Latency in milliseconds. |
| `params` | `dict[str, Any] \| None` | Input parameters. |
| `call_id` | `str \| None` | Audit call ID assigned by the registry. |

### `ToolPermission`

Permission level enforced by `ToolRegistry`.

| Member | Value | Meaning |
|--------|-------|---------|
| `READ` | `read` | Safe read-only tool. |
| `WRITE_WITH_CONFIRM` | `write_with_confirm` | Side-effecting tool requires explicit confirmation. |
| `FORBIDDEN` | `forbidden` | Tool is not allowed to run. |

### `ToolCallRecord`

Immutable audit record for a tool call.

| Field | Type | Description |
|-------|------|-------------|
| `call_id` | `str` | Unique call ID. |
| `trace_id` | `str` | Trace ID linking the call to an agent run. |
| `tool_name` | `str` | Tool name. |
| `params_json` | `str` | JSON-serialized, redacted parameters. |
| `permission` | `ToolPermission` | Permission used. |
| `success` | `bool` | Success flag. |
| `data_hash` | `str \| None` | SHA-256 of result data. |
| `data_json` | `str \| None` | JSON-serialized, redacted result data. |
| `error` | `str \| None` | Error message. |
| `latency_ms` | `float` | Latency in milliseconds. |
| `called_at` | `datetime` | UTC call timestamp. |

| Method/Property | Description |
|-----------------|-------------|
| `serialize_params(cls, value)` | Validator that serializes parameter dictionaries to JSON. |
| `params` | Property returning a defensive copy of parsed parameters. |
| `data` | Property returning a defensive copy of parsed result data. |

### `BaseTool` (abstract)

Abstract base for all research tools.

| Method/Property | Description |
|-----------------|-------------|
| `name` | Abstract tool name. |
| `permission` | Defaults to `ToolPermission.READ`. |
| `run(params)` | Abstract execution method. |
| `_hash(data)` | SHA-256 helper. |

### `PythonTool`

Controlled numeric computation; no shell access and no unsafe imports.

| Property | Value |
|----------|-------|
| `name` | `python` |

| Method | Description |
|--------|-------------|
| `run(params)` | Evaluates `params["expression"]` in a restricted namespace containing `abs`, `round`, `max`, `min`, `sum`, `pow`, and `math`. Rejects disallowed names. |

### `RetrievalTool`

Wraps `margin.vector.retrieval.RetrievalTool` when an embedding/retrieval pipeline is available.

| Property | Value |
|----------|-------|
| `name` | `retrieval` |

| Method | Description |
|--------|-------------|
| `run(params)` | Requires `symbol` and `decision_at`. Calls the vector retrieval pipeline with `query`, `symbol`, and `decision_at`, returning serialized result chunks. |

### `_AdapterTool` (abstract)

Typed adapter that fails closed when no handler is configured.

| Constructor | Description |
|-------------|-------------|
| `_AdapterTool(handler)` | Accepts an optional callable `handler(params) -> Any`. |

| Method | Description |
|--------|-------------|
| `run(params)` | If `handler` is `None`, returns an adapter-not-configured error. Otherwise invokes the handler and returns the result. |

### Adapter subclasses

| Class | Tool name | Responsibility |
|-------|-----------|----------------|
| `MarketDataTool` | `market_data` | Market data lookup adapter. |
| `FinancialTool` | `financial` | Financial statement adapter. |
| `FactorTool` | `factor` | Factor computation adapter. |
| `PortfolioTool` | `portfolio` | Read-only portfolio constraint adapter. |
| `WebSearchTool` | `websearch` | Web search adapter. |
| `CalendarTool` | `calendar` | Trading calendar adapter. |
| `AlertTool` | `alert` | Alert creation adapter; returns `WRITE_WITH_CONFIRM`. |
| `BacktestTool` | `backtest` | Backtest adapter. |
| `FilingTool` | `filing` | Filing lookup adapter. |
| `DocumentCollectorTool` | `document_collector` | Compliant document acquisition/snapshot adapter. |

### `ValuationTool`

Simple P/E valuation stub that delegates arithmetic to `PythonTool`.

| Property | Value |
|----------|-------|
| `name` | `valuation` |

| Method | Description |
|--------|-------------|
| `run(params)` | Computes `eps * pe` and returns `{"method": "pe", "value": <value>}`. |

### `ToolRegistry`

Registry of tools available to agents, with permission enforcement and audit recording.

#### Constructor

No parameters. Initializes an empty tool map and audit record list.

#### Methods

| Method | Parameters | Returns | Description |
|--------|------------|---------|-------------|
| `register(tool)` | `tool: BaseTool` | `None` | Registers a tool by name. |
| `register_defaults(pipeline)` | `pipeline: Any \| None` | `None` | Registers the standard tool set, optionally with a retrieval pipeline. |
| `get(name)` | `name: str` | `BaseTool \| None` | Returns a tool by name. |
| `list_tools()` | — | `list[str]` | Returns sorted tool names. |
| `describe_tools()` | — | `list[dict[str, str]]` | Returns public metadata (`name`, `permission`) without exposing handlers. |
| `audit_records` | — | `tuple[ToolCallRecord, ...]` | Immutable view of recorded calls. |
| `call(name, params, *, trace_id, confirmed)` | `name: str`, `params: dict[str, Any]`, `trace_id: str`, `confirmed: bool` | `ToolResult` | Looks up the tool, enforces permission, executes it, records an audit entry, and returns the result with `call_id`. |
| `_record(result, *, permission, trace_id)` | `result: ToolResult`, `permission: ToolPermission`, `trace_id: str` | `ToolResult` | Internal method that creates a `ToolCallRecord`, redacts sensitive fields, and appends it to the audit log. |

### `_redact`

Recursive helper that scrubs sensitive keys (`api_key`, `token`, `password`, `secret`, `authorization`) from parameter and result payloads before audit logging.

| Parameter | Type | Description |
|-----------|------|-------------|
| `value` | `Any` | Value to redact. |
| `key` | `str` | Current dictionary key for sensitivity checks. |

---

## 8. Production tool adapters

Source file: `src/margin/research/production_tools.py`

`build_production_tool_registry` assembles a `ToolRegistry` with real data adapters. It is the bridge between the abstract research tools and Margin's market-data, news, and vector modules.

### `build_production_tool_registry`

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `settings` | `MarginSettings` | required | Application settings, including `websearch_api_key`. |
| `market_data_provider` | `Any \| None` | `AKShareProvider()` | Provider used for bars and financials. |
| `embedding_provider` | `Any \| None` | `None` | Optional embedding provider for persistent retrieval. |
| `news_repository` | `NewsRepository \| None` | `None` | Optional repository for persisting web-search records and documents. |
| `snapshot_store` | `SnapshotStore \| None` | `SnapshotStore()` | Store used to snapshot original web content. |
| `vector_repository` | `VectorRepository \| None` | `None` | Optional vector repository for persistent retrieval. |

| Returns | Description |
|---------|-------------|
| `ToolRegistry` | Registry configured with production-ready tool handlers. |

#### Behavior

1. Builds an `EmbeddingPipeline` or `PersistentEmbeddingPipeline` depending on whether both `embedding_provider` and `vector_repository` are supplied.
2. Registers defaults via `ToolRegistry.register_defaults(pipeline)`.
3. Defines local helpers:
   - `load_bars(symbol)` — fetches up to 120 days of OHLCV bars, caches them, and returns a degraded placeholder on error.
   - `market_data(params)` — returns the latest available bar for a symbol.
   - `factors(params)` — computes trailing return factor scores for a list of symbols.
   - `financials(params)` — returns financial statements for the requested symbols.
   - `portfolio_constraints(params)` — checks whether current weight exceeds `max_weight`.
4. If a web-search API key is configured, it registers:
   - `websearch(params)` — performs a Tavily search and optionally stores the record in `news_repository`.
   - `collect_document(params)` — verifies and snapshots a search result, creates a document event, and optionally persists the snapshot and event.
5. Returns the populated registry.

---

## 9. Snapshot and repository

### `ResearchSnapshotBuilder`

Source file: `src/margin/research/snapshot.py`

Fluent builder for immutable `ResearchSnapshot` instances. Each `with_*` method returns `self` to allow chaining.

#### Methods

| Method | Parameters | Returns | Description |
|--------|------------|---------|-------------|
| `for_run(run_id)` | `run_id: str` | `ResearchSnapshotBuilder` | Sets the run ID. |
| `with_state(state)` | `state: WorkflowState` | `ResearchSnapshotBuilder` | Sets the terminal state. |
| `with_decision_at(decision_at)` | `decision_at: datetime` | `ResearchSnapshotBuilder` | Sets the decision timestamp. |
| `with_symbols(symbols)` | `symbols: list[str]` | `ResearchSnapshotBuilder` | Sets processed symbols. |
| `with_strategy_version(version)` | `version: str` | `ResearchSnapshotBuilder` | Sets strategy version. |
| `with_prompt_version(version)` | `version: str` | `ResearchSnapshotBuilder` | Sets prompt version. |
| `with_tool_versions(versions)` | `versions: dict[str, str]` | `ResearchSnapshotBuilder` | Sets tool versions. |
| `with_model_versions(versions)` | `versions: dict[str, str]` | `ResearchSnapshotBuilder` | Sets model versions. |
| `with_evidence_ids(ids)` | `ids: list[str]` | `ResearchSnapshotBuilder` | Sets evidence IDs. |
| `with_claim_ids(ids)` | `ids: list[str]` | `ResearchSnapshotBuilder` | Sets claim IDs. |
| `with_signals(signals)` | `signals: list[ResearchSignal]` | `ResearchSnapshotBuilder` | Sets emitted signals. |
| `with_traces(traces)` | `traces: list[AgentTrace]` | `ResearchSnapshotBuilder` | Sets agent traces. |
| `with_prior_outputs(outputs)` | `outputs: dict[str, Any]` | `ResearchSnapshotBuilder` | Sets per-agent outputs. |
| `with_tool_call_ids(call_ids)` | `call_ids: list[str]` | `ResearchSnapshotBuilder` | Sets tool-call IDs. |
| `with_tool_calls(tool_calls)` | `tool_calls: list[dict[str, Any]]` | `ResearchSnapshotBuilder` | Sets serialized tool-call records. |
| `with_error(error)` | `error: str \| None` | `ResearchSnapshotBuilder` | Sets terminal error. |
| `_hash(data)` | `data: Any` | `str` | Static SHA-256 helper. |
| `build()` | — | `ResearchSnapshot` | Computes input/output hashes and returns an immutable `ResearchSnapshot`. |

### `ResearchRepository`

Source file: `src/margin/research/repository.py`

Protocol defining the persistence boundary required by `ResearchWorkflow`.

| Method | Parameters | Returns | Description |
|--------|------------|---------|-------------|
| `add_snapshot(snapshot)` | `snapshot: ResearchSnapshot` | `None` | Persists a snapshot idempotently; raises `ValueError` if an existing snapshot would be mutated. |
| `get_snapshot(snapshot_id)` | `snapshot_id: str` | `ResearchSnapshot \| None` | Returns a snapshot by identifier. |
| `get_snapshot_for_run(run_id)` | `run_id: str` | `ResearchSnapshot \| None` | Returns the most recent snapshot for a workflow run. |

### `MemoryResearchRepository`

Process-local append-only repository used by tests and local callers.

#### Methods

| Method | Description |
|--------|-------------|
| `add_snapshot(snapshot)` | Stores the snapshot in memory and records the latest ID per run. Raises `ValueError` on mutation. |
| `get_snapshot(snapshot_id)` | Returns the snapshot from memory. |
| `get_snapshot_for_run(run_id)` | Returns the most recently added snapshot for the run. |

### `SQLAlchemyResearchRepository`

PostgreSQL-backed append-only research snapshot repository.

#### Constructor

| Parameter | Type | Description |
|-----------|------|-------------|
| `session_factory` | `Callable[[], Session]` | SQLAlchemy session factory. |

#### Methods

| Method | Description |
|--------|-------------|
| `add_snapshot(snapshot)` | Serializes the snapshot to JSON, inserts a `ResearchSnapshotRow` if absent, and raises `ValueError` if a row with the same ID has different content. |
| `get_snapshot(snapshot_id)` | Loads the row by primary key and deserializes it into a `ResearchSnapshot`. |
| `get_snapshot_for_run(run_id)` | Queries the latest row for the run ordered by `created_at` and `snapshot_id`, then deserializes it. |

### `ResearchSnapshotRow`

Source file: `src/margin/research/db_models.py`

SQLAlchemy row for append-only serialized research snapshots.

| Column | Type | Description |
|--------|------|-------------|
| `snapshot_id` | `String(64)` | Primary key. |
| `run_id` | `String(64)` | Run identifier, indexed. |
| `workflow_state` | `String(32)` | Terminal workflow state value. |
| `payload` | `JSONB` | Full serialized `ResearchSnapshot`. |
| `input_hash` | `String(96)` | SHA-256 of canonical input. |
| `output_hash` | `String(96)` | SHA-256 of canonical output. |
| `created_at` | `DateTime(timezone=True)` | UTC creation timestamp. |

Index: `ix_research_snapshots_run_created` on `(run_id, created_at)`.

---

## 10. Service and API

### `ResearchService`

Source file: `src/margin/research/service.py`

High-level entry point for running research workflows.

#### Constructor

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `tool_registry` | `ToolRegistry \| None` | `ToolRegistry()` | Tool registry; defaults are registered if empty. |
| `llm_provider` | `LLMProvider \| None` | `None` | LLM provider; if supplied, a `ModelRouter` is configured automatically. |
| `strategy_config` | `dict[str, Any] \| None` | `{}` | Strategy parameters passed to each workflow. |
| `repository` | `ResearchRepository \| None` | `MemoryResearchRepository()` | Snapshot repository. |
| `audit_repository` | `AuditRepository \| None` | `None` | Optional audit repository for recording snapshots. |

#### Methods

| Method | Parameters | Returns | Description |
|--------|------------|---------|-------------|
| `run(symbol, decision_at, portfolio_id)` | `symbol: str`, `decision_at: datetime \| None`, `portfolio_id: str \| None` | `WorkflowResult` | Builds a `ResearchWorkflow`, runs it, and records an audit log if `audit_repository` is configured. |
| `list_tools()` | — | `list[dict[str, str]]` | Returns public metadata for registered tools. |
| `get_snapshot(snapshot_id)` | `snapshot_id: str` | `ResearchSnapshot \| None` | Returns a persisted terminal snapshot. |

### FastAPI routes

Source file: `src/margin/api/routes/research.py`

Router prefix: `/research`

#### `ResearchRunRequest`

| Field | Type | Constraints | Description |
|-------|------|-------------|-------------|
| `symbol` | `str` | `min_length=1`, `max_length=32` | Symbol to research. |
| `decision_at` | `datetime \| None` | optional | Decision timestamp. |
| `portfolio_id` | `str \| None` | optional | Portfolio context. |

| Validator | Description |
|-----------|-------------|
| `normalize_symbol(cls, value)` | Strips whitespace, uppercases, and rejects blank symbols. |

#### `ResearchRunResponse`

| Field | Type | Description |
|-------|------|-------------|
| `run_id` | `str` | Workflow run ID. |
| `state` | `str` | Terminal workflow state. |
| `signals` | `list[dict[str, Any]]` | Emitted signals serialized as JSON objects. |
| `snapshot_id` | `str \| None` | Snapshot ID if persistence succeeded. |
| `error` | `str \| None` | Error or abstention reason. |

#### Endpoints

| Method | Path | Handler | Description |
|--------|------|---------|-------------|
| `POST` | `/research/run` | `run_research` | Runs a research workflow for the requested symbol. Returns `422` if the workflow aborts. |
| `GET` | `/research/tools` | `list_tools` | Returns the list of available research tools and their permissions. |

---

## 11. Cross-module usage notes

| Dependency | Module | Usage |
|------------|--------|-------|
| `BaseProvider`, `ProviderDescriptor`, `ProviderStatus`, `ProviderType`, `HealthCheckResult` | `margin.core.provider` | `LLMProvider` implements the Margin provider interface. |
| `ProviderRegistry`, `ProviderNotFoundError` | `margin.core.registry` | `ModelRouter` routes completions through the shared registry. |
| `ProviderError` | `margin.core.resilience` | `LLMProvider.complete_or_raise` raises this on failures. |
| `AuditRepository`, `AuditLogRecord` | `margin.core.audit_repository`, `margin.core.models` | `ResearchService` records a snapshot audit log after each run. |
| `Claim`, `Evidence`, `ClaimType`, `FactOrInference`, `make_claim` | `margin.evidence.models` | `EvidenceResearchAgent` converts retrieval chunks into claims and evidence. |
| `CitationValidator`, `ValidationStatus` | `margin.evidence.validator` | `CitationValidatorAgent` validates citations and computes capped confidence. |
| `SourceDescriptor`, `SourceLevel`, `make_document_event` | `margin.news.models` | `build_production_tool_registry` creates document events for web sources. |
| `HTTPConnector`, `SnapshotStore`, `SourceRegistry` | `margin.news.acquirer` | Web search source registration and content snapshotting. |
| `TavilySearchAdapter` | `margin.news.providers.tavily` | Production web search backend. |
| `WebSearchProvider`, `SearchResult`, `OriginalContentVerifier` | `margin.news.websearch` | Web search execution and original-content verification. |
| `Chunk` | `margin.vector.models` | `EvidenceResearchAgent` validates and converts retrieval chunks. |
| `EmbeddingPipeline`, `PersistentEmbeddingPipeline` | `margin.vector.embedding`, `margin.vector.persistent_pipeline` | Production retrieval pipeline construction. |
| `VectorRetrievalTool` | `margin.vector.retrieval` | `RetrievalTool.run` dynamically imports and wraps this. |
| `AKShareProvider` | `margin.data.providers.akshare_provider` | Default production market-data provider. |
| `Base` | `margin.storage.base` | `ResearchSnapshotRow` extends the shared SQLAlchemy base. |
| `MarginSettings` | `margin.settings` | `build_production_tool_registry` reads `websearch_api_key`. |
| `utc_now`, `ensure_utc` | `margin.news.models` | UTC timestamp helpers used by models and providers. |
| `get_research_service` | `margin.api.dependencies` | Dependency-injection helper that supplies `ResearchService` to API routes. |
