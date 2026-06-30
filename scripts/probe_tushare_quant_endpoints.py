#!/usr/bin/env python3
"""Probe all quant-admitted Tushare APIs with low-volume redacted output."""

from __future__ import annotations

import json
import os
import sys
from datetime import UTC, datetime
from typing import Any

from margin.data.tushare_query import TushareQueryCatalog


def _safe_error(exc: Exception) -> str:
    """Redact known secret values from an exception message."""
    message = str(exc)
    for secret_name in ("MARGIN_TUSHARE_TOKEN", "TUSHARE_TOKEN"):
        secret = os.getenv(secret_name, "")
        if secret:
            message = message.replace(secret, "***")
    return message[:500]


def main() -> int:
    """Run one minimal call per admitted API and emit JSON lines."""
    import tushare as ts

    token = os.getenv("MARGIN_TUSHARE_TOKEN", "")
    if not token:
        print(json.dumps({"status": "failed", "error": "token_not_configured"}))
        return 2
    client = ts.pro_api(token=token)
    http_url = os.getenv("MARGIN_TUSHARE_HTTP_URL", "").strip()
    if http_url:
        client._DataApi__http_url = http_url

    catalog = TushareQueryCatalog.default()
    as_of = datetime.now(UTC)
    failed = 0
    industry_code = "801010.SI"
    industry_codes = [industry_code]
    for api_name in catalog.api_names():
        params = catalog.probe_params(
            api_name,
            as_of=as_of,
            sample_symbol="000001.SZ",
            industry_code=industry_code,
        )
        try:
            frame: Any
            if api_name == "index_member":
                frame = client.query(api_name, **params)
                for candidate in industry_codes:
                    if len(frame.index):
                        break
                    params["index_code"] = candidate
                    frame = client.query(api_name, **params)
            else:
                frame = client.query(api_name, **params)
            row_count = int(len(frame.index))
            columns = [str(column) for column in frame.columns]
            if api_name == "index_classify" and row_count:
                industry_code = str(frame.iloc[0].get("index_code") or industry_code)
                industry_codes = [
                    str(value)
                    for value in frame["index_code"].tolist()
                    if str(value).strip()
                ]
            status = "ok_nonempty" if row_count else "ok_empty"
            payload = {
                "api_name": api_name,
                "status": status,
                "rows": row_count,
                "columns": columns,
            }
        except Exception as exc:  # noqa: BLE001 - probe records provider behavior.
            failed += 1
            payload = {
                "api_name": api_name,
                "status": "failed",
                "error_type": type(exc).__name__,
                "error": _safe_error(exc),
            }
        print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
