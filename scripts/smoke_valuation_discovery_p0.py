"""P0 smoke for valuation discovery quant path.

This script never fabricates market/fundamental data. It requires a persisted
QuantInputSnapshot and either a real cross-section CSV exported from the data
warehouse or a production cross-section loader wired outside the script.
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd

from margin.settings import get_settings
from margin.storage.database import (
    DatabaseSettings,
    create_database_engine,
    create_session_factory,
)
from margin.valuation_discovery.quant.repository import SQLAlchemyQuantRepository
from margin.valuation_discovery.quant.service import QuantService
from margin.valuation_discovery.repository import SQLAlchemyValuationDiscoveryRepository


def main() -> int:
    """Run the P0 valuation-discovery quant smoke against real data.

    Returns:
        int: 0 on success, 2 when required inputs are missing or invalid.
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scope-version-id", required=True)
    parser.add_argument("--decision-at", required=True)
    parser.add_argument("--database-url")
    parser.add_argument(
        "--cross-section-csv",
        help="Real warehouse-exported quant cross-section CSV. No sample data is generated.",
    )
    args = parser.parse_args()

    decision_at = _parse_datetime(args.decision_at)
    database_url = args.database_url or str(get_settings().database_url)
    engine = create_database_engine(DatabaseSettings(url=database_url))
    session_factory = create_session_factory(engine)
    try:
        valuation_repository = SQLAlchemyValuationDiscoveryRepository(session_factory)
        snapshots = [
            snapshot
            for snapshot in valuation_repository.list_quant_input_snapshots()
            if snapshot.scope_version_id == args.scope_version_id
            and snapshot.decision_at == decision_at
        ]
        if not snapshots:
            return _emit_failure(
                "missing_quant_input_snapshot",
                {
                    "scope_version_id": args.scope_version_id,
                    "decision_at": decision_at.isoformat(),
                },
            )
        snapshot = snapshots[-1]
        if not snapshot.is_valid:
            return _emit_failure(
                "invalid_quant_input_snapshot",
                {
                    "snapshot_id": snapshot.snapshot_id,
                    "missing_required": list(snapshot.missing_required),
                },
            )
        if args.cross_section_csv is None:
            return _emit_failure(
                "missing_real_cross_section",
                {
                    "snapshot_id": snapshot.snapshot_id,
                    "message": "pass --cross-section-csv exported from the real warehouse",
                },
            )
        cross_section = pd.read_csv(Path(args.cross_section_csv))
        quant_repository = SQLAlchemyQuantRepository(
            session_factory,
            cross_section_loader=lambda _: cross_section,
        )
        quant_run = QuantService(quant_repository).run(snapshot, decision_at=decision_at)
        results = quant_repository.list_results(quant_run.quant_run_id)
        pass_count = sum(result.screening_status.value == "pass" for result in results)
        invalid_count = sum(result.data_status.value != "ok" for result in results)
        top5 = [
            result.security_id
            for result in sorted(
                results,
                key=lambda item: (-item.final_score, item.security_id),
            )[:5]
        ]
        print(
            json.dumps(
                {
                    "status": "ok",
                    "quant_run_id": quant_run.quant_run_id,
                    "result_count": len(results),
                    "pass_count": pass_count,
                    "invalid_snapshot_count": invalid_count,
                    "top5": top5,
                },
                ensure_ascii=False,
                sort_keys=True,
            )
        )
        return 0
    finally:
        engine.dispose()


def _parse_datetime(value: str) -> datetime:
    """Parse a timezone-aware ISO 8601 datetime string."""
    normalized = value.replace("Z", "+00:00")
    parsed = datetime.fromisoformat(normalized)
    if parsed.utcoffset() is None:
        raise ValueError("--decision-at must be timezone-aware")
    return parsed


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
