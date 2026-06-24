#!/usr/bin/env python3
"""Probe scalable financial query variants without exposing credentials."""

from __future__ import annotations

import json
import os
import sys

from margin.data.tushare_query import TushareQueryCatalog


def main() -> int:
    """Probe bulk parameter variants for statement-like APIs."""
    import tushare as ts

    token = os.getenv("MARGIN_TUSHARE_TOKEN", "")
    if not token:
        return 2
    client = ts.pro_api(token=token)
    if os.getenv("MARGIN_TUSHARE_HTTP_URL"):
        client._DataApi__http_url = os.environ["MARGIN_TUSHARE_HTTP_URL"]
    catalog = TushareQueryCatalog.default()
    variants = {
        "date_range": {"start_date": "20260101", "end_date": "20260622"},
        "announcement": {"ann_date": "20260430"},
        "period": {"period": "20251231"},
        "symbol": {"ts_code": "000001.SZ"},
        "symbol_csv": {"ts_code": "000001.SZ,000002.SZ"},
    }
    for api_name in (
        "income",
        "balancesheet",
        "cashflow",
        "fina_indicator",
        "fina_audit",
        "pledge_stat",
    ):
        for variant, params in variants.items():
            try:
                frame = client.query(
                    api_name,
                    **params,
                    fields=catalog.get(api_name).fields_csv,
                    limit=20,
                )
                output = {
                    "api_name": api_name,
                    "variant": variant,
                    "rows": len(frame.index),
                    "symbol_count": (
                        int(frame["ts_code"].nunique())
                        if "ts_code" in frame.columns
                        else 0
                    ),
                    "columns": [str(column) for column in frame.columns],
                    "status": "ok_nonempty" if len(frame.index) else "ok_empty",
                }
            except Exception as exc:  # noqa: BLE001
                output = {
                    "api_name": api_name,
                    "variant": variant,
                    "status": "failed",
                    "error": str(exc)[:160],
                }
            print(json.dumps(output, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
