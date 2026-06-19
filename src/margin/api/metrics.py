"""Prometheus metrics registry and endpoint."""

from __future__ import annotations

from fastapi import APIRouter, Response
from prometheus_client import (
    CONTENT_TYPE_LATEST,
    CollectorRegistry,
    Counter,
    Histogram,
    generate_latest,
)

router = APIRouter(tags=["metrics"])

REGISTRY = CollectorRegistry(auto_describe=True)

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


@router.get("/metrics")
def metrics() -> Response:
    return Response(content=generate_latest(REGISTRY), media_type=CONTENT_TYPE_LATEST)
