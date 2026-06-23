#!/usr/bin/env python3
"""Token-safe real WebSearch smoke for module 03."""

from __future__ import annotations

import argparse
import os
import sys

from margin.news.providers.tavily import TavilySearchAdapter
from margin.news.websearch import WebSearchProvider


def main() -> int:
    """main."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--query", default="平安银行 公告")
    parser.add_argument("--max-results", type=int, default=3)
    args = parser.parse_args()

    api_key = os.getenv("MARGIN_WEBSEARCH_API_KEY", "").strip()
    if not api_key:
        print("provider=tavily status=blocked external_blocker=missing_secret")
        return 2

    try:
        adapter = TavilySearchAdapter(api_key=api_key)
        provider = WebSearchProvider(
            name="tavily_websearch",
            search_func=adapter.search,
        )
        record = provider.search(args.query, max_results=args.max_results)
    except Exception as exc:  # noqa: BLE001 - smoke reports only classified status
        error_code = getattr(exc, "code", "provider_unreachable")
        print(f"provider=tavily status=failed external_blocker={error_code}")
        return 3

    snapshot_count = sum(1 for result in record.results if result.snapshot_id)
    print(
        "provider=tavily "
        "status=ok "
        f"result_count={record.result_count} "
        f"query_id={record.query_id} "
        f"snapshot_ids={snapshot_count}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
