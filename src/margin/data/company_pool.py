"""Company-pool serving view and immutable non-ST All-A snapshots."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from datetime import date, datetime
from typing import Any

from pydantic import BaseModel, computed_field, field_validator
from sqlalchemy import text
from sqlalchemy.orm import Session

from margin.data.db_models import CompanyPoolSnapshotRow
from margin.data.tushare_source import is_delisting_security_name, is_st_security_name
from margin.news.models import ensure_utc, utc_now
from margin.sql.data_queries import (
    insert_pool_members,
    latest_pool_snapshot,
    pool_members_by_snapshot,
    pool_snapshot_by_run,
)


class CompanyPoolMember(BaseModel):
    """One company-pool member exposed to quant and upper services."""

    membership_id: str
    security_id: str
    name: str
    exchange: str
    industry_code: str | None = None
    industry_name: str | None = None
    included: bool = True
    exclusion_reasons: tuple[str, ...] = ()
    data_status: str = "pending_quant_input"

    model_config = {"frozen": True}


class CompanyPoolSnapshot(BaseModel):
    """Immutable materialization of the current non-ST All-A view."""

    snapshot_id: str
    pool_code: str = "ALL_A_NON_ST"
    source_run_id: str
    business_at: datetime
    known_at: datetime
    members: tuple[CompanyPoolMember, ...]
    criteria: dict[str, Any]
    input_hash: str
    created_at: datetime

    model_config = {"frozen": True}

    @field_validator("business_at", "known_at", "created_at")
    @classmethod
    def normalize_time(cls, value: datetime) -> datetime:
        """Normalize snapshot clocks to UTC."""
        return ensure_utc(value)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def member_count(self) -> int:
        """Return included company count."""
        return sum(member.included for member in self.members)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def security_ids(self) -> tuple[str, ...]:
        """Return deterministic included security IDs."""
        return tuple(
            member.security_id for member in self.members if member.included
        )

    @computed_field  # type: ignore[prop-decorator]
    @property
    def membership_ids(self) -> tuple[str, ...]:
        """Return deterministic membership IDs."""
        return tuple(
            member.membership_id for member in self.members if member.included
        )


def build_company_pool_snapshot(
    rows: list[dict[str, Any]],
    *,
    source_run_id: str,
    business_at: datetime,
    known_at: datetime,
    created_at: datetime | None = None,
) -> CompanyPoolSnapshot:
    """Build a stable immutable snapshot from serving-view rows.

    Args:
        rows: Serving-view rows keyed by ``security_id`` with optional
            ``name``, ``exchange``, ``industry_code`` and ``industry_name``.
        source_run_id: The source run that produced the serving view.
        business_at: The business date the snapshot represents.
        known_at: The system time at which the snapshot became known.
        created_at: Optional override for the creation timestamp.

    Returns:
        An immutable ``CompanyPoolSnapshot`` with deterministic IDs and a
        content-addressed ``input_hash``.
    """
    normalized_rows = sorted(rows, key=lambda row: str(row["security_id"]))
    payload = [
        {
            "security_id": str(row["security_id"]),
            "name": str(row.get("name") or row["security_id"]),
            "exchange": str(row.get("exchange") or ""),
            "industry_code": row.get("industry_code"),
            "industry_name": row.get("industry_name"),
        }
        for row in normalized_rows
    ]
    input_hash = "sha256:" + hashlib.sha256(
        json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            default=str,
        ).encode()
    ).hexdigest()
    snapshot_id = "cps_" + hashlib.sha256(
        f"{source_run_id}|{input_hash}".encode()
    ).hexdigest()[:28]
    members = tuple(
        CompanyPoolMember(
            membership_id="cpm_"
            + hashlib.sha256(
                f"{snapshot_id}|{row['security_id']}".encode()
            ).hexdigest()[:28],
            security_id=str(row["security_id"]),
            name=str(row.get("name") or row["security_id"]),
            exchange=str(row.get("exchange") or ""),
            industry_code=(
                str(row["industry_code"]) if row.get("industry_code") else None
            ),
            industry_name=(
                str(row["industry_name"]) if row.get("industry_name") else None
            ),
        )
        for row in normalized_rows
    )
    return CompanyPoolSnapshot(
        snapshot_id=snapshot_id,
        source_run_id=source_run_id,
        business_at=business_at,
        known_at=known_at,
        members=members,
        criteria={
            "listed": True,
            "security_type": "stock",
            "exclude_st": True,
            "exclude_delisted": True,
        },
        input_hash=input_hash,
        created_at=created_at or utc_now(),
    )


def filter_company_pool_rows_as_of(
    rows: list[dict[str, Any]],
    *,
    business_at: datetime,
) -> list[dict[str, Any]]:
    """Filter serving-view rows to securities listed by the business date.

    Args:
        rows: Raw serving-view rows to filter.
        business_at: The business date used for listing-date and ST/delisting
            exclusion checks.

    Returns:
        Rows excluding ST, delisting-transition, and not-yet-listed securities.
    """
    business_date = ensure_utc(business_at).date()
    return [
        row
        for row in rows
        if (listed_at := _row_date(row.get("listed_at"))) is None
        or listed_at <= business_date
        if not is_st_security_name(str(row.get("name") or ""))
        and not is_delisting_security_name(str(row.get("name") or ""))
    ]


class SQLAlchemyCompanyPoolRepository:
    """Materialize and load company-pool snapshots from PostgreSQL."""

    def __init__(self, session_factory: Callable[[], Session]) -> None:
        """Initialize the repository.

        Args:
            session_factory: Callable returning a SQLAlchemy ``Session``.
        """
        self._session_factory = session_factory

    def materialize(
        self,
        *,
        source_run_id: str,
        business_at: datetime,
        known_at: datetime,
    ) -> CompanyPoolSnapshot:
        """Freeze the current serving view for one completed source run.

        Args:
            source_run_id: The source run that produced the serving view.
            business_at: The business date the snapshot represents.
            known_at: The system time at which the snapshot became known.

        Returns:
            The materialized immutable ``CompanyPoolSnapshot``. If a snapshot
            for this source run already exists, the existing one is returned.
        """
        with self._session_factory.begin() as session:
            existing = session.scalar(
                pool_snapshot_by_run("ALL_A_NON_ST", source_run_id)
            )
            if existing is not None:
                return self._load(session, existing)
            rows = [
                dict(row._mapping)
                for row in session.execute(
                    text(
                        "SELECT security_id, symbol, name, exchange, "
                        "listed_at, industry_code, industry_name "
                        "FROM company_pool_current_non_st "
                        "ORDER BY security_id"
                    )
                )
            ]
            rows = filter_company_pool_rows_as_of(rows, business_at=business_at)
            snapshot = build_company_pool_snapshot(
                rows,
                source_run_id=source_run_id,
                business_at=business_at,
                known_at=known_at,
            )
            session.add(
                CompanyPoolSnapshotRow(
                    snapshot_id=snapshot.snapshot_id,
                    pool_code=snapshot.pool_code,
                    source_run_id=snapshot.source_run_id,
                    business_at=snapshot.business_at,
                    known_at=snapshot.known_at,
                    member_count=snapshot.member_count,
                    criteria=snapshot.criteria,
                    input_hash=snapshot.input_hash,
                    created_at=snapshot.created_at,
                )
            )
            session.flush()
            if snapshot.members:
                session.execute(
                    insert_pool_members(
                        [
                            {
                                **member.model_dump(mode="python"),
                                "snapshot_id": snapshot.snapshot_id,
                                "exclusion_reasons": list(
                                    member.exclusion_reasons
                                ),
                            }
                            for member in snapshot.members
                        ]
                    )
                )
            return snapshot

    def latest(self, pool_code: str = "ALL_A_NON_ST") -> CompanyPoolSnapshot | None:
        """Return the newest immutable snapshot for upper services.

        Args:
            pool_code: The pool code to look up. Defaults to ``ALL_A_NON_ST``.

        Returns:
            The latest ``CompanyPoolSnapshot``, or ``None`` if none exists.
        """
        with self._session_factory() as session:
            row = session.scalar(latest_pool_snapshot(pool_code))
            return self._load(session, row) if row is not None else None

    def _load(
        self,
        session: Session,
        row: CompanyPoolSnapshotRow,
    ) -> CompanyPoolSnapshot:
        """Reconstruct a snapshot model from persisted rows."""
        members = session.scalars(
            pool_members_by_snapshot(row.snapshot_id)
        ).all()
        return CompanyPoolSnapshot(
            snapshot_id=row.snapshot_id,
            pool_code=row.pool_code,
            source_run_id=row.source_run_id,
            business_at=row.business_at,
            known_at=row.known_at,
            members=tuple(
                CompanyPoolMember(
                    membership_id=member.membership_id,
                    security_id=member.security_id,
                    name=member.name,
                    exchange=member.exchange,
                    industry_code=member.industry_code,
                    industry_name=member.industry_name,
                    included=member.included,
                    exclusion_reasons=tuple(member.exclusion_reasons or ()),
                    data_status=member.data_status,
                )
                for member in members
            ),
            criteria=dict(row.criteria or {}),
            input_hash=row.input_hash,
            created_at=row.created_at,
        )


def _row_date(value: Any) -> date | None:
    """Normalize SQL/string date values from serving-view rows."""
    if value is None:
        return None
    if isinstance(value, datetime):
        return ensure_utc(value).date()
    if isinstance(value, date):
        return value
    normalized = str(value).strip()
    if not normalized:
        return None
    return datetime.fromisoformat(normalized).date()
