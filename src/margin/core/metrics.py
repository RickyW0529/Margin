"""Shared Prometheus metrics used by core and API layers.

Metrics are registered to a single ``CollectorRegistry`` so that the
``/metrics`` endpoint can expose both HTTP and provider counters from one
consistent source of truth.
"""

from prometheus_client import CollectorRegistry, Counter, Histogram

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
