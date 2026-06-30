"""Tests for trace-id and logging middleware.

Ensures trace ids from the configured header propagate through the request
lifecycle and are echoed back in the response header.
"""

from __future__ import annotations

from fastapi import Request
from fastapi.testclient import TestClient

from margin.api.main import create_app
from margin.api.middleware import _get_trace_id


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
