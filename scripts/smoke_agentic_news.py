#!/usr/bin/env python3
"""Token-safe smoke for v0.3 agentic news acquisition."""

from __future__ import annotations

import argparse
import sys
from datetime import UTC, datetime

from fastapi import HTTPException

from margin.api.dependencies import (
    build_database_engine,
    create_session_factory,
    get_agentic_news_service,
)
from margin.news.repository import NewsRepository
from margin.settings import get_settings


def main() -> int:
    """Run one agentic news acquisition smoke."""
    args = _parse_args()
    try:
        decision_at = _parse_datetime(args.decision_at)
        service = get_agentic_news_service()
        run = service.run_for_quant_run(
            scope_version_id=args.scope_version_id,
            quant_run_id=args.quant_run_id,
            decision_at=decision_at,
            include_near_threshold=args.include_near_threshold,
            max_workers=args.max_workers,
        )
    except HTTPException:
        print("status=blocked external_blocker=missing_provider_config")
        return 2
    except Exception:  # noqa: BLE001 - token-safe smoke omits internal details
        print("status=failed external_blocker=agentic_news_run_failed")
        return 3

    repository = _repository()
    plans = repository.list_news_search_plans(run.run_id)
    findings = repository.list_news_article_findings(run.run_id)
    briefs = repository.list_news_security_briefs(run.run_id)
    outbox_count = 0
    for brief in briefs:
        for event_id in brief.source_event_ids:
            if repository.get_outbox_by_event(event_id, "vector_index") is not None:
                outbox_count += 1

    print(
        f"run_id={run.run_id} "
        f"status={run.status.value} "
        f"target_count={run.target_count} "
        f"search_plan_count={len(plans)} "
        f"finding_count={len(findings)} "
        f"brief_count={len(briefs)} "
        f"outbox_count={outbox_count}"
    )
    return 0 if run.status.value in {"completed", "completed_empty"} else 3


def _parse_args() -> argparse.Namespace:
    """Parse command-line arguments for the agentic news smoke."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scope-version-id", required=True)
    parser.add_argument("--quant-run-id", required=True)
    parser.add_argument("--decision-at", required=True)
    parser.add_argument("--include-near-threshold", action="store_true")
    parser.add_argument("--max-workers", type=int, default=4)
    return parser.parse_args()


def _parse_datetime(value: str) -> datetime:
    """Parse an ISO 8601 datetime string and normalize to UTC."""
    normalized = value.replace("Z", "+00:00")
    parsed = datetime.fromisoformat(normalized)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _repository() -> NewsRepository:
    """Build a NewsRepository from current application settings."""
    settings = get_settings()
    engine = build_database_engine(settings)
    return NewsRepository(create_session_factory(engine))


if __name__ == "__main__":
    sys.exit(main())
