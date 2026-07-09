"""CLI for deterministic 20-year backfill campaign dry-runs."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from datetime import date
from typing import Any

from margin.data.backfill.campaign import BackfillCampaignService
from margin.data.backfill.planner import BackfillPlanner
from margin.data.backfill.publisher import BackfillPublisher
from margin.data.backfill.quality import BackfillQualityService


def build_parser() -> argparse.ArgumentParser:
    """Build parser.

    Returns:
        argparse.ArgumentParser: .
    """
    parser = argparse.ArgumentParser(prog="python -m margin.cli.backfill")
    subparsers = parser.add_subparsers(dest="command", required=True)

    init_parser = subparsers.add_parser("init")
    init_parser.add_argument("--years", type=int, default=20)
    init_parser.add_argument("--start-date", default="2006-01-01")
    init_parser.add_argument("--end-date", default="auto")
    init_parser.add_argument("--providers", default="tushare,akshare")
    init_parser.add_argument("--campaign-name", default="full_market_20y")
    init_parser.add_argument("--today", default=None)

    for command in ("run", "verify", "publish"):
        command_parser = subparsers.add_parser(command)
        command_parser.add_argument("--campaign-id", required=True)
    return parser


def run_command(argv: Sequence[str]) -> dict[str, Any]:
    """Run command.

    Args:
        argv: Sequence[str]: .

    Returns:
        dict[str, Any]: .
    """
    args = build_parser().parse_args(list(argv))
    if args.command == "init":
        today = date.fromisoformat(args.today) if args.today else None
        providers = tuple(
            provider.strip() for provider in str(args.providers).split(",") if provider.strip()
        )
        end_date: date | str = (
            date.fromisoformat(args.end_date) if _is_iso_date(args.end_date) else args.end_date
        )
        service = BackfillCampaignService(today=today)
        campaign = service.init_campaign(
            campaign_name=args.campaign_name,
            providers=providers,
            years=args.years,
            start_date=args.start_date,
            end_date=end_date,
        )
        planner = BackfillPlanner()
        endpoint_plan = planner.plan_endpoints(campaign)
        partitions = planner.plan_partitions(campaign, endpoint_plan)
        return {
            "command": "init",
            "campaign": campaign.model_dump(mode="json"),
            "endpoint_count": len(endpoint_plan.endpoints),
            "partition_count": len(partitions),
            "endpoint_plan_hash": endpoint_plan.payload_hash,
        }
    if args.command == "run":
        return {
            "command": "run",
            "campaign_id": args.campaign_id,
            "status": "dry_run_ready",
            "safe_summary": "Use live executor wiring to fetch provider data.",
        }
    if args.command == "verify":
        quality = BackfillQualityService()
        report = quality.validate_pit_visibility(rows=[])
        return {
            "command": "verify",
            "campaign_id": args.campaign_id,
            "pit_validation": report.model_dump(mode="json"),
        }
    publisher = BackfillPublisher()
    return {
        "command": "publish",
        "campaign_id": args.campaign_id,
        "status": "blocked",
        "safe_summary": (
            "Publish requires a persisted campaign and a passing quality report; "
            f"{publisher.__class__.__name__} enforces this in service code."
        ),
    }


def main(argv: Sequence[str] | None = None) -> int:
    """Main.

    Args:
        argv: Sequence[str] | None: .

    Returns:
        int: .
    """
    output = run_command(sys.argv[1:] if argv is None else argv)
    print(json.dumps(output, ensure_ascii=False, sort_keys=True, indent=2))
    return 0


def _is_iso_date(value: object) -> bool:
    """Is iso date.

    Args:
        value: object: .

    Returns:
        bool: .
    """
    if not isinstance(value, str):
        return False
    try:
        date.fromisoformat(value)
    except ValueError:
        return False
    return True


if __name__ == "__main__":
    raise SystemExit(main())
