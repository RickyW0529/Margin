# Module 07 - Strategy Configuration

## Table of Contents

- [Module Overview](#module-overview)
- [File-Level Summaries](#file-level-summaries)
- [Domain Models](#domain-models)
  - [Enums](#enums)
  - [Configuration Models](#configuration-models)
  - [Version and Profile Models](#version-and-profile-models)
  - [Support Models](#support-models)
- [Templates](#templates)
- [Service and Lifecycle](#service-and-lifecycle)
  - [StrategyService](#strategyservice)
  - [StrategyValidator](#strategyvalidator)
  - [StrategyLifecycle](#strategylifecycle)
  - [StrategySandbox](#strategysandbox)
- [Prompt Layer](#prompt-layer)
- [Repository Layer](#repository-layer)
- [FastAPI Endpoints](#fastapi-endpoints)
- [Cross-Module Usage Notes](#cross-module-usage-notes)

## Module Overview

The `07-strategy_config` module defines how investment strategies are created, validated, versioned, and promoted in Margin v0.1. It is the single source of truth for the user-editable configuration that drives AI research, evidence requirements, decision boundaries, valuation assumptions, and risk limits.

Responsibilities:

- Define the strategy configuration schema and immutable version model.
- Provide built-in strategy templates with default parameters.
- Validate configurations against guardrails that cannot be disabled by users.
- Manage the strategy lifecycle from draft through active to archived.
- Build layered prompts that merge system guardrails, platform context, strategy template, user instructions, task context, and retrieved evidence.
- Persist strategy profiles and versions in memory or in PostgreSQL.
- Expose REST endpoints for strategy creation, updates, validation, activation, and prompt retrieval.

## File-Level Summaries

| File | Responsibility |
|------|----------------|
| `src/margin/strategy/__init__.py` | Public exports for the strategy module. |
| `src/margin/strategy/models.py` | Pydantic domain models: config components, versions, profiles, and sandbox results. |
| `src/margin/strategy/db_models.py` | SQLAlchemy ORM rows for PostgreSQL persistence. |
| `src/margin/strategy/templates.py` | Built-in strategy templates and template metadata. |
| `src/margin/strategy/validator.py` | Validation and guardrail merging for user configurations. |
| `src/margin/strategy/lifecycle.py` | State machine enforcing valid version transitions. |
| `src/margin/strategy/sandbox.py` | Lightweight pre-promotion checks for a strategy config. |
| `src/margin/strategy/prompt.py` | Layered prompt builder for research runs. |
| `src/margin/strategy/repository.py` | Persistence protocol and in-memory/PostgreSQL implementations. |
| `src/margin/strategy/service.py` | High-level service orchestrating creation, validation, and lifecycle. |
| `src/margin/api/routes/strategy.py` | FastAPI routes for strategy management. |

## Domain Models

All domain models are defined in `src/margin/strategy/models.py` unless noted otherwise.

### Enums

#### `StrategyState`

`StrEnum` representing the lifecycle states of a strategy version.

| Member | Value |
|--------|-------|
| `DRAFT` | `draft` |
| `VALIDATING` | `validating` |
| `INVALID` | `invalid` |
| `BACKTESTING` | `backtesting` |
| `PAPER_TRADING` | `paper_trading` |
| `ACTIVE` | `active` |
| `ARCHIVED` | `archived` |
| `SUSPENDED` | `suspended` |

#### `ProhibitedOutput`

`StrEnum` listing outputs that strategies must never produce.

| Member | Value |
|--------|-------|
| `GUARANTEED_RETURN` | `GUARANTEED_RETURN` |
| `DIRECT_BUY_SELL_ORDER` | `DIRECT_BUY_SELL_ORDER` |

### Configuration Models

#### `AIConfig`

AI provider and prompt settings for a strategy.

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `provider` | `str` | `openai` | AI provider name. |
| `model` | `str` | `deepseek-v4-pro` | Model identifier. |
| `websearch_provider` | `str` | `tavily` | Web search provider. |
| `system_prompt_template` | `str` | `default` | Template key for the system prompt. |
| `custom_instructions` | `str` | `""` | Free-text user instructions appended to prompts. |

#### `EvidenceConfig`

Evidence requirements for a strategy.

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `required_levels` | `list[str]` | `["L1", "L2", "L3"]` | Required evidence source levels. |
| `min_evidence_count` | `int` | `3` | Minimum number of evidence items required. Must be non-negative. |

Validation:

- `min_evidence_count` must be greater than or equal to `0`.

#### `DecisionConfig`

Decision boundaries and prohibited outputs.

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `research_states` | `list[str]` | `["research_candidate", "watch", "abstained"]` | Allowed research signal states. |
| `position_review_states` | `list[str]` | `["hold", "review", "close"]` | Allowed position review states. |
| `prohibited_outputs` | `list[str]` | `[]` | Outputs the strategy must never produce. |

#### `ValuationConfig`

Valuation method configuration.

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `method` | `str` | `pe` | Valuation method identifier, e.g. `pe`, `peg`, `pb`, `dividend_yield`. |
| `eps` | `float` | `1.0` | Earnings per share placeholder. |
| `pe` | `float` | `10.0` | Target price-to-earnings ratio. |

#### `QualityConfig`

Data quality and source constraints.

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `min_source_level` | `str` | `L3` | Minimum acceptable evidence source level. |
| `require_primary_source` | `bool` | `True` | Whether primary sources are required. |

#### `RiskConfig`

Risk limits for a strategy.

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `max_position_weight` | `float` | `0.1` | Maximum portfolio weight for a single position. Must be in `(0, 1]`. |
| `max_sector_weight` | `float` | `0.3` | Maximum sector weight. Must be in `(0, 1]`. |
| `max_drawdown` | `float \| None` | `None` | Optional maximum drawdown limit. |
| `risk_score_threshold` | `float` | `0.7` | Risk score cutoff. |

Validation:

- `max_position_weight` and `max_sector_weight` must be in `(0, 1]`.

#### `StrategyConfig`

Complete user-editable strategy configuration.

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `universe` | `list[str]` | `["000001.SZ"]` | Symbols or identifiers the strategy covers. |
| `horizon` | `int` | `90` | Investment horizon in days. Must be at least `1`. |
| `valuation` | `ValuationConfig` | `ValuationConfig()` | Valuation assumptions. |
| `quality` | `QualityConfig` | `QualityConfig()` | Data quality constraints. |
| `risk` | `RiskConfig` | `RiskConfig()` | Risk limits. |
| `ai` | `AIConfig` | `AIConfig()` | AI and prompt settings. |
| `evidence` | `EvidenceConfig` | `EvidenceConfig()` | Evidence requirements. |
| `decision` | `DecisionConfig` | `DecisionConfig()` | Decision boundaries. |

### Version and Profile Models

#### `StrategyVersion`

Immutable snapshot of a strategy configuration.

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `strategy_id` | `str` | required | Parent profile identifier. |
| `version_id` | `str` | `sv_<uuid[:12]>` | Unique version identifier. |
| `name` | `str` | required | Version display name. |
| `description` | `str` | `""` | Free-text description. |
| `config` | `StrategyConfig` | required | Snapshot of the strategy config. |
| `prompt_layers` | `tuple[PromptLayer, ...]` | `()` | Cached prompt layers. |
| `state` | `StrategyState` | `StrategyState.DRAFT` | Current lifecycle state. |
| `prompt_version` | `str` | `""` | Prompt schema version. |
| `sandbox_result` | `StrategySandboxResult \| None` | `None` | Last sandbox evaluation result. |
| `created_at` | `datetime` | `utc_now()` | Creation timestamp, normalized to UTC. |

Model config: frozen.

#### `StrategyProfile`

Mutable profile owning a sequence of immutable strategy versions.

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `strategy_id` | `str` | `st_<uuid[:12]>` | Unique profile identifier. |
| `owner_id` | `str` | required | Profile owner identifier. |
| `name` | `str` | required | Profile display name. |
| `active_version_id` | `str` | `""` | Currently active version identifier. |
| `versions` | `tuple[StrategyVersion, ...]` | `()` | Immutable version history. |
| `created_at` | `datetime` | `utc_now()` | Profile creation timestamp, UTC. |
| `updated_at` | `datetime` | `utc_now()` | Last update timestamp, UTC. |

Model config: frozen.

Methods:

| Method | Parameters | Returns | Description |
|--------|------------|---------|-------------|
| `with_version` | `version: StrategyVersion` | `StrategyProfile` | Returns a new profile with `version` appended and `updated_at` refreshed. |
| `with_active_version` | `version_id: str` | `StrategyProfile` | Returns a new profile with `active_version_id` and `updated_at` updated. |

### Support Models

#### `PromptLayer`

A single layer in the final merged prompt.

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `layer` | `str` | required | Layer identifier, e.g. `system_guardrail`. |
| `content` | `str` | required | Layer content. |
| `editable` | `bool` | `True` | Whether the layer may be edited by the user. |

Model config: frozen.

#### `StrategySandboxResult`

Result of running a strategy through the sandbox.

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `validation_ok` | `bool` | `False` | Configuration validation passed. |
| `sample_run_ok` | `bool` | `False` | Sample run feasibility passed. |
| `backtest_ok` | `bool` | `False` | Backtest feasibility passed. |
| `data_leak_ok` | `bool` | `False` | No future-dated constraints detected. |
| `cost_ok` | `bool` | `False` | Cost estimate acceptable. |
| `preview_ok` | `bool` | `False` | Report preview available. |
| `messages` | `list[str]` | `[]` | Human-readable check messages. |

#### `StrategyTemplateMeta`

Metadata for a built-in strategy template.

| Field | Type | Description |
|-------|------|-------------|
| `template_id` | `str` | Unique template identifier. |
| `name` | `str` | Display name. |
| `description` | `str` | Short description. |
| `category` | `str` | Template category, e.g. `value`, `growth`. |

Model config: frozen.

## Templates

Templates are defined in `src/margin/strategy/templates.py`.

### `StrategyTemplate`

A built-in strategy template with metadata and default config.

| Field | Type | Description |
|-------|------|-------------|
| `meta` | `StrategyTemplateMeta` | Template metadata. |
| `config` | `StrategyConfig` | Default strategy configuration. |

Built-in templates are created by private factory functions and registered in `BUILTIN_TEMPLATES`:

| Template ID | Name | Category | Description |
|-------------|------|----------|-------------|
| `value_quality` | 价值质量 | `value` | Low valuation, high quality leaders with stable ROE and cash flow. |
| `undervalued_recovery` | 低估修复 | `value` | Short-term negative news creating valuation compression with recovery potential. |
| `high_dividend` | 高股息 | `income` | Consistent dividend payers with stable yield and ample cash flow. |
| `growth_at_reasonable_price` | 成长合理估值 | `growth` | Sustainable growth companies within reasonable valuation ranges. |
| `cyclical_reversal` | 周期反转 | `cyclical` | Cyclical industries at supply/demand inflection points. |
| `custom` | 用户完全自定义 | `custom` | Blank template with default `StrategyConfig`. |

### `list_templates`

```python
def list_templates() -> list[StrategyTemplateMeta]
```

Returns metadata for all built-in strategy templates.

## Service and Lifecycle

### `StrategyService`

Entry point for creating, validating, and activating strategies. Defined in `src/margin/strategy/service.py`.

Constructor parameters:

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `repository` | `StrategyRepository \| None` | `MemoryStrategyRepository()` | Persistence implementation. |
| `validator` | `StrategyValidator \| None` | `StrategyValidator()` | Configuration validator. |
| `lifecycle` | `StrategyLifecycle \| None` | `StrategyLifecycle()` | Lifecycle state machine. |
| `sandbox` | `StrategySandbox \| None` | `StrategySandbox(...)` | Sandbox evaluator. |
| `prompt_builder` | `PromptLayerBuilder \| None` | `PromptLayerBuilder()` | Prompt layer builder. |

Public methods:

| Method | Parameters | Returns | Description |
|--------|------------|---------|-------------|
| `create_from_template` | `owner_id: str`, `template_id: str`, `name: str = ""`, `description: str = ""` | `StrategyProfile` | Create a new profile from a built-in template. |
| `create_custom` | `owner_id: str`, `config: StrategyConfig`, `name: str`, `description: str = ""` | `StrategyProfile` | Create a new profile from a user-supplied config. |
| `update_strategy` | `strategy_id: str`, `config_delta: dict \| None = None`, `name: str \| None = None`, `description: str \| None = None` | `StrategyProfile` | Create a new version by merging `config_delta` into the latest version. |
| `validate_version` | `strategy_id: str`, `version_id: str` | `StrategyProfile` | Validate and sandbox a version, advancing to `BACKTESTING` or `INVALID`. |
| `backtest_version` | `strategy_id: str`, `version_id: str` | `StrategyProfile` | Advance a version from `BACKTESTING` to `PAPER_TRADING`. |
| `paper_trade_version` | `strategy_id: str`, `version_id: str` | `StrategyProfile` | Confirm paper-trading readiness. |
| `activate_version` | `strategy_id: str`, `version_id: str` | `StrategyProfile` | Activate a version for live research and set it as active. |
| `suspend_version` | `strategy_id: str`, `version_id: str`, `reason: str = ""` | `StrategyProfile` | Suspend an active version. |
| `archive_strategy` | `strategy_id: str` | `StrategyProfile` | Archive the currently active version. |
| `get_profile` | `strategy_id: str` | `StrategyProfile` | Return a profile by identifier. |
| `list_profiles` | `owner_id: str` | `list[StrategyProfile]` | Return all profiles for an owner. |
| `get_prompt` | `strategy_id: str`, `version_id: str`, `task: str = ""`, `evidence_context: str = ""` | `str` | Return the merged prompt for a version. |
| `list_templates` | none | `list[StrategyTemplateMeta]` | Return metadata for built-in templates. |

Private helpers:

| Method | Purpose |
|--------|---------|
| `_create_version` | Build a new `StrategyProfile` with an initial `StrategyVersion`. |
| `_must_get_profile` | Load a profile or raise `KeyError`. |
| `_must_get_version` | Locate a version inside a profile or raise `KeyError`. |
| `_replace_version` | Return a profile with one version replaced. |

### `StrategyValidator`

Validates user strategy configs and merges with system guardrails. Defined in `src/margin/strategy/validator.py`.

| Method | Parameters | Returns | Description |
|--------|------------|---------|-------------|
| `validate` | `config: StrategyConfig` | `tuple[bool, list[str]]` | Return `(ok, errors)`. Adds guardrail checks on top of Pydantic validation. |
| `merge_with_guardrails` | `config: StrategyConfig` | `StrategyConfig` | Return a config with mandatory prohibited outputs and minimum evidence count enforced. |
| `validate_dict` | `data: dict[str, Any]` | `tuple[bool, list[str]]` | Validate a raw dictionary. |

Guardrail checks in `validate`:

- Universe must not be empty.
- `evidence.min_evidence_count` must be at least `1`.
- `horizon` must be positive.
- `risk.max_position_weight` must be in `(0, 1]`.

`merge_with_guardrails` always adds `GUARANTEED_RETURN` and `DIRECT_BUY_SELL_ORDER` to `decision.prohibited_outputs`.

### `StrategyLifecycle`

Enforces valid state transitions for strategy versions. Defined in `src/margin/strategy/lifecycle.py`.

| Method | Parameters | Returns | Description |
|--------|------------|---------|-------------|
| `can_transition` | `from_state: StrategyState`, `to_state: StrategyState` | `bool` | Whether the transition is allowed. |
| `transition` | `version: StrategyVersion`, `to_state: StrategyState`, `reason: str = ""` | `StrategyVersion` | Return a new version with updated state and optional reason note. Raises `ValueError` if disallowed. |

Allowed transitions:

| From | To |
|------|-----|
| `DRAFT` | `VALIDATING` |
| `VALIDATING` | `INVALID`, `BACKTESTING` |
| `INVALID` | none |
| `BACKTESTING` | `PAPER_TRADING` |
| `PAPER_TRADING` | `ACTIVE` |
| `ACTIVE` | `ARCHIVED`, `SUSPENDED` |
| `SUSPENDED` | `ACTIVE`, `ARCHIVED` |
| `ARCHIVED` | none |

### `StrategySandbox`

Runs lightweight checks before a strategy version is promoted. Defined in `src/margin/strategy/sandbox.py`.

| Method | Parameters | Returns | Description |
|--------|------------|---------|-------------|
| `evaluate` | `config: StrategyConfig` | `StrategySandboxResult` | Run all sandbox checks and return a structured result. |
| `_check_data_leak` | `config: StrategyConfig` | `bool` | Placeholder check ensuring no future-dated constraints. |

Check mapping:

- `validation_ok`: result of `StrategyValidator.validate`.
- `sample_run_ok`: validation passed and universe is non-empty.
- `backtest_ok`: same as `sample_run_ok`.
- `cost_ok`: same as `sample_run_ok`.
- `data_leak_ok`: `horizon >= 0` and `min_evidence_count >= 1`.
- `preview_ok`: all of `validation_ok`, `sample_run_ok`, and `data_leak_ok`.

## Prompt Layer

### `PromptLayerBuilder`

Composes the final research prompt from immutable layered sources. Defined in `src/margin/strategy/prompt.py`.

Layer order, outer to inner:

1. System Guardrail Prompt
2. Platform Research Prompt
3. Strategy Template Prompt
4. User Custom Prompt
5. Current Task Context
6. Retrieved Evidence

| Method | Parameters | Returns | Description |
|--------|------------|---------|-------------|
| `build_layers` | `config: StrategyConfig`, `custom_instructions: str \| None = None`, `evidence_context: str = ""`, `task: str = ""` | `tuple[PromptLayer, ...]` | Return all prompt layers for audit and serialization. |
| `build` | same as `build_layers` | `str` | Return the final merged prompt string. |
| `_guardrail_prompt` | none | `str` | Compliance and output-format guardrails. |
| `_platform_prompt` | none | `str` | Platform context for A-share research. |
| `_template_prompt` | `config: StrategyConfig` | `str` | Strategy-specific parameters. |
| `_default_task` | `config: StrategyConfig` | `str` | Default task instruction. |

`build` skips layers whose content is empty after stripping whitespace.

## Repository Layer

Defined in `src/margin/strategy/repository.py`.

### `StrategyRepository` Protocol

Persistence contract consumed by `StrategyService`.

| Method | Parameters | Returns | Description |
|--------|------------|---------|-------------|
| `add_profile` | `profile: StrategyProfile` | `None` | Persist a new strategy profile. |
| `get_profile` | `strategy_id: str` | `StrategyProfile \| None` | Return a profile by identifier. |
| `list_profiles` | `owner_id: str` | `list[StrategyProfile]` | Return all profiles owned by the user. |
| `update_profile` | `profile: StrategyProfile` | `None` | Persist an updated profile. |

### `MemoryStrategyRepository`

In-memory strategy repository for tests and local usage.

| Method | Notes |
|--------|-------|
| `add_profile` | Raises `ValueError` if the strategy identifier already exists. |
| `get_profile` | Returns `None` if not found. |
| `list_profiles` | Filters by `owner_id`. |
| `update_profile` | Raises `KeyError` if the strategy identifier does not exist. |

### `SQLAlchemyStrategyRepository`

PostgreSQL-backed strategy repository.

| Method | Notes |
|--------|-------|
| `add_profile` | Inserts a `StrategyProfileRow` and one `StrategyVersionRow` per version inside a transaction. Raises `ValueError` on duplicate profile. |
| `get_profile` | Reconstructs `StrategyProfile` and nested `StrategyVersion` objects from rows. |
| `list_profiles` | Queries profiles by `owner_id` and reconstructs each via `get_profile`. |
| `update_profile` | Updates header fields and merges version rows. New versions are inserted; existing versions update `description`, `state`, and `sandbox_result`. |

Constructor:

```python
def __init__(self, session_factory: Callable[[], Session]) -> None
```

Database rows are defined in `src/margin/strategy/db_models.py`:

- `StrategyProfileRow`: mutable header table `strategy_profiles`.
- `StrategyVersionRow`: immutable snapshot table `strategy_versions` with JSONB `config`, `prompt_layers`, and `sandbox_result`.

## FastAPI Endpoints

All routes are defined in `src/margin/api/routes/strategy.py` under the `/strategies` prefix with tag `strategy`.

| Method | Path | Summary | Request | Response |
|--------|------|---------|---------|----------|
| `GET` | `/strategies/templates` | List built-in templates | Query: none | `list[dict[str, str]]` |
| `POST` | `/strategies` | Create strategy from template | `CreateStrategyRequest` | `dict[str, Any]` |
| `POST` | `/strategies/custom` | Create custom strategy | `CreateCustomStrategyRequest` | `dict[str, Any]` |
| `GET` | `/strategies` | List owner strategies | Query: `owner_id: str` | `list[dict[str, Any]]` |
| `GET` | `/strategies/{strategy_id}` | Get a strategy profile | Path: `strategy_id` | `dict[str, Any]` |
| `PUT` | `/strategies/{strategy_id}` | Update strategy (new version) | `UpdateStrategyRequest` | `dict[str, Any]` |
| `POST` | `/strategies/{strategy_id}/versions/{version_id}/validate` | Validate and advance to backtesting | Path params | `dict[str, Any]` |
| `POST` | `/strategies/{strategy_id}/versions/{version_id}/backtest` | Advance to paper trading | Path params | `dict[str, Any]` |
| `POST` | `/strategies/{strategy_id}/versions/{version_id}/paper-trade` | Confirm paper-trading readiness | Path params | `dict[str, Any]` |
| `POST` | `/strategies/{strategy_id}/versions/{version_id}/activate` | Activate version | Path params | `dict[str, Any]` |
| `POST` | `/strategies/{strategy_id}/archive` | Archive active version | Path: `strategy_id` | `dict[str, Any]` |
| `GET` | `/strategies/{strategy_id}/versions/{version_id}/prompt` | Get merged prompt | Query: `task: str = ""` | `PromptResponse` |

Request schemas:

- `CreateStrategyRequest`: `owner_id`, `template`, `name`, `description`.
- `CreateCustomStrategyRequest`: `owner_id`, `config`, `name`, `description`.
- `UpdateStrategyRequest`: `config_delta`, `name`, `description`.

Response schema:

- `PromptResponse`: `prompt: str`.

Error handling:

- `KeyError` from the service is converted to `404 Not Found`.
- `ValueError` and Pydantic `ValidationError` are converted to `400 Bad Request`.

## Cross-Module Usage Notes

- `margin.news.models.ensure_utc` and `utc_now` are reused for timestamp normalization.
- `margin.api.dependencies.get_strategy_service` provides the shared `StrategyService` instance to API routes.
- Strategy configuration drives downstream research modules: the `universe`, `evidence`, `decision`, `valuation`, `quality`, `risk`, and `ai` fields are consumed when building research prompts and evaluating candidates.
- The prompt layer order is fixed by architecture section 15.2; only `user_custom` and `task_context` layers are editable.
- `ProhibitedOutput` values are enforced by `StrategyValidator.merge_with_guardrails` and cannot be removed by users.
