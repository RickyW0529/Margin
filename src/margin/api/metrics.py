"""Prometheus metrics registry endpoint.

Exposes the shared ``CollectorRegistry`` in Prometheus text exposition format
so that scrapers such as Prometheus can collect application metrics.
"""

from __future__ import annotations

from fastapi import APIRouter, Response
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

from margin.core.metrics import REGISTRY

router = APIRouter(tags=["metrics"])


@router.get("/metrics")
def metrics() -> Response:
    """Return the current metrics payload in Prometheus exposition format.

    Returns:
        A Response with Prometheus-formatted metrics content and the
        appropriate content type.
    """
    return Response(content=generate_latest(REGISTRY), media_type=CONTENT_TYPE_LATEST)
