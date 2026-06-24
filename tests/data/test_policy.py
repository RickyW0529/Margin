"""Versioned rolling-window data acquisition policy tests."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from margin.data.policy import (
    DataAcquisitionPolicyService,
    DataAcquisitionPolicyVersion,
    MemoryDataAcquisitionPolicyRepository,
)


def test_default_policy_uses_24_calendar_months() -> None:
    """The default policy computes a calendar-month window, not fixed days."""
    policy = DataAcquisitionPolicyVersion(version_id="policy-default")

    window = policy.window_for(datetime(2026, 3, 31, 8, tzinfo=UTC))

    assert policy.rolling_window_months == 24
    assert window.start == datetime(2024, 3, 31, 0, tzinfo=UTC)
    assert window.end == datetime(2026, 3, 31, 8, tzinfo=UTC)


@pytest.mark.parametrize("months", [11, 61])
def test_policy_rejects_frontend_window_outside_safe_range(months: int) -> None:
    """The server remains authoritative over frontend policy bounds."""
    with pytest.raises(ValidationError):
        DataAcquisitionPolicyVersion(
            version_id=f"policy-{months}",
            rolling_window_months=months,
        )


def test_activation_deprecates_previous_active_version() -> None:
    """Only one acquisition policy may be active for an owner."""
    repository = MemoryDataAcquisitionPolicyRepository()
    service = DataAcquisitionPolicyService(repository)
    first = service.create(
        rolling_window_months=24,
        actor_id="local-admin",
        idempotency_key="create-24",
    )
    second = service.create(
        rolling_window_months=36,
        actor_id="local-admin",
        idempotency_key="create-36",
    )

    service.activate(
        first.version_id,
        actor_id="local-admin",
        idempotency_key="activate-24",
    )
    activated = service.activate(
        second.version_id,
        actor_id="local-admin",
        idempotency_key="activate-36",
    )

    assert activated.lifecycle.value == "active"
    assert service.get_active().version_id == second.version_id
    assert service.get(first.version_id).lifecycle.value == "deprecated"


def test_create_is_idempotent_for_same_admin_key() -> None:
    """Frontend retries do not create duplicate policy versions."""
    service = DataAcquisitionPolicyService(
        MemoryDataAcquisitionPolicyRepository()
    )

    first = service.create(
        rolling_window_months=18,
        actor_id="local-admin",
        idempotency_key="same-create",
    )
    replay = service.create(
        rolling_window_months=18,
        actor_id="local-admin",
        idempotency_key="same-create",
    )

    assert replay.version_id == first.version_id
    assert len(service.list_versions()) == 1
