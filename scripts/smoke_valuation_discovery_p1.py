"""P1 smoke for the full valuation discovery refresh API path."""

from __future__ import annotations

import argparse
import json
import urllib.error
import urllib.request
from datetime import datetime
from typing import Any
from urllib.parse import urlparse

LOCAL_API_HOSTS = {"localhost", "127.0.0.1", "::1"}
NO_PROXY_OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def main() -> int:
    """Run the P1 valuation-discovery refresh API smoke.

    Returns:
        int: 0 on success, 2 when the API returns an error.
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scope-version-id", required=True)
    parser.add_argument("--decision-at", required=True)
    parser.add_argument("--api-url", default="http://127.0.0.1:8000")
    parser.add_argument("--idempotency-key", default="valuation-discovery-smoke")
    args = parser.parse_args()

    decision_at = _parse_datetime(args.decision_at)
    payload = json.dumps(
        {
            "scope_version_id": args.scope_version_id,
            "decision_at": decision_at.isoformat(),
        }
    ).encode("utf-8")
    request = urllib.request.Request(
        f"{args.api_url.rstrip('/')}/api/v1/valuation-discovery/refreshes",
        data=payload,
        method="POST",
        headers={
            "Content-Type": "application/json",
            "Idempotency-Key": args.idempotency_key,
        },
    )
    try:
        opener = (
            NO_PROXY_OPENER.open
            if _is_local_api_url(args.api_url)
            else urllib.request.urlopen
        )
        with opener(request, timeout=30) as response:  # noqa: S310
            body = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        body = _safe_error_body(exc)
        code = "service_not_configured" if exc.code == 503 else f"http_{exc.code}"
        return _emit_failure(code, body)
    except urllib.error.URLError as exc:
        return _emit_failure("api_unreachable", {"reason": str(exc.reason)})

    print(
        json.dumps(
            {
                "status": "ok",
                "run_id": body["run_id"],
                "stages": "accepted",
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0


def _parse_datetime(value: str) -> datetime:
    """Parse a timezone-aware ISO 8601 datetime string."""
    normalized = value.replace("Z", "+00:00")
    parsed = datetime.fromisoformat(normalized)
    if parsed.utcoffset() is None:
        raise ValueError("--decision-at must be timezone-aware")
    return parsed


def _safe_error_body(exc: urllib.error.HTTPError) -> dict[str, Any]:
    """Best-effort parse of an HTTPError JSON body, falling back to reason."""
    try:
        return json.loads(exc.read().decode("utf-8"))
    except Exception:  # noqa: BLE001
        return {"detail": exc.reason}


def _is_local_api_url(url: str) -> bool:
    """Return true when an API smoke URL should bypass system proxies."""
    return (urlparse(url).hostname or "").lower() in LOCAL_API_HOSTS


def _emit_failure(code: str, details: dict[str, Any]) -> int:
    """Print a JSON failure payload and return exit code 2."""
    print(
        json.dumps(
            {
                "status": "failed",
                "external_blocker": code,
                "details": details,
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
