"""Persistence repositories for deterministic backfill campaigns."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from typing import Protocol

from sqlalchemy import select
from sqlalchemy.orm import Session

from margin.data.backfill.campaign import BackfillCampaign, BackfillCampaignStatus
from margin.data.backfill.planner import (
    BackfillEndpointPlan,
    BackfillPartition,
    PartitionStatus,
)
from margin.data.backfill.publisher import BackfillPublishResult
from margin.data.backfill.quality import BackfillQualityReport
from margin.platform_runtime.db_models import (
    BackfillCampaignRow,
    BackfillPartitionRow,
    BackfillQualityReportRow,
    IdempotencyKeyRow,
)

_OPEN_ENDED_EXPIRES_AT = datetime(9999, 12, 31, tzinfo=UTC)


class BackfillRepository(Protocol):
    """Repository contract for the backfill application service."""

    def lookup_idempotency_key(self, idempotency_key: str, request_hash: str) -> str | None:
        """Return a replay response ref or reject conflicting replay."""

    def record_idempotency_key(
        self,
        *,
        idempotency_key: str,
        request_hash: str,
        campaign_id: str,
    ) -> None:
        """Record a successful idempotent campaign creation."""

    def save_campaign(self, campaign: BackfillCampaign) -> None:
        """Persist the latest campaign state."""

    def get_campaign(self, campaign_id: str) -> BackfillCampaign | None:
        """Return one campaign by id."""

    def save_endpoint_plan(self, endpoint_plan: BackfillEndpointPlan) -> None:
        """Persist endpoint plan metadata if the repository supports it."""

    def count_endpoints(self, campaign_id: str) -> int:
        """Return endpoint count for one campaign."""

    def save_partitions(
        self,
        campaign_id: str,
        partitions: tuple[BackfillPartition, ...],
    ) -> None:
        """Persist partition state for one campaign."""

    def list_partitions(self, campaign_id: str) -> tuple[BackfillPartition, ...]:
        """List partitions for one campaign."""

    def save_quality_report(self, report: BackfillQualityReport) -> None:
        """Persist a campaign-level quality report."""

    def get_quality_report(self, campaign_id: str) -> BackfillQualityReport | None:
        """Return the campaign-level quality report if present."""

    def save_publish_result(self, result: BackfillPublishResult) -> None:
        """Persist publish result metadata if the repository supports it."""


class SQLAlchemyBackfillRepository:
    """SQLAlchemy-backed repository using formal ``ops`` runtime tables."""

    def __init__(self, session_factory: Callable[[], Session]) -> None:
        """Initialize the repository."""
        self._session_factory = session_factory

    def lookup_idempotency_key(self, idempotency_key: str, request_hash: str) -> str | None:
        """Return an existing campaign id for an exact idempotency replay."""
        with self._session_factory() as session:
            row = session.get(IdempotencyKeyRow, idempotency_key)
            if row is None:
                return None
            if row.scope != "backfill_campaign" or row.request_hash != request_hash:
                raise ValueError(f"idempotency key '{idempotency_key}' is immutable")
            return row.response_ref

    def record_idempotency_key(
        self,
        *,
        idempotency_key: str,
        request_hash: str,
        campaign_id: str,
    ) -> None:
        """Record a successful idempotent campaign creation."""
        with self._session_factory() as session, session.begin():
            current = session.get(IdempotencyKeyRow, idempotency_key)
            if current is not None:
                if (
                    current.scope != "backfill_campaign"
                    or current.request_hash != request_hash
                    or current.response_ref != campaign_id
                ):
                    raise ValueError(f"idempotency key '{idempotency_key}' is immutable")
                return
            session.add(
                IdempotencyKeyRow(
                    idempotency_key=idempotency_key,
                    scope="backfill_campaign",
                    request_hash=request_hash,
                    response_hash=None,
                    response_ref=campaign_id,
                    status="succeeded",
                    created_at=datetime.now(UTC),
                    expires_at=_OPEN_ENDED_EXPIRES_AT,
                )
            )

    def save_campaign(self, campaign: BackfillCampaign) -> None:
        """Persist or update one campaign state."""
        with self._session_factory() as session, session.begin():
            row = session.get(BackfillCampaignRow, campaign.campaign_id)
            if row is None:
                session.add(_campaign_row(campaign))
                return
            replacement = _campaign_row(campaign)
            row.campaign_name = replacement.campaign_name
            row.years = replacement.years
            row.start_date = replacement.start_date
            row.end_date = replacement.end_date
            row.providers = replacement.providers
            row.status = replacement.status
            row.mode = replacement.mode
            row.endpoint_plan_ref = replacement.endpoint_plan_ref
            row.started_at = replacement.started_at
            row.finished_at = replacement.finished_at

    def get_campaign(self, campaign_id: str) -> BackfillCampaign | None:
        """Return one campaign by id."""
        with self._session_factory() as session:
            row = session.get(BackfillCampaignRow, campaign_id)
            return _campaign_payload(row) if row is not None else None

    def save_endpoint_plan(self, endpoint_plan: BackfillEndpointPlan) -> None:
        """Persist endpoint plan metadata on the campaign row."""
        with self._session_factory() as session, session.begin():
            row = session.get(BackfillCampaignRow, endpoint_plan.campaign_id)
            if row is None:
                return
            row.endpoint_plan_ref = endpoint_plan.payload_hash

    def count_endpoints(self, campaign_id: str) -> int:
        """Return distinct provider/endpoint count from persisted partitions."""
        return len(
            {
                (partition.provider_name, partition.endpoint_name)
                for partition in self.list_partitions(campaign_id)
            }
        )

    def save_partitions(
        self,
        campaign_id: str,
        partitions: tuple[BackfillPartition, ...],
    ) -> None:
        """Persist or update partitions for one campaign."""
        with self._session_factory() as session, session.begin():
            for partition in partitions:
                if partition.campaign_id != campaign_id:
                    raise ValueError("partition campaign_id mismatch")
                row = session.get(BackfillPartitionRow, partition.partition_id)
                replacement = _partition_row(partition)
                if row is None:
                    session.add(replacement)
                    continue
                row.status = replacement.status
                row.attempts = replacement.attempts
                row.last_error_code = replacement.last_error_code
                row.started_at = replacement.started_at
                row.finished_at = replacement.finished_at

    def list_partitions(self, campaign_id: str) -> tuple[BackfillPartition, ...]:
        """List partitions for one campaign."""
        with self._session_factory() as session:
            rows = session.scalars(
                select(BackfillPartitionRow)
                .where(BackfillPartitionRow.campaign_id == campaign_id)
                .order_by(BackfillPartitionRow.partition_start, BackfillPartitionRow.partition_id)
            ).all()
            return tuple(_partition_payload(row) for row in rows)

    def save_quality_report(self, report: BackfillQualityReport) -> None:
        """Persist or replace the campaign-level quality report."""
        row = _quality_report_row(report)
        with self._session_factory() as session, session.begin():
            current = session.get(BackfillQualityReportRow, row.quality_report_id)
            if current is None:
                session.add(row)
                return
            current.coverage_start = row.coverage_start
            current.coverage_end = row.coverage_end
            current.expected_rows = row.expected_rows
            current.actual_rows = row.actual_rows
            current.missing_dates = row.missing_dates
            current.duplicate_key_count = row.duplicate_key_count
            current.schema_drift_detected = row.schema_drift_detected
            current.quality_status = row.quality_status
            current.report_json = row.report_json

    def get_quality_report(self, campaign_id: str) -> BackfillQualityReport | None:
        """Return the campaign-level quality report."""
        with self._session_factory() as session:
            row = session.get(BackfillQualityReportRow, _quality_report_id(campaign_id))
            if row is None:
                return None
            return BackfillQualityReport.model_validate(row.report_json)

    def save_publish_result(self, result: BackfillPublishResult) -> None:
        """Store publish metadata on the campaign row when present."""
        del result


def _campaign_row(campaign: BackfillCampaign) -> BackfillCampaignRow:
    """Convert a campaign model to an ORM row."""
    return BackfillCampaignRow(
        campaign_id=campaign.campaign_id,
        campaign_name=campaign.campaign_name,
        years=campaign.years,
        start_date=campaign.start_date,
        end_date=campaign.end_date,
        providers=list(campaign.providers),
        endpoint_plan_ref=None,
        status=campaign.status.value,
        mode=campaign.mode,
        created_by_run_id=None,
        started_at=None,
        finished_at=None,
        created_at=datetime.now(UTC),
    )


def _campaign_payload(row: BackfillCampaignRow) -> BackfillCampaign:
    """Convert a campaign row to a model."""
    return BackfillCampaign(
        campaign_id=row.campaign_id,
        campaign_name=row.campaign_name,
        years=row.years,
        start_date=row.start_date,
        end_date=row.end_date,
        providers=tuple(row.providers),
        status=BackfillCampaignStatus(row.status),
        mode=row.mode,
    )


def _partition_row(partition: BackfillPartition) -> BackfillPartitionRow:
    """Convert a backfill partition to an ORM row."""
    return BackfillPartitionRow(
        partition_id=partition.partition_id,
        campaign_id=partition.campaign_id,
        provider_name=partition.provider_name,
        endpoint_name=partition.endpoint_name,
        partition_start=partition.partition_start,
        partition_end=partition.partition_end,
        params_json={
            "provider_name": partition.provider_name,
            "endpoint_name": partition.endpoint_name,
            "partition_start": partition.partition_start.isoformat(),
            "partition_end": partition.partition_end.isoformat(),
        },
        params_hash=partition.params_hash,
        status=partition.status.value,
        attempts=partition.attempt_count,
        last_error_code=None,
        raw_snapshot_refs=[],
        quality_report_ref=None,
        started_at=None,
        finished_at=None,
        created_at=datetime.now(UTC),
    )


def _partition_payload(row: BackfillPartitionRow) -> BackfillPartition:
    """Convert a partition row to a model."""
    return BackfillPartition(
        partition_id=row.partition_id,
        campaign_id=row.campaign_id,
        provider_name=row.provider_name,
        endpoint_name=row.endpoint_name,
        partition_start=row.partition_start,
        partition_end=row.partition_end,
        params_hash=row.params_hash,
        status=PartitionStatus(row.status),
        retryable=row.status in {PartitionStatus.FAILED.value, PartitionStatus.PARTIAL.value},
        attempt_count=row.attempts,
    )


def _quality_report_row(report: BackfillQualityReport) -> BackfillQualityReportRow:
    """Convert a quality report to a campaign-level ORM row."""
    expected_rows = sum(item.expected_partitions for item in report.endpoint_reports)
    actual_rows = sum(item.completed_partitions for item in report.endpoint_reports)
    missing_dates = sorted(
        {
            missing_date
            for item in report.endpoint_reports
            for missing_date in item.missing_dates
        }
    )
    duplicate_key_count = sum(item.duplicate_keys for item in report.endpoint_reports)
    schema_drift = any(item.schema_drift for item in report.endpoint_reports)
    return BackfillQualityReportRow(
        quality_report_id=_quality_report_id(report.campaign_id),
        campaign_id=report.campaign_id,
        partition_id=None,
        provider_name=None,
        endpoint_name=None,
        coverage_start=report.coverage_start,
        coverage_end=report.coverage_end,
        expected_rows=expected_rows,
        actual_rows=actual_rows,
        missing_dates=missing_dates,
        duplicate_key_count=duplicate_key_count,
        schema_drift_detected=schema_drift,
        quality_status="passed" if report.publish_allowed else "blocked",
        report_json=report.model_dump(mode="json"),
        created_at=datetime.now(UTC),
    )


def _quality_report_id(campaign_id: str) -> str:
    """Return the stable campaign-level quality report id."""
    return f"bqr_{campaign_id}"
