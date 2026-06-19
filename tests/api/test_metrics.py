"""Tests for Prometheus metrics endpoint.

Checks that the ``/metrics`` endpoint exposes the HTTP request counter after at
least one request has been served.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from margin.api.main import create_app


def test_metrics_endpoint_exposes_http_requests():
    app = create_app()
    client = TestClient(app)
    # Make at least one request so the HTTP counter is non-zero and visible.
    client.get("/health")
    response = client.get("/metrics")
    assert response.status_code == 200
    assert "margin_http_requests_total" in response.text
