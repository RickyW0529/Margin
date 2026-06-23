#!/usr/bin/env python3
"""Token-safe dashboard E2E smoke for the Margin web frontend.

The script intentionally does not type, print, or read provider secrets. It
checks the browser-facing pages over HTTP and follows live item/run links when
the running environment has seeded data.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import asdict, dataclass
from html import unescape
from urllib.error import URLError
from urllib.parse import urljoin, urlparse
from urllib.request import ProxyHandler, Request, build_opener, urlopen


@dataclass(frozen=True)
class Stage:
    """One dashboard smoke stage result."""

    name: str
    status: str
    detail: str = ""


SECRET_PATTERNS = (
    re.compile(r"tvly-[A-Za-z0-9_-]+"),
    re.compile(r"secret_value", re.IGNORECASE),
    re.compile(r"api[_-]?token['\"]?\s*[:=]", re.IGNORECASE),
)
LOCAL_DASHBOARD_HOSTS = {"localhost", "127.0.0.1", "::1"}
NO_PROXY_OPENER = build_opener(ProxyHandler({}))


def main() -> int:
    """Run the dashboard E2E smoke."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://localhost:3000")
    parser.add_argument("--scope-version-id", default="scope-current")
    parser.add_argument("--require-live-data", action="store_true")
    args = parser.parse_args()

    stages: list[Stage] = []
    try:
        scope_html = fetch(args.base_url, "/settings/scope")
        stages.append(assert_contains("settings_scope", scope_html, "Scope 设置"))
        stages.append(assert_secret_safe("settings_scope_secret_safe", scope_html))

        providers_html = fetch(args.base_url, "/settings/providers")
        stages.append(
            assert_contains("settings_providers", providers_html, "Provider 密钥配置")
        )
        stages.append(assert_secret_safe("settings_providers_secret_safe", providers_html))

        strategy_html = fetch(args.base_url, "/settings/strategy")
        stages.append(assert_contains("settings_strategy", strategy_html, "Strategy 设置"))

        research_path = f"/research?scope_version_id={args.scope_version_id}&universe=ALL_A"
        research_html = fetch(args.base_url, research_path)
        stages.append(assert_contains("research_list", research_html, "研究候选面板"))
        stages.append(assert_secret_safe("research_list_secret_safe", research_html))

        item_path = first_href(research_html, r"/research/items/[^\"'#?]+")
        if item_path:
            item_html = fetch(args.base_url, item_path)
            stages.append(assert_contains("research_item_detail", item_html, "Research Item"))
            stages.append(assert_contains("research_item_evidence", item_html, "证据定位"))
            stages.append(assert_secret_safe("research_item_secret_safe", item_html))
        else:
            status = "failed" if args.require_live_data else "skipped"
            stages.append(Stage("research_item_detail", status, "no item link found"))

        run_path = first_href(research_html, r"/research/runs/[^\"'#?]+")
        if run_path:
            run_html = fetch(args.base_url, run_path)
            stages.append(assert_contains("research_run_detail", run_html, "Research Run"))
            stages.append(assert_secret_safe("research_run_secret_safe", run_html))
        else:
            status = "failed" if args.require_live_data else "skipped"
            stages.append(Stage("research_run_detail", status, "no run link found"))
    except URLError as exc:
        stages.append(Stage("frontend_reachable", "failed", str(exc.reason)))
    except TimeoutError as exc:
        stages.append(Stage("frontend_reachable", "failed", str(exc)))

    failed = [stage for stage in stages if stage.status == "failed"]
    payload = {
        "status": "failed" if failed else "ok",
        "base_url": args.base_url,
        "stages": [asdict(stage) for stage in stages],
    }
    print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
    return 1 if failed else 0


def fetch(base_url: str, path: str) -> str:
    """Fetch one frontend path and return decoded HTML."""
    url = urljoin(base_url.rstrip("/") + "/", path.lstrip("/"))
    request = Request(url, headers={"accept": "text/html"})
    opener = NO_PROXY_OPENER.open if _is_local_dashboard_url(url) else urlopen
    with opener(request, timeout=10) as response:  # noqa: S310 - smoke target is user-provided
        if response.status >= 400:
            raise URLError(f"HTTP {response.status} for {path}")
        return response.read().decode("utf-8", errors="replace")


def _is_local_dashboard_url(url: str) -> bool:
    """Return true when a dashboard smoke URL should bypass system proxies."""
    return (urlparse(url).hostname or "").lower() in LOCAL_DASHBOARD_HOSTS


def assert_contains(name: str, html: str, needle: str) -> Stage:
    """Assert one page contains an expected marker."""
    return Stage(name, "ok" if needle in html else "failed", f"expected={needle}")


def assert_secret_safe(name: str, html: str) -> Stage:
    """Assert page HTML does not contain obvious secret material."""
    for pattern in SECRET_PATTERNS:
        if pattern.search(html):
            return Stage(name, "failed", f"matched={pattern.pattern}")
    return Stage(name, "ok")


def first_href(html: str, pattern: str) -> str | None:
    """Extract the first href path matching a regex."""
    for match in re.finditer(r"href=[\"']([^\"']+)[\"']", html):
        href = unescape(match.group(1))
        found = re.search(pattern, href)
        if found:
            return found.group(0)
    return None


if __name__ == "__main__":
    sys.exit(main())
