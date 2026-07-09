"""Data-layer query factory (warehouse, sync, ingestion, company pool, retention, policy).

Every SQLAlchemy ``select``/``insert``/``update``/``delete`` that was previously
constructed inline inside data-layer repository classes is defined here as a
standalone function.  Repository classes call these functions to obtain ready
statements, keeping query construction centralized and auditable.
"""

from __future__ import annotations

from datetime import UTC, datetime, time, timedelta
from typing import Any

from sqlalchemy import Select, case, delete, func, insert, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert

from margin.data.db_models import (
    AdjustedPriceSeriesRow,
    CanonicalIndicatorValueRow,
    CompanyPoolMemberRow,
    CompanyPoolSnapshotRow,
    CorporateActionRow,
    DataAcquisitionPolicyVersionRow,
    DataFreshnessStateRow,
    DataQualityEventRow,
    DataSyncRunRow,
    DataSyncWorkItemRow,
    ProviderEndpointRow,
    RawDataSnapshotRow,
    SecurityIndustryMembershipRow,
    SecurityMasterRow,
    StandardizedIndicatorFactRow,
)
from margin.data.sync_models import DataSyncStatus

# ── Warehouse queries (warehouse_repository.py) ──────────────────────────────


def canonical_values_by_decision(
    security_ids: tuple[str, ...],
    decision_at: datetime,
    indicator_ids: tuple[str, ...] | None = None,
) -> Select:
    """PIT-safe canonical value query: latest values known at ``decision_at``.

    Args:
        security_ids: tuple[str, ...]: .
        decision_at: datetime: .
        indicator_ids: tuple[str, ...] | None: .

    Returns:
        Select: .
    """
    stmt = (
        select(CanonicalIndicatorValueRow)
        .where(CanonicalIndicatorValueRow.security_id.in_(security_ids))
        .where(CanonicalIndicatorValueRow.decision_at <= decision_at)
        .order_by(
            CanonicalIndicatorValueRow.security_id,
            CanonicalIndicatorValueRow.indicator_id,
            CanonicalIndicatorValueRow.decision_at.desc(),
            CanonicalIndicatorValueRow.created_at.desc(),
        )
    )
    if indicator_ids:
        stmt = stmt.where(CanonicalIndicatorValueRow.indicator_id.in_(indicator_ids))
    return stmt


def industry_memberships_bitemporal(
    security_ids: tuple[str, ...],
    on_date: Any,
    taxonomy: str,
    system_as_of: datetime,
) -> Select:
    """Bitemporal industry membership query.

    Args:
        security_ids: tuple[str, ...]: .
        on_date: Any: .
        taxonomy: str: .
        system_as_of: datetime: .

    Returns:
        Select: .
    """
    return (
        select(SecurityIndustryMembershipRow)
        .where(SecurityIndustryMembershipRow.security_id.in_(security_ids))
        .where(SecurityIndustryMembershipRow.taxonomy == taxonomy)
        .where(SecurityIndustryMembershipRow.valid_from <= on_date)
        .where(
            (SecurityIndustryMembershipRow.valid_to.is_(None))
            | (SecurityIndustryMembershipRow.valid_to > on_date)
        )
        .where(SecurityIndustryMembershipRow.system_from <= system_as_of)
        .where(
            (SecurityIndustryMembershipRow.system_to.is_(None))
            | (SecurityIndustryMembershipRow.system_to > system_as_of)
        )
        .order_by(
            SecurityIndustryMembershipRow.security_id,
            SecurityIndustryMembershipRow.system_from.desc(),
        )
    )


def adjusted_prices_by_decision(
    security_ids: tuple[str, ...],
    start_date: Any,
    end_date: Any,
    decision_at: datetime,
) -> Select:
    """PIT-safe adjusted price query.

    Args:
        security_ids: tuple[str, ...]: .
        start_date: Any: .
        end_date: Any: .
        decision_at: datetime: .

    Returns:
        Select: .
    """
    return (
        select(AdjustedPriceSeriesRow)
        .where(AdjustedPriceSeriesRow.security_id.in_(security_ids))
        .where(AdjustedPriceSeriesRow.trade_date >= start_date)
        .where(AdjustedPriceSeriesRow.trade_date <= end_date)
        .where(AdjustedPriceSeriesRow.decision_at <= decision_at)
        .order_by(
            AdjustedPriceSeriesRow.security_id,
            AdjustedPriceSeriesRow.trade_date,
            AdjustedPriceSeriesRow.decision_at.desc(),
            AdjustedPriceSeriesRow.created_at.desc(),
        )
    )


def freshness_records(domains: set[str] | None = None) -> Select:
    """Freshness records optionally filtered by endpoint domain.

    Args:
        domains: set[str] | None: .

    Returns:
        Select: .
    """
    stmt = select(DataFreshnessStateRow)
    if domains:
        stmt = stmt.join(
            ProviderEndpointRow,
            (ProviderEndpointRow.provider == DataFreshnessStateRow.provider)
            & (ProviderEndpointRow.code == DataFreshnessStateRow.endpoint_code),
        ).where(ProviderEndpointRow.domain.in_(domains))
    return stmt.order_by(
        DataFreshnessStateRow.provider,
        DataFreshnessStateRow.endpoint_code,
        DataFreshnessStateRow.as_of_date.desc(),
        DataFreshnessStateRow.created_at.desc(),
    )


def quality_events_recent(
    security_ids: tuple[str, ...] = (),
    since: datetime | None = None,
) -> Select:
    """Append-only quality event query.

    Args:
        security_ids: tuple[str, ...]: .
        since: datetime | None: .

    Returns:
        Select: .
    """
    stmt = select(DataQualityEventRow).order_by(DataQualityEventRow.created_at.desc())
    if security_ids:
        stmt = stmt.where(DataQualityEventRow.security_id.in_(security_ids))
    if since is not None:
        stmt = stmt.where(DataQualityEventRow.created_at >= since)
    return stmt


def security_profiles_active(
    security_ids: tuple[str, ...],
    system_as_of: datetime,
) -> Select:
    """Active security-master records known at ``system_as_of``.

    Args:
        security_ids: tuple[str, ...]: .
        system_as_of: datetime: .

    Returns:
        Select: .
    """
    return (
        select(SecurityMasterRow)
        .where(SecurityMasterRow.security_id.in_(security_ids))
        .where(SecurityMasterRow.system_from <= system_as_of)
        .where(
            (SecurityMasterRow.system_to.is_(None)) | (SecurityMasterRow.system_to > system_as_of)
        )
        .order_by(
            SecurityMasterRow.security_id,
            SecurityMasterRow.system_from.desc(),
        )
    )


def indicator_history_pit(
    security_ids: tuple[str, ...],
    indicator_ids: tuple[str, ...],
    start_date: Any,
    end_date: Any,
    decision_at: datetime,
    max_points_per_indicator: int | None = None,
) -> Select:
    """PIT-safe indicator history with deterministic provider deduplication.

    Args:
        security_ids: tuple[str, ...]: .
        indicator_ids: tuple[str, ...]: .
        start_date: Any: .
        end_date: Any: .
        decision_at: datetime: .
        max_points_per_indicator: int | None: .

    Returns:
        Select: .
    """
    window_start = datetime.combine(start_date, time.min, tzinfo=UTC)
    window_end = datetime.combine(end_date + timedelta(days=1), time.min, tzinfo=UTC)
    provider_priority = case(
        (StandardizedIndicatorFactRow.provider == "tushare", 0),
        (StandardizedIndicatorFactRow.provider == "akshare", 1),
        else_=2,
    )
    base = (
        select(
            StandardizedIndicatorFactRow.fact_id.label("fact_id"),
            StandardizedIndicatorFactRow.provider.label("provider"),
            StandardizedIndicatorFactRow.security_id.label("security_id"),
            StandardizedIndicatorFactRow.indicator_id.label("indicator_id"),
            StandardizedIndicatorFactRow.event_at.label("event_at"),
            StandardizedIndicatorFactRow.available_at.label("available_at"),
            StandardizedIndicatorFactRow.fetched_at.label("fetched_at"),
            StandardizedIndicatorFactRow.numeric_value.label("numeric_value"),
            StandardizedIndicatorFactRow.quality_score.label("quality_score"),
            func.row_number()
            .over(
                partition_by=(
                    StandardizedIndicatorFactRow.security_id,
                    StandardizedIndicatorFactRow.indicator_id,
                    StandardizedIndicatorFactRow.event_at,
                ),
                order_by=(
                    StandardizedIndicatorFactRow.quality_score.desc(),
                    provider_priority,
                    StandardizedIndicatorFactRow.fetched_at.desc(),
                    StandardizedIndicatorFactRow.fact_id,
                ),
            )
            .label("revision_rank"),
        )
        .where(StandardizedIndicatorFactRow.security_id.in_(security_ids))
        .where(StandardizedIndicatorFactRow.indicator_id.in_(indicator_ids))
        .where(StandardizedIndicatorFactRow.event_at >= window_start)
        .where(StandardizedIndicatorFactRow.event_at < window_end)
        .where(StandardizedIndicatorFactRow.available_at <= decision_at)
        .where(StandardizedIndicatorFactRow.numeric_value.is_not(None))
    ).subquery()
    deduped = select(
        base.c.fact_id,
        base.c.provider,
        base.c.security_id,
        base.c.indicator_id,
        base.c.event_at,
        base.c.available_at,
        base.c.fetched_at,
        base.c.numeric_value,
        base.c.quality_score,
    ).where(base.c.revision_rank == 1)
    if max_points_per_indicator is not None:
        ranked_base = deduped.subquery()
        ranked = (
            select(
                ranked_base,
                func.row_number()
                .over(
                    partition_by=(
                        ranked_base.c.security_id,
                        ranked_base.c.indicator_id,
                    ),
                    order_by=ranked_base.c.event_at.desc(),
                )
                .label("point_rank"),
            )
        ).subquery()
        return (
            select(
                ranked.c.fact_id,
                ranked.c.provider,
                ranked.c.security_id,
                ranked.c.indicator_id,
                ranked.c.event_at,
                ranked.c.available_at,
                ranked.c.fetched_at,
                ranked.c.numeric_value,
                ranked.c.quality_score,
            )
            .where(ranked.c.point_rank <= max_points_per_indicator)
            .order_by(
                ranked.c.security_id,
                ranked.c.indicator_id,
                ranked.c.event_at,
            )
        )
    unbounded = deduped.subquery()
    return select(unbounded).order_by(
        unbounded.c.security_id,
        unbounded.c.indicator_id,
        unbounded.c.event_at,
    )


# ── Sync queries (sync_service.py) ───────────────────────────────────────────


def sync_run_by_id_for_update(run_id: str) -> Select:
    """Lock a sync run row for exclusive claim.

    Args:
        run_id: str: .

    Returns:
        Select: .
    """
    return (
        select(DataSyncRunRow)
        .where(DataSyncRunRow.run_id == run_id)
        .with_for_update(skip_locked=True)
    )


def sync_runs_active_for_update() -> Select:
    """Lock all non-terminal sync runs for cross-run claiming.

    Returns:
        Select: .
    """
    return (
        select(DataSyncRunRow)
        .where(
            DataSyncRunRow.status.in_(
                [
                    DataSyncStatus.PENDING.value,
                    DataSyncStatus.RUNNING.value,
                    DataSyncStatus.FAILED_RETRYABLE.value,
                ]
            )
        )
        .order_by(DataSyncRunRow.created_at, DataSyncRunRow.run_id)
        .with_for_update(skip_locked=True)
    )


def sync_run_latest_by_requester(requested_by: str) -> Select:
    """Find the newest run created by a specific requester.

    Args:
        requested_by: str: .

    Returns:
        Select: .
    """
    return (
        select(DataSyncRunRow)
        .where(DataSyncRunRow.requested_by == requested_by)
        .order_by(
            DataSyncRunRow.created_at.desc(),
            DataSyncRunRow.run_id.desc(),
        )
        .limit(1)
    )


def active_work_item_for_run(run_id: str, lease_cutoff: datetime) -> Select:
    """Check whether a run has an actively-claimed work item.

    Args:
        run_id: str: .
        lease_cutoff: datetime: .

    Returns:
        Select: .
    """
    return (
        select(DataSyncWorkItemRow.work_item_id)
        .where(DataSyncWorkItemRow.run_id == run_id)
        .where(DataSyncWorkItemRow.status == DataSyncStatus.RUNNING.value)
        .where(DataSyncWorkItemRow.claimed_at > lease_cutoff)
        .limit(1)
    )


def claimable_work_item(run_id: str, claimed_at: datetime, lease_cutoff: datetime) -> Select:
    """Select the next claimable work item with priority ordering and skip-locked.

    Args:
        run_id: str: .
        claimed_at: datetime: .
        lease_cutoff: datetime: .

    Returns:
        Select: .
    """
    priority = case(
        (DataSyncWorkItemRow.endpoint_id.like("%:security_master"), 10),
        (DataSyncWorkItemRow.endpoint_id.like("%:index_member_csi300"), 20),
        (DataSyncWorkItemRow.endpoint_id.like("%:index_member_csi500"), 21),
        (DataSyncWorkItemRow.endpoint_id.like("%:daily_bar"), 30),
        (DataSyncWorkItemRow.endpoint_id.like("%:adjustment_factor"), 40),
        (DataSyncWorkItemRow.endpoint_id.like("%:financial_statement"), 50),
        (DataSyncWorkItemRow.endpoint_id.like("%:valuation"), 60),
        else_=100,
    )
    return (
        select(DataSyncWorkItemRow)
        .where(DataSyncWorkItemRow.run_id == run_id)
        .where(
            (
                DataSyncWorkItemRow.status.in_(
                    [
                        DataSyncStatus.PENDING.value,
                        DataSyncStatus.FAILED_RETRYABLE.value,
                    ]
                )
                & (
                    (DataSyncWorkItemRow.next_attempt_at.is_(None))
                    | (DataSyncWorkItemRow.next_attempt_at <= claimed_at)
                )
            )
            | (
                (DataSyncWorkItemRow.status == DataSyncStatus.RUNNING.value)
                & (DataSyncWorkItemRow.claimed_at <= lease_cutoff)
            )
        )
        .order_by(priority, DataSyncWorkItemRow.created_at)
        .with_for_update(skip_locked=True)
        .limit(1)
    )


def work_items_for_run(run_id: str) -> Select:
    """Return all work items for a run (used for reconciliation).

    Args:
        run_id: str: .

    Returns:
        Select: .
    """
    return select(DataSyncWorkItemRow).where(DataSyncWorkItemRow.run_id == run_id)


def upsert_freshness(
    freshness_id: str,
    provider: str,
    endpoint_code: str,
    as_of_date: Any,
    observed_at: datetime,
) -> Any:
    """Upsert a freshness state row on conflict.

    Args:
        freshness_id: str: .
        provider: str: .
        endpoint_code: str: .
        as_of_date: Any: .
        observed_at: datetime: .

    Returns:
        Any: .
    """
    return (
        pg_insert(DataFreshnessStateRow)
        .values(
            freshness_id=freshness_id,
            provider=provider,
            endpoint_code=endpoint_code,
            as_of_date=as_of_date,
            expected_at=observed_at,
            observed_at=observed_at,
            status="fresh",
            lag_seconds=0,
            created_at=observed_at,
        )
        .on_conflict_do_update(
            constraint="uq_data_freshness",
            set_={
                "expected_at": observed_at,
                "observed_at": observed_at,
                "status": "fresh",
                "lag_seconds": 0,
            },
        )
    )


# ── Ingestion queries (ingestion.py) ─────────────────────────────────────────


def active_security_ids() -> Select:
    """Return all active A-share security IDs in deterministic order.

    Returns:
        Select: .
    """
    return (
        select(SecurityMasterRow.security_id)
        .where(SecurityMasterRow.system_to.is_(None))
        .order_by(SecurityMasterRow.security_id)
    )


def active_stock_security_ids() -> Select:
    """Return all active stock security IDs in deterministic order.

    Returns:
        Select: .
    """
    return (
        select(SecurityMasterRow.security_id)
        .where(SecurityMasterRow.system_to.is_(None))
        .where(SecurityMasterRow.security_type == "stock")
        .order_by(SecurityMasterRow.security_id)
    )


def raw_snapshot_by_payload_hash(
    provider: str,
    endpoint_code: str,
    payload_hash: str,
) -> Select:
    """Find an existing raw snapshot by content-addressed hash.

    Args:
        provider: str: .
        endpoint_code: str: .
        payload_hash: str: .

    Returns:
        Select: .
    """
    return select(RawDataSnapshotRow).where(
        RawDataSnapshotRow.provider == provider,
        RawDataSnapshotRow.endpoint_code == endpoint_code,
        RawDataSnapshotRow.payload_hash == payload_hash,
    )


def insert_facts_batch(fact_payloads: list[dict[str, Any]]) -> Any:
    """Batch insert standardized indicator facts with conflict-don't-nothing.

    Args:
        fact_payloads: list[dict[str, Any]]: .

    Returns:
        Any: .
    """
    return (
        pg_insert(StandardizedIndicatorFactRow)
        .values(fact_payloads)
        .on_conflict_do_nothing()
        .returning(StandardizedIndicatorFactRow.fact_id)
    )


def insert_canonical_values_batch(payloads: list[dict[str, Any]]) -> Any:
    """Batch insert canonical indicator values with conflict-don't-nothing.

    Args:
        payloads: list[dict[str, Any]]: .

    Returns:
        Any: .
    """
    return (
        pg_insert(CanonicalIndicatorValueRow)
        .values(payloads)
        .on_conflict_do_nothing()
        .returning(CanonicalIndicatorValueRow.canonical_id)
    )


# ── Company pool queries (company_pool.py) ────────────────────────────────────


def pool_snapshot_by_run(pool_code: str, source_run_id: str) -> Select:
    """Find an existing pool snapshot for a source run.

    Args:
        pool_code: str: .
        source_run_id: str: .

    Returns:
        Select: .
    """
    return select(CompanyPoolSnapshotRow).where(
        CompanyPoolSnapshotRow.pool_code == pool_code,
        CompanyPoolSnapshotRow.source_run_id == source_run_id,
    )


def latest_pool_snapshot(pool_code: str) -> Select:
    """Return the newest immutable pool snapshot.

    Args:
        pool_code: str: .

    Returns:
        Select: .
    """
    return (
        select(CompanyPoolSnapshotRow)
        .where(CompanyPoolSnapshotRow.pool_code == pool_code)
        .order_by(
            CompanyPoolSnapshotRow.business_at.desc(),
            CompanyPoolSnapshotRow.created_at.desc(),
        )
        .limit(1)
    )


def pool_members_by_snapshot(snapshot_id: str) -> Select:
    """Return all members frozen into a pool snapshot.

    Args:
        snapshot_id: str: .

    Returns:
        Select: .
    """
    return (
        select(CompanyPoolMemberRow)
        .where(CompanyPoolMemberRow.snapshot_id == snapshot_id)
        .order_by(CompanyPoolMemberRow.security_id)
    )


def insert_pool_members(member_payloads: list[dict[str, Any]]) -> Any:
    """Batch insert company pool members.

    Args:
        member_payloads: list[dict[str, Any]]: .

    Returns:
        Any: .
    """
    return insert(CompanyPoolMemberRow).values(member_payloads)


# ── Retention queries (retention.py) ──────────────────────────────────────────


def delete_raw_snapshot(snapshot_id: str) -> Any:
    """Delete an unreferenced raw snapshot.

    Args:
        snapshot_id: str: .

    Returns:
        Any: .
    """
    return delete(RawDataSnapshotRow).where(RawDataSnapshotRow.snapshot_id == snapshot_id)


def fact_reference_count(snapshot_id: str) -> Select:
    """Count facts referencing a raw snapshot.

    Args:
        snapshot_id: str: .

    Returns:
        Select: .
    """
    return (
        select(func.count())
        .select_from(StandardizedIndicatorFactRow)
        .where(StandardizedIndicatorFactRow.raw_snapshot_id == snapshot_id)
    )


def corporate_action_reference_count(snapshot_id: str) -> Select:
    """Count corporate actions referencing a raw snapshot.

    Args:
        snapshot_id: str: .

    Returns:
        Select: .
    """
    return (
        select(func.count())
        .select_from(CorporateActionRow)
        .where(CorporateActionRow.raw_snapshot_id == snapshot_id)
    )


# ── Policy queries (policy.py) ───────────────────────────────────────────────


def policy_versions_by_owner(owner_id: str) -> Select:
    """List policy versions newest-first.

    Args:
        owner_id: str: .

    Returns:
        Select: .
    """
    return (
        select(DataAcquisitionPolicyVersionRow)
        .where(DataAcquisitionPolicyVersionRow.owner_id == owner_id)
        .order_by(
            DataAcquisitionPolicyVersionRow.created_at.desc(),
            DataAcquisitionPolicyVersionRow.version_id.desc(),
        )
    )


def active_policy_by_owner(owner_id: str, lifecycle_value: str) -> Select:
    """Return the active policy for an owner.

    Args:
        owner_id: str: .
        lifecycle_value: str: .

    Returns:
        Select: .
    """
    return (
        select(DataAcquisitionPolicyVersionRow)
        .where(DataAcquisitionPolicyVersionRow.owner_id == owner_id)
        .where(DataAcquisitionPolicyVersionRow.lifecycle == lifecycle_value)
        .limit(1)
    )


def policy_by_create_idempotency(actor_id: str, idempotency_key: str) -> Select:
    """Find a prior policy create by actor and idempotency key.

    Args:
        actor_id: str: .
        idempotency_key: str: .

    Returns:
        Select: .
    """
    return (
        select(DataAcquisitionPolicyVersionRow)
        .where(DataAcquisitionPolicyVersionRow.created_by == actor_id)
        .where(DataAcquisitionPolicyVersionRow.create_idempotency_key == idempotency_key)
        .limit(1)
    )


def policy_by_activation_idempotency(actor_id: str, idempotency_key: str) -> Select:
    """Find a prior policy activation by actor and idempotency key.

    Args:
        actor_id: str: .
        idempotency_key: str: .

    Returns:
        Select: .
    """
    return (
        select(DataAcquisitionPolicyVersionRow)
        .where(DataAcquisitionPolicyVersionRow.activation_idempotency_key == idempotency_key)
        .where(DataAcquisitionPolicyVersionRow.created_by == actor_id)
        .limit(1)
    )


def active_policies_for_update(owner_id: str, lifecycle_value: str) -> Select:
    """Lock active policy versions for deprecation during activation.

    Args:
        owner_id: str: .
        lifecycle_value: str: .

    Returns:
        Select: .
    """
    return (
        select(DataAcquisitionPolicyVersionRow)
        .where(DataAcquisitionPolicyVersionRow.owner_id == owner_id)
        .where(DataAcquisitionPolicyVersionRow.lifecycle == lifecycle_value)
        .with_for_update()
    )


# ── Tushare source repository queries (tushare_repository.py) ────────────────


def insert_landing_records(table: Any, payloads: list[dict[str, Any]]) -> Any:
    """Insert immutable source landing rows with conflict-don't-nothing.

    Args:
        table: Any: .
        payloads: list[dict[str, Any]]: .

    Returns:
        Any: .
    """
    return (
        insert(table)
        .values(payloads)
        .on_conflict_do_nothing(index_elements=["natural_key_hash", "revision_hash"])
        .returning(table.c.source_row_id)
    )


def update_landing_quality_status(
    table: Any,
    source_row_ids: list[str],
    status: str,
) -> Any:
    """Update quality_status on landing rows after quality decision.

    Args:
        table: Any: .
        source_row_ids: list[str]: .
        status: str: .

    Returns:
        Any: .
    """
    return (
        update(table).where(table.c.source_row_id.in_(source_row_ids)).values(quality_status=status)
    )


def insert_quality_decisions(payloads: list[dict[str, Any]]) -> Any:
    """Append quality decisions with conflict-don't-nothing.

    Args:
        payloads: list[dict[str, Any]]: .

    Returns:
        Any: .
    """
    return (
        insert(_QUALITY_TABLE_PLACEHOLDER)
        .values(payloads)
        .on_conflict_do_nothing()
        .returning(_QUALITY_TABLE_PLACEHOLDER.c.decision_id)
    )


def landing_row_count(table: Any) -> Select:
    """Count source rows for coverage reporting.

    Args:
        table: Any: .

    Returns:
        Select: .
    """
    return select(func.count()).select_from(table)


def quality_decision_counts(provider: str, endpoint: str) -> Select:
    """Return quality-decision counts by state for one endpoint.

    Args:
        provider: str: .
        endpoint: str: .

    Returns:
        Select: .
    """
    return (
        select(_QUALITY_TABLE_PLACEHOLDER.c.decision, func.count())
        .where(
            _QUALITY_TABLE_PLACEHOLDER.c.provider == provider,
            _QUALITY_TABLE_PLACEHOLDER.c.endpoint == endpoint,
        )
        .group_by(_QUALITY_TABLE_PLACEHOLDER.c.decision)
    )


# Placeholder — the real table is defined in tushare_repository.py at module
# load time using SQLAlchemy Core MetaData.  The query functions above accept
# the table as a parameter so this placeholder is only used for type hints.
_QUALITY_TABLE_PLACEHOLDER: Any = None
