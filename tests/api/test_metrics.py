"""Tests for Prometheus metrics endpoint."""

from __future__ import annotations

from fastapi.testclient import TestClient

from margin.api.main import create_app


def test_metrics_endpoint_exposes_http_requests():
    app = create_app()
    client = TestClient(app)
    client.get("/health")
    response = client.get("/metrics")
    assert response.status_code == 200
    assert "margin_http_requests_total" in response.text
