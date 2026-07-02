#!/usr/bin/env python3
"""Run the quant-only rolling Tushare source backfill."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime

from margin.core.secret import SecretManager, SecretNotFoundError
from margin.data.company_pool import SQLAlchemyCompanyPoolRepository
from margin.data.ingestion import DataWarehouseIngestionStack
from margin.data.policy import DataAcquisitionPolicyVersion
from margin.data.tushare_backfill import (
    TushareBackfillConfig,
    TushareBackfillService,
)
from margin.data.tushare_repository import SQLAlchemyTushareSourceRepository
from margin.data.tushare_warehouse import TushareWarehousePublisher
from margin.settings import get_settings
from margin.storage.database import create_database_engine, create_session_factory


def main(argv: list[str] | None = None) -> int:
    """Execute a rolling backfill and print a secret-free coverage report."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--months", type=int, default=24)
    parser.add_argument("--start-date")
    parser.add_argument("--end-date")
    parser.add_argument("--comparison-years", type=int, default=1)
    parser.add_argument("--endpoints", default="")
    parser.add_argument("--idempotency-key")
    parser.add_argument("--output-json")
    args = parser.parse_args(argv)

    settings = get_settings()
    token = _resolve_tushare_token()
    if token is None:
        print(json.dumps({"status": "failed", "error": "token_not_configured"}))
        return 2
    import tushare as ts

    client = ts.pro_api(token=token)
    engine = create_database_engine()
    session_factory = create_session_factory(engine)
    repository = SQLAlchemyTushareSourceRepository(session_factory)
    company_pool_repository = SQLAlchemyCompanyPoolRepository(session_factory)
    warehouse_publisher = TushareWarehousePublisher(
        DataWarehouseIngestionStack(
            session_factory=session_factory,
            snapshot_root=settings.data_snapshot_root,
        )
    )
    now = (
        datetime.strptime(args.end_date, "%Y-%m-%d").replace(hour=16, tzinfo=UTC)
        if args.end_date
        else datetime.now(UTC)
    )
    policy = DataAcquisitionPolicyVersion(
        version_id="cli-window",
        rolling_window_months=args.months,
        financial_comparison_years=args.comparison_years,
    )
    window = policy.window_for(now)
    window_start = (
        datetime.strptime(args.start_date, "%Y-%m-%d").replace(tzinfo=UTC)
        if args.start_date
        else window.start
    )
    endpoints = tuple(
        item.strip()
        for item in args.endpoints.split(",")
        if item.strip()
    )
    idempotency_key = args.idempotency_key or (
        f"tushare-{args.months}m-{now.date().isoformat()}-"
        f"{','.join(endpoints) or 'all'}"
    )
    try:
        report = TushareBackfillService(
            client=client,
            repository=repository,
            warehouse_publisher=warehouse_publisher,
            company_pool_repository=company_pool_repository,
        ).run(
            TushareBackfillConfig(
                window_start=window_start,
                window_end=window.end,
                financial_comparison_years=args.comparison_years,
                endpoints=endpoints,
                idempotency_key=idempotency_key,
            )
        )
        payload = {"status": "ok", **report.model_dump(mode="json")}
    finally:
        engine.dispose()
    output = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    if args.output_json:
        with open(args.output_json, "w", encoding="utf-8") as handle:
            handle.write(output + "\n")
    else:
        print(output)
    return 0


def _resolve_tushare_token() -> str | None:
    """Resolve the Tushare token for this manual backfill script."""
    try:
        token = SecretManager().resolve("tushare_token").strip()
    except SecretNotFoundError:
        return None
    return token or None


if __name__ == "__main__":
    sys.exit(main())
