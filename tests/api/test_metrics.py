"""Tests for Prometheus metrics endpoint.

Checks that the ``/metrics`` endpoint exposes the HTTP request counter after at
least one request has been served.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from margin.api.main import create_app


def test_metrics_endpoint_exposes_http_requests():
    """Test that the metrics endpoint exposes HTTP request counters.

    Returns:
        Any: .
    """
    app = create_app()
    client = TestClient(app)
    # Make at least one request so the HTTP counter is non-zero and visible.
    client.get("/health")
    response = client.get("/metrics")
    assert response.status_code == 200
    assert "margin_http_requests_total" in response.text


def test_metrics_endpoint_exposes_v02_orchestration_metrics():
    """Test that the metrics endpoint exposes v0.2 orchestration metrics.

    Returns:
        Any: .
    """
    client = TestClient(create_app())

    response = client.get("/metrics")

    assert response.status_code == 200
    assert "margin_queue_age_seconds" in response.text
    assert "margin_provider_request_total" in response.text
    assert "margin_run_duration_seconds" in response.text
    assert "margin_outbox_lag_seconds" in response.text
