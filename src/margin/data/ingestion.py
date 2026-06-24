"""End-to-end ingestion from provider payloads into the PIT warehouse."""

from __future__ import annotations

import hashlib
from collections import defaultdict
from collections.abc import Callable
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from margin.core.snapshot_store import CompressedSnapshotStore
from margin.data.canonical import CanonicalResolver
from margin.data.db_models import (
    RawDataSnapshotRow,
    SecurityIndustryMembershipRow,
    SecurityMasterRow,
    SecurityProviderIdentifierRow,
    SourceSchemaFieldRow,
)
from margin.data.endpoints import ProviderEndpoint, ProviderEndpointRegistry
from margin.data.facts import StandardizedIndicatorFact
from margin.data.standardize import DataDomain as StandardDataDomain
from margin.data.standardize import (
    StandardDataEvent,
    Standardizer,
    TimeStandardizer,
    normalize_symbol,
)
from margin.data.sync_models import (
    DataSyncRequest,
    DataSyncRun,
    DataSyncStatus,
    EndpointSyncResult,
    EndpointWorkItem,
)
from margin.data.sync_service import SQLAlchemyDataSyncRepository, SyncService
from margin.data.warehouse_repository import SQLAlchemyWarehouseRepository
from margin.news.models import ensure_utc
from margin.sql.data_queries import (
    active_security_ids,
    insert_canonical_values_batch,
    insert_facts_batch,
    raw_snapshot_by_payload_hash,
)

NUMERIC_MARKET_FIELDS = ("open", "high", "low", "close", "volume", "amount")


class DataWarehouseIngestionStack:
    """Production data stack used by workers, tests, and smoke scripts."""

    def __init__(
        self,
        *,
        session_factory: Callable[[], Session],
        snapshot_root: str | Path,
        standardizer: Standardizer | None = None,
        resolver: CanonicalResolver | None = None,
        endpoint_registry: ProviderEndpointRegistry | None = None,
        default_provider: str = "tushare",
    ) -> None:
        """Initialize the instance."""
        self._session_factory = session_factory
        self._snapshot_store = CompressedSnapshotStore(snapshot_root)
        self._standardizer = standardizer or Standardizer(mapping_version="mapping-v0.2.0")
        self._resolver = resolver or CanonicalResolver()
        self._endpoint_registry = endpoint_registry or ProviderEndpointRegistry.default()
        self._default_provider = default_provider.strip().lower()
        self._sync_repository = SQLAlchemyDataSyncRepository(session_factory)
        self.warehouse = SQLAlchemyWarehouseRepository(session_factory)

    def create_sync_run(
        self,
        request: DataSyncRequest,
        *,
        endpoints: tuple[ProviderEndpoint, ...] = (),
    ) -> DataSyncRun:
        """Create a durable data sync run without executing it synchronously.

        Args:
            request: The sync request describing the provider and scope.
            endpoints: Provider endpoints to enqueue as work items. May be
                empty when the run is a manual trigger populated by workers.

        Returns:
            The newly created ``DataSyncRun`` in the ``pending`` state.
        """
        resolved_endpoints = endpoints or self._resolve_endpoints(request)
        return self._sync_repository.create_run(
            request.model_copy(
                update={"provider": request.provider or self._default_provider}
            ),
            endpoints=resolved_endpoints,
        )

    @property
    def sync_repository(self) -> SQLAlchemyDataSyncRepository:
        """Expose the durable repository to background workers."""
        return self._sync_repository

    def endpoint(self, provider: str, code: str) -> ProviderEndpoint:
        """Return the versioned endpoint policy used by workers."""
        return self._endpoint_registry.get(provider, code)

    def _resolve_endpoints(
        self,
        request: DataSyncRequest,
    ) -> tuple[ProviderEndpoint, ...]:
        """Resolve an executable endpoint set from the versioned registry."""
        provider = (request.provider or self._default_provider).strip().lower()
        if request.endpoint_codes:
            return tuple(
                self._endpoint_registry.get(provider, code)
                for code in request.endpoint_codes
            )
        return self._endpoint_registry.list(provider=provider)

    def sync_daily_bars(
        self,
        provider: Any,
        *,
        symbols: tuple[str, ...],
        start: datetime,
        end: datetime,
        decision_at: datetime,
        frequency: str = "1d",
    ) -> EndpointSyncResult:
        """Fetch daily bars through a provider and persist warehouse outputs."""
        provider_name = _provider_name(provider)
        endpoint = ProviderEndpoint(provider=provider_name, code="daily_bar", domain="market")
        run = self._sync_repository.create_run(
            DataSyncRequest(
                provider=provider_name,
                endpoint_codes=("daily_bar",),
                requested_by="data_ingestion_stack",
                backfill_start=start,
                backfill_end=end,
            ),
            endpoints=(endpoint,),
        )
        item = self._sync_repository.claim_next_endpoint(run.run_id, worker_id="data-ingestion")
        if item is None:
            raise RuntimeError(f"failed to claim daily_bar work item for run {run.run_id}")

        def handler(work_item: EndpointWorkItem) -> EndpointSyncResult:
            """handler."""
            records = provider.get_bars(list(symbols), start, end, frequency=frequency)
            return self.ingest_records(
                work_item,
                provider=provider_name,
                endpoint_code="daily_bar",
                raw_records=records,
                decision_at=decision_at,
            )

        return SyncService(
            self._sync_repository,
            handlers={(provider_name, "daily_bar"): handler},
        ).execute_endpoint(item, now=decision_at)

    def ingest_records(
        self,
        work_item: EndpointWorkItem,
        *,
        provider: str,
        endpoint_code: str,
        raw_records: list[dict[str, Any]],
        decision_at: datetime,
    ) -> EndpointSyncResult:
        """Persist raw payload, facts, and canonical values for provider records."""
        normalized_decision_at = ensure_utc(decision_at)
        snapshot = self._snapshot_store.write_json(
            provider,
            {
                "provider": provider,
                "endpoint_code": endpoint_code,
                "records": raw_records,
            },
        )
        snapshot_id = _raw_snapshot_id(snapshot.payload_hash)
        events = self._standardize(endpoint_code, raw_records, provider)
        facts = _events_to_facts(
            events,
            provider=provider,
            endpoint_code=endpoint_code,
            raw_snapshot_id=snapshot_id,
        )
        grouped_facts: dict[tuple[str, str], list[StandardizedIndicatorFact]] = defaultdict(list)
        for fact in facts:
            grouped_facts[(fact.security_id, fact.indicator_id)].append(fact)
        resolutions = [
            self._resolver.resolve(fact_group, decision_at=normalized_decision_at)
            for fact_group in grouped_facts.values()
        ]
        with self._session_factory.begin() as session:
            _upsert_raw_snapshot(
                session,
                snapshot_id=snapshot_id,
                provider=provider,
                endpoint_code=endpoint_code,
                snapshot=snapshot,
                decision_at=normalized_decision_at,
            )
            _upsert_schema_fields(
                session,
                provider,
                endpoint_code,
                raw_records,
                normalized_decision_at,
            )
            fact_count = _insert_facts(session, facts)
            session.flush()
            canonical_count = _insert_canonical_values(session, resolutions)
        return EndpointSyncResult(
            work_item_id=work_item.work_item_id,
            status=DataSyncStatus.SUCCEEDED,
            raw_snapshot_ids=(snapshot_id,),
            fact_count=fact_count,
            canonical_count=canonical_count,
            cursor_before=work_item.cursor_before,
            cursor_after=normalized_decision_at.isoformat(),
            finished_at=normalized_decision_at,
        )

    def ingest_security_master(
        self,
        work_item: EndpointWorkItem,
        *,
        provider: str,
        raw_records: list[dict[str, Any]],
        decision_at: datetime,
    ) -> EndpointSyncResult:
        """Persist a provider security master with raw and bitemporal lineage."""
        normalized_decision_at = ensure_utc(decision_at)
        snapshot = self._snapshot_store.write_json(
            provider,
            {
                "provider": provider,
                "endpoint_code": "security_master",
                "records": raw_records,
            },
        )
        snapshot_id = _raw_snapshot_id(snapshot.payload_hash)
        with self._session_factory.begin() as session:
            _upsert_raw_snapshot(
                session,
                snapshot_id=snapshot_id,
                provider=provider,
                endpoint_code="security_master",
                snapshot=snapshot,
                decision_at=normalized_decision_at,
            )
            _upsert_schema_fields(
                session,
                provider,
                "security_master",
                raw_records,
                normalized_decision_at,
            )
            for record in raw_records:
                symbol = normalize_symbol(str(record.get("symbol", "")))
                if not symbol or "." not in symbol:
                    continue
                listed = TimeStandardizer.parse_date(record.get("list_date"))
                listed_at = listed.date() if listed is not None else None
                exchange = symbol.rsplit(".", 1)[1]
                row = session.get(SecurityMasterRow, symbol)
                lineage = list(dict.fromkeys([*(row.raw_lineage_ids if row else []), snapshot_id]))
                if row is None:
                    session.add(
                        SecurityMasterRow(
                            security_id=symbol,
                            symbol=symbol,
                            name=str(record.get("name", symbol)),
                            exchange=exchange,
                            listed_at=listed_at,
                            delisted_at=None,
                            security_type="stock",
                            system_from=normalized_decision_at,
                            system_to=None,
                            raw_lineage_ids=lineage,
                        )
                    )
                else:
                    row.name = str(record.get("name", row.name))
                    row.exchange = exchange
                    row.listed_at = listed_at or row.listed_at
                    row.raw_lineage_ids = lineage
                identifier_id = _dimension_id(
                    "spi",
                    provider,
                    symbol,
                    str(listed_at or normalized_decision_at.date()),
                )
                if session.get(SecurityProviderIdentifierRow, identifier_id) is None:
                    session.add(
                        SecurityProviderIdentifierRow(
                            identifier_id=identifier_id,
                            security_id=symbol,
                            provider=provider,
                            provider_symbol=str(record.get("symbol", symbol)),
                            valid_from=listed_at or normalized_decision_at.date(),
                            valid_to=None,
                            system_from=normalized_decision_at,
                            system_to=None,
                        )
                    )
                industry_name = str(record.get("industry") or "").strip()
                if industry_name:
                    membership_id = _dimension_id(
                        "sim",
                        symbol,
                        industry_name,
                        normalized_decision_at.date().isoformat(),
                    )
                    if session.get(SecurityIndustryMembershipRow, membership_id) is None:
                        session.add(
                            SecurityIndustryMembershipRow(
                                membership_id=membership_id,
                                security_id=symbol,
                                taxonomy="provider-industry",
                                industry_code=industry_name,
                                industry_name=industry_name,
                                valid_from=normalized_decision_at.date(),
                                valid_to=None,
                                system_from=normalized_decision_at,
                                system_to=None,
                                source=provider,
                                quality="provider_reported",
                                raw_lineage_ids=[snapshot_id],
                            )
                        )
        return EndpointSyncResult(
            work_item_id=work_item.work_item_id,
            status=DataSyncStatus.SUCCEEDED,
            raw_snapshot_ids=(snapshot_id,),
            cursor_before=work_item.cursor_before,
            cursor_after=normalized_decision_at.isoformat(),
            finished_at=normalized_decision_at,
        )

    def ingest_indicator_records(
        self,
        work_item: EndpointWorkItem,
        *,
        provider: str,
        endpoint_code: str,
        raw_records: list[dict[str, Any]],
        decision_at: datetime,
        indicator_prefix: str = "",
    ) -> EndpointSyncResult:
        """Persist arbitrary numeric or text provider records as PIT facts."""
        normalized_decision_at = ensure_utc(decision_at)
        snapshot = self._snapshot_store.write_json(
            provider,
            {
                "provider": provider,
                "endpoint_code": endpoint_code,
                "records": raw_records,
            },
        )
        snapshot_id = _raw_snapshot_id(snapshot.payload_hash)
        facts: list[StandardizedIndicatorFact] = []
        metadata_fields = {
            "symbol",
            "date",
            "trade_date",
            "report_date",
            "ann_date",
            "as_of",
            "fetched_at",
            "available_at",
            "published_at",
            "source",
            "frequency",
            "index_code",
            "name",
        }
        for record in raw_records:
            symbol = normalize_symbol(str(record.get("symbol", "")))
            if not symbol or "." not in symbol:
                continue
            metadata_payload = _indicator_metadata_payload(
                endpoint_code,
                record,
            )
            event_at = (
                TimeStandardizer.parse_date(record.get("date"))
                or TimeStandardizer.parse_date(record.get("trade_date"))
                or TimeStandardizer.parse_date(record.get("report_date"))
                or TimeStandardizer.parse_date(record.get("as_of"))
                or normalized_decision_at
            )
            published_at = (
                TimeStandardizer.parse_date(record.get("ann_date"))
                or TimeStandardizer.parse_date(record.get("published_at"))
                or event_at
            )
            available_at = (
                TimeStandardizer.parse_date(record.get("available_at"))
                or published_at
            )
            fetched_at = (
                TimeStandardizer.parse_date(record.get("fetched_at"))
                or normalized_decision_at
            )
            for source_field, value in record.items():
                if (
                    source_field in metadata_fields
                    or value is None
                    or isinstance(value, bool)
                ):
                    continue
                numeric_value: Decimal | None = None
                text_value: str | None = None
                if isinstance(value, (int, float, Decimal)):
                    numeric_value = Decimal(str(value))
                elif isinstance(value, str) and value.strip():
                    text_value = value.strip()
                else:
                    continue
                indicator_id = f"{indicator_prefix}{source_field}"
                fact_json_value = (
                    metadata_payload
                    if metadata_payload and source_field == "index_weight"
                    else None
                )
                fact_id = _fact_id(
                    provider=provider,
                    endpoint_code=endpoint_code,
                    security_id=symbol,
                    indicator_id=indicator_id,
                    event_at=event_at,
                    raw_snapshot_id=snapshot_id,
                )
                facts.append(
                    StandardizedIndicatorFact(
                        fact_id=fact_id,
                        provider_code=provider,
                        provider_fact_id=fact_id,
                        endpoint_code=endpoint_code,
                        security_id=symbol,
                        indicator_id=indicator_id,
                        indicator_version="indicator-v0.2.0",
                        event_at=event_at,
                        published_at=published_at,
                        available_at=available_at,
                        fetched_at=fetched_at,
                        numeric_value=numeric_value,
                        text_value=text_value,
                        json_value=fact_json_value,
                        unit=_unit_for_indicator(indicator_id),
                        quality_score=Decimal("0.90000"),
                        mapping_version="mapping-v0.2.0",
                        raw_snapshot_id=snapshot_id,
                        lineage={
                            "source": provider,
                            "source_field": source_field,
                            "raw_snapshot_id": snapshot_id,
                            **(
                                {"metadata": metadata_payload}
                                if metadata_payload
                                else {}
                            ),
                        },
                    )
                )
        grouped: dict[tuple[str, str], list[StandardizedIndicatorFact]] = defaultdict(list)
        for fact in facts:
            grouped[(fact.security_id, fact.indicator_id)].append(fact)
        resolutions = [
            self._resolver.resolve(group, decision_at=normalized_decision_at)
            for group in grouped.values()
        ]
        with self._session_factory.begin() as session:
            _upsert_raw_snapshot(
                session,
                snapshot_id=snapshot_id,
                provider=provider,
                endpoint_code=endpoint_code,
                snapshot=snapshot,
                decision_at=normalized_decision_at,
            )
            _upsert_schema_fields(
                session,
                provider,
                endpoint_code,
                raw_records,
                normalized_decision_at,
            )
            fact_count = _insert_facts(session, facts)
            session.flush()
            canonical_count = _insert_canonical_values(session, resolutions)
        return EndpointSyncResult(
            work_item_id=work_item.work_item_id,
            status=DataSyncStatus.SUCCEEDED,
            raw_snapshot_ids=(snapshot_id,),
            fact_count=fact_count,
            canonical_count=canonical_count,
            cursor_before=work_item.cursor_before,
            cursor_after=normalized_decision_at.isoformat(),
            finished_at=normalized_decision_at,
        )

    def active_security_ids(self) -> tuple[str, ...]:
        """Return all active A-share security IDs in deterministic order."""
        with self._session_factory() as session:
            return tuple(
                session.scalars(active_security_ids()).all()
            )

    def _standardize(
        self,
        endpoint_code: str,
        raw_records: list[dict[str, Any]],
        provider: str,
    ) -> list[StandardDataEvent]:
        """standardize."""
        if endpoint_code == "daily_bar":
            return self._standardizer.standardize_bars(raw_records, provider)
        raise ValueError(f"unsupported data endpoint for ingestion: {endpoint_code}")


def _provider_name(provider: Any) -> str:
    """provider name."""
    name = getattr(provider, "name", None)
    if isinstance(name, str) and name.strip():
        return name.strip().lower()
    descriptor = getattr(provider, "descriptor", None)
    if descriptor is not None and getattr(descriptor, "name", None):
        return str(descriptor.name).strip().lower()
    return provider.__class__.__name__.strip().lower()


def _indicator_metadata_payload(
    endpoint_code: str,
    record: dict[str, Any],
) -> dict[str, Any]:
    """Return typed metadata that must travel with an indicator fact."""
    if endpoint_code != "index_weight":
        return {}
    index_code = str(record.get("index_code") or "").strip()
    return {"index_code": index_code} if index_code else {}


def _events_to_facts(
    events: list[StandardDataEvent],
    *,
    provider: str,
    endpoint_code: str,
    raw_snapshot_id: str,
) -> list[StandardizedIndicatorFact]:
    """events to facts."""
    facts: list[StandardizedIndicatorFact] = []
    for event in events:
        if event.domain is not StandardDataDomain.MARKET_BAR or event.symbol is None:
            continue
        for indicator_id in NUMERIC_MARKET_FIELDS:
            value = event.data.get(indicator_id)
            if value is None:
                continue
            fact_id = _fact_id(
                provider=provider,
                endpoint_code=endpoint_code,
                security_id=event.symbol,
                indicator_id=indicator_id,
                event_at=event.event_at,
                raw_snapshot_id=raw_snapshot_id,
            )
            facts.append(
                StandardizedIndicatorFact(
                    fact_id=fact_id,
                    provider_code=provider,
                    provider_fact_id=fact_id,
                    endpoint_code=endpoint_code,
                    security_id=event.symbol,
                    indicator_id=indicator_id,
                    indicator_version="indicator-v0.2.0",
                    event_at=event.event_at,
                    published_at=event.published_at,
                    available_at=event.available_at,
                    fetched_at=event.fetched_at,
                    numeric_value=Decimal(str(value)),
                    unit=_unit_for_indicator(indicator_id),
                    quality_score=Decimal("0.90000"),
                    mapping_version=event.mapping_version,
                    raw_snapshot_id=raw_snapshot_id,
                    lineage={"source": event.source, "raw_snapshot_id": raw_snapshot_id},
                )
            )
    return facts


def _upsert_raw_snapshot(
    session: Session,
    *,
    snapshot_id: str,
    provider: str,
    endpoint_code: str,
    snapshot,
    decision_at: datetime,
) -> None:
    """upsert raw snapshot."""
    existing = session.scalar(
        raw_snapshot_by_payload_hash(provider, endpoint_code, snapshot.payload_hash)
    )
    if existing is not None:
        return
    session.add(
        RawDataSnapshotRow(
            snapshot_id=snapshot_id,
            provider=provider,
            endpoint_code=endpoint_code,
            payload_hash=snapshot.payload_hash,
            storage_uri=snapshot.storage_uri,
            compression=snapshot.compression,
            raw_size=snapshot.raw_size,
            compressed_size=snapshot.compressed_size,
            fetched_at=decision_at,
            available_at=decision_at,
            retention_class="hot",
            payload_metadata={"content_addressed": True},
        )
    )
    session.flush()


def _upsert_schema_fields(
    session: Session,
    provider: str,
    endpoint_code: str,
    raw_records: list[dict[str, Any]],
    observed_at: datetime,
) -> None:
    """upsert schema fields."""
    fields: dict[str, list[Any]] = defaultdict(list)
    for record in raw_records:
        for field_name, value in record.items():
            fields[field_name].append(value)
    for field_name, values in fields.items():
        field_id = _schema_field_id(provider, endpoint_code, field_name)
        row = session.get(SourceSchemaFieldRow, field_id)
        sample_values = [str(value) for value in values[:3]]
        if row is None:
            session.add(
                SourceSchemaFieldRow(
                    field_id=field_id,
                    provider=provider,
                    endpoint_code=endpoint_code,
                    field_name=field_name,
                    inferred_type=_infer_type(values),
                    status="active",
                    first_seen_at=observed_at,
                    last_seen_at=observed_at,
                    consecutive_missing_count=0,
                    type_change_count=0,
                    sample_values=sample_values,
                )
            )
            continue
        row.last_seen_at = observed_at
        row.status = "active"
        row.consecutive_missing_count = 0
        row.sample_values = sample_values


def _insert_facts(session: Session, facts: list[StandardizedIndicatorFact]) -> int:
    """insert facts."""
    inserted = 0
    payloads = [
        {
            "fact_id": fact.fact_id,
            "provider": fact.provider_code,
            "provider_fact_id": fact.provider_fact_id,
            "endpoint_code": fact.endpoint_code,
            "security_id": fact.security_id,
            "indicator_id": fact.indicator_id,
            "indicator_version": fact.indicator_version,
            "event_at": fact.event_at,
            "published_at": fact.published_at,
            "available_at": fact.available_at,
            "fetched_at": fact.fetched_at,
            "revised_at": fact.revised_at,
            "numeric_value": fact.numeric_value,
            "text_value": fact.text_value,
            "json_value": fact.json_value,
            "unit": fact.unit,
            "quality_score": fact.quality_score,
            "mapping_version": fact.mapping_version,
            "raw_snapshot_id": fact.raw_snapshot_id,
            "lineage": fact.lineage,
        }
        for fact in facts
    ]
    for offset in range(0, len(payloads), 500):
        result = session.execute(
            insert_facts_batch(payloads[offset : offset + 500])
        )
        inserted += len(result.scalars().all())
    return inserted


def _insert_canonical_values(session: Session, resolutions) -> int:
    """insert canonical values."""
    payloads: list[dict[str, Any]] = []
    for resolution in resolutions:
        if resolution.selected is None:
            continue
        canonical_id = _canonical_id(
            security_id=resolution.selected.security_id,
            indicator_id=resolution.selected.indicator_id,
            decision_at=resolution.decision_at,
            resolver_version=resolution.resolver_version,
        )
        payloads.append(
            {
                "canonical_id": canonical_id,
                "security_id": resolution.selected.security_id,
                "indicator_id": resolution.selected.indicator_id,
                "indicator_version": resolution.selected.indicator_version,
                "decision_at": resolution.decision_at,
                "selected_fact_id": resolution.selected.fact_id,
                "candidate_fact_ids": [
                    fact.fact_id for fact in resolution.candidates
                ],
                "status": resolution.status,
                "numeric_value": resolution.selected.numeric_value,
                "text_value": resolution.selected.text_value,
                "json_value": resolution.selected.json_value,
                "confidence": resolution.confidence,
                "resolver_version": resolution.resolver_version,
                "resolver_hash": resolution.resolver_hash,
                "created_at": resolution.created_at,
            }
        )
    inserted = 0
    for offset in range(0, len(payloads), 500):
        result = session.execute(
            insert_canonical_values_batch(payloads[offset : offset + 500])
        )
        inserted += len(result.scalars().all())
    return inserted


def _raw_snapshot_id(payload_hash: str) -> str:
    """raw snapshot id."""
    return "raw_" + payload_hash.removeprefix("sha256:")[:20]


def _schema_field_id(provider: str, endpoint_code: str, field_name: str) -> str:
    """schema field id."""
    payload = f"{provider}|{endpoint_code}|{field_name}"
    return "sf_" + hashlib.sha256(payload.encode("utf-8")).hexdigest()[:20]


def _dimension_id(prefix: str, *parts: str) -> str:
    """Return a deterministic identifier for PIT dimension records."""
    payload = "|".join(parts)
    return f"{prefix}_" + hashlib.sha256(payload.encode("utf-8")).hexdigest()[:20]


def _fact_id(
    *,
    provider: str,
    endpoint_code: str,
    security_id: str,
    indicator_id: str,
    event_at: datetime,
    raw_snapshot_id: str,
) -> str:
    """fact id."""
    payload = "|".join(
        [
            provider,
            endpoint_code,
            security_id,
            indicator_id,
            ensure_utc(event_at).isoformat(),
            raw_snapshot_id,
        ]
    )
    return "fact_" + hashlib.sha256(payload.encode("utf-8")).hexdigest()[:24]


def _canonical_id(
    *,
    security_id: str,
    indicator_id: str,
    decision_at: datetime,
    resolver_version: str,
) -> str:
    """canonical id."""
    payload = "|".join(
        [
            security_id,
            indicator_id,
            ensure_utc(decision_at).isoformat(),
            resolver_version,
        ]
    )
    return "cv_" + hashlib.sha256(payload.encode("utf-8")).hexdigest()[:24]


def _infer_type(values: list[Any]) -> str:
    """infer type."""
    for value in values:
        if value is None:
            continue
        if isinstance(value, bool):
            return "bool"
        if isinstance(value, int):
            return "integer"
        if isinstance(value, float | Decimal):
            return "number"
        if isinstance(value, datetime):
            return "datetime"
        return "text"
    return "unknown"


def _unit_for_indicator(indicator_id: str) -> str:
    """unit for indicator."""
    if indicator_id in {"open", "high", "low", "close"}:
        return "CNY"
    if indicator_id == "volume":
        return "share"
    if indicator_id == "amount":
        return "CNY"
    return ""
