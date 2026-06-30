#!/usr/bin/env python3
"""Real data-provider smoke for the v0.2 PIT warehouse.

The script prints only provider names, statuses, counts, and snapshot IDs. It
never prints API tokens. Unit tests exercise ``--dry-run``; real verification
must run without ``--dry-run`` against configured providers.
"""

from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime, timedelta
from typing import Any

from margin.core.secret import SecretManager, SecretNotFoundError
from margin.data.ingestion import DataWarehouseIngestionStack
from margin.data.providers.akshare_provider import AKShareProvider
from margin.data.providers.tushare_provider import TushareProvider
from margin.data.warehouse_repository import CanonicalQuery
from margin.settings import MarginSettings
from margin.storage.database import (
    DatabaseSettings,
    create_database_engine,
    create_session_factory,
)


def main() -> int:
    """Run the smoke check and return a process exit code."""
    args = _parse_args()
    settings = MarginSettings(_env_file=None)
    providers = _parse_csv(args.providers)
    symbols = tuple(_parse_csv(args.symbols or settings.data_smoke_symbols))
    token = _resolve_tushare_token(settings)
    if args.dry_run:
        print(
            json.dumps(
                {
                    "dry_run": True,
                    "providers": [
                        _provider_dry_run_status(provider, token) for provider in providers
                    ],
                },
                ensure_ascii=False,
            )
        )
        return 0

    stack = _build_stack(settings)
    decision_at = _decision_at(args.end_date)
    start = decision_at - timedelta(days=args.days)
    secret_values = [value for value in [token] if value]
    results: list[dict[str, Any]] = []
    exit_code = 0
    for provider_name in providers:
        provider_name = provider_name.lower()
        if provider_name == "tushare" and not token:
            results.append({"provider": "tushare", "status": "missing_secret"})
            exit_code = 2
            continue
        try:
            provider = _build_provider(provider_name, token, settings.tushare_http_url)
            result = stack.sync_daily_bars(
                provider,
                symbols=symbols,
                start=start,
                end=decision_at,
                decision_at=decision_at,
            )
            values = stack.warehouse.canonical_values(
                CanonicalQuery(
                    security_ids=symbols,
                    indicator_ids=("close",),
                    decision_at=decision_at,
                )
            )
            results.append(
                {
                    "provider": provider_name,
                    "status": result.status.value,
                    "raw_snapshot_ids": list(result.raw_snapshot_ids),
                    "fact_count": result.fact_count,
                    "canonical_count": result.canonical_count,
                    "canonical_value_count": len(values),
                    "finished_at": result.finished_at.isoformat(),
                }
            )
        except Exception as exc:  # noqa: BLE001
            results.append(
                {
                    "provider": provider_name,
                    "status": "failed",
                    "error": _redact(str(exc), secret_values),
                }
            )
            exit_code = 1
    print(json.dumps({"dry_run": False, "providers": results}, ensure_ascii=False))
    return exit_code


def _parse_args() -> argparse.Namespace:
    """Parse command-line arguments for the data-provider smoke."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--providers",
        default="akshare,tushare",
        help="Comma-separated providers to smoke, e.g. akshare,tushare.",
    )
    parser.add_argument(
        "--symbols",
        default="",
        help="Comma-separated symbols. Defaults to MARGIN_DATA_SMOKE_SYMBOLS.",
    )
    parser.add_argument("--days", type=int, default=7, help="Calendar-day lookback window.")
    parser.add_argument(
        "--end-date",
        default="",
        help="UTC end date for deterministic smoke windows, formatted YYYY-MM-DD.",
    )
    parser.add_argument("--dry-run", action="store_true", help="Validate config without network.")
    return parser.parse_args()


def _build_stack(settings: MarginSettings) -> DataWarehouseIngestionStack:
    """Build a DataWarehouseIngestionStack from application settings."""
    engine = create_database_engine(
        DatabaseSettings(
            url=str(settings.database_url),
            echo=settings.database_echo,
            pool_pre_ping=settings.database_pool_pre_ping,
        )
    )
    return DataWarehouseIngestionStack(
        session_factory=create_session_factory(engine),
        snapshot_root=settings.data_snapshot_root,
    )


def _build_provider(provider_name: str, tushare_token: str | None, tushare_http_url: str | None):
    """Instantiate a data provider by name."""
    if provider_name == "akshare":
        return AKShareProvider()
    if provider_name == "tushare":
        return TushareProvider(token=tushare_token, http_url=tushare_http_url)
    raise ValueError(f"unsupported data provider: {provider_name}")


def _resolve_tushare_token(settings: MarginSettings) -> str | None:
    """Resolve the Tushare API token from settings or secret manager."""
    if settings.tushare_token is not None:
        token = settings.tushare_token.get_secret_value().strip()
        if token:
            return token
    try:
        token = SecretManager().resolve("tushare_token").strip()
    except SecretNotFoundError:
        return None
    return token or None


def _provider_dry_run_status(provider_name: str, tushare_token: str | None) -> dict[str, str]:
    """Return dry-run status for a provider without network calls."""
    provider_name = provider_name.lower()
    if provider_name == "tushare":
        return {
            "provider": provider_name,
            "status": "configured" if tushare_token else "missing_secret",
        }
    return {"provider": provider_name, "status": "configured"}


def _parse_csv(value: str) -> list[str]:
    """Split a comma-separated string into a stripped token list."""
    return [item.strip() for item in value.split(",") if item.strip()]


def _decision_at(end_date: str) -> datetime:
    """Parse an end-date string or return current UTC time."""
    if not end_date:
        return datetime.now(UTC)
    return datetime.strptime(end_date, "%Y-%m-%d").replace(tzinfo=UTC)


def _redact(message: str, secret_values: list[str]) -> str:
    """Replace known secret values in a message with [REDACTED]."""
    redacted = message
    for secret in secret_values:
        if secret:
            redacted = redacted.replace(secret, "[REDACTED]")
    return redacted


if __name__ == "__main__":
    raise SystemExit(main())
