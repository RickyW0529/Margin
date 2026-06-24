"""DB-backed provider sync orchestration for the data warehouse."""

from __future__ import annotations

import uuid
from collections.abc import Callable
from datetime import datetime, timedelta

from sqlalchemy.orm import Session

from margin.data.db_models import (
    DataSyncRunRow,
    DataSyncWorkItemRow,
    ProviderEndpointRow,
)
from margin.data.endpoints import ProviderEndpoint
from margin.data.sync_models import (
    DataSyncRequest,
    DataSyncRun,
    DataSyncStatus,
    EndpointSyncResult,
    EndpointWorkItem,
)
from margin.news.models import ensure_utc, utc_now
from margin.sql.data_queries import (
    active_work_item_for_run,
    claimable_work_item,
    sync_run_by_id_for_update,
    sync_run_latest_by_requester,
    sync_runs_active_for_update,
    upsert_freshness,
    work_items_for_run,
)


class ProviderSyncError(RuntimeError):
    """Retryable provider sync error with a stable code."""

    def __init__(self, error_code: str, message: str) -> None:
        """Initialize the instance."""
        super().__init__(message)
        self.error_code = error_code
        self.message = message


SyncHandler = Callable[[EndpointWorkItem], EndpointSyncResult]


class SQLAlchemyDataSyncRepository:
    """SQLAlchemy-backed repository for data sync runs and work items."""

    def __init__(self, session_factory: Callable[[], Session]) -> None:
        """Initialize the instance."""
        self._session_factory = session_factory

    def create_run(
        self,
        request: DataSyncRequest,
        *,
        endpoints: tuple[ProviderEndpoint, ...],
    ) -> DataSyncRun:
        """Create a sync run and all endpoint work items in one transaction."""
        run_id = f"dsr_{uuid.uuid4().hex[:12]}"
        now = utc_now()
        with self._session_factory.begin() as session:
            for endpoint in endpoints:
                if session.get(ProviderEndpointRow, endpoint.endpoint_id) is None:
                    session.add(_endpoint_to_row(endpoint, now))
            session.add(
                DataSyncRunRow(
                    run_id=run_id,
                    provider=request.provider,
                    status=DataSyncStatus.PENDING.value,
                    requested_by=request.requested_by,
                    endpoint_count=len(endpoints),
                    completed_count=0,
                    failed_count=0,
                    input_hash=request.input_hash,
                    request_payload=request.model_dump(mode="json"),
                    created_at=now,
                    error_summary={},
                )
            )
            session.flush()
            for endpoint in endpoints:
                session.add(
                    DataSyncWorkItemRow(
                        work_item_id=f"dwi_{uuid.uuid4().hex[:12]}",
                        run_id=run_id,
                        endpoint_id=endpoint.endpoint_id,
                        status=DataSyncStatus.PENDING.value,
                        cursor_before=None,
                        cursor_after=None,
                        attempt_count=0,
                        created_at=now,
                    )
                )
        return DataSyncRun(
            run_id=run_id,
            request=request,
            status=DataSyncStatus.PENDING,
            endpoint_count=len(endpoints),
            created_at=now,
        )

    def claim_next_endpoint(
        self,
        run_id: str,
        *,
        worker_id: str,
        now: datetime | None = None,
        lease_seconds: int = 300,
    ) -> EndpointWorkItem | None:
        """Claim the next pending/retryable endpoint work item."""
        claimed_at = ensure_utc(now or utc_now())
        with self._session_factory.begin() as session:
            run_row = session.scalars(
                sync_run_by_id_for_update(run_id)
            ).first()
            if run_row is None:
                return None
            return self._claim_for_run(
                session,
                run_row,
                worker_id=worker_id,
                claimed_at=claimed_at,
                lease_seconds=lease_seconds,
            )

    def claim_next(
        self,
        *,
        worker_id: str,
        now: datetime | None = None,
        lease_seconds: int = 300,
    ) -> EndpointWorkItem | None:
        """Claim the next executable item across all non-terminal sync runs."""
        claimed_at = ensure_utc(now or utc_now())
        with self._session_factory.begin() as session:
            run_rows = session.scalars(
                sync_runs_active_for_update()
            ).all()
            for run_row in run_rows:
                claimed = self._claim_for_run(
                    session,
                    run_row,
                    worker_id=worker_id,
                    claimed_at=claimed_at,
                    lease_seconds=lease_seconds,
                )
                if claimed is not None:
                    return claimed
        return None

    def get_run(self, run_id: str) -> DataSyncRun | None:
        """Return a durable sync run with current counters and status."""
        with self._session_factory() as session:
            row = session.get(DataSyncRunRow, run_id)
            return _run_from_row(row) if row is not None else None

    def find_latest_run(self, *, requested_by: str) -> DataSyncRun | None:
        """Return the newest run created by a durable orchestration requester."""
        with self._session_factory() as session:
            row = session.scalar(
                sync_run_latest_by_requester(requested_by=requested_by)
            )
            return _run_from_row(row) if row is not None else None

    def get_work_item(self, work_item_id: str) -> EndpointWorkItem | None:
        """Fetch a work item by ID."""
        with self._session_factory() as session:
            row = session.get(DataSyncWorkItemRow, work_item_id)
            return _work_item_from_row(row) if row is not None else None

    def mark_retry(
        self,
        work_item_id: str,
        *,
        error_code: str,
        error_message: str,
        retry_after: datetime,
    ) -> None:
        """Mark a work item as retryable without advancing its cursor."""
        with self._session_factory.begin() as session:
            row = session.get(DataSyncWorkItemRow, work_item_id)
            if row is None:
                raise KeyError(f"unknown data sync work item: {work_item_id}")
            row.status = DataSyncStatus.FAILED_RETRYABLE.value
            row.cursor_after = None
            row.next_attempt_at = ensure_utc(retry_after)
            row.last_error_code = error_code
            row.last_error_message = error_message
            self._reconcile_run(session, row.run_id)

    def mark_succeeded(
        self,
        work_item_id: str,
        *,
        cursor_after: str | None,
        finished_at: datetime,
    ) -> None:
        """Mark a work item succeeded and store the advanced cursor."""
        with self._session_factory.begin() as session:
            row = session.get(DataSyncWorkItemRow, work_item_id)
            if row is None:
                raise KeyError(f"unknown data sync work item: {work_item_id}")
            row.status = DataSyncStatus.SUCCEEDED.value
            row.cursor_after = cursor_after
            observed_at = ensure_utc(finished_at)
            row.finished_at = observed_at
            row.next_attempt_at = None
            provider, endpoint_code = row.endpoint_id.split(":", 1)
            freshness_id = (
                f"fresh_{provider}_{endpoint_code}_{observed_at.date().isoformat()}"
            )[:64]
            session.execute(
                upsert_freshness(
                    freshness_id=freshness_id,
                    provider=provider,
                    endpoint_code=endpoint_code,
                    as_of_date=observed_at.date(),
                    observed_at=observed_at,
                )
            )
            self._reconcile_run(session, row.run_id)

    def mark_final_failure(
        self,
        work_item_id: str,
        *,
        error_code: str,
        error_message: str,
        finished_at: datetime,
    ) -> None:
        """Mark an endpoint permanently failed and reconcile the parent run."""
        with self._session_factory.begin() as session:
            row = session.get(DataSyncWorkItemRow, work_item_id)
            if row is None:
                raise KeyError(f"unknown data sync work item: {work_item_id}")
            row.status = DataSyncStatus.FAILED_FINAL.value
            row.finished_at = ensure_utc(finished_at)
            row.last_error_code = error_code
            row.last_error_message = error_message
            row.next_attempt_at = None
            self._reconcile_run(session, row.run_id)

    def _claim_for_run(
        self,
        session: Session,
        run_row: DataSyncRunRow,
        *,
        worker_id: str,
        claimed_at: datetime,
        lease_seconds: int,
    ) -> EndpointWorkItem | None:
        """Claim one sequential endpoint while recovering expired leases."""
        lease_cutoff = claimed_at - timedelta(seconds=lease_seconds)
        active_running = session.scalars(
            active_work_item_for_run(run_row.run_id, lease_cutoff)
        ).first()
        if active_running is not None:
            return None
        row = session.scalars(
            claimable_work_item(run_row.run_id, claimed_at, lease_cutoff)
        ).first()
        if row is None:
            return None
        row.status = DataSyncStatus.RUNNING.value
        row.claimed_by = worker_id
        row.claimed_at = claimed_at
        row.next_attempt_at = None
        row.attempt_count += 1
        run_row.status = DataSyncStatus.RUNNING.value
        if run_row.started_at is None:
            run_row.started_at = claimed_at
        return _work_item_from_row(row)

    def _reconcile_run(self, session: Session, run_id: str) -> None:
        """Update counters and status from the immutable set of work items."""
        run_row = session.get(DataSyncRunRow, run_id)
        if run_row is None:
            raise KeyError(f"unknown data sync run: {run_id}")
        items = session.scalars(
            work_items_for_run(run_id)
        ).all()
        succeeded = sum(
            item.status == DataSyncStatus.SUCCEEDED.value for item in items
        )
        failed_final = sum(
            item.status == DataSyncStatus.FAILED_FINAL.value for item in items
        )
        retryable = sum(
            item.status == DataSyncStatus.FAILED_RETRYABLE.value for item in items
        )
        run_row.completed_count = succeeded
        run_row.failed_count = failed_final
        run_row.error_summary = {
            item.endpoint_id: {
                "code": item.last_error_code,
                "message": item.last_error_message,
            }
            for item in items
            if item.last_error_code
        }
        if items and succeeded == len(items):
            run_row.status = DataSyncStatus.SUCCEEDED.value
            run_row.finished_at = max(
                item.finished_at for item in items if item.finished_at is not None
            )
        elif items and succeeded + failed_final == len(items):
            run_row.status = (
                DataSyncStatus.PARTIAL.value
                if succeeded
                else DataSyncStatus.FAILED_FINAL.value
            )
            run_row.finished_at = max(
                item.finished_at for item in items if item.finished_at is not None
            )
        elif retryable:
            run_row.status = DataSyncStatus.FAILED_RETRYABLE.value
        else:
            run_row.status = DataSyncStatus.RUNNING.value


class SyncService:
    """Execute endpoint work items with retry-safe cursor semantics."""

    def __init__(
        self,
        repository: SQLAlchemyDataSyncRepository,
        *,
        handlers: dict[tuple[str, str], SyncHandler],
        retry_delay_seconds: int = 60,
    ) -> None:
        """Initialize the instance."""
        self._repository = repository
        self._handlers = handlers
        self._retry_delay_seconds = retry_delay_seconds

    def execute_endpoint(
        self,
        item: EndpointWorkItem,
        *,
        now: datetime | None = None,
    ) -> EndpointSyncResult:
        """Execute one endpoint handler and persist success or retry state."""
        finished_at = ensure_utc(now or utc_now())
        handler = self._handlers[(item.provider, item.endpoint_code)]
        try:
            result = handler(item)
        except ProviderSyncError as exc:
            retry_after = finished_at + timedelta(seconds=self._retry_delay_seconds)
            self._repository.mark_retry(
                item.work_item_id,
                error_code=exc.error_code,
                error_message=exc.message,
                retry_after=retry_after,
            )
            return EndpointSyncResult(
                work_item_id=item.work_item_id,
                status=DataSyncStatus.FAILED_RETRYABLE,
                cursor_before=item.cursor_before,
                cursor_after=None,
                retry_after_seconds=self._retry_delay_seconds,
                error_code=exc.error_code,
                error_message=exc.message,
                finished_at=finished_at,
            )
        self._repository.mark_succeeded(
            item.work_item_id,
            cursor_after=result.cursor_after,
            finished_at=finished_at,
        )
        return result


def _endpoint_to_row(endpoint: ProviderEndpoint, now: datetime) -> ProviderEndpointRow:
    """endpoint to row."""
    return ProviderEndpointRow(
        endpoint_id=endpoint.endpoint_id,
        provider=endpoint.provider,
        code=endpoint.code,
        domain=endpoint.domain,
        enabled=endpoint.enabled,
        backfill_policy=endpoint.backfill.model_dump(mode="json"),
        revision_lookback_days=endpoint.revision_lookback_days,
        rate_limit_policy=endpoint.rate_limit.model_dump(mode="json"),
        schema_version=endpoint.schema_version,
        created_at=now,
        updated_at=now,
    )


def _work_item_from_row(row: DataSyncWorkItemRow) -> EndpointWorkItem:
    """work item from row."""
    provider, endpoint_code = row.endpoint_id.split(":", 1)
    return EndpointWorkItem(
        work_item_id=row.work_item_id,
        run_id=row.run_id,
        provider=provider,
        endpoint_code=endpoint_code,
        status=DataSyncStatus(row.status),
        cursor_before=row.cursor_before,
        cursor_after=row.cursor_after,
        attempt_count=row.attempt_count,
        next_attempt_at=row.next_attempt_at,
        claimed_by=row.claimed_by,
        claimed_at=row.claimed_at,
        created_at=row.created_at,
    )


def _run_from_row(row: DataSyncRunRow) -> DataSyncRun:
    """Convert a persisted run row to the public immutable contract."""
    request = DataSyncRequest.model_validate(
        row.request_payload
        or {
            "provider": row.provider,
            "requested_by": row.requested_by,
        }
    )
    return DataSyncRun(
        run_id=row.run_id,
        request=request,
        status=DataSyncStatus(row.status),
        endpoint_count=row.endpoint_count,
        completed_count=row.completed_count,
        failed_count=row.failed_count,
        created_at=row.created_at,
        started_at=row.started_at,
        finished_at=row.finished_at,
        error_summary=dict(row.error_summary or {}),
    )
