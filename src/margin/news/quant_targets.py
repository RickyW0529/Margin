"""Scoped quant-result readers for agentic news acquisition."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from margin.data.db_models import CompanyPoolMemberRow, CompanyPoolSnapshotRow
from margin.news.models import NewsTarget, TargetTriggerType
from margin.sql.valuation_queries import quant_news_candidate_results


class SQLAlchemyQuantNewsTargetRepository:
    """Load quant-selected securities as existing ``NewsTarget`` objects.."""

    def __init__(self, session_factory: Callable[[], Session]) -> None:
        """Initialize the repository.

        Args:
            session_factory: Callable[[], Session]: .

        Returns:
            None: .
        """
        self._session_factory = session_factory

    def list_targets(
        self,
        *,
        scope_version_id: str,
        quant_run_id: str,
        decision_at: datetime,
        include_near_threshold: bool = False,
    ) -> tuple[NewsTarget, ...]:
        """Return PASS targets, optionally including near-threshold securities.

        Args:
            scope_version_id: str: .
            quant_run_id: str: .
            decision_at: datetime: .
            include_near_threshold: bool: .

        Returns:
            tuple[NewsTarget, ...]: .
        """
        with self._session_factory() as session:
            rows = session.scalars(
                quant_news_candidate_results(
                    quant_run_id,
                    include_near_threshold=include_near_threshold,
                    scope_version_id=scope_version_id,
                )
            ).all()
            company_context = _company_context_by_security(
                session,
                tuple(str(row.security_id) for row in rows),
            )
        targets = [
            _target_from_row(
                row,
                scope_version_id=scope_version_id,
                decision_at=decision_at,
                company_context=company_context.get(str(row.security_id)),
            )
            for row in rows
        ]
        return tuple(sorted(targets, key=lambda item: (-item.priority, item.security_id)))


def _target_from_row(
    row: Any,
    *,
    scope_version_id: str,
    decision_at: datetime,
    company_context: CompanyPoolMemberRow | None = None,
) -> NewsTarget:
    """Map one quant result row to a durable news target.

    Args:
        row: Any: .
        scope_version_id: str: .
        decision_at: datetime: .
        company_context: CompanyPoolMemberRow | None: .

    Returns:
        NewsTarget: .
    """
    details = dict(row.factor_details or {})
    screening_status = str(row.screening_status)
    is_pass = screening_status == "pass"
    trigger_type = TargetTriggerType.QUANT_PASS if is_pass else TargetTriggerType.NEAR_THRESHOLD
    priority = 100 if is_pass else 60
    name = _first_text(details.get("name"), getattr(company_context, "name", None), row.security_id)
    symbol = str(details.get("symbol") or row.security_id)
    aliases = _unique_texts(
        *(details.get("aliases", ()) or ()),
        getattr(company_context, "name", None),
    )
    industry_terms = _unique_texts(
        *(details.get("industry_terms", ()) or ()),
        getattr(company_context, "industry_name", None),
    )
    return NewsTarget(
        scope_version_id=scope_version_id,
        quant_run_id=row.quant_run_id,
        security_id=row.security_id,
        symbol=symbol,
        name=name,
        trigger_type=trigger_type,
        decision_at=decision_at,
        priority=priority,
        aliases=aliases,
        industry_terms=industry_terms,
    )


def _company_context_by_security(
    session: Session,
    security_ids: tuple[str, ...],
) -> dict[str, CompanyPoolMemberRow]:
    """Return latest included company-pool member metadata for securities.

    Args:
        session: Session: .
        security_ids: tuple[str, ...]: .

    Returns:
        dict[str, CompanyPoolMemberRow]: .
    """
    if not security_ids:
        return {}
    rows = session.scalars(
        select(CompanyPoolMemberRow)
        .join(
            CompanyPoolSnapshotRow,
            CompanyPoolSnapshotRow.snapshot_id == CompanyPoolMemberRow.snapshot_id,
        )
        .where(
            CompanyPoolMemberRow.security_id.in_(security_ids),
            CompanyPoolMemberRow.included.is_(True),
        )
        .order_by(
            CompanyPoolMemberRow.security_id.asc(),
            CompanyPoolSnapshotRow.business_at.desc(),
            CompanyPoolSnapshotRow.created_at.desc(),
            CompanyPoolMemberRow.snapshot_id.desc(),
        )
    ).all()
    context: dict[str, CompanyPoolMemberRow] = {}
    for row in rows:
        context.setdefault(row.security_id, row)
    return context


def _first_text(*values: Any) -> str:
    """Return the first non-empty string among values.

    Args:
        *values: Any: .

    Returns:
        str: .
    """
    for value in values:
        text = str(value).strip() if value is not None else ""
        if text:
            return text
    return ""


def _unique_texts(*values: Any) -> tuple[str, ...]:
    """Return unique non-empty text values, preserving order.

    Args:
        *values: Any: .

    Returns:
        tuple[str, ...]: .
    """
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        text = str(value).strip() if value is not None else ""
        if text and text not in seen:
            seen.add(text)
            result.append(text)
    return tuple(result)
