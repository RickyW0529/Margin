"""Proxy-bypass tests for the dashboard end-to-end smoke script.

Verifies that ``scripts.smoke_dashboard_e2e.fetch`` bypasses HTTP proxy
environment variables when fetching local dashboard pages.
"""

from __future__ import annotations

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread

from scripts import smoke_dashboard_e2e


class _OkHandler(BaseHTTPRequestHandler):
    """HTTP handler that always returns a 200 HTML response.."""

    def do_GET(self) -> None:  # noqa: N802 - stdlib callback name
        """Return a 200 response with a minimal HTML body.

        Returns:
            None: .
        """
        self.send_response(200)
        self.send_header("content-type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write(b"<html><body>Scope \xe8\xae\xbe\xe7\xbd\xae</body></html>")

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
    """HTTP handler that always returns a 502 response to detect proxy usage.."""

    def do_GET(self) -> None:  # noqa: N802 - stdlib callback name
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


def test_fetch_bypasses_proxy_for_local_dashboard(monkeypatch) -> None:
    """Test that fetch bypasses proxy settings when fetching a local dashboard page.

    Args:
        monkeypatch: Any: .

    Returns:
        None: .
    """
    target_server, target_port = _serve(_OkHandler)
    proxy_server, proxy_port = _serve(_ProxyFailHandler)
    monkeypatch.setenv("http_proxy", f"http://127.0.0.1:{proxy_port}")
    monkeypatch.setenv("HTTP_PROXY", f"http://127.0.0.1:{proxy_port}")
    monkeypatch.setenv("no_proxy", "")
    monkeypatch.setenv("NO_PROXY", "")

    try:
        html = smoke_dashboard_e2e.fetch(f"http://127.0.0.1:{target_port}", "/settings/scope")
    finally:
        target_server.shutdown()
        proxy_server.shutdown()

    assert "Scope 设置" in html
