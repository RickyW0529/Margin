from __future__ import annotations

import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread

from scripts import smoke_valuation_discovery_p1


class _AcceptedHandler(BaseHTTPRequestHandler):
    def do_POST(self) -> None:  # noqa: N802 - stdlib callback name
        body = json.dumps({"run_id": "run-local"}).encode("utf-8")
        self.send_response(200)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args: object) -> None:  # noqa: A002
        return


class _ProxyFailHandler(BaseHTTPRequestHandler):
    def do_POST(self) -> None:  # noqa: N802 - stdlib callback name
        self.send_response(502)
        self.end_headers()
        self.wfile.write(b"proxy should not be used")

    def log_message(self, format: str, *args: object) -> None:  # noqa: A002
        return


def _serve(handler: type[BaseHTTPRequestHandler]) -> tuple[ThreadingHTTPServer, int]:
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, server.server_address[1]


def test_smoke_posts_to_local_api_without_proxy(
    monkeypatch,
    capsys,
) -> None:
    api_server, api_port = _serve(_AcceptedHandler)
    proxy_server, proxy_port = _serve(_ProxyFailHandler)
    monkeypatch.setenv("MARGIN_ADMIN_API_TOKEN", "admin")
    monkeypatch.setenv("MARGIN_CSRF_TOKEN", "csrf")
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
