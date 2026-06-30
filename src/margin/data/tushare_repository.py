"""PostgreSQL repository for the independent Tushare source system."""

from __future__ import annotations

import hashlib
from collections.abc import Callable, Iterable
from datetime import datetime
from typing import TypeVar

from sqlalchemy import (
    Boolean,
    Column,
    Date,
    DateTime,
    Integer,
    MetaData,
    Numeric,
    String,
    Table,
    Text,
    update,
)
from sqlalchemy.dialects.postgresql import JSONB, insert
from sqlalchemy.orm import Session

from margin.data.db_models import DataSyncRunRow
from margin.data.requirements import QuantDataRequirementCatalog
from margin.data.sync_models import DataSyncRequest, DataSyncStatus
from margin.data.tushare_quality import SourceQualityDecision
from margin.data.tushare_source import (
    TUSHARE_SOURCE_SCHEMA,
    TushareLandingRecord,
    TushareSourceCatalog,
)
from margin.news.models import ensure_utc, utc_now

CATALOG_VERSION = "quant-data-v0.3.0"
_METADATA = MetaData()
_T = TypeVar("_T")


def _landing_table(api_name: str) -> Table:
    """Build a lightweight Core table for one admitted endpoint."""
    name = f"ts_{api_name}"
    key = f"{TUSHARE_SOURCE_SCHEMA}.{name}"
    existing = _METADATA.tables.get(key)
    if existing is not None:
        return existing
    return Table(
        name,
        _METADATA,
        Column("source_row_id", String(72), primary_key=True),
        Column("natural_key_hash", String(80), nullable=False),
        Column("revision_hash", String(80), nullable=False),
        Column("symbol", String(32)),
        Column("business_date", Date),
        Column("published_at", DateTime(timezone=True)),
        Column("available_at", DateTime(timezone=True), nullable=False),
        Column("fetched_at", DateTime(timezone=True), nullable=False),
        Column("source_partition", String(16), nullable=False),
        Column("raw_payload", JSONB, nullable=False),
        Column("raw_snapshot_id", String(64)),
        Column("sync_run_id", String(64), nullable=False),
        Column("quality_status", String(24), nullable=False),
        Column("created_at", DateTime(timezone=True), nullable=False),
        schema=TUSHARE_SOURCE_SCHEMA,
    )


_QUALITY_TABLE = Table(
    "source_quality_decisions",
    _METADATA,
    Column("decision_id", String(72), primary_key=True),
    Column("provider", String(64), nullable=False),
    Column("endpoint", String(96), nullable=False),
    Column("source_row_id", String(72), nullable=False),
    Column("decision", String(24), nullable=False),
    Column("quality_score", Numeric(6, 5), nullable=False),
    Column("issue_codes", JSONB, nullable=False),
    Column("rule_version", String(64), nullable=False),
    Column("published_fact_count", Integer, nullable=False),
    Column("checked_at", DateTime(timezone=True), nullable=False),
)
_REQUIREMENTS_TABLE = Table(
    "quant_data_requirements",
    _METADATA,
    Column("requirement_code", String(96), primary_key=True),
    Column("consumer", String(160), nullable=False),
    Column("warehouse_fields", JSONB, nullable=False),
    Column("minimum_history_days", Integer, nullable=False),
    Column("active", Boolean, nullable=False),
    Column("description", Text, nullable=False),
    Column("catalog_version", String(64), primary_key=True),
    Column("created_at", DateTime(timezone=True), nullable=False),
)
_ENDPOINTS_TABLE = Table(
    "provider_endpoint_requirements",
    _METADATA,
    Column("provider", String(64), primary_key=True),
    Column("api_name", String(96), primary_key=True),
    Column("domain", String(64), nullable=False),
    Column("admission", String(32), nullable=False),
    Column("partition_by", String(64), nullable=False),
    Column("natural_key_fields", JSONB, nullable=False),
    Column("pit_fields", JSONB, nullable=False),
    Column("description", Text, nullable=False),
    Column("catalog_version", String(64), primary_key=True),
    Column("created_at", DateTime(timezone=True), nullable=False),
)
_LINKS_TABLE = Table(
    "provider_endpoint_requirement_links",
    _METADATA,
    Column("provider", String(64), primary_key=True),
    Column("api_name", String(96), primary_key=True),
    Column("requirement_code", String(96), primary_key=True),
    Column("catalog_version", String(64), primary_key=True),
)


class SQLAlchemyTushareSourceRepository:
    """Persist source rows, catalog lineage, and quality decisions."""

    def __init__(
        self,
        session_factory: Callable[[], Session],
        *,
        requirements: QuantDataRequirementCatalog | None = None,
    ) -> None:
        """Initialize with the admitted endpoint allowlist.

        Args:
            session_factory: Callable returning a SQLAlchemy ``Session``.
            requirements: Optional custom quant requirement catalog.
        """
        self._session_factory = session_factory
        self._requirements = requirements or QuantDataRequirementCatalog.default()
        self._source_catalog = TushareSourceCatalog(self._requirements)

    def seed_catalog(self, *, created_at: datetime | None = None) -> None:
        """Idempotently persist the versioned quant-to-endpoint closure.

        Args:
            created_at: Optional override for the catalog creation timestamp.
        """
        observed_at = ensure_utc(created_at or utc_now())
        requirement_rows = [
            {
                "requirement_code": item.code,
                "consumer": item.consumer,
                "warehouse_fields": list(item.warehouse_fields),
                "minimum_history_days": item.minimum_history_days,
                "active": item.active,
                "description": item.description,
                "catalog_version": CATALOG_VERSION,
                "created_at": observed_at,
            }
            for item in self._requirements.requirements()
        ]
        endpoint_rows = [
            {
                "provider": item.provider,
                "api_name": item.api_name,
                "domain": item.domain,
                "admission": item.admission,
                "partition_by": item.partition_by,
                "natural_key_fields": list(item.natural_key_fields),
                "pit_fields": list(item.pit_fields),
                "description": item.description,
                "catalog_version": CATALOG_VERSION,
                "created_at": observed_at,
            }
            for item in self._requirements.endpoints("tushare")
        ]
        link_rows = [
            {
                "provider": endpoint.provider,
                "api_name": endpoint.api_name,
                "requirement_code": requirement_code,
                "catalog_version": CATALOG_VERSION,
            }
            for endpoint in self._requirements.endpoints("tushare")
            for requirement_code in endpoint.quant_requirement_codes
        ]
        with self._session_factory.begin() as session:
            if requirement_rows:
                session.execute(
                    insert(_REQUIREMENTS_TABLE)
                    .values(requirement_rows)
                    .on_conflict_do_nothing()
                )
            if endpoint_rows:
                session.execute(
                    insert(_ENDPOINTS_TABLE)
                    .values(endpoint_rows)
                    .on_conflict_do_nothing()
                )
            if link_rows:
                session.execute(
                    insert(_LINKS_TABLE)
                    .values(link_rows)
                    .on_conflict_do_nothing()
                )

    def start_run(
        self,
        request: DataSyncRequest,
        *,
        endpoint_count: int,
        started_at: datetime | None = None,
    ) -> str:
        """Create or replay a deterministic source-system backfill run.

        Args:
            request: The sync request describing the provider and scope.
            endpoint_count: The number of endpoints included in the run.
            started_at: Optional override for the run start timestamp.

        Returns:
            The deterministic run ID.
        """
        observed_at = ensure_utc(started_at or utc_now())
        digest = hashlib.sha256(
            (request.idempotency_key or request.input_hash).encode()
        ).hexdigest()
        run_id = f"tsr_{digest[:12]}"
        with self._session_factory.begin() as session:
            row = session.get(DataSyncRunRow, run_id)
            if row is None:
                session.add(
                    DataSyncRunRow(
                        run_id=run_id,
                        provider="tushare",
                        status=DataSyncStatus.RUNNING.value,
                        requested_by=request.requested_by,
                        endpoint_count=endpoint_count,
                        completed_count=0,
                        failed_count=0,
                        input_hash=request.input_hash,
                        request_payload=request.model_dump(mode="json"),
                        started_at=observed_at,
                        created_at=observed_at,
                        error_summary={},
                    )
                )
        return run_id

    def finish_run(
        self,
        run_id: str,
        *,
        completed_count: int,
        failed_endpoints: dict[str, str],
        finished_at: datetime | None = None,
    ) -> None:
        """Finalize source-system run counters and safe error summaries.

        Args:
            run_id: The sync run ID to finalize.
            completed_count: The number of successfully completed endpoints.
            failed_endpoints: Mapping of failed endpoint name to error message.
            finished_at: Optional override for the finish timestamp.

        Raises:
            KeyError: If the run ID does not exist.
        """
        observed_at = ensure_utc(finished_at or utc_now())
        with self._session_factory.begin() as session:
            row = session.get(DataSyncRunRow, run_id)
            if row is None:
                raise KeyError(f"unknown data sync run: {run_id}")
            row.completed_count = completed_count
            row.failed_count = len(failed_endpoints)
            row.error_summary = {
                endpoint: {"code": "source_endpoint_failed", "message": message[:500]}
                for endpoint, message in failed_endpoints.items()
            }
            row.status = (
                DataSyncStatus.SUCCEEDED.value
                if not failed_endpoints
                else (
                    DataSyncStatus.PARTIAL.value
                    if completed_count
                    else DataSyncStatus.FAILED_FINAL.value
                )
            )
            row.finished_at = observed_at

    def insert_records(self, records: Iterable[TushareLandingRecord]) -> int:
        """Insert immutable source revisions, returning newly inserted rows.

        Args:
            records: Landing records for a single endpoint batch.

        Returns:
            The number of newly inserted rows.

        Raises:
            ValueError: If records span more than one endpoint.
        """
        rows = list(records)
        if not rows:
            return 0
        endpoints = {row.endpoint for row in rows}
        if len(endpoints) != 1:
            raise ValueError("insert_records requires one endpoint per batch")
        endpoint = next(iter(endpoints))
        self._source_catalog.endpoint(endpoint)
        table = _landing_table(endpoint)
        inserted = 0
        with self._session_factory.begin() as session:
            for batch in chunk_landing_records(rows):
                result = session.execute(
                    insert(table)
                    .values([landing_insert_values(row) for row in batch])
                    .on_conflict_do_nothing(
                        index_elements=["natural_key_hash", "revision_hash"]
                    )
                    .returning(table.c.source_row_id)
                )
                inserted += len(result.scalars().all())
        return inserted

    def record_quality_decisions(
        self,
        decisions: Iterable[SourceQualityDecision],
    ) -> int:
        """Append quality decisions and update landing publication state.

        Args:
            decisions: Quality decisions to persist.

        Returns:
            The number of newly inserted decision rows.
        """
        rows = list(decisions)
        if not rows:
            return 0
        inserted = 0
        with self._session_factory.begin() as session:
            for batch in chunk_quality_decisions(rows):
                result = session.execute(
                    insert(_QUALITY_TABLE)
                    .values(
                        [
                            {
                                **row.model_dump(mode="python"),
                                "issue_codes": list(row.issue_codes),
                            }
                            for row in batch
                        ]
                    )
                    .on_conflict_do_nothing()
                    .returning(_QUALITY_TABLE.c.decision_id)
                )
                inserted += len(result.scalars().all())
            grouped: dict[tuple[str, str], list[str]] = {}
            for decision in rows:
                grouped.setdefault(
                    (decision.endpoint, decision.decision),
                    [],
                ).append(decision.source_row_id)
            for (endpoint, status), source_row_ids in grouped.items():
                table = _landing_table(endpoint)
                for batch in chunk_landing_records(source_row_ids):
                    session.execute(
                        update(table)
                        .where(table.c.source_row_id.in_(batch))
                        .values(quality_status=status)
                    )
        return inserted

    def count_rows(self, api_name: str) -> int:
        """Return source-row count for coverage reporting.

        Args:
            api_name: The Tushare API name to count.

        Returns:
            The total number of rows in the endpoint's landing table.
        """
        from sqlalchemy import func, select

        table = _landing_table(self._source_catalog.endpoint(api_name).api_name)
        with self._session_factory() as session:
            return int(session.scalar(select(func.count()).select_from(table)) or 0)

    def count_quality(self, api_name: str) -> dict[str, int]:
        """Return quality-decision counts by state for one endpoint.

        Args:
            api_name: The Tushare API name to summarize.

        Returns:
            A mapping of decision state to row count.
        """
        from sqlalchemy import func, select

        with self._session_factory() as session:
            rows = session.execute(
                select(_QUALITY_TABLE.c.decision, func.count())
                .where(
                    _QUALITY_TABLE.c.provider == "tushare",
                    _QUALITY_TABLE.c.endpoint == api_name,
                )
                .group_by(_QUALITY_TABLE.c.decision)
            ).all()
        return {str(decision): int(count) for decision, count in rows}


def landing_table_columns(api_name: str) -> tuple[str, ...]:
    """Expose the physical source-table contract for tests and diagnostics.

    Args:
        api_name: The Tushare API name.

    Returns:
        A tuple of column names in physical order.
    """
    return tuple(column.name for column in _landing_table(api_name).columns)


def landing_insert_values(record: TushareLandingRecord) -> dict[str, object]:
    """Map one logical landing record to physical SQL columns only.

    Args:
        record: The landing record to map.

    Returns:
        A dictionary of column names to values for SQL insertion.
    """
    return {
        **record.model_dump(mode="python", exclude={"endpoint"}),
        "raw_payload": record.raw_payload,
        "created_at": utc_now(),
    }


def chunk_landing_records(
    records: list[_T],
    *,
    batch_size: int = 1000,
) -> Iterable[list[_T]]:
    """Split large source pages below PostgreSQL's bind-parameter limit.

    Args:
        records: The records to split into batches.
        batch_size: Maximum number of records per batch.

    Yields:
        Successive batches of records.

    Raises:
        ValueError: If ``batch_size`` is less than 1.
    """
    if batch_size < 1:
        raise ValueError("batch_size must be positive")
    for offset in range(0, len(records), batch_size):
        yield records[offset : offset + batch_size]


def chunk_quality_decisions(
    decisions: list[_T],
    *,
    batch_size: int = 1000,
) -> Iterable[list[_T]]:
    """Split quality-decision pages below PostgreSQL's bind-parameter limit.

    Args:
        decisions: The decisions to split into batches.
        batch_size: Maximum number of decisions per batch.

    Yields:
        Successive batches of decisions.
    """
    yield from chunk_landing_records(decisions, batch_size=batch_size)
