"""Proxy-bypass tests for the valuation-discovery P1 smoke script.

Verifies that ``scripts.smoke_valuation_discovery_p1.main`` posts to the local
API without using HTTP proxy environment variables.
"""

from __future__ import annotations

import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread

from scripts import smoke_valuation_discovery_p1


class _AcceptedHandler(BaseHTTPRequestHandler):
    """HTTP handler that accepts POST requests and returns a run-id JSON body.."""

    def do_POST(self) -> None:  # noqa: N802 - stdlib callback name
        """Return a 200 JSON response with a deterministic run_id.

        Returns:
            None: .
        """
        body = json.dumps({"run_id": "run-local"}).encode("utf-8")
        self.send_response(200)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args: object) -> None:  # noqa: A002
        """Suppress default request logging.

        Args:
            format: str: .
            *args: object: .

        Returns:
            None: .
        """
        return


class _ProxyFailHandler(BaseHTTPRequestHandler):
    """HTTP handler that returns 502 on POST to detect proxy usage.."""

    def do_POST(self) -> None:  # noqa: N802 - stdlib callback name
        """Return a 502 response indicating the proxy should not be used.

        Returns:
            None: .
        """
        self.send_response(502)
        self.end_headers()
        self.wfile.write(b"proxy should not be used")

    def log_message(self, format: str, *args: object) -> None:  # noqa: A002
        """Suppress default request logging.

        Args:
            format: str: .
            *args: object: .

        Returns:
            None: .
        """
        return


def _serve(handler: type[BaseHTTPRequestHandler]) -> tuple[ThreadingHTTPServer, int]:
    """Start a local threaded HTTP server with the given handler and return it with its port.

    Args:
        handler: type[BaseHTTPRequestHandler]: .

    Returns:
        tuple[ThreadingHTTPServer, int]: .
    """
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, server.server_address[1]


def test_smoke_posts_to_local_api_without_proxy(
    monkeypatch,
    capsys,
) -> None:
    """Test that the smoke script posts to the local API without using a proxy.

    Args:
        monkeypatch: Any: .
        capsys: Any: .

    Returns:
        None: .
    """
    api_server, api_port = _serve(_AcceptedHandler)
    proxy_server, proxy_port = _serve(_ProxyFailHandler)
    monkeypatch.setenv("http_proxy", f"http://127.0.0.1:{proxy_port}")
    monkeypatch.setenv("HTTP_PROXY", f"http://127.0.0.1:{proxy_port}")
    monkeypatch.setenv("no_proxy", "")
    monkeypatch.setenv("NO_PROXY", "")
    monkeypatch.setattr(
        "sys.argv",
        [
            "smoke_valuation_discovery_p1.py",
            "--scope-version-id",
            "scope-current",
            "--decision-at",
            "2026-06-23T00:00:00+00:00",
            "--api-url",
            f"http://127.0.0.1:{api_port}",
        ],
    )

    try:
        exit_code = smoke_valuation_discovery_p1.main()
    finally:
        api_server.shutdown()
        proxy_server.shutdown()

    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["run_id"] == "run-local"
