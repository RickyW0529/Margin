"""News targets from quant eligibility and independently indexed filings.

The selector intentionally does not impose top-N or per-industry truncation.
Capacity and provider rate limits belong to the downstream orchestration layer;
this layer preserves quant coverage while allowing a new filing to enter the
catalyst branch without first passing the ML screen.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from sqlalchemy import select

from margin.news.db_models import DocumentEventRow, DocumentSecurityLinkRow
from margin.news.models import NewsTarget, TargetTriggerType
from margin.research.db_models import ResearchDeltaReviewRow
from margin.storage.database import SessionFactory
from margin.valuation_discovery.db_models import ResearchContextSnapshotRow
from margin.valuation_discovery.models import (
    DataStatus,
    QuantResult,
    ResearchGuardrail,
    ScreeningStatus,
)


@dataclass(frozen=True)
class FilingCatalystSeed:
    """One security with newly indexed filing evidence not yet researched."""

    security_id: str
    filing_event_ids: tuple[str, ...]
    latest_available_at: datetime


class FilingCatalystCandidateLoader(Protocol):
    """Discover independent filing candidates from the durable document store."""

    def load(
        self,
        *,
        scope_version_id: str,
        decision_at: datetime,
    ) -> tuple[FilingCatalystSeed, ...]:
        """Return new in-season filing seeds as of the PIT decision time."""


class SQLAlchemyFilingCatalystCandidateLoader:
    """Find ready, security-linked filings not consumed by an earlier context."""

    def __init__(self, session_factory: SessionFactory) -> None:
        self._session_factory = session_factory

    def load(
        self,
        *,
        scope_version_id: str,
        decision_at: datetime,
    ) -> tuple[FilingCatalystSeed, ...]:
        """Return unconsumed filings only during mainland reporting windows."""
        if decision_at.month not in {1, 2, 3, 4, 7, 8, 10}:
            return ()
        season_start = _reporting_window_start(decision_at)
        with self._session_factory() as session:
            prior_payloads = session.scalars(
                select(ResearchContextSnapshotRow.payload_json)
                .join(
                    ResearchDeltaReviewRow,
                    ResearchDeltaReviewRow.context_snapshot_id
                    == ResearchContextSnapshotRow.context_snapshot_id,
                )
                .where(
                    ResearchContextSnapshotRow.scope_version_id == scope_version_id,
                    ResearchContextSnapshotRow.decision_at >= season_start,
                    ResearchContextSnapshotRow.decision_at <= decision_at,
                )
            ).all()
            rows = session.execute(
                select(
                    DocumentSecurityLinkRow.security_id,
                    DocumentEventRow.event_id,
                    DocumentEventRow.available_at,
                )
                .join(
                    DocumentEventRow,
                    DocumentEventRow.event_id == DocumentSecurityLinkRow.event_id,
                )
                .where(
                    DocumentEventRow.doc_type.in_(("filing", "report")),
                    DocumentEventRow.processing_status == "ready",
                    DocumentEventRow.available_at >= season_start,
                    DocumentEventRow.available_at <= decision_at,
                    DocumentEventRow.duplicate_of.is_(None),
                )
                .order_by(
                    DocumentSecurityLinkRow.security_id,
                    DocumentEventRow.available_at,
                    DocumentEventRow.event_id,
                )
            ).all()

        consumed_event_ids = {
            str(event_id)
            for payload in prior_payloads
            if isinstance(payload, dict)
            for event_id in payload.get("new_filing_document_ids", ()) or ()
        }
        filings_by_security: dict[str, list[tuple[str, datetime]]] = {}
        for security_id, event_id, available_at in rows:
            if str(event_id) in consumed_event_ids:
                continue
            filings_by_security.setdefault(str(security_id), []).append(
                (str(event_id), available_at)
            )
        return tuple(
            FilingCatalystSeed(
                security_id=security_id,
                filing_event_ids=tuple(event_id for event_id, _ in filings),
                latest_available_at=max(available_at for _, available_at in filings),
            )
            for security_id, filings in sorted(filings_by_security.items())
        )


class NewsTargetSelector:
    """Select company targets that should receive news refresh after quant.."""

    def __init__(
        self,
        *,
        include_near_threshold: bool = True,
        filing_candidate_loader: FilingCatalystCandidateLoader | None = None,
        allowed_guardrails: tuple[ResearchGuardrail, ...] = (
            ResearchGuardrail.RESEARCH_ALLOWED,
            ResearchGuardrail.LIMITED_RESEARCH,
            ResearchGuardrail.OVERHEAT_CAUTION,
            ResearchGuardrail.CONFIDENCE_REDUCED,
            ResearchGuardrail.THESIS_RECHECK_REQUIRED,
        ),
    ) -> None:
        """Initialize the selector with eligibility and guardrail filters.

        Args:
            include_near_threshold: bool: .
            filing_candidate_loader: FilingCatalystCandidateLoader | None: .
            allowed_guardrails: tuple[ResearchGuardrail, ...]: .

        Returns:
            None: .
        """
        self._include_near_threshold = include_near_threshold
        self._allowed_guardrails = allowed_guardrails
        self._filing_candidate_loader = filing_candidate_loader

    def select(
        self,
        *,
        scope_version_id: str,
        quant_run_id: str,
        results: Iterable[QuantResult],
        decision_at: datetime | None = None,
    ) -> tuple[NewsTarget, ...]:
        """Return every eligible news target sorted by priority descending.

        Args:
            scope_version_id: str: .
            quant_run_id: str: .
            results: Iterable[QuantResult]: .
            decision_at: datetime | None: .

        Returns:
            tuple[NewsTarget, ...]: .
        """
        result_list = tuple(results)
        targets_by_security = {
            target.security_id: target
            for target in (
                self._target_for(
                    scope_version_id=scope_version_id,
                    quant_run_id=quant_run_id,
                    result=result,
                    decision_at=decision_at or result.created_at,
                )
                for result in result_list
                if self._is_eligible(result)
            )
        }
        if self._filing_candidate_loader is not None and decision_at is not None:
            result_by_security = {result.security_id: result for result in result_list}
            for seed in self._filing_candidate_loader.load(
                scope_version_id=scope_version_id,
                decision_at=decision_at,
            ):
                result = result_by_security.get(seed.security_id)
                if result is None or not self._is_catalyst_eligible(result):
                    continue
                targets_by_security[seed.security_id] = self._filing_target_for(
                    scope_version_id=scope_version_id,
                    quant_run_id=quant_run_id,
                    result=result,
                    seed=seed,
                    decision_at=decision_at,
                    existing=targets_by_security.get(seed.security_id),
                )
        return tuple(
            sorted(
                targets_by_security.values(),
                key=lambda item: (-item.priority, item.security_id),
            )
        )

    def _is_eligible(self, result: QuantResult) -> bool:
        """Return whether a quant result is eligible for news refresh.

        Args:
            result: QuantResult: .

        Returns:
            bool: .
        """
        if result.research_guardrail not in self._allowed_guardrails:
            return False
        if result.screening_status == ScreeningStatus.PASS:
            return True
        return (
            self._include_near_threshold
            and result.screening_status == ScreeningStatus.NEAR_THRESHOLD
        )

    @staticmethod
    def _is_catalyst_eligible(result: QuantResult) -> bool:
        """Allow a filing to enter independently of the quant pass threshold."""
        return (
            result.data_status is DataStatus.OK
            and result.research_guardrail is not ResearchGuardrail.RESEARCH_BLOCKED
        )

    def _target_for(
        self,
        *,
        scope_version_id: str,
        quant_run_id: str,
        result: QuantResult,
        decision_at: datetime,
    ) -> NewsTarget:
        """Build a ``NewsTarget`` from one eligible quant result.

        Args:
            scope_version_id: str: .
            quant_run_id: str: .
            result: QuantResult: .
            decision_at: datetime: .

        Returns:
            NewsTarget: .
        """
        priority, _, trigger_type = _priority_and_reasons(result)
        details = result.factor_details
        name = str(details.get("name") or result.security_id)
        return NewsTarget(
            quant_run_id=quant_run_id,
            scope_version_id=scope_version_id,
            security_id=result.security_id,
            symbol=str(details.get("symbol") or result.security_id),
            name=name,
            trigger_type=trigger_type,
            decision_at=decision_at,
            priority=priority,
            aliases=tuple(str(value) for value in details.get("aliases", ())),
            industry_terms=tuple(
                str(value)
                for value in details.get(
                    "industry_terms",
                    (details.get("industry_id"),),
                )
                if value
            ),
        )

    def _filing_target_for(
        self,
        *,
        scope_version_id: str,
        quant_run_id: str,
        result: QuantResult,
        seed: FilingCatalystSeed,
        decision_at: datetime,
        existing: NewsTarget | None,
    ) -> NewsTarget:
        """Build one material-filing target without duplicating a quant target."""
        base = self._target_for(
            scope_version_id=scope_version_id,
            quant_run_id=quant_run_id,
            result=result,
            decision_at=decision_at,
        )
        return base.model_copy(
            update={
                "trigger_type": TargetTriggerType.MATERIAL_FILING,
                "priority": max(130, existing.priority if existing is not None else 0),
                "filing_event_ids": seed.filing_event_ids,
            }
        )


def _priority_and_reasons(
    result: QuantResult,
) -> tuple[int, tuple[str, ...], TargetTriggerType]:
    """Compute priority, reasons, and trigger type from a quant result.

    Args:
        result: QuantResult: .

    Returns:
        tuple[int, tuple[str, ...], TargetTriggerType]: .
    """
    priority = 100 if result.screening_status == ScreeningStatus.PASS else 60
    reasons: list[str] = [f"quant_{result.screening_status.value}"]
    trigger_type = (
        TargetTriggerType.QUANT_PASS
        if result.screening_status == ScreeningStatus.PASS
        else TargetTriggerType.NEAR_THRESHOLD
    )
    details = result.factor_details
    if bool(details.get("new_pass")):
        priority += 10
        reasons.append("new_pass")
        trigger_type = TargetTriggerType.NEW_PASS
    if result.review_required or bool(details.get("review_due")):
        priority += 20
        reasons.append("review_due")
        trigger_type = TargetTriggerType.REVIEW_DUE
    if bool(details.get("material_filing")):
        priority += 30
        reasons.append("material_filing")
        trigger_type = TargetTriggerType.MATERIAL_FILING
    if result.research_guardrail == ResearchGuardrail.THESIS_RECHECK_REQUIRED or bool(
        details.get("thesis_invalidation_risk")
    ):
        priority += 40
        reasons.append("thesis_invalidation_risk")
        trigger_type = TargetTriggerType.THESIS_INVALIDATION_RISK
    return priority, tuple(reasons), trigger_type


def _reporting_window_start(decision_at: datetime) -> datetime:
    """Return the beginning of the mainland reporting season at decision time."""
    month = decision_at.month
    start_month = 1 if month <= 4 else 7 if month <= 8 else 10
    return decision_at.replace(
        month=start_month,
        day=1,
        hour=0,
        minute=0,
        second=0,
        microsecond=0,
    )


__all__ = [
    "FilingCatalystCandidateLoader",
    "FilingCatalystSeed",
    "NewsTargetSelector",
    "SQLAlchemyFilingCatalystCandidateLoader",
]
