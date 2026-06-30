"""Versioned rolling-window policy for provider acquisition and serving."""

from __future__ import annotations

import calendar
import hashlib
import json
import uuid
from collections.abc import Callable
from datetime import UTC, datetime
from enum import StrEnum
from typing import Protocol

from pydantic import BaseModel, Field, computed_field, field_validator
from sqlalchemy.orm import Session

from margin.data.db_models import DataAcquisitionPolicyVersionRow
from margin.news.models import ensure_utc, utc_now
from margin.sql.data_queries import (
    active_policies_for_update,
    active_policy_by_owner,
    policy_by_activation_idempotency,
    policy_by_create_idempotency,
    policy_versions_by_owner,
)


class DataPolicyLifecycle(StrEnum):
    """Lifecycle states for an immutable data-acquisition policy version."""

    DRAFT = "draft"
    ACTIVE = "active"
    DEPRECATED = "deprecated"


class DataWindow(BaseModel):
    """Calendar-derived acquisition window frozen into a sync run."""

    start: datetime
    end: datetime

    model_config = {"frozen": True}


class DataAcquisitionPolicyVersion(BaseModel):
    """Append-only policy controlling rolling source and warehouse coverage."""

    version_id: str
    owner_id: str = "local-admin"
    rolling_window_months: int = Field(default=24, ge=12, le=60)
    revision_lookback_days: int = Field(default=30, ge=0, le=365)
    financial_comparison_years: int = Field(default=1, ge=1, le=3)
    lifecycle: DataPolicyLifecycle = DataPolicyLifecycle.DRAFT
    created_by: str = "local-admin"
    create_idempotency_key: str = "model-default"
    activation_idempotency_key: str | None = None
    created_at: datetime = Field(default_factory=utc_now)
    activated_at: datetime | None = None
    deprecated_at: datetime | None = None

    model_config = {"frozen": True}

    @field_validator("created_at", "activated_at", "deprecated_at")
    @classmethod
    def normalize_timestamps(cls, value: datetime | None) -> datetime | None:
        """Normalize all policy timestamps to UTC."""
        return ensure_utc(value) if value is not None else None

    @computed_field  # type: ignore[prop-decorator]
    @property
    def config_hash(self) -> str:
        """Return a stable hash over behavior-affecting policy fields."""
        payload = {
            "rolling_window_months": self.rolling_window_months,
            "revision_lookback_days": self.revision_lookback_days,
            "financial_comparison_years": self.financial_comparison_years,
        }
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
        return "sha256:" + hashlib.sha256(encoded).hexdigest()

    def window_for(self, decision_at: datetime) -> DataWindow:
        """Compute a calendar-month rolling window ending at ``decision_at``.

        Args:
            decision_at: The point in time at which the window is evaluated.

        Returns:
            A ``DataWindow`` spanning ``rolling_window_months`` calendar months
            ending at ``decision_at``.
        """
        end = ensure_utc(decision_at)
        start = _subtract_calendar_months(end, self.rolling_window_months)
        return DataWindow(
            start=start.replace(hour=0, minute=0, second=0, microsecond=0),
            end=end,
        )


class DataAcquisitionPolicyRepository(Protocol):
    """Persistence contract used by the data-policy service."""

    def save(self, version: DataAcquisitionPolicyVersion) -> None: ...

    def get(self, version_id: str) -> DataAcquisitionPolicyVersion | None: ...

    def list_versions(self, owner_id: str) -> list[DataAcquisitionPolicyVersion]: ...

    def get_active(self, owner_id: str) -> DataAcquisitionPolicyVersion | None: ...

    def find_create_replay(
        self,
        *,
        actor_id: str,
        idempotency_key: str,
    ) -> DataAcquisitionPolicyVersion | None: ...

    def activate(
        self,
        version_id: str,
        *,
        actor_id: str,
        idempotency_key: str,
    ) -> DataAcquisitionPolicyVersion: ...


class MemoryDataAcquisitionPolicyRepository:
    """In-memory policy repository for unit and API tests."""

    def __init__(self) -> None:
        """Initialize an empty repository."""
        self._versions: dict[str, DataAcquisitionPolicyVersion] = {}

    def save(self, version: DataAcquisitionPolicyVersion) -> None:
        """Append a policy version.

        Args:
            version: The policy version to persist.

        Raises:
            ValueError: If the version ID already exists.
        """
        if version.version_id in self._versions:
            raise ValueError(f"data policy '{version.version_id}' already exists")
        self._versions[version.version_id] = version

    def get(self, version_id: str) -> DataAcquisitionPolicyVersion | None:
        """Return a policy version.

        Args:
            version_id: The version ID to look up.

        Returns:
            The matching policy version, or ``None`` if not found.
        """
        return self._versions.get(version_id)

    def list_versions(self, owner_id: str) -> list[DataAcquisitionPolicyVersion]:
        """List newest policy versions first.

        Args:
            owner_id: The owner whose versions to list.

        Returns:
            Policy versions sorted by creation time descending.
        """
        return sorted(
            (
                version
                for version in self._versions.values()
                if version.owner_id == owner_id
            ),
            key=lambda version: (version.created_at, version.version_id),
            reverse=True,
        )

    def get_active(self, owner_id: str) -> DataAcquisitionPolicyVersion | None:
        """Return the single active policy.

        Args:
            owner_id: The owner whose active policy to return.

        Returns:
            The active policy version, or ``None`` if none is active.
        """
        return next(
            (
                version
                for version in self.list_versions(owner_id)
                if version.lifecycle is DataPolicyLifecycle.ACTIVE
            ),
            None,
        )

    def find_create_replay(
        self,
        *,
        actor_id: str,
        idempotency_key: str,
    ) -> DataAcquisitionPolicyVersion | None:
        """Return a prior create result for the same actor/key.

        Args:
            actor_id: The actor that created the version.
            idempotency_key: The idempotency key of the original create.

        Returns:
            The previously created version, or ``None`` if no replay exists.
        """
        return next(
            (
                version
                for version in self._versions.values()
                if version.created_by == actor_id
                and version.create_idempotency_key == idempotency_key
            ),
            None,
        )

    def activate(
        self,
        version_id: str,
        *,
        actor_id: str,
        idempotency_key: str,
    ) -> DataAcquisitionPolicyVersion:
        """Activate one version and deprecate the previous active sibling.

        Args:
            version_id: The version to activate.
            actor_id: The actor performing the activation.
            idempotency_key: Idempotency key for replay-safe activation.

        Returns:
            The activated policy version.

        Raises:
            KeyError: If ``version_id`` does not exist.
        """
        replay = next(
            (
                version
                for version in self._versions.values()
                if version.activation_idempotency_key == idempotency_key
                and version.created_by == actor_id
            ),
            None,
        )
        if replay is not None:
            return replay
        target = self._versions.get(version_id)
        if target is None:
            raise KeyError(f"data policy '{version_id}' not found")
        now = utc_now()
        for current_id, current in tuple(self._versions.items()):
            if (
                current.owner_id == target.owner_id
                and current.lifecycle is DataPolicyLifecycle.ACTIVE
                and current_id != version_id
            ):
                self._versions[current_id] = current.model_copy(
                    update={
                        "lifecycle": DataPolicyLifecycle.DEPRECATED,
                        "deprecated_at": now,
                    }
                )
        activated = target.model_copy(
            update={
                "lifecycle": DataPolicyLifecycle.ACTIVE,
                "activated_at": target.activated_at or now,
                "activation_idempotency_key": idempotency_key,
            }
        )
        self._versions[version_id] = activated
        return activated


class SQLAlchemyDataAcquisitionPolicyRepository:
    """PostgreSQL-backed policy repository."""

    def __init__(self, session_factory: Callable[[], Session]) -> None:
        """Initialize the repository.

        Args:
            session_factory: Callable returning a SQLAlchemy ``Session``.
        """
        self._session_factory = session_factory

    def save(self, version: DataAcquisitionPolicyVersion) -> None:
        """Append a policy version.

        Args:
            version: The policy version to persist.
        """
        with self._session_factory.begin() as session:
            session.add(_policy_to_row(version))

    def get(self, version_id: str) -> DataAcquisitionPolicyVersion | None:
        """Return a policy version.

        Args:
            version_id: The version ID to look up.

        Returns:
            The matching policy version, or ``None`` if not found.
        """
        with self._session_factory() as session:
            row = session.get(DataAcquisitionPolicyVersionRow, version_id)
        return _policy_from_row(row) if row is not None else None

    def list_versions(self, owner_id: str) -> list[DataAcquisitionPolicyVersion]:
        """List newest policy versions first.

        Args:
            owner_id: The owner whose versions to list.

        Returns:
            Policy versions sorted by creation time descending.
        """
        with self._session_factory() as session:
            rows = session.scalars(
                policy_versions_by_owner(owner_id)
            ).all()
        return [_policy_from_row(row) for row in rows]

    def get_active(self, owner_id: str) -> DataAcquisitionPolicyVersion | None:
        """Return the active policy.

        Args:
            owner_id: The owner whose active policy to return.

        Returns:
            The active policy version, or ``None`` if none is active.
        """
        with self._session_factory() as session:
            row = session.scalar(
                active_policy_by_owner(
                    owner_id, DataPolicyLifecycle.ACTIVE.value
                )
            )
        return _policy_from_row(row) if row is not None else None

    def find_create_replay(
        self,
        *,
        actor_id: str,
        idempotency_key: str,
    ) -> DataAcquisitionPolicyVersion | None:
        """Return a prior create result for the same actor/key.

        Args:
            actor_id: The actor that created the version.
            idempotency_key: The idempotency key of the original create.

        Returns:
            The previously created version, or ``None`` if no replay exists.
        """
        with self._session_factory() as session:
            row = session.scalar(
                policy_by_create_idempotency(actor_id, idempotency_key)
            )
        return _policy_from_row(row) if row is not None else None

    def activate(
        self,
        version_id: str,
        *,
        actor_id: str,
        idempotency_key: str,
    ) -> DataAcquisitionPolicyVersion:
        """Activate one policy version transactionally.

        Args:
            version_id: The version to activate.
            actor_id: The actor performing the activation.
            idempotency_key: Idempotency key for replay-safe activation.

        Returns:
            The activated policy version.

        Raises:
            KeyError: If ``version_id`` does not exist.
        """
        with self._session_factory.begin() as session:
            replay = session.scalar(
                policy_by_activation_idempotency(actor_id, idempotency_key)
            )
            if replay is not None:
                return _policy_from_row(replay)
            target = session.get(DataAcquisitionPolicyVersionRow, version_id)
            if target is None:
                raise KeyError(f"data policy '{version_id}' not found")
            now = utc_now()
            current_rows = session.scalars(
                active_policies_for_update(
                    target.owner_id, DataPolicyLifecycle.ACTIVE.value
                )
            ).all()
            for current in current_rows:
                if current.version_id != version_id:
                    current.lifecycle = DataPolicyLifecycle.DEPRECATED.value
                    current.deprecated_at = now
            target.lifecycle = DataPolicyLifecycle.ACTIVE.value
            target.activated_at = target.activated_at or now
            target.activation_idempotency_key = idempotency_key
            session.flush()
            return _policy_from_row(target)


class DataAcquisitionPolicyService:
    """Application service for creating, activating, and resolving policies."""

    def __init__(
        self,
        repository: DataAcquisitionPolicyRepository,
        *,
        owner_id: str = "local-admin",
    ) -> None:
        """Initialize the service.

        Args:
            repository: The policy persistence repository.
            owner_id: The default owner for created policies.
        """
        self._repository = repository
        self._owner_id = owner_id

    def create(
        self,
        *,
        rolling_window_months: int = 24,
        revision_lookback_days: int = 30,
        financial_comparison_years: int = 1,
        actor_id: str,
        idempotency_key: str,
    ) -> DataAcquisitionPolicyVersion:
        """Create an append-only draft, replaying duplicate frontend retries.

        Args:
            rolling_window_months: Rolling window size in months.
            revision_lookback_days: Revision lookback in days.
            financial_comparison_years: Financial comparison horizon in years.
            actor_id: The actor creating the policy.
            idempotency_key: Idempotency key for replay-safe creation.

        Returns:
            The newly created or replayed draft policy version.
        """
        replay = self._repository.find_create_replay(
            actor_id=actor_id,
            idempotency_key=idempotency_key,
        )
        if replay is not None:
            return replay
        version = DataAcquisitionPolicyVersion(
            version_id=f"data-policy-{uuid.uuid4().hex[:16]}",
            owner_id=self._owner_id,
            rolling_window_months=rolling_window_months,
            revision_lookback_days=revision_lookback_days,
            financial_comparison_years=financial_comparison_years,
            created_by=actor_id,
            create_idempotency_key=idempotency_key,
        )
        self._repository.save(version)
        return version

    def activate(
        self,
        version_id: str,
        *,
        actor_id: str,
        idempotency_key: str,
    ) -> DataAcquisitionPolicyVersion:
        """Activate a policy version.

        Args:
            version_id: The version to activate.
            actor_id: The actor performing the activation.
            idempotency_key: Idempotency key for replay-safe activation.

        Returns:
            The activated policy version.
        """
        return self._repository.activate(
            version_id,
            actor_id=actor_id,
            idempotency_key=idempotency_key,
        )

    def get(self, version_id: str) -> DataAcquisitionPolicyVersion:
        """Return one version or raise a stable missing-resource error.

        Args:
            version_id: The version ID to look up.

        Returns:
            The matching policy version.

        Raises:
            KeyError: If ``version_id`` does not exist.
        """
        version = self._repository.get(version_id)
        if version is None:
            raise KeyError(f"data policy '{version_id}' not found")
        return version

    def list_versions(self) -> list[DataAcquisitionPolicyVersion]:
        """List policy versions for the configured owner.

        Returns:
            Policy versions sorted by creation time descending.
        """
        return self._repository.list_versions(self._owner_id)

    def get_active(self) -> DataAcquisitionPolicyVersion:
        """Return the active policy or the non-persisted safe default.

        Returns:
            The active policy version, or a system default if none is active.
        """
        return self._repository.get_active(self._owner_id) or DataAcquisitionPolicyVersion(
            version_id="data-policy-default-v0.3",
            owner_id=self._owner_id,
            lifecycle=DataPolicyLifecycle.ACTIVE,
            created_by="system-default",
            create_idempotency_key="system-default-v0.3",
        )


def _subtract_calendar_months(value: datetime, months: int) -> datetime:
    """Subtract whole calendar months while clamping end-of-month days.

    Args:
        value: The datetime to subtract from.
        months: The number of calendar months to subtract.

    Returns:
        A datetime shifted back by ``months`` calendar months.
    """
    month_index = value.year * 12 + (value.month - 1) - months
    year, zero_based_month = divmod(month_index, 12)
    month = zero_based_month + 1
    day = min(value.day, calendar.monthrange(year, month)[1])
    return value.replace(year=year, month=month, day=day, tzinfo=UTC)


def _policy_to_row(
    version: DataAcquisitionPolicyVersion,
) -> DataAcquisitionPolicyVersionRow:
    """Map a policy model to its ORM row."""
    return DataAcquisitionPolicyVersionRow(
        version_id=version.version_id,
        owner_id=version.owner_id,
        rolling_window_months=version.rolling_window_months,
        revision_lookback_days=version.revision_lookback_days,
        financial_comparison_years=version.financial_comparison_years,
        lifecycle=version.lifecycle.value,
        config_hash=version.config_hash,
        created_by=version.created_by,
        create_idempotency_key=version.create_idempotency_key,
        activation_idempotency_key=version.activation_idempotency_key,
        created_at=version.created_at,
        activated_at=version.activated_at,
        deprecated_at=version.deprecated_at,
    )


def _policy_from_row(
    row: DataAcquisitionPolicyVersionRow,
) -> DataAcquisitionPolicyVersion:
    """Map an ORM row to the immutable policy model."""
    return DataAcquisitionPolicyVersion(
        version_id=row.version_id,
        owner_id=row.owner_id,
        rolling_window_months=row.rolling_window_months,
        revision_lookback_days=row.revision_lookback_days,
        financial_comparison_years=row.financial_comparison_years,
        lifecycle=DataPolicyLifecycle(row.lifecycle),
        created_by=row.created_by,
        create_idempotency_key=row.create_idempotency_key,
        activation_idempotency_key=row.activation_idempotency_key,
        created_at=row.created_at,
        activated_at=row.activated_at,
        deprecated_at=row.deprecated_at,
    )
