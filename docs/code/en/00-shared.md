# Current Margin Implementation Shared / Core Components Documentation

This document describes the cross-cutting infrastructure components used throughout the current Margin implementation. These modules handle configuration, database connectivity, dependency injection, external provider contracts, resilience, secrets, background workers, and shared API schemas.

## Table of Contents

- [1. Module Overview and Responsibilities](#1-module-overview-and-responsibilities)
- [2. File-Level Summaries](#2-file-level-summaries)
- [3. `src/margin/settings.py` — Application Configuration](#3-srcmarginsettingspy--application-configuration)
- [4. `src/margin/worker.py` — Background Worker](#4-srcmarginworkerpy--background-worker)
- [5. `src/margin/storage/base.py` — ORM Declarative Base](#5-srcmarginstoragebasepy--orm-declarative-base)
- [6. `src/margin/storage/database.py` — Database Engine and Session Factory](#6-srcmarginstoragedatabasepy--database-engine-and-session-factory)
- [7. `src/margin/api/main.py` — FastAPI Application Factory](#7-srcmarginapimainpy--fastapi-application-factory)
- [8. `src/margin/api/dependencies.py` — Dependency Factories](#8-srcmarginapidependenciespy--dependency-factories)
- [9. `src/margin/api/schemas.py` — Shared Request/Response Schemas](#9-srcmarginapischemaspy--shared-requestresponse-schemas)
- [10. `src/margin/core/provider.py` — Provider Contracts](#10-srcmargincoreproviderpy--provider-contracts)
- [11. `src/margin/core/registry.py` — Provider Registry](#11-srcmargincoreregistrypy--provider-registry)
- [12. `src/margin/core/resilience.py` — Resilience Primitives](#12-srcmargincoreresiliencepy--resilience-primitives)
- [13. `src/margin/core/secret.py` — Secret Resolution](#13-srcmargincoresecretpy--secret-resolution)
- [14. Cross-Module Usage Notes](#14-cross-module-usage-notes)
- [15. SQL Query Factory](#15-sql-query-factory)

---

## 1. Module Overview and Responsibilities

The shared / core layer of the current Margin implementation provides the foundation on which all business modules are built. Its responsibilities include:

- **Configuration management**: Loading environment-driven settings once per process via Pydantic.
- **Persistence plumbing**: Creating and sharing the SQLAlchemy engine, session factory, and declarative base.
- **API bootstrap**: Constructing the FastAPI application, registering routers, middleware, and dependency overrides.
- **Dependency injection**: Supplying cached service instances for portfolio, research, strategy, dashboard, and monitoring domains.
- **External provider abstraction**: Defining typed contracts, descriptors, health checks, and call results for LLM, embedding, web search, rerank, market data, and notification providers.
- **Provider lifecycle**: Registering providers, resolving secrets, running health checks, and wrapping calls with rate limiting, retry, fallback, audit logging, and cost tracking.
- **Resilience**: Token-bucket rate limiting and configurable exponential-backoff retry.
- **Secret management**: Resolving credential references from environment variables or local secret files without storing plain-text values in code or configuration.
- **Background execution**: Scheduling recurring holdings monitoring and document indexing jobs.
- **Durable orchestration state**: `OrchestrationRun` / `StepAttempt` store durable runs and append-only step events. Run `metadata_json` carries business context such as valuation-discovery `decision_at`; `started_at` / `finished_at` represent lifecycle timing only so PIT timestamps cannot poison worker scheduling or terminal-state validation.
- **Document normalization pipeline**: `margin.documents` exposes a shared Docling interface that converts PDF/HTML/DOCX/XLSX/CSV/JSON/Text into Markdown, then runs Review / Repair / Verifier / Slimming to emit final Markdown, JSON, and RAG chunks. RAG chunking preserves paragraph/table-line boundaries where possible and hard-splits any single oversized block so every chunk stays within the configured `max_chunk_chars`; this prevents embedding providers from rejecting overlong inputs. PDF conversion enables RapidOCR by default and pins the backend to `onnxruntime`; visual verification runs only when the verifier supports multimodal inputs and page images exist, otherwise it is skipped with an explicit status.

---

## 2. File-Level Summaries

| File | Purpose |
| --- | --- |
| `src/margin/settings.py` | Centralized Pydantic-based application settings. |
| `src/margin/worker.py` | APScheduler-based persistent worker for monitoring and indexing sweeps. |
| `src/margin/storage/base.py` | Shared SQLAlchemy `DeclarativeBase` used by all ORM models. |
| `src/margin/storage/database.py` | Database settings, engine creation, and session factory helpers. |
| `src/margin/api/main.py` | FastAPI application factory and router registration. |
| `src/margin/api/dependencies.py` | Cached dependency factories for FastAPI injection. |
| `src/margin/api/schemas.py` | Shared Pydantic request and response models. |
| `src/margin/core/provider.py` | Provider type definitions, descriptors, base class, and business protocols. |
| `src/margin/core/registry.py` | Central provider registry with retry, fallback, audit, and cost tracking. |
| `src/margin/core/resilience.py` | Rate limiter, retry configuration, and retry wrapper. |
| `src/margin/core/secret.py` | Reference-based secret manager. |
| `src/margin/core/run_states.py` | Durable orchestration run and step-event domain models; `metadata_json` carries business context while lifecycle timestamps remain scheduler/audit time. |
| `src/margin/core/db_orchestration.py` | ORM rows for orchestration runs, step attempts, outbox, and capacity tables; `orchestration_runs.metadata_json` persists run business metadata. |
| `src/margin/core/orchestration_repository.py` | Memory/PostgreSQL repositories for durable runs and append-only step events, including atomic claim and state append behavior. |
| `src/margin/documents/markdown.py` | Shared Docling Markdown conversion interface: format routing, request/result models, Docling backend, PDF OCR configuration, and lightweight fallback. |
| `src/margin/documents/pipeline.py` | Shared document normalization pipeline: Review/Repair/Verifier/Slimming agent protocols and default rule-based implementations, final Markdown/JSON/RAG chunks with oversized-block splitting under `max_chunk_chars`, and multimodal visual-verification fallback. |

---

## 3. `src/margin/settings.py` — Application Configuration

Defines the central `MarginSettings` object and a cached factory for retrieving it.

### Class: `MarginSettings`

Single source of truth for all Margin environment configuration.

**Inheritance**: `pydantic_settings.BaseSettings`

**Key attributes / properties**:

`MarginSettings` only owns runtime infrastructure settings such as database,
logging, monitoring, and SSRF guards. Provider URL/token/model values for LLM,
web search, Tushare, embedding, and rerank are not read from `.env`; they are
written by the settings UI into provider config tables and encrypted by
AES-GCM Secret Store.

| Attribute | Type | Default | Description |
| --- | --- | --- | --- |
| `database_url` | `PostgresDsn` | `postgresql+psycopg://margin:margin@localhost:5432/margin` | SQLAlchemy database connection URL. |
| `database_echo` | `bool` | `False` | Whether SQLAlchemy logs emitted SQL statements. |
| `database_pool_pre_ping` | `bool` | `True` | Verify connections before checkout from the pool. |
| `secret_master_key` | `SecretStr` | `dev-only-change-me-32-byte-key!!` | 32-byte/base64 AES-GCM-256 Secret Store master key; local personal mode has a stable default and production can override it. |
| `secret_key_version` | `str` | `local-v1` | Key version included in encryption associated data. |
| `allow_local_provider_urls` | `bool` | `False` | Allow explicitly local provider URLs for development. |
| `resolve_provider_dns` | `bool` | `True` | Resolve DNS targets for SSRF IP checks. |
| `data_snapshot_root` | `Path` | `.margin/snapshots/data` | Root directory for v0.2 compressed raw provider snapshots. |
| `data_sync_on_startup` | `bool` | `True` | Whether the worker enables the data-provider sync job. |
| `data_freshness_timezone` | `str` | `Asia/Shanghai` | Timezone used for data freshness calculations. |
| `data_smoke_symbols` | `str` | `000001.SZ` | Symbols used by real data-provider smoke checks. |
| `log_level` | `str` | `INFO` | Logging level. |
| `log_format` | `Literal["json", "console"]` | `json` | Logging output format. |
| `metrics_enabled` | `bool` | `True` | Whether Prometheus metrics are enabled. |
| `trace_id_header` | `str` | `x-margin-trace-id` | HTTP header used to carry trace identifiers. |
| `monitoring_interval_seconds` | `int` | `300` | Interval between background monitoring/indexing sweeps. |
| `audit_log_path` | `Path` | `.margin/audit/provider_calls.jsonl` | Path to the provider audit log file. |
| `environment` | `Literal["development", "test", "production"]` | `development` | Deployment environment. |
| `service_name` | `str` | `margin-api` | Service name used for observability. |
| `service_version` | `str` | `0.1.0` | Service version string. |

**Model configuration**:

- `env_prefix="MARGIN_"`
- `env_file=".env"`
- `env_file_encoding="utf-8"`
- `extra="ignore"`

### Function: `get_settings`

| Aspect | Description |
| --- | --- |
| Signature | `() -> MarginSettings` |
| Decorator | `@lru_cache` |
| Purpose | Returns a cached `MarginSettings` instance to avoid re-parsing environment variables on every call. |
| Parameters | None. |
| Returns | `MarginSettings` instance populated from the process environment and `.env` file. |

---

## 4. `src/margin/worker.py` — Background Worker

Implements the persistent APScheduler worker that runs recurring holdings monitoring and document indexing sweeps.

### Function: `build_scheduler`

| Aspect | Description |
| --- | --- |
| Signature | `(monitoring_job: Callable[[], None], *, interval_seconds: int, indexing_job: Callable[[], None] \| None = None, data_sync_job: Callable[[], None] \| None = None) -> BlockingScheduler` |
| Purpose | Builds an APScheduler `BlockingScheduler` configured for the Asia/Shanghai timezone without starting it. |
| Parameters | `monitoring_job` — callable executed for holdings monitoring. <br> `interval_seconds` — sweep interval in seconds. <br> `indexing_job` — optional callable executed for document indexing. <br> `data_sync_job` — optional callable executed for data-provider sync readiness/work. |
| Returns | Configured `BlockingScheduler` with interval jobs. |

### Function: `build_monitoring_runner`

| Aspect | Description |
| --- | --- |
| Signature | `() -> HoldingsMonitoringRunner` |
| Purpose | Builds the production holdings monitoring runner from centralized settings. |
| Parameters | None. |
| Returns | `HoldingsMonitoringRunner` wired to PostgreSQL, AKShare price data, and repository-backed news events. |

### Function: `build_document_indexing_runner`

| Aspect | Description |
| --- | --- |
| Signature | `() -> DocumentIndexingRunner` |
| Purpose | Builds the persistent document indexing runner that indexes news content for vector search. |
| Parameters | None. |
| Returns | `DocumentIndexingRunner` using either `OpenAIEmbeddingProvider` when configured or a fallback `EmbeddingProvider`. |

### Function: `build_data_ingestion_stack`

| Aspect | Description |
| --- | --- |
| Signature | `(settings: MarginSettings \| None = None) -> DataWarehouseIngestionStack` |
| Purpose | Builds the v0.2 data warehouse ingestion stack from centralized settings or an explicit settings object. |
| Parameters | Optional `settings`; when omitted, `get_settings()` is used. |
| Returns | `DataWarehouseIngestionStack` configured with PostgreSQL sessions and compressed snapshot root. |

### Function: `main`

| Aspect | Description |
| --- | --- |
| Signature | `() -> None` |
| Purpose | Entry point for the worker process. Configures logging, builds runners, defines sweep jobs, and starts the scheduler. |
| Parameters | None. |
| Returns | None. |

---

## 5. `src/margin/storage/base.py` — ORM Declarative Base

### Class: `Base`

Shared SQLAlchemy declarative base class for all PostgreSQL ORM models.

**Inheritance**: `sqlalchemy.orm.DeclarativeBase`

| Attribute | Type | Description |
| --- | --- | --- |
| `metadata` | `sqlalchemy.MetaData` | SQLAlchemy metadata instance used for table registration across models. |

---

## 6. `src/margin/storage/database.py` — Database Engine and Session Factory

### Constant: `DEFAULT_DATABASE_URL`

| Aspect | Description |
| --- | --- |
| Type | `str` |
| Value | `postgresql+psycopg://margin:margin@localhost:5432/margin` |
| Purpose | Default SQLAlchemy connection URL used when no environment override is provided. |

### Type Alias: `SessionFactory`

| Aspect | Description |
| --- | --- |
| Definition | `sessionmaker[Session]` |
| Purpose | Typed alias for a SQLAlchemy session factory bound to an engine. |

### Class: `DatabaseSettings`

Immutable PostgreSQL database connection settings.

**Inheritance**: frozen `dataclass`

| Attribute | Type | Default | Description |
| --- | --- | --- | --- |
| `url` | `str` | `DEFAULT_DATABASE_URL` | Fully-qualified SQLAlchemy database URL. |
| `echo` | `bool` | `False` | Whether SQLAlchemy logs every emitted SQL statement. |
| `pool_pre_ping` | `bool` | `True` | Whether to verify connections before checkout from the pool. |

### Method: `DatabaseSettings.from_env`

| Aspect | Description |
| --- | --- |
| Signature | `cls -> DatabaseSettings` |
| Purpose | Loads connection settings from environment variables. |
| Parameters | None. |
| Returns | `DatabaseSettings` populated from `MARGIN_DATABASE_URL` and `MARGIN_DATABASE_ECHO`. |

### Function: `create_database_engine`

| Aspect | Description |
| --- | --- |
| Signature | `(settings: DatabaseSettings \| None = None) -> Engine` |
| Purpose | Creates the shared SQLAlchemy engine. |
| Parameters | `settings` — optional database settings. If `None`, settings are loaded from the environment. |
| Returns | Configured `sqlalchemy.Engine`. |

### Function: `create_session_factory`

| Aspect | Description |
| --- | --- |
| Signature | `(engine: Engine) -> SessionFactory` |
| Purpose | Creates a typed session factory bound to the given engine. |
| Parameters | `engine` — SQLAlchemy engine that produced sessions will use. |
| Returns | `SessionFactory` configured with `expire_on_commit=False`. |

---

## 7. `src/margin/api/main.py` — FastAPI Application Factory

Constructs and configures the Margin API application.

### Function: `create_app`

| Aspect | Description |
| --- | --- |
| Signature | `(portfolio_service: PortfolioService \| None = None, research_service: ResearchService \| None = None, strategy_service: StrategyService \| None = None, dashboard_services: DashboardServiceBundle \| None = None, monitoring_services: MonitoringServiceBundle \| None = None) -> FastAPI` |
| Purpose | Creates and configures the Margin API application, including routers, middleware, and optional test dependency overrides. |
| Parameters | `portfolio_service` — optional portfolio service override. <br> `research_service` — optional research service override. <br> `strategy_service` — optional strategy service override. <br> `dashboard_services` — optional dashboard service bundle override. <br> `monitoring_services` — optional monitoring service bundle override. |
| Returns | Configured `FastAPI` application. |

### FastAPI Application Wiring

| Aspect | Detail |
| --- | --- |
| Title | `Margin API` |
| Version | `settings.service_version` |
| Middleware order | `TraceIdMiddleware` first, then `MetricsMiddleware`. |
| Routers included | `metrics_router`, `health_router`, `portfolio_router`, `research_router`, `strategy_router`, `dashboard_router`, `monitoring_router`. |
| Dependency overrides | Optional injected services override `get_portfolio_service`, `get_research_service`, `get_strategy_service`, `get_dashboard_services`, and `get_monitoring_services`. |

### Constant: `app`

| Aspect | Description |
| --- | --- |
| Type | `FastAPI` |
| Purpose | Default Margin API application instance created with production settings. |

---

## 8. `src/margin/api/dependencies.py` — Dependency Factories

Provides production-ready FastAPI dependency callables. Returned services are cached per process.

### Class: `MissingConfiguredProvider`

Provider-status placeholder for an external provider whose configuration is missing.

| Attribute | Type | Description |
| --- | --- | --- |
| `descriptor` | `ProviderDescriptor` | Metadata descriptor describing the missing provider. |
| `message` | `str` | Human-readable explanation of why the provider is unavailable. |

### Method: `MissingConfiguredProvider.healthcheck`

| Aspect | Description |
| --- | --- |
| Signature | `() -> HealthCheckResult` |
| Purpose | Returns a degraded health status without attempting a network call. |
| Parameters | None. |
| Returns | `HealthCheckResult` with `ProviderStatus.DEGRADED`. |

### Function: `build_database_engine`

| Aspect | Description |
| --- | --- |
| Signature | `(settings: MarginSettings) -> Engine` |
| Purpose | Builds the database engine from centralized application settings. |
| Parameters | `settings` — `MarginSettings` instance. |
| Returns | Configured SQLAlchemy `Engine`. |

### Function: `_missing_provider`

| Aspect | Description |
| --- | --- |
| Signature | `(*, name: str, provider_type: ProviderType, message: str, capabilities: list[str], secret_refs: list[str]) -> MissingConfiguredProvider` |
| Purpose | Internal helper that builds a degraded placeholder for an unconfigured provider. |
| Parameters | `name` — provider name. <br> `provider_type` — capability category. <br> `message` — explanation message. <br> `capabilities` — advertised capability names. <br> `secret_refs` — required secret reference names. |
| Returns | `MissingConfiguredProvider` instance. |

### Function: `build_provider_status_providers`

| Aspect | Description |
| --- | --- |
| Signature | `(repository, health_service, *, owner_id: str = "local-admin") -> list[Any]` |
| Purpose | Loads active provider configs from the provider database, checks them through `ProviderConfigHealthService`, and emits degraded placeholders for missing LLM, embedding, web search, and rerank integrations. |
| Parameters | `repository` — strategy repository. <br> `health_service` — encrypted provider health service. <br> `owner_id` — local owner ID. |
| Returns | `ProviderConfigStatusProbe` and degraded placeholder list. |

### Provider Runtime Boundary

LLM, embedding, web search, rerank, and Tushare adapters are no longer built from `MarginSettings` or `.env`. Runtime consumers use `ProviderRuntimeFactory` to load the active provider config version, read non-sensitive URL/model fields, and decrypt the token from `SecretStore` only at the final trusted adapter-construction boundary. Secrets may be scoped by provider name or provider config version ID; the settings UI scopes them by config version ID so draft tokens do not deactivate older active tokens. Successful provider activation clears dashboard/news/agentic-news/valuation-discovery runtime caches through `clear_provider_runtime_caches()`.

### Function: `build_data_warehouse_stack`

| Aspect | Description |
| --- | --- |
| Signature | `(settings: MarginSettings) -> DataWarehouseIngestionStack` |
| Purpose | Builds the DB-backed data warehouse ingestion stack from centralized settings. |
| Parameters | `settings` — `MarginSettings` instance. |
| Returns | `DataWarehouseIngestionStack` instance. |

### Dependency Factory: `get_data_warehouse_stack`

| Aspect | Description |
| --- | --- |
| Signature | `() -> DataWarehouseIngestionStack` |
| Decorator | `@lru_cache` |
| Purpose | Returns the cached production data warehouse ingestion stack. |
| Parameters | None. |
| Returns | `DataWarehouseIngestionStack` instance. |

### Dependency Factory: `get_portfolio_service`

| Aspect | Description |
| --- | --- |
| Signature | `() -> PortfolioService` |
| Decorator | `@lru_cache` |
| Purpose | Returns the cached production PostgreSQL-backed portfolio service. |
| Parameters | None. |
| Returns | `PortfolioService` instance. |

### Dependency Factory: `get_research_service`

| Aspect | Description |
| --- | --- |
| Signature | `() -> ResearchService` |
| Decorator | `@lru_cache` |
| Purpose | Returns the cached production research service with append-only persistence. |
| Parameters | None. |
| Returns | `ResearchService` instance configured with tool registry, LLM provider, and audit repository. |

### Dependency Factory: `get_strategy_service`

| Aspect | Description |
| --- | --- |
| Signature | `() -> StrategyService` |
| Decorator | `@lru_cache` |
| Purpose | Returns the cached production PostgreSQL-backed strategy configuration service. |
| Parameters | None. |
| Returns | `StrategyService` instance. |

### Dependency Factory: `get_dashboard_services`

| Aspect | Description |
| --- | --- |
| Signature | `() -> DashboardServiceBundle` |
| Decorator | `@lru_cache` |
| Purpose | Returns the cached production dashboard service bundle. |
| Parameters | None. |
| Returns | `DashboardServiceBundle` instance assembled from dashboard/research repositories, research service, and provider status providers. |

### Dependency Factory: `get_monitoring_services`

| Aspect | Description |
| --- | --- |
| Signature | `() -> MonitoringServiceBundle` |
| Decorator | `@lru_cache` |
| Purpose | Returns the cached production holdings monitoring service bundle. |
| Parameters | None. |
| Returns | `MonitoringServiceBundle` instance assembled from monitoring/portfolio repositories and portfolio service. |

---

## 9. `src/margin/api/schemas.py` — Shared Request/Response Schemas

Defines Pydantic models used to validate incoming request bodies and serialize outgoing responses.

### Class: `TradeCreate`

Request body for manually entering a single trade.

| Attribute | Type | Constraints / Default | Description |
| --- | --- | --- | --- |
| `symbol` | `str` | `min_length=1` | Ticker or instrument identifier. |
| `side` | `TradeSide` | required | Whether the trade is a buy or sell. |
| `quantity` | `float` | `gt=0` | Number of shares or units traded. |
| `price` | `float` | `gt=0` | Execution price per unit. |
| `traded_at` | `datetime` | required | Timestamp when the trade occurred. |
| `fee` | `float` | `default=0`, `ge=0` | Optional brokerage fee. |
| `tax` | `float` | `default=0`, `ge=0` | Optional tax amount. |
| `note` | `str \| None` | `default=None` | Optional free-form note. |

### Class: `CSVImportRequest`

Request body for importing trades from CSV content.

| Attribute | Type | Constraints / Default | Description |
| --- | --- | --- | --- |
| `content` | `str` | `min_length=1` | Raw CSV text. |
| `field_mapping` | `dict[str, str] \| None` | `default=None` | Optional mapping from CSV column names to canonical trade field names. |

### Class: `CSVImportResponse`

Response payload returned after a CSV import completes.

| Attribute | Type | Description |
| --- | --- | --- |
| `trades` | `list[Trade]` | Trades created from the imported rows. |
| `record` | `ImportRecord` | Import record tracking outcome and lineage. |

### Class: `ThesisUpdate`

Request body for creating a new investment thesis version.

| Attribute | Type | Constraints / Default | Description |
| --- | --- | --- | --- |
| `portfolio_id` | `str` | `min_length=1` | Identifier of the portfolio that owns the position. |
| `thesis` | `str` | `min_length=1` | Main investment thesis text. |
| `entry_conditions` | `list[str]` | `default_factory=list` | Conditions justifying entering the position. |
| `hold_conditions` | `list[str]` | `default_factory=list` | Conditions justifying keeping the position open. |
| `invalidation_conditions` | `list[str]` | `default_factory=list` | Conditions that would invalidate the thesis. |
| `target_horizon` | `list[int]` | `default_factory=lambda: [60, 120]` | Target review horizons in days. |
| `next_review_at` | `datetime \| None` | `default=None` | Optional timestamp for the next scheduled review. |
| `status` | `ThesisStatus` | `ThesisStatus.THESIS_VALID` | Current thesis status. |

### Class: `PortfolioDashboardResponse`

Response payload that combines identity and overview for a portfolio.

| Attribute | Type | Description |
| --- | --- | --- |
| `portfolio` | `Portfolio` | Portfolio identity and metadata. |
| `overview` | `PortfolioOverview` | Aggregated dashboard metrics for the portfolio. |

---

## 10. `src/margin/core/provider.py` — Provider Contracts

Defines the contracts every provider must satisfy, including metadata descriptors, health checks, call results, and typed business protocols.

### Enum: `ProviderType`

Capability category of a provider.

| Member | Value |
| --- | --- |
| `MARKET_DATA` | `market_data` |
| `WEB_SEARCH` | `web_search` |
| `LLM` | `llm` |
| `EMBEDDING` | `embedding` |
| `RERANK` | `rerank` |
| `VECTOR_STORE` | `vector_store` |
| `NOTIFICATION` | `notification` |

### Enum: `ProviderStatus`

Health status returned by a provider health check.

| Member | Value |
| --- | --- |
| `HEALTHY` | `healthy` |
| `DEGRADED` | `degraded` |
| `UNHEALTHY` | `unhealthy` |
| `UNKNOWN` | `unknown` |

### Class: `HealthCheckResult`

Result of a provider health check.

**Inheritance**: `pydantic.BaseModel`

| Attribute | Type | Default | Description |
| --- | --- | --- | --- |
| `provider_name` | `str` | required | Name of the provider checked. |
| `status` | `ProviderStatus` | required | Health status. |
| `checked_at` | `datetime` | required | Timestamp of the check. |
| `latency_ms` | `float \| None` | `None` | Optional observed latency. |
| `message` | `str \| None` | `None` | Optional human-readable message. |
| `details` | `dict[str, Any]` | `{}` | Optional additional details. |

### Class: `CallResult`

Result of a provider method call, including audit and cost metadata.

**Inheritance**: `pydantic.BaseModel`

| Attribute | Type | Default | Description |
| --- | --- | --- | --- |
| `provider_name` | `str` | required | Name of the provider called. |
| `provider_version` | `str` | required | Version of the provider. |
| `success` | `bool` | required | Whether the call succeeded. |
| `data` | `Any` | `None` | Returned data payload. |
| `error` | `str \| None` | `None` | Error message if the call failed. |
| `fetched_at` | `datetime` | `datetime.now()` | Timestamp when the call completed. |
| `available_at` | `datetime \| None` | `None` | Optional data availability timestamp. |
| `response_hash` | `str \| None` | `None` | Optional hash of the response payload. |
| `cost` | `float` | `0.0` | Estimated cost of the call. |
| `latency_ms` | `float \| None` | `None` | Observed latency in milliseconds. |
| `attempt_count` | `int` | `1` | Number of attempts made. |
| `from_fallback` | `bool` | `False` | Whether the result came from a fallback provider. |

### Class: `ProviderDescriptor`

Immutable metadata descriptor for a provider.

**Inheritance**: `pydantic.BaseModel` (frozen)

| Attribute | Type | Default | Description |
| --- | --- | --- | --- |
| `name` | `str` | required | Unique provider name. |
| `version` | `str` | required | Provider version string. |
| `provider_type` | `ProviderType` | required | Capability category. |
| `capabilities` | `list[str]` | `[]` | List of supported method names. |
| `secret_refs` | `list[str]` | `[]` | Secret reference names required by the provider. |
| `config` | `dict[str, Any]` | `[]` | Provider-specific configuration dictionary. |

### Class: `BaseProvider`

Abstract base class for all providers.

**Inheritance**: `abc.ABC`

### Property: `BaseProvider.descriptor`

| Aspect | Description |
| --- | --- |
| Signature | `() -> ProviderDescriptor` |
| Decorator | `@property`, `@abstractmethod` |
| Purpose | Returns the metadata descriptor for the provider. |
| Returns | `ProviderDescriptor` instance. |

### Method: `BaseProvider.healthcheck`

| Aspect | Description |
| --- | --- |
| Signature | `() -> HealthCheckResult` |
| Decorator | `@abstractmethod` |
| Purpose | Executes a health check and returns the status. |
| Returns | `HealthCheckResult` describing the provider's health. |

### Protocol: `MarketDataProvider`

Structural subtyping protocol for A-share market data providers.

| Method | Signature | Description |
| --- | --- | --- |
| `get_securities` | `(as_of: datetime) -> list[dict[str, Any]]` | Returns the universe of available securities as of a given date. |
| `get_bars` | `(symbols: list[str], start: datetime, end: datetime, frequency: str = "1d") -> list[dict[str, Any]]` | Returns OHLCV bars for the requested symbols and date range. |
| `get_adjustment_factors` | `(symbols: list[str], start: datetime, end: datetime) -> list[dict[str, Any]]` | Returns adjustment factors for the requested symbols and date range. |
| `get_financials` | `(symbols: list[str], start: datetime, end: datetime) -> list[dict[str, Any]]` | Returns financial statement indicators for the requested symbols. |
| `get_index_members` | `(index_code: str, as_of: datetime) -> list[dict[str, Any]]` | Returns the constituents of an index as of a given date. |

### Protocol: `WebSearchProvider`

Structural subtyping protocol for web search providers.

| Method | Signature | Description |
| --- | --- | --- |
| `search` | `(query: str, max_results: int = 10) -> list[dict[str, Any]]` | Executes a web search. |

---

## 11. `src/margin/core/registry.py` — Provider Registry

Central registry for provider instances, combining registration, health checks, rate limiting, retry, fallback, secret resolution, cost tracking, and audit logging.

### Exception: `ProviderNotFoundError`

| Aspect | Description |
| --- | --- |
| Inheritance | `KeyError` |
| Purpose | Raised when a requested provider has not been registered. |

### Exception: `ProviderAlreadyRegisteredError`

| Aspect | Description |
| --- | --- |
| Inheritance | `ValueError` |
| Purpose | Raised when registering a provider whose name is already taken. |

### Class: `ProviderRegistry`

Central registry for provider instances.

| Attribute | Type | Description |
| --- | --- | --- |
| `_providers` | `dict[str, BaseProvider]` | Mapping from provider name to instance. |
| `_rate_limiters` | `dict[str, RateLimiter]` | Mapping from provider name to rate limiter. |
| `_retry_configs` | `dict[str, RetryConfig]` | Mapping from provider name to retry configuration. |
| `_cost_rates` | `dict[str, float]` | Mapping from provider name to cost per call. |
| `_fallbacks` | `dict[str, list[str]]` | Mapping from primary provider name to fallback chain. |
| `_secret_manager` | `SecretManager` | Secret resolver used during registration. |
| `_audit_logger` | `AuditLogger` | Audit logger used for every call. |

### Method: `ProviderRegistry.__init__`

| Aspect | Description |
| --- | --- |
| Signature | `(secret_manager: SecretManager \| None = None, audit_logger: AuditLogger \| None = None) -> None` |
| Purpose | Initializes the registry with optional secret manager and audit logger. |
| Parameters | `secret_manager` — secret resolver (defaults to `SecretManager()`). <br> `audit_logger` — audit logger (defaults to `AuditLogger()`). |
| Returns | None. |

### Method: `ProviderRegistry.register`

| Aspect | Description |
| --- | --- |
| Signature | `(provider: BaseProvider, *, rate_limiter: RateLimiter \| None = None, retry_config: RetryConfig \| None = None, cost_per_call: float = 0.0, fallback_names: list[str] \| None = None, allow_override: bool = False) -> None` |
| Purpose | Registers a provider instance and configures runtime policies. |
| Parameters | `provider` — provider instance to register. <br> `rate_limiter` — optional rate limiter. <br> `retry_config` — optional retry configuration. <br> `cost_per_call` — cost charged per call attempt. <br> `fallback_names` — ordered fallback provider names. <br> `allow_override` — whether to replace an existing provider with the same name. |
| Raises | `ProviderAlreadyRegisteredError` when the name is already taken and `allow_override` is `False`. |
| Returns | None. |

### Method: `ProviderRegistry.get`

| Aspect | Description |
| --- | --- |
| Signature | `(name: str) -> BaseProvider` |
| Purpose | Retrieves a registered provider by name. |
| Parameters | `name` — registered provider name. |
| Returns | The registered provider instance. |
| Raises | `ProviderNotFoundError` when no provider with the given name exists. |

### Method: `ProviderRegistry.list_by_type`

| Aspect | Description |
| --- | --- |
| Signature | `(provider_type: ProviderType) -> list[str]` |
| Purpose | Lists registered provider names filtered by capability type. |
| Parameters | `provider_type` — capability category. |
| Returns | List of matching provider names. |

### Method: `ProviderRegistry.list_all`

| Aspect | Description |
| --- | --- |
| Signature | `() -> list[str]` |
| Purpose | Lists all registered provider names. |
| Returns | List of registered provider names. |

### Method: `ProviderRegistry.resolve_secrets`

| Aspect | Description |
| --- | --- |
| Signature | `(name: str) -> dict[str, str]` |
| Purpose | Resolves all secret references for a registered provider. |
| Parameters | `name` — registered provider name. |
| Returns | Mapping from reference name to resolved secret value. |

### Method: `ProviderRegistry.healthcheck`

| Aspect | Description |
| --- | --- |
| Signature | `(name: str) -> HealthCheckResult` |
| Purpose | Runs a health check for a single provider. |
| Parameters | `name` — registered provider name. |
| Returns | The provider's `HealthCheckResult`. |

### Method: `ProviderRegistry.healthcheck_all`

| Aspect | Description |
| --- | --- |
| Signature | `() -> dict[str, HealthCheckResult]` |
| Purpose | Runs health checks for all registered providers. |
| Returns | Mapping from provider name to health check result. |

### Method: `ProviderRegistry.call`

| Aspect | Description |
| --- | --- |
| Signature | `(provider_name: str, method: str, args: tuple = (), kwargs: dict[str, Any] \| None = None, trace_id: str = "") -> tuple[Any, CallResult]` |
| Purpose | Calls a provider method with retry, fallback, audit logging, and cost tracking. |
| Parameters | `provider_name` — primary provider name. <br> `method` — method name to invoke. <br> `args` — positional arguments. <br> `kwargs` — keyword arguments. <br> `trace_id` — optional trace identifier. |
| Returns | Tuple of (method return value, `CallResult` metadata). |

### Method: `ProviderRegistry._call_single`

| Aspect | Description |
| --- | --- |
| Signature | `(name: str, method: str, args: tuple, kwargs: dict[str, Any], trace_id: str, is_fallback: bool) -> tuple[Any, CallResult]` |
| Purpose | Internal helper that executes a single provider call with rate limiting and retry. |
| Parameters | `name` — provider name. <br> `method` — method name. <br> `args` — positional arguments. <br> `kwargs` — keyword arguments. <br> `trace_id` — trace identifier. <br> `is_fallback` — whether this is a fallback invocation. |
| Returns | Tuple of (method return value or `None`, `CallResult` metadata). |

### Method: `ProviderRegistry._inject_secrets`

| Aspect | Description |
| --- | --- |
| Signature | `(provider: BaseProvider) -> None` |
| Purpose | Resolves configured secret references and injects them into providers that opt in via `configure_secrets` or `set_token`. |
| Parameters | `provider` — provider being registered. |
| Returns | None. |

### Function: `_positional_args`

| Aspect | Description |
| --- | --- |
| Signature | `(func: Callable, args: tuple) -> dict[str, Any]` |
| Purpose | Maps positional arguments to parameter names for audit summaries. |
| Parameters | `func` — target callable. <br> `args` — positional arguments. |
| Returns | Dictionary mapping parameter names to argument values, falling back to `argN` keys when inspection fails. |

### Function: `_raw_positional_args`

| Aspect | Description |
| --- | --- |
| Signature | `(args: tuple) -> dict[str, Any]` |
| Purpose | Maps positional arguments to generic `argN` keys. |
| Parameters | `args` — positional arguments. |
| Returns | Dictionary of the form `{"arg0": value0, ...}`. |

---

## 12. `src/margin/core/resilience.py` — Resilience Primitives

Provides token-bucket rate limiting and configurable exponential-backoff retry for provider calls.

### Exception: `RateLimitError`

| Aspect | Description |
| --- | --- |
| Inheritance | `Exception` |
| Purpose | Raised when a rate limiter has no available tokens. |

### Exception: `ProviderError`

| Aspect | Description |
| --- | --- |
| Inheritance | `Exception` |
| Purpose | Raised when a provider call fails. |

### Class: `RateLimiter`

Token-bucket rate limiter.

| Attribute | Type | Default | Description |
| --- | --- | --- | --- |
| `max_calls` | `int` | `60` | Maximum number of tokens in the bucket. |
| `per_seconds` | `float` | `60.0` | Time window over which tokens are allocated. |
| `_tokens` | `float` | `max_calls` | Current number of available tokens. |
| `_last_refill` | `float` | current time | Timestamp of the last token refill. |

### Method: `RateLimiter.__post_init__`

| Aspect | Description |
| --- | --- |
| Signature | `() -> None` |
| Purpose | Initializes the token bucket to full capacity. |

### Method: `RateLimiter._refill`

| Aspect | Description |
| --- | --- |
| Signature | `() -> None` |
| Purpose | Refills tokens based on elapsed time since the last refill. |

### Method: `RateLimiter.acquire`

| Aspect | Description |
| --- | --- |
| Signature | `() -> None` |
| Purpose | Acquires one token, raising if the bucket is empty. |
| Raises | `RateLimitError` when no tokens are available. |
| Returns | None. |

### Method: `RateLimiter.try_acquire`

| Aspect | Description |
| --- | --- |
| Signature | `() -> bool` |
| Purpose | Tries to acquire one token without raising. |
| Returns | `True` if a token was acquired, otherwise `False`. |

### Class: `RetryConfig`

Configuration for retry behavior.

| Attribute | Type | Default | Description |
| --- | --- | --- | --- |
| `max_retries` | `int` | `3` | Maximum number of retry attempts. |
| `base_delay` | `float` | `1.0` | Initial delay between retries in seconds. |
| `max_delay` | `float` | `30.0` | Maximum delay between retries in seconds. |
| `backoff_factor` | `float` | `2.0` | Multiplier applied to the delay on each retry. |
| `retry_on` | `tuple[type[Exception], ...]` | `(ProviderError,)` | Exception types that trigger a retry. |

### Method: `RetryConfig.compute_delay`

| Aspect | Description |
| --- | --- |
| Signature | `(attempt: int) -> float` |
| Purpose | Computes the delay before retry `attempt` using exponential backoff. |
| Parameters | `attempt` — 1-based retry attempt number. |
| Returns | Delay in seconds, capped at `max_delay`. |

### Function: `with_retry`

| Aspect | Description |
| --- | --- |
| Signature | `(func: Callable[..., T], args: tuple = (), kwargs: dict[str, Any] \| None = None, config: RetryConfig \| None = None, rate_limiter: RateLimiter \| None = None, sleep: Callable[[float], None] = time.sleep) -> tuple[T, int]` |
| Purpose | Calls a function with retry, exponential backoff, and optional rate limiting. |
| Parameters | `func` — callable to invoke. <br> `args` — positional arguments. <br> `kwargs` — keyword arguments. <br> `config` — retry configuration (defaults to `RetryConfig()`). <br> `rate_limiter` — optional rate limiter. <br> `sleep` — sleep function used between retries (injectable for testing). |
| Returns | Tuple of (`func` return value, number of attempts made). |
| Raises | The last exception encountered when retries are exhausted; non-retryable exceptions propagate immediately. |

---

## 13. `src/margin/core/secret.py` — Secret Resolution

Implements reference-based secret management. API keys and credentials are referenced by name and resolved at runtime from environment variables or local secret files.

### Exception: `SecretNotFoundError`

| Aspect | Description |
| --- | --- |
| Inheritance | `KeyError` |
| Purpose | Raised when a secret reference cannot be resolved. |

### Class: `SecretManager`

Reference-based secret manager.

| Attribute | Type | Description |
| --- | --- | --- |
| `_secrets_dir` | `Path` | Directory used for local secret files. |
| `_env_prefix` | `str` | Prefix for environment variable lookups. |
| `_cache` | `dict[str, str]` | In-memory cache of resolved secret values. |

### Method: `SecretManager.__init__`

| Aspect | Description |
| --- | --- |
| Signature | `(secrets_dir: Path \| None = None, env_prefix: str = "MARGIN_SECRET_") -> None` |
| Purpose | Initializes the secret manager. |
| Parameters | `secrets_dir` — directory containing local secret files (defaults to `.margin/secrets`). <br> `env_prefix` — prefix for environment variables (defaults to `MARGIN_SECRET_`). |
| Returns | None. |

### Method: `SecretManager.resolve`

| Aspect | Description |
| --- | --- |
| Signature | `(ref: str) -> str` |
| Purpose | Resolves a secret value by its reference name. |
| Parameters | `ref` — secret reference name (e.g. `tushare_token`). |
| Returns | The secret value as a string. |
| Raises | `SecretNotFoundError` when the reference is not found. |

### Method: `SecretManager.has`

| Aspect | Description |
| --- | --- |
| Signature | `(ref: str) -> bool` |
| Purpose | Checks whether a secret reference can be resolved. |
| Parameters | `ref` — secret reference name. |
| Returns | `True` if resolvable, otherwise `False`. |

### Method: `SecretManager.list_refs`

| Aspect | Description |
| --- | --- |
| Signature | `() -> list[str]` |
| Purpose | Lists all resolvable secret reference names without exposing values. |
| Returns | Sorted list of reference names found in environment variables and local secret files. |

### Class: `SecretRefInfo`

Secret reference metadata for display; does not contain the secret value.

**Inheritance**: `pydantic.BaseModel`

| Attribute | Type | Description |
| --- | --- | --- |
| `ref` | `str` | Secret reference name. |
| `resolvable` | `bool` | Whether the reference can be resolved. |

### v0.2 `SecretStore`

`src/margin/core/secret_store.py` implements AES-GCM-256 versioned provider secrets. `create_or_replace` encrypts with a random nonce and deactivates the prior active version in the same scope; `metadata` returns configured/last-four/version/status/time only; `resolve` returns a masked `SecretValue` to trusted provider adapters. Strategy provider configs use the provider config version ID as the secret scope so tokens bound to different config versions do not deactivate each other. `get_secret_store()` uses a stable local default master key for personal mode; production may override the master key at process level, but provider tokens themselves are stored only as provider-database ciphertext.

---

## 14. Cross-Module Usage Notes

- **`settings.py` is the root dependency**: `worker.py`, `dependencies.py`, and `api/main.py` all call `get_settings()` to obtain database URLs, logging configuration, SSRF guard settings, and service metadata. Provider credentials are loaded through provider config tables, not `.env`.
- **Engine reuse**: `build_database_engine(get_settings())` is the canonical path for creating a shared engine. Both the API dependencies and the background worker use this pattern.
- **Session factory lifecycle**: `create_session_factory(engine)` produces `sessionmaker` factories with `expire_on_commit=False`. Repositories receive the factory and create their own sessions.
- **Dependency caching**: All service factories in `dependencies.py` are decorated with `@lru_cache`, ensuring the same engine and repository instances are reused across requests within a process.
- **Test wiring**: `create_app()` accepts optional service overrides and maps them through `application.dependency_overrides`, allowing tests to inject fakes without changing route code.
- **Provider pluggability**: New external integrations should implement `BaseProvider`, expose a `ProviderDescriptor`, and can then be registered in `ProviderRegistry` with retry, rate limiting, fallback, and audit.
- **Secret discipline**: `ProviderDescriptor` stores only secret reference names, never values. Application runtime adapters are built by `ProviderRuntimeFactory`, which resolves active provider config versions and decrypts the matching database secret only at the trusted adapter-construction boundary.
- **Resilience defaults**: `RateLimiter` and `RetryConfig` use sensible defaults (`60 calls / 60 s`, `3` retries with exponential backoff). They are intentionally not thread-safe, matching the MVP single-threaded worker model.
- **Worker scheduling**: The worker schedules two interval jobs (`holdings-monitoring` and `document-indexing`) with coalescing and single-instance constraints to prevent overlapping sweeps.
- **Dashboard transparency**: `build_provider_status_providers` deliberately returns degraded placeholders for missing integrations so the dashboard can display explicit configuration gaps instead of omitting providers silently.

---

## 15. SQL Query Factory

SQLAlchemy `select()/insert()/update()/delete()` builders and raw `text()` statements are centralized in `src/margin/sql/`. Repositories own session/transaction handling and row mapping; query construction lives in domain-specific factory modules.

| File | Query functions | Main consumers |
| --- | ---: | --- |
| `raw_statements.py` | constants | health routes, migration verification, repair and backtest scripts |
| `health_queries.py` | 8 | health routes and deployment checks |
| `data_queries.py` | 36 | warehouse, sync, ingestion, company-pool, retention, policy, and Tushare repositories |
| `strategy_queries.py` | 18 | strategy repository and bootstrap scripts |
| `news_queries.py` | 15 | news repository |
| `evidence_queries.py` | 8 | evidence repository |
| `valuation_queries.py` | 16 | valuation discovery repositories, context adapters, and Analysis Mart repository |
| `research_queries.py` | 6 | research repository, graph audit, delta repository, and checkpoint saver |
| `core_queries.py` | 17 | outbox, capacity, secret store, audit, and orchestration repositories |
| `vector_queries.py` | 5 | vector repository |
| `dashboard_queries.py` | 5 | dashboard repository |
| `backtest_queries.py` | 8 | database backtest scripts |
| **Total** | **142 functions** | — |
