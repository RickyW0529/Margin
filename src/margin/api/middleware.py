"""FastAPI middleware for trace ID propagation and HTTP metrics."""

from __future__ import annotations

import uuid
from collections.abc import Callable

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware

from margin.settings import get_settings

_TRACE_KEY = "margin_trace_id"


def _get_trace_id(request: Request) -> str:
    return request.scope.get(_TRACE_KEY, "")


class TraceIdMiddleware(BaseHTTPMiddleware):
    """Populate trace_id from header or generate a new one."""

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        settings = get_settings()
        trace_id = request.headers.get(settings.trace_id_header) or f"t-{uuid.uuid4().hex[:12]}"
        request.scope[_TRACE_KEY] = trace_id
        response = await call_next(request)
        response.headers[settings.trace_id_header] = trace_id
        return response
