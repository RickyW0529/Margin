"""Background execution for durable provider data-sync work items."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from margin.data.ingestion import DataWarehouseIngestionStack
from margin.data.sync_models import EndpointSyncResult, EndpointWorkItem
from margin.data.sync_service import ProviderSyncError
from margin.news.models import ensure_utc, utc_now

INDEX_CODES = {
    "index_member_csi300": "000300.SH",
    "index_member_csi500": "000905.SH",
}


class DataSyncWorker:
    """Claim and execute data-sync items with retry-safe run reconciliation."""

    def __init__(
        self,
        *,
        stack: DataWarehouseIngestionStack,
        providers: dict[str, Any],
        provider_config_version_ids: dict[str, str] | None = None,
        worker_id: str,
        lease_seconds: int = 900,
        retry_delay_seconds: int = 60,
        max_attempts: int = 3,
    ) -> None:
        """Initialize the worker with configured provider instances."""
        self._stack = stack
        self._providers = {name.lower(): provider for name, provider in providers.items()}
        self._provider_config_version_ids = {
            name.lower(): version_id
            for name, version_id in (provider_config_version_ids or {}).items()
        }
        self._worker_id = worker_id
        self._lease_seconds = lease_seconds
        self._retry_delay_seconds = retry_delay_seconds
        self._max_attempts = max_attempts

    @property
    def providers(self) -> dict[str, Any]:
        """Return a copy of configured executable Provider adapters."""
        return dict(self._providers)

    @property
    def provider_config_version_ids(self) -> dict[str, str]:
        """Return frozen Provider config lineage by provider code."""
        return dict(self._provider_config_version_ids)

    def run_once(
        self,
        *,
        max_items: int = 1,
        now: datetime | None = None,
        run_id: str | None = None,
    ) -> int:
        """Process up to ``max_items`` currently executable work items."""
        processed = 0
        observed_at = ensure_utc(now or utc_now())
        while processed < max_items:
            item = (
                self._stack.sync_repository.claim_next_endpoint(
                    run_id,
                    worker_id=self._worker_id,
                    now=observed_at,
                    lease_seconds=self._lease_seconds,
                )
                if run_id is not None
                else self._stack.sync_repository.claim_next(
                    worker_id=self._worker_id,
                    now=observed_at,
                    lease_seconds=self._lease_seconds,
                )
            )
            if item is None:
                break
            self._execute(item, observed_at)
            processed += 1
        return processed

    def _execute(self, item: EndpointWorkItem, now: datetime) -> None:
        """Execute one claimed work item and persist its terminal/retry state."""
        try:
            result = self._dispatch(item, now)
        except Exception as exc:  # noqa: BLE001 - converted to durable safe state.
            error_code = (
                exc.error_code
                if isinstance(exc, ProviderSyncError)
                else type(exc).__name__
            )
            error_message = (
                exc.message if isinstance(exc, ProviderSyncError) else str(exc)
            )
            if item.attempt_count >= self._max_attempts:
                self._stack.sync_repository.mark_final_failure(
                    item.work_item_id,
                    error_code=error_code,
                    error_message=error_message,
                    finished_at=now,
                )
            else:
                self._stack.sync_repository.mark_retry(
                    item.work_item_id,
                    error_code=error_code,
                    error_message=error_message,
                    retry_after=now + timedelta(seconds=self._retry_delay_seconds),
                )
            return
        self._stack.sync_repository.mark_succeeded(
            item.work_item_id,
            cursor_after=result.cursor_after,
            finished_at=result.finished_at,
        )

    def _dispatch(
        self,
        item: EndpointWorkItem,
        now: datetime,
    ) -> EndpointSyncResult:
        """Call the configured provider and persist the endpoint payload."""
        provider = self._providers.get(item.provider)
        if provider is None:
            raise ProviderSyncError(
                "provider_not_configured",
                f"provider is not configured: {item.provider}",
            )
        run = self._stack.sync_repository.get_run(item.run_id)
        if run is None:
            raise ProviderSyncError("sync_run_missing", f"sync run not found: {item.run_id}")
        endpoint = self._stack.endpoint(item.provider, item.endpoint_code)
        start = run.request.backfill_start or now - timedelta(
            days=endpoint.backfill.default_lookback_days
        )
        end = run.request.backfill_end or now
        code = item.endpoint_code

        if code == "security_master":
            records = provider.get_securities(end)
            return self._stack.ingest_security_master(
                item,
                provider=item.provider,
                raw_records=records,
                decision_at=now,
            )

        symbols = list(self._stack.active_security_ids())
        if not symbols:
            raise ProviderSyncError(
                "security_master_empty",
                "security master must complete before dependent endpoints",
            )
        if code == "daily_bar":
            records = provider.get_bars(symbols, start, end, frequency="1d")
            return self._stack.ingest_records(
                item,
                provider=item.provider,
                endpoint_code=code,
                raw_records=records,
                decision_at=now,
            )
        if code == "adjustment_factor":
            records = provider.get_adjustment_factors(symbols, start, end)
            return self._stack.ingest_indicator_records(
                item,
                provider=item.provider,
                endpoint_code=code,
                raw_records=records,
                decision_at=now,
            )
        if code == "financial_statement":
            records = provider.get_financials(symbols, start, end)
            return self._stack.ingest_indicator_records(
                item,
                provider=item.provider,
                endpoint_code=code,
                raw_records=records,
                decision_at=now,
            )
        if code == "valuation":
            records = provider.get_valuations(symbols, start, end)
            return self._stack.ingest_indicator_records(
                item,
                provider=item.provider,
                endpoint_code=code,
                raw_records=records,
                decision_at=now,
            )
        if code in INDEX_CODES:
            records = provider.get_index_members(INDEX_CODES[code], end)
            return self._stack.ingest_indicator_records(
                item,
                provider=item.provider,
                endpoint_code=code,
                raw_records=records,
                decision_at=now,
                indicator_prefix=f"{code}_",
            )
        raise ProviderSyncError(
            "endpoint_not_supported",
            f"unsupported endpoint: {item.provider}/{code}",
        )
