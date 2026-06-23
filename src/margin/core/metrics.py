"""Shared Prometheus metrics used by core and API layers.

Metrics are registered to a single ``CollectorRegistry`` so that the
``/metrics`` endpoint can expose both HTTP and provider counters from one
consistent source of truth.
"""

from prometheus_client import CollectorRegistry, Counter, Gauge, Histogram

# A dedicated registry keeps Margin metrics isolated from the global default
# registry, avoiding collisions with other libraries that may register metrics.
REGISTRY = CollectorRegistry(auto_describe=True)

# HTTP request counters are used by MetricsMiddleware and exposed via /metrics.
HTTP_REQUESTS = Counter(
    "margin_http_requests_total",
    "Total HTTP requests",
    ["method", "path", "status_code"],
    registry=REGISTRY,
)

HTTP_REQUEST_DURATION = Histogram(
    "margin_http_request_duration_seconds",
    "HTTP request duration",
    ["method", "path"],
    registry=REGISTRY,
)

# Provider counters are updated from the degradation wrapper in core.
PROVIDER_CALLS = Counter(
    "margin_provider_calls_total",
    "Total provider calls",
    ["provider", "method", "status"],
    registry=REGISTRY,
)

PROVIDER_DEGRADED = Counter(
    "margin_provider_degraded_total",
    "Total degraded provider calls",
    ["provider", "method"],
    registry=REGISTRY,
)

# v0.2 durable orchestration and capacity metrics. Labels are intentionally
# bounded; full-market symbol, URL, run_id, step event id, and trace id are not
# valid metric labels.
RUN_DURATION = Histogram(
    "margin_run_duration_seconds",
    "Durable orchestration run duration",
    ["run_type", "status"],
    registry=REGISTRY,
)

STEP_DURATION = Histogram(
    "margin_step_duration_seconds",
    "Durable orchestration step duration",
    ["run_type", "step", "status"],
    registry=REGISTRY,
)

QUEUE_AGE = Gauge(
    "margin_queue_age_seconds",
    "Age of the oldest ready item in a bounded queue",
    ["queue"],
    registry=REGISTRY,
)

RETRY_TOTAL = Counter(
    "margin_retry_total",
    "Retry attempts by bounded component and reason code",
    ["component", "reason"],
    registry=REGISTRY,
)

FAILURE_TOTAL = Counter(
    "margin_failure_total",
    "Final or retryable failures by bounded component and reason code",
    ["component", "reason", "retryable"],
    registry=REGISTRY,
)

TARGET_RECONCILIATION = Gauge(
    "margin_target_reconciliation_count",
    "Target reconciliation counts by bounded status",
    ["target_type", "status"],
    registry=REGISTRY,
)

PROVIDER_REQUESTS = Counter(
    "margin_provider_request_total",
    "Provider requests by provider, operation, and status class",
    ["provider", "operation", "status_class"],
    registry=REGISTRY,
)

PROVIDER_LATENCY = Histogram(
    "margin_provider_request_duration_seconds",
    "Provider request duration",
    ["provider", "operation"],
    registry=REGISTRY,
)

DATA_FRESHNESS = Gauge(
    "margin_data_freshness_seconds",
    "Data age relative to expected as-of time",
    ["dataset"],
    registry=REGISTRY,
)

SCHEMA_DRIFT_TOTAL = Counter(
    "margin_schema_drift_total",
    "Detected provider schema drift events",
    ["provider", "dataset"],
    registry=REGISTRY,
)

DATA_QUALITY = Gauge(
    "margin_data_quality_score",
    "Bounded data quality score",
    ["dataset", "dimension"],
    registry=REGISTRY,
)

LLM_TOKENS = Counter(
    "margin_llm_tokens_total",
    "LLM tokens by provider, model, and direction",
    ["provider", "model", "direction"],
    registry=REGISTRY,
)

LLM_COST = Counter(
    "margin_llm_cost_total",
    "Estimated LLM cost",
    ["provider", "model"],
    registry=REGISTRY,
)

GRAPH_PATH_TOTAL = Counter(
    "margin_graph_path_total",
    "LangGraph path outcomes",
    ["path", "status"],
    registry=REGISTRY,
)

REFLECTION_TOTAL = Counter(
    "margin_reflection_total",
    "Reflection outcomes",
    ["outcome"],
    registry=REGISTRY,
)

CHECKPOINT_RECOVERY_TOTAL = Counter(
    "margin_checkpoint_recovery_total",
    "Checkpoint recovery outcomes",
    ["outcome"],
    registry=REGISTRY,
)

OUTBOX_LAG = Gauge(
    "margin_outbox_lag_seconds",
    "Age of the oldest deliverable outbox message",
    ["topic"],
    registry=REGISTRY,
)

DB_POOL_CONNECTIONS = Gauge(
    "margin_db_pool_connections",
    "Database pool connections by state",
    ["state"],
    registry=REGISTRY,
)

DB_STATEMENT_TIMEOUT_TOTAL = Counter(
    "margin_db_statement_timeout_total",
    "Database statement timeout count",
    ["operation"],
    registry=REGISTRY,
)
