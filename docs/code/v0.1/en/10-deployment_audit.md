# Module 10 - Deployment Audit

## Table of Contents

- [Module Overview](#module-overview)
- [File-Level Summaries](#file-level-summaries)
- [Audit](#audit)
  - [Provider Call Audit](#provider-call-audit)
  - [Business Audit Records](#business-audit-records)
  - [Audit Repository Protocol and Implementations](#audit-repository-protocol-and-implementations)
  - [PostgreSQL Audit ORM Model](#postgresql-audit-orm-model)
- [Snapshot Store](#snapshot-store)
- [Degradation](#degradation)
- [Logging](#logging)
- [Metrics](#metrics)
- [Middleware](#middleware)
- [Health Endpoints](#health-endpoints)
- [Deployment Artifacts](#deployment-artifacts)
  - [Docker Images](#docker-images)
  - [Docker Compose Services](#docker-compose-services)
  - [CI Workflow](#ci-workflow)
  - [Prometheus Configuration](#prometheus-configuration)
  - [Operational Scripts](#operational-scripts)
- [Cross-Module Usage Notes](#cross-module-usage-notes)

## Module Overview

The `10-deployment_audit` module supplies the operational and observability infrastructure required to run Margin v0.1 in a containerized environment. It focuses on three cross-cutting concerns: immutable audit logging, graceful degradation, and production-ready telemetry (metrics, logging, health checks, and tracing). It also includes the Docker, Compose, CI, and Prometheus artifacts that package and deploy the system.

Responsibilities:

- Record every external Provider call as an append-only, tamper-evident audit entry.
- Persist business-level audit records in memory for tests or in PostgreSQL for production.
- Store content-addressed JSON snapshots of critical objects for lineage and integrity verification.
- Wrap primary Provider calls with optional fallbacks and emit Prometheus counters for degraded behavior.
- Configure structured JSON or console logging shared by stdlib `logging` and `structlog`.
- Expose a Prometheus `/metrics` endpoint and collect HTTP request counts, durations, and Provider call counters.
- Propagate trace identifiers across HTTP requests and responses.
- Provide Kubernetes-style liveness, readiness, and degradation health probes.
- Define Docker images for the backend API and Next.js frontend, a `docker-compose.yml` stack, a GitHub Actions CI workflow, and a Prometheus scrape configuration.

## File-Level Summaries

| File | Responsibility |
|------|----------------|
| `/Users/wangruiqi/PycharmProjects/Margin/src/margin/core/audit.py` | Append-only JSONL audit logger for Provider calls with parameter redaction and response hashing. |
| `/Users/wangruiqi/PycharmProjects/Margin/src/margin/core/audit_repository.py` | Protocol and in-memory/SQLAlchemy implementations for business audit record persistence. |
| `/Users/wangruiqi/PycharmProjects/Margin/src/margin/core/db_audit.py` | SQLAlchemy ORM model for immutable audit records in PostgreSQL. |
| `/Users/wangruiqi/PycharmProjects/Margin/src/margin/core/degradation.py` | Fallback wrapper for Provider calls with Prometheus instrumentation. |
| `/Users/wangruiqi/PycharmProjects/Margin/src/margin/core/logging_config.py` | Structured logging configuration using `structlog`. |
| `/Users/wangruiqi/PycharmProjects/Margin/src/margin/core/metrics.py` | Shared Prometheus `CollectorRegistry` and metric definitions. |
| `/Users/wangruiqi/PycharmProjects/Margin/src/margin/core/models.py` | Shared lightweight Pydantic models, including `AuditLogRecord`. |
| `/Users/wangruiqi/PycharmProjects/Margin/src/margin/core/provider.py` | Provider contracts, `CallResult`, `HealthCheckResult`, and typed protocols. |
| `/Users/wangruiqi/PycharmProjects/Margin/src/margin/core/snapshot_store.py` | Append-only content-addressed snapshot store on local filesystem. |
| `/Users/wangruiqi/PycharmProjects/Margin/src/margin/api/metrics.py` | FastAPI router that exposes `/metrics`. |
| `/Users/wangruiqi/PycharmProjects/Margin/src/margin/api/middleware.py` | `TraceIdMiddleware` and `MetricsMiddleware`. |
| `/Users/wangruiqi/PycharmProjects/Margin/src/margin/api/routes/health.py` | `/health`, `/health/ready`, and `/health/degraded` endpoints. |
| `/Users/wangruiqi/PycharmProjects/Margin/Dockerfile` | Backend API container image. |
| `/Users/wangruiqi/PycharmProjects/Margin/web/Dockerfile` | Next.js frontend container image. |
| `/Users/wangruiqi/PycharmProjects/Margin/docker-compose.yml` | Full local stack including Postgres, migrate, seed, API, worker, web, Prometheus, and Grafana. |
| `/Users/wangruiqi/PycharmProjects/Margin/.github/workflows/ci.yml` | GitHub Actions CI pipeline for backend, frontend, and Docker validation. |
| `/Users/wangruiqi/PycharmProjects/Margin/docker/prometheus.yml` | Prometheus scrape configuration for the Margin API. |
| `/Users/wangruiqi/PycharmProjects/Margin/scripts/migrate.py` | One-shot migration entry point used by Compose. |
| `/Users/wangruiqi/PycharmProjects/Margin/scripts/seed_demo.py` | One-shot demo data seed script used by Compose. |
| `/Users/wangruiqi/PycharmProjects/Margin/scripts/health_check.py` | Container readiness probe used by Docker healthcheck. |
| `/Users/wangruiqi/PycharmProjects/Margin/scripts/snapshot_store.py` | CLI for writing, reading, and listing snapshots. |

## Audit

Margin maintains two audit surfaces. Provider calls are recorded by `AuditLogger` to a JSONL file, while critical business events are persisted through the `AuditRepository` abstraction backed by either memory or PostgreSQL.

### Provider Call Audit

Defined in `/Users/wangruiqi/PycharmProjects/Margin/src/margin/core/audit.py`.

#### `AuditRecord`

Immutable Pydantic model describing one Provider call. The model is frozen to prevent accidental mutation after writing.

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `provider_name` | `str` | required | Name of the Provider that was called. |
| `provider_version` | `str` | required | Version string of the Provider. |
| `method` | `str` | required | Method name invoked. |
| `params_summary` | `dict[str, Any]` | required | Sanitized parameter summary; sensitive keys are redacted. |
| `success` | `bool` | required | Whether the call succeeded. |
| `error` | `str \| None` | `None` | Error message when `success` is `False`. |
| `fetched_at` | `datetime` | required | Timestamp when the result was fetched. |
| `available_at` | `datetime \| None` | `None` | Timestamp when the data became available upstream. |
| `response_hash` | `str \| None` | `None` | SHA-256 fingerprint of the response payload. |
| `cost` | `float` | `0.0` | Estimated monetary or token cost of the call. |
| `latency_ms` | `float \| None` | `None` | Call latency in milliseconds. |
| `attempt_count` | `int` | `1` | Number of attempts made before the recorded result. |
| `from_fallback` | `bool` | `False` | `True` if the result came from a fallback path. |
| `trace_id` | `str` | `""` | Request trace identifier for observability. |

#### `compute_hash(data: Any) -> str`

Compute a deterministic SHA-256 hash for arbitrary JSON-serializable data.

| Parameter | Type | Description |
|-----------|------|-------------|
| `data` | `Any` | JSON-serializable value; `None` is handled explicitly. |

Returns a string of the form `sha256:<hex_digest>` or `sha256:none` for `None`.

#### `AuditLogger`

Append-only audit log writer. The current implementation writes JSON Lines to a local file. Future iterations may migrate to the immutable PostgreSQL audit table.

| Method | Signature | Description |
|--------|-----------|-------------|
| `__init__` | `(log_path: Path \| None = None)` | Create the log file parent directories. Defaults to `~/.margin/audit/provider_calls.jsonl`. |
| `log_call` | `(provider_name, provider_version, method, params, result, trace_id="") -> AuditRecord` | Build a sanitized `AuditRecord` and append it to the log. |
| `_append` | `(record: AuditRecord) -> None` | Serialize and append a single record to the JSONL file. |
| `read_all` | `() -> list[AuditRecord]` | Parse every record from the log file; returns an empty list when the file is missing. |

#### `_summarize_params(params: dict[str, Any]) -> dict[str, Any]`

Sanitize call parameters before persistence. Sensitive keys (`token`, `api_key`, `password`, `secret`) are replaced with `***REDACTED***`, long strings are truncated to 200 characters, and sequences longer than 10 items are replaced by a length summary.

### Business Audit Records

Defined in `/Users/wangruiqi/PycharmProjects/Margin/src/margin/core/models.py`.

#### `AuditLogRecord`

Immutable Pydantic model for critical business-level audit events (for example, strategy changes, research decisions, or monitoring alerts).

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `record_id` | `str` | `ar_<uuid_hex[:12]>` | Unique identifier for the audit entry. |
| `record_type` | `str` | required | Logical type of the audit record. |
| `object_id` | `str \| None` | `None` | Identifier of the business object being audited. |
| `trace_id` | `str` | `""` | Request trace identifier. |
| `input_hash` | `str \| None` | `None` | SHA-256 hash of input data. |
| `output_hash` | `str \| None` | `None` | SHA-256 hash of output data. |
| `payload_json` | `dict[str, Any] \| None` | `None` | Arbitrary structured payload. |
| `recorded_at` | `datetime` | `utc_now()` | Timestamp of the record, coerced to UTC. |
| `service_version` | `str` | `"0.1.0"` | Service version that emitted the record. |

| Validator | Description |
|-----------|-------------|
| `normalize_recorded_at` | Coerces the timestamp to UTC to keep audit ordering deterministic. |

### Audit Repository Protocol and Implementations

Defined in `/Users/wangruiqi/PycharmProjects/Margin/src/margin/core/audit_repository.py`.

#### `AuditRepository` (Protocol)

Persistence contract for immutable audit records.

| Method | Description |
|--------|-------------|
| `record(record: AuditLogRecord) -> None` | Append an audit record. |
| `list_records(record_type=None, object_id=None, trace_id=None, limit=100) -> list[AuditLogRecord]` | Return records ordered by `recorded_at` descending. |

#### `MemoryAuditRepository`

In-memory implementation intended for tests.

| Method | Description |
|--------|-------------|
| `record(record)` | Stores the record; raises `ValueError` if `record_id` already exists to preserve the append-only contract. |
| `list_records(...)` | Filters by optional dimensions and returns the most recent records first. |

#### `SQLAlchemyAuditRepository`

PostgreSQL-backed implementation.

| Method | Description |
|--------|-------------|
| `record(record)` | Inserts the mapped row inside a transaction; rollback happens automatically on exception. |
| `list_records(...)` | Builds a filtered `SELECT` ordered by `recorded_at DESC` with a `LIMIT`. |

#### Private mapping helpers

| Function | Description |
|----------|-------------|
| `_record_to_row(record)` | Maps an `AuditLogRecord` domain model to an `AuditLogRecordRow`. |
| `_record_from_row(row)` | Maps an `AuditLogRecordRow` back to an `AuditLogRecord`; copies `payload_json` into a plain dict to avoid ORM state mutation. |

### PostgreSQL Audit ORM Model

Defined in `/Users/wangruiqi/PycharmProjects/Margin/src/margin/core/db_audit.py`.

#### `AuditLogRecordRow`

SQLAlchemy ORM model mapped to the `audit_records` table.

| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| `record_id` | `String(64)` | Primary key | Unique audit record identifier. |
| `record_type` | `String(48)` | `nullable=False` | Logical type of the record. |
| `object_id` | `String(96)` | Nullable | Audited business object identifier. |
| `trace_id` | `String(64)` | `nullable=False`, default `""` | Request trace identifier. |
| `input_hash` | `String(96)` | Nullable | SHA-256 input hash. |
| `output_hash` | `String(96)` | Nullable | SHA-256 output hash. |
| `payload_json` | `JSONB` | Nullable | Structured payload. |
| `recorded_at` | `DateTime(timezone=True)` | `nullable=False` | UTC timestamp. |
| `service_version` | `String(32)` | `nullable=False`, default `"0.1.0"` | Service version. |

| Index | Columns | Purpose |
|-------|---------|---------|
| `ix_audit_records_record_type` | `record_type` | Filter by record type. |
| `ix_audit_records_object_id` | `object_id` | Filter by business object. |
| `ix_audit_records_trace_id` | `trace_id` | Request-level forensics. |
| `ix_audit_records_recorded_at` | `recorded_at` | Time-ordered audit queries. |

## Snapshot Store

Defined in `/Users/wangruiqi/PycharmProjects/Margin/src/margin/core/snapshot_store.py`.

The `FileSnapshotStore` is an append-only, content-addressed store for serialized JSON snapshots. Each snapshot is written under `<base>/<object_type>/<object_id>/<snapshot_id>.json` and indexed by a per-object `index.jsonl` file that records snapshot lineage without duplicating payload data.

#### `SnapshotEntry`

Frozen dataclass pointing to a persisted snapshot.

| Field | Type | Description |
|-------|------|-------------|
| `snapshot_id` | `str` | Unique snapshot identifier. |
| `object_type` | `str` | Logical type of the snapshotted object. |
| `object_id` | `str` | Identifier of the snapshotted object. |
| `snapshot_path` | `Path` | Relative path within the store base. |
| `sha256` | `str` | SHA-256 hash of the serialized payload. |
| `created_at` | `datetime` | Snapshot creation timestamp. |
| `metadata` | `dict[str, Any]` | Optional metadata. |
| `payload` | `Any` | In-memory payload reference; may be `None`. |

#### `FileSnapshotStore`

| Method | Signature | Description |
|--------|-----------|-------------|
| `__init__` | `(base_path: str \| Path)` | Ensure the base directory exists. |
| `write` | `(object_type, object_id, payload, metadata=None) -> SnapshotEntry` | Serialize the payload with sorted keys, compute SHA-256, persist the file, append an index record, and return the entry. |
| `read` | `(snapshot_id: str) -> SnapshotEntry` | Recursively locate the snapshot file by id, recompute the hash to verify integrity, parse the JSON payload, and return the entry. Raises `KeyError` if not found. |
| `list_snapshots` | `(object_type, object_id) -> list[SnapshotEntry]` | Return all snapshots for an object, sorted by filename, excluding `index.jsonl`. |

## Degradation

Defined in `/Users/wangruiqi/PycharmProjects/Margin/src/margin/core/degradation.py`.

This module wraps Provider calls so that a failure of the primary path can optionally fall back to a secondary implementation. Prometheus counters track primary/fallback outcomes and degraded states.

#### `CallResult`

See `/Users/wangruiqi/PycharmProjects/Margin/src/margin/core/provider.py`. The relevant fields for degradation are:

| Field | Type | Description |
|-------|------|-------------|
| `success` | `bool` | Whether the call succeeded. |
| `error` | `str \| None` | Error message on failure. |
| `from_fallback` | `bool` | `True` when the result came from the fallback path. |

#### `call_with_fallback(fn, fallback, *, trace_id, metrics_label, **kwargs) -> CallResult`

Execute `fn` and, on failure, execute `fallback`.

| Parameter | Type | Description |
|-----------|------|-------------|
| `fn` | `Callable[..., CallResult]` | Primary function to call. |
| `fallback` | `Callable[..., CallResult] \| None` | Optional fallback function. |
| `trace_id` | `str` | Trace identifier for observability. |
| `metrics_label` | `str` | Label used for Prometheus provider metrics. |
| `**kwargs` | `Any` | Arguments passed to both functions. |

Behavior:

- On primary success, increments `margin_provider_calls_total` with `method="primary"` and returns the result.
- On primary failure, increments the error counter, logs a warning, and attempts the fallback when available.
- If no fallback is configured, increments `margin_provider_degraded_total` and returns a synthetic failure.
- On fallback success, sets `from_fallback=True`, increments the fallback success counter, increments the degraded counter, and returns the result.
- On fallback failure, increments the fallback error counter, increments the degraded counter, and returns a combined error message.

## Logging

Defined in `/Users/wangruiqi/PycharmProjects/Margin/src/margin/core/logging_config.py`.

#### `configure_logging(*, log_level: str = "INFO", log_format: str = "json") -> None`

Configure shared structured logging for both stdlib `logging` and `structlog` bound loggers.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `log_level` | `str` | `"INFO"` | Root logger level. |
| `log_format` | `str` | `"json"` | `"json"` for JSON output; any other value selects the colored console renderer. |

Shared processors (run for both stdlib and structlog):

| Processor | Purpose |
|-----------|---------|
| `structlog.contextvars.merge_contextvars` | Merge context variables into the event dict. |
| `structlog.processors.add_log_level` | Add the log level to the event dict. |
| `structlog.processors.TimeStamper(fmt="iso")` | Add an ISO format timestamp. |
| `structlog.stdlib.ExtraAdder()` | Include extra fields from stdlib log records. |

JSON-specific processors:

| Processor | Purpose |
|-----------|---------|
| `structlog.processors.dict_tracebacks` | Render tracebacks as structured dictionaries. |
| `structlog.processors.JSONRenderer()` | Render the event dict as JSON. |

The function clears existing root handlers to avoid duplicate log lines, attaches a `StreamHandler` writing to `sys.stdout`, sets the requested level, and configures `structlog` with the shared processors plus `ProcessorFormatter.wrap_for_formatter`.

## Metrics

Defined in `/Users/wangruiqi/PycharmProjects/Margin/src/margin/core/metrics.py` and `/Users/wangruiqi/PycharmProjects/Margin/src/margin/api/metrics.py`.

#### `REGISTRY`

A dedicated `prometheus_client.CollectorRegistry(auto_describe=True)` used instead of the global default registry. This isolates Margin metrics from collisions with third-party libraries.

#### Metric definitions

| Metric | Type | Labels | Description |
|--------|------|--------|-------------|
| `margin_http_requests_total` | `Counter` | `method`, `path`, `status_code` | Total HTTP requests. |
| `margin_http_request_duration_seconds` | `Histogram` | `method`, `path` | HTTP request duration. |
| `margin_provider_calls_total` | `Counter` | `provider`, `method`, `status` | Total Provider calls (primary/fallback). |
| `margin_provider_degraded_total` | `Counter` | `provider`, `method` | Total degraded Provider calls. |

#### `/metrics` endpoint

In `/Users/wangruiqi/PycharmProjects/Margin/src/margin/api/metrics.py`.

| Function | Route | Description |
|----------|-------|-------------|
| `metrics()` | `GET /metrics` | Returns the current metrics payload in Prometheus text exposition format using `generate_latest(REGISTRY)`. |

#### `MetricsMiddleware`

Defined in `/Users/wangruiqi/PycharmProjects/Margin/src/margin/api/middleware.py`.

Records HTTP request counts and durations. It uses the route path template when available to avoid high-cardinality raw URL labels.

| Method | Description |
|--------|-------------|
| `dispatch(request, call_next)` | Times the request, observes `margin_http_request_duration_seconds`, and increments `margin_http_requests_total` with the final status code. |

## Middleware

Defined in `/Users/wangruiqi/PycharmProjects/Margin/src/margin/api/middleware.py`.

#### `TraceIdMiddleware`

Populates a request-scoped trace identifier that flows through logs and responses.

| Method | Description |
|--------|-------------|
| `dispatch(request, call_next)` | Reads the trace id from the incoming header configured by `settings.trace_id_header` (default `x-margin-trace-id`) or generates a new `t-<uuid_hex[:12]>` id, stores it in request scope, and echoes it back in the response header. |

#### `_get_trace_id(request: Request) -> str`

Helper that reads the trace id attached by `TraceIdMiddleware` from request scope. Returns an empty string when no trace id is present.

## Health Endpoints

Defined in `/Users/wangruiqi/PycharmProjects/Margin/src/margin/api/routes/health.py`.

#### `health()`

`GET /health`

Simple liveness probe. Always returns `{"status": "ok"}` with HTTP 200.

#### `_database_health() -> tuple[bool, str | None]`

Private helper that checks database connectivity.

- Creates a dedicated temporary engine to avoid coupling the probe to the lifespan-managed application engine.
- Executes `SELECT 1`.
- Disposes the engine in a `finally` block to prevent connection pool leaks.
- Returns `(True, None)` on success or `(False, "<ExceptionName>: <message>")` on failure.

#### `ready()`

`GET /health/ready`

Readiness probe that verifies the database is reachable.

| Status | Response | HTTP Code |
|--------|----------|-----------|
| Database healthy | `{"status": "ready"}` | 200 |
| Database unhealthy | `{"status": "not_ready"}` | 503 |

#### `degraded()`

`GET /health/degraded`

Aggregated degradation status across infrastructure. Currently checks database health and includes the result in a list of degraded providers.

| Field | Type | Description |
|-------|------|-------------|
| `degraded` | `bool` | `True` when at least one provider or the database is degraded. |
| `degraded_count` | `int` | Number of degraded providers. |
| `providers` | `list[dict]` | Serialized `HealthCheckResult` entries for degraded components. |
| `service` | `str` | Service name from settings. |
| `version` | `str` | Service version from settings. |

## Deployment Artifacts

### Docker Images

#### `/Users/wangruiqi/PycharmProjects/Margin/Dockerfile`

Backend API image.

| Stage/Step | Description |
|------------|-------------|
| Base image | `python:3.12-slim` |
| Environment | `PYTHONDONTWRITEBYTECODE=1`, `PYTHONUNBUFFERED=1`, `PIP_NO_CACHE_DIR=1` |
| Dependency install | Copies `pyproject.toml`, `README.md`, and `src/margin/__init__.py`, then runs `pip install -e ".[data]"` to maximize layer caching. |
| Source copy | Copies `src`, `scripts`, `alembic`, and `alembic.ini`. |
| User setup | Creates `margin` user with UID `10001`, prepares `/home/margin/.margin/audit` and `/home/margin/.margin/snapshots`, and changes ownership. |
| Runtime | Exposes port `8000` and runs `uvicorn margin.api.main:app --host 0.0.0.0 --port 8000` as the `margin` user. |

#### `/Users/wangruiqi/PycharmProjects/Margin/web/Dockerfile`

Next.js frontend image.

| Stage/Step | Description |
|------------|-------------|
| Base image | `node:20-slim` |
| Dependency install | Copies `package.json` and `package-lock.json*`, then runs `npm ci`. |
| Build | Copies the full `web` directory and runs `npm run build`. |
| Prune | Removes development dependencies with `npm prune --omit=dev` to reduce image size. |
| User setup | Changes ownership to `node:node`. |
| Runtime | Sets `NODE_ENV=production`, exposes port `3000`, and runs `npm start` as the `node` user. |

### Docker Compose Services

Defined in `/Users/wangruiqi/PycharmProjects/Margin/docker-compose.yml`.

| Service | Purpose | Key Configuration |
|---------|---------|-------------------|
| `postgres` | PostgreSQL with pgvector | Image `pgvector/pgvector:pg16`; exposes `5432`; healthcheck with `pg_isready`. |
| `migrate` | One-shot Alembic migration | Builds backend image; depends on `postgres` being healthy; runs `scripts/migrate.py`. |
| `seed` | One-shot demo data seed | Builds backend image; depends on `migrate` completing successfully; runs `scripts/seed_demo.py`. |
| `api` | Main REST API | Builds backend image; exposes `8000`; depends on `seed`; mounts `margin-audit` and `margin-snapshots` volumes; healthcheck via `scripts/health_check.py`. |
| `worker` | Background worker | Builds backend image; depends on `seed`; mounts the same persistent volumes as `api`; runs `python -m margin.worker`. |
| `web` | Next.js frontend | Builds frontend image; exposes `3000`; depends on `api` being healthy; sets `MARGIN_API_BASE_URL`. |
| `prometheus` | Metrics scraper | Image `prom/prometheus:v3.12.0`; mounts `docker/prometheus.yml`; exposes `9090`; depends on `api`. |
| `grafana` | Metrics dashboards | Image `grafana/grafana:13.0.2`; mounts provisioning; exposes `3002` (configurable via `GRAFANA_PORT`); depends on `prometheus`. |

Volumes:

| Volume | Used By | Purpose |
|--------|---------|---------|
| `margin-postgres` | `postgres` | Persistent database data. |
| `margin-audit` | `api`, `worker` | Persistent Provider call audit logs. |
| `margin-snapshots` | `api`, `worker` | Persistent content-addressed snapshots. |
| `margin-grafana` | `grafana` | Persistent Grafana data. |

### CI Workflow

Defined in `/Users/wangruiqi/PycharmProjects/Margin/.github/workflows/ci.yml`.

| Job | Steps |
|-----|-------|
| `backend` | Check out code; set up Python 3.12; install `pip install -e ".[dev]"`; run `ruff check src tests`; run `alembic upgrade head` against a service container Postgres; run `pytest`. |
| `frontend` | Check out code; set up Node 20 with npm cache; run `npm ci`, `npm run lint`, `npm test`, and `npm run build` inside the `web` directory. |
| `docker` | Build the API image (`docker build -t margin-api .`); build the web image (`docker build -t margin-web ./web`); validate Compose with `docker compose config --quiet`. |

### Prometheus Configuration

Defined in `/Users/wangruiqi/PycharmProjects/Margin/docker/prometheus.yml`.

| Setting | Value |
|---------|-------|
| `global.scrape_interval` | `15s` |
| `scrape_configs.job_name` | `margin-api` |
| `static_configs.targets` | `["api:8000"]` |
| `metrics_path` | `/metrics` |

### Operational Scripts

| Script | Purpose |
|--------|---------|
| `/Users/wangruiqi/PycharmProjects/Margin/scripts/migrate.py` | Runs `alembic upgrade head` as the migration service entry point in Compose. |
| `/Users/wangruiqi/PycharmProjects/Margin/scripts/seed_demo.py` | Populates a demo portfolio, trades, and a demo filing event after migrations finish. |
| `/Users/wangruiqi/PycharmProjects/Margin/scripts/health_check.py` | HTTP readiness probe; exits `0` only when `GET http://localhost:8000/health/ready` returns HTTP 200. |
| `/Users/wangruiqi/PycharmProjects/Margin/scripts/snapshot_store.py` | CLI for the snapshot store supporting `write`, `read`, and `list` commands. |

## Cross-Module Usage Notes

- `AuditLogger` is intended for Provider call logging and is consumed by Provider implementations. It writes to `~/.margin/audit/provider_calls.jsonl` by default; the path can also be overridden through `MarginSettings.audit_log_path`.
- `SQLAlchemyAuditRepository` is injected into `ResearchService` via `/Users/wangruiqi/PycharmProjects/Margin/src/margin/api/dependencies.py` so research decisions are persisted as immutable business audit records.
- `MemoryAuditRepository` is used in unit tests to avoid database setup while still validating append-only semantics.
- `FileSnapshotStore` can be used by any service that needs to persist lineage snapshots of critical objects (for example, strategy versions or research reports). The CLI script at `/Users/wangruiqi/PycharmProjects/Margin/scripts/snapshot_store.py` uses the same implementation to guarantee compatibility.
- `call_with_fallback` is called by Provider adapters and reports to the metrics defined in `/Users/wangruiqi/PycharmProjects/Margin/src/margin/core/metrics.py`.
- `configure_logging` is invoked once during `create_app()` in `/Users/wangruiqi/PycharmProjects/Margin/src/margin/api/main.py`.
- `TraceIdMiddleware` is added before `MetricsMiddleware` in `create_app()` so the trace id is available for the entire request lifecycle.
- `MetricsMiddleware` and the `/metrics` router expose HTTP and Provider metrics to Prometheus.
- `health`, `ready`, and `degraded` routes are registered in `create_app()` and used by Docker healthchecks and Kubernetes probes.
- The `docker-compose.yml` `backend-environment` YAML anchor is reused across `migrate`, `seed`, `api`, and `worker` to keep environment variables consistent.
