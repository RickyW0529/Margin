"""Bitemporal universe domain tests for valuation discovery."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime

import pytest

from margin.valuation_discovery.models import (
    DataStatus,
    ResearchGuardrail,
    ScreeningStatus,
    UniverseCode,
    UniverseMembership,
)
from margin.valuation_discovery.repository import MemoryValuationDiscoveryRepository
from margin.valuation_discovery.universe import SecurityListing, UniverseResolver


@pytest.fixture
def valuation_repository() -> MemoryValuationDiscoveryRepository:
    """valuation repository."""
    return MemoryValuationDiscoveryRepository()


def test_universe_membership_has_valid_and_system_time() -> None:
    """universe membership has valid and system time."""
    membership = UniverseMembership(
        universe_code=UniverseCode.CSI300,
        universe_version_id="univ-v1",
        security_id="000001.SZ",
        valid_from=datetime(2026, 1, 1, tzinfo=UTC),
        valid_to=None,
        system_from=datetime(2026, 1, 2, tzinfo=UTC),
        system_to=None,
        weight=0.012,
        rank=3,
        source="warehouse:index_weight",
        quality="ok",
        raw_lineage_ids=("raw-1",),
    )

    assert membership.is_visible_at(
        business_at=datetime(2026, 6, 22, tzinfo=UTC),
        known_at=datetime(2026, 6, 22, tzinfo=UTC),
    )
    assert ScreeningStatus.PASS.value == "pass"
    assert DataStatus.PIT_DEGRADED.value == "pit_degraded"
    assert ResearchGuardrail.OVERHEAT_CAUTION.value == "overheat_caution"


def test_resolver_returns_members_known_at_system_time(
    valuation_repository: MemoryValuationDiscoveryRepository,
) -> None:
    """resolver returns members known at system time."""
    valuation_repository.add_universe_membership(
        UniverseMembership(
            universe_code=UniverseCode.CSI300,
            universe_version_id="univ-v1",
            security_id="000001.SZ",
            valid_from=datetime(2026, 1, 1, tzinfo=UTC),
            valid_to=None,
            system_from=datetime(2026, 1, 2, tzinfo=UTC),
            system_to=datetime(2026, 6, 20, tzinfo=UTC),
            source="warehouse:index_weight",
        )
    )
    valuation_repository.add_universe_membership(
        UniverseMembership(
            universe_code=UniverseCode.CSI300,
            universe_version_id="univ-v2",
            security_id="000002.SZ",
            valid_from=datetime(2026, 1, 1, tzinfo=UTC),
            valid_to=None,
            system_from=datetime(2026, 6, 21, tzinfo=UTC),
            system_to=None,
            source="warehouse:index_weight",
        )
    )
    resolver = UniverseResolver(valuation_repository)

    snapshot = resolver.snapshot(
        universe_code=UniverseCode.CSI300,
        business_at=datetime(2026, 6, 22, tzinfo=UTC),
        known_at=datetime(2026, 6, 19, tzinfo=UTC),
    )

    assert snapshot.security_ids == ("000001.SZ",)
    assert snapshot.membership_ids
    assert snapshot.input_hash.startswith("sha256:")


@dataclass(frozen=True)
class FakeSecuritySource:
    """FakeSecuritySource."""
    listings: tuple[SecurityListing, ...]

    def list_listed_securities(
        self,
        *,
        business_at: datetime,
        known_at: datetime,
    ) -> Iterable[SecurityListing]:
        """list listed securities."""
        return tuple(
            listing
            for listing in self.listings
            if listing.is_visible_at(business_at=business_at, known_at=known_at)
        )


def test_all_a_pool_accepts_new_listing_when_known(
    valuation_repository: MemoryValuationDiscoveryRepository,
) -> None:
    """all a pool accepts new listing when known."""
    source = FakeSecuritySource(
        listings=(
            SecurityListing(
                security_id="000003.SZ",
                listed_at=datetime(2026, 1, 1, tzinfo=UTC),
                delisted_at=None,
                known_from=datetime(2026, 1, 2, tzinfo=UTC),
                known_to=None,
            ),
            SecurityListing(
                security_id="000004.SZ",
                listed_at=datetime(2026, 1, 1, tzinfo=UTC),
                delisted_at=None,
                known_from=datetime(2026, 6, 23, tzinfo=UTC),
                known_to=None,
            ),
        )
    )
    resolver = UniverseResolver(valuation_repository, security_source=source)

    snapshot = resolver.snapshot(
        universe_code=UniverseCode.ALL_A,
        business_at=datetime(2026, 6, 22, tzinfo=UTC),
        known_at=datetime(2026, 6, 22, tzinfo=UTC),
    )

    assert snapshot.security_ids == ("000003.SZ",)
