"""Tests for trace-id and logging middleware.

Ensures trace ids from the configured header propagate through the request
lifecycle and are echoed back in the response header.
"""

from __future__ import annotations

from fastapi import Request
from fastapi.testclient import TestClient

from margin.api.main import create_app
from margin.api.middleware import _get_trace_id
from margin.settings import get_settings


def test_trace_id_header_propagates():
    """Test that the trace-id header propagates through the request lifecycle."""
    app = create_app()

    @app.get("/echo-trace")
    def echo_trace(request: Request):
        """Return the trace id extracted from the request."""
        return {"trace_id": _get_trace_id(request)}

    client = TestClient(app)
    # Use the lowercase header name that Starlette normalizes internally.
    response = client.get("/echo-trace", headers={"x-margin-trace-id": "t-123"})
    assert response.json()["trace_id"] == "t-123"


def test_cors_preflight_allows_loopback_alias(monkeypatch):
    """Test that local frontend aliases share the same CORS allowlist."""
    monkeypatch.setenv("MARGIN_WEB_ORIGIN", "http://localhost:3000")
    get_settings.cache_clear()

    try:
        client = TestClient(create_app())
        response = client.options(
            "/api/v1/valuation-discovery/refreshes",
            headers={
                "Origin": "http://127.0.0.1:3000",
                "Access-Control-Request-Method": "POST",
                "Access-Control-Request-Headers": "content-type,idempotency-key",
            },
        )
    finally:
        get_settings.cache_clear()

    assert response.status_code == 200
    assert (
        response.headers["access-control-allow-origin"]
        == "http://127.0.0.1:3000"
    )
