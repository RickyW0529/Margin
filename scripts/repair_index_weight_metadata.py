#!/usr/bin/env python3
"""Repair index_weight metadata from DB source landing rows."""

from __future__ import annotations

import argparse
import json
from typing import Any

from sqlalchemy import create_engine

from margin.settings import MarginSettings
from margin.sql.raw_statements import (
    INDEX_WEIGHT_MATCH,
    INDEX_WEIGHT_UPDATE_CANONICAL,
    INDEX_WEIGHT_UPDATE_FACTS,
    INDEX_WEIGHT_VERIFY,
)


def main(argv: list[str] | None = None) -> int:
    """Inspect or apply index_weight metadata repair from DB landing rows.

    Args:
        argv: Optional argument list. When ``None``, arguments are read from
            ``sys.argv``.

    Returns:
        int: 0 on success.
    """
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--write",
        action="store_true",
        help="Apply the repair. Without this flag the script only reports coverage.",
    )
    args = parser.parse_args(argv)

    engine = create_engine(str(MarginSettings().database_url))
    try:
        if args.write:
            payload = apply_repair(engine)
        else:
            payload = inspect_repair(engine)
    finally:
        engine.dispose()
    print(json.dumps(payload, ensure_ascii=False, default=str, indent=2))
    return 0


def inspect_repair(engine) -> dict[str, Any]:
    """Report index_weight repair coverage without writing changes.

    Args:
        engine: SQLAlchemy engine connected to the target database.

    Returns:
        dict[str, Any]: Dry-run coverage report with missing, safe-match and
            ambiguous counts grouped by index code.
    """
    with engine.connect() as conn:
        match_row = dict(conn.execute(INDEX_WEIGHT_MATCH).mappings().one())
        by_index = [dict(row) for row in conn.execute(INDEX_WEIGHT_VERIFY).mappings()]
    return {
        "mode": "dry_run",
        "missing_count": int(match_row["missing_count"]),
        "safe_match_count": int(match_row["safe_match_count"]),
        "ambiguous_count": int(match_row["ambiguous_count"]),
        "index_weight_by_index_code": by_index,
    }


def apply_repair(engine) -> dict[str, Any]:
    """Apply the index_weight metadata repair and return before/after stats.

    Args:
        engine: SQLAlchemy engine connected to the target database.

    Returns:
        dict[str, Any]: Write-mode report with facts/canonical update counts
            and before/after coverage snapshots.

    Raises:
        SystemExit: When ambiguous matches are detected and a safe repair is
            not possible.
    """
    before = inspect_repair(engine)
    if before["ambiguous_count"]:
        raise SystemExit(
            f"Refusing to repair {before['ambiguous_count']} ambiguous index_weight facts."
        )
    with engine.begin() as conn:
        fact_result = conn.execute(INDEX_WEIGHT_UPDATE_FACTS)
        canonical_result = conn.execute(INDEX_WEIGHT_UPDATE_CANONICAL)
    after = inspect_repair(engine)
    return {
        "mode": "write",
        "facts_updated": int(fact_result.rowcount or 0),
        "canonical_values_updated": int(canonical_result.rowcount or 0),
        "before": before,
        "after": after,
    }


if __name__ == "__main__":
    raise SystemExit(main())
