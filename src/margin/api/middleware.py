"""FastAPI middleware for trace ID propagation and HTTP metrics.

``TraceIdMiddleware`` attaches a request-scoped trace identifier that flows
through logs and responses. ``MetricsMiddleware`` records request counts and
latencies using the path template where available, avoiding high-cardinality
raw URLs.
"""

from __future__ import annotations

import time
import uuid
from collections.abc import Callable

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware

from margin.core.metrics import HTTP_REQUEST_DURATION, HTTP_REQUESTS
from margin.settings import get_settings

_TRACE_KEY = "margin_trace_id"


def _get_trace_id(request: Request) -> str:
    """Read the trace id attached by ``TraceIdMiddleware`` from request scope."""
    return request.scope.get(_TRACE_KEY, "")


class TraceIdMiddleware(BaseHTTPMiddleware):
    """Populate trace_id from header or generate a new one."""

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        """dispatch."""
        settings = get_settings()
        # Prefer the incoming header so distributed callers can correlate requests.
        trace_id = request.headers.get(settings.trace_id_header) or f"t-{uuid.uuid4().hex[:12]}"
        request.scope[_TRACE_KEY] = trace_id
        response = await call_next(request)
        response.headers[settings.trace_id_header] = trace_id
        return response


class MetricsMiddleware(BaseHTTPMiddleware):
    """Record HTTP request counts and durations."""

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        """dispatch."""
        start = time.perf_counter()
        status_code = 500  # Default used if call_next raises an unhandled exception.
        try:
            response = await call_next(request)
            status_code = response.status_code
            return response
        finally:
            duration = time.perf_counter() - start
            # Use the route path template when available so label cardinality stays low.
            route = request.scope.get("route")
            path = getattr(route, "path", request.url.path) if route else request.url.path
            HTTP_REQUEST_DURATION.labels(
                method=request.method,
                path=path,
            ).observe(duration)
            HTTP_REQUESTS.labels(
                method=request.method,
                path=path,
                status_code=status_code,
            ).inc()
