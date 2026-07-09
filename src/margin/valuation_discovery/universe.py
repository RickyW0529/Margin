"""Bitemporal universe resolution for valuation discovery."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol

from margin.valuation_discovery.models import (
    UniverseCode,
    UniverseDefinition,
    UniverseSnapshot,
)
from margin.valuation_discovery.repository import ValuationDiscoveryRepository


def _normalize_datetime(value: datetime) -> datetime:
    """Normalize a datetime to timezone-aware UTC.

    Args:
        value: datetime: .

    Returns:
        datetime: .
    """
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


@dataclass(frozen=True)
class SecurityListing:
    """Bitemporal listed-security record used to derive ALL_A.."""

    security_id: str
    listed_at: datetime
    delisted_at: datetime | None
    known_from: datetime
    known_to: datetime | None

    def is_visible_at(self, *, business_at: datetime, known_at: datetime) -> bool:
        """Return whether the security is listed and known at the supplied times.

        Args:
            business_at: datetime: .
            known_at: datetime: .

        Returns:
            bool: .
        """
        business = _normalize_datetime(business_at)
        known = _normalize_datetime(known_at)
        listed_at = _normalize_datetime(self.listed_at)
        delisted_at = (
            _normalize_datetime(self.delisted_at)
            if self.delisted_at is not None
            else datetime.max.replace(tzinfo=UTC)
        )
        known_from = _normalize_datetime(self.known_from)
        known_to = (
            _normalize_datetime(self.known_to)
            if self.known_to is not None
            else datetime.max.replace(tzinfo=UTC)
        )
        return listed_at <= business < delisted_at and known_from <= known < known_to


class SecurityListingSource(Protocol):
    """PIT source for ALL_A security listings.."""

    def list_listed_securities(
        self,
        *,
        business_at: datetime,
        known_at: datetime,
    ) -> Iterable[SecurityListing]:
        """Return securities listed at business time and known at system time.

        Args:
            business_at: datetime: .
            known_at: datetime: .

        Returns:
            Iterable[SecurityListing]: .
        """


class UniverseResolver:
    """Resolve built-in and custom company pools into frozen universe snapshots.."""

    def __init__(
        self,
        repository: ValuationDiscoveryRepository,
        *,
        security_source: SecurityListingSource | None = None,
    ) -> None:
        """Initialize the resolver with a repository and optional security source.

        Args:
            repository: ValuationDiscoveryRepository: .
            security_source: SecurityListingSource | None: .

        Returns:
            None: .
        """
        self._repository = repository
        self._security_source = security_source

    def seed_default_definitions(self) -> None:
        """Create default data-driven definitions for CSI300, CSI500, and ALL_A.

        Returns:
            None: .
        """
        add_definition = getattr(self._repository, "add_universe_definition", None)
        if add_definition is None:
            return
        for code, name, rule_code in (
            (UniverseCode.CSI300, "沪深300", "index_membership"),
            (UniverseCode.CSI500, "中证500", "index_membership"),
            (UniverseCode.ALL_A, "全 A", "listed_security"),
        ):
            add_definition(
                UniverseDefinition(
                    universe_code=code,
                    name=name,
                    rule_code=rule_code,
                    rule_config={"code": code.value},
                )
            )

    def snapshot(
        self,
        *,
        universe_code: UniverseCode | str,
        business_at: datetime,
        known_at: datetime,
    ) -> UniverseSnapshot:
        """Resolve and persist a frozen universe snapshot.

        Args:
            universe_code: UniverseCode | str: .
            business_at: datetime: .
            known_at: datetime: .

        Returns:
            UniverseSnapshot: .
        """
        if str(universe_code) == UniverseCode.ALL_A.value:
            snapshot = self._snapshot_all_a(
                universe_code=universe_code,
                business_at=business_at,
                known_at=known_at,
            )
        else:
            snapshot = self._snapshot_membership_pool(
                universe_code=universe_code,
                business_at=business_at,
                known_at=known_at,
            )
        self._repository.add_universe_snapshot(snapshot)
        return snapshot

    def _snapshot_membership_pool(
        self,
        *,
        universe_code: UniverseCode | str,
        business_at: datetime,
        known_at: datetime,
    ) -> UniverseSnapshot:
        """Build a universe snapshot from visible index memberships.

        Args:
            universe_code: UniverseCode | str: .
            business_at: datetime: .
            known_at: datetime: .

        Returns:
            UniverseSnapshot: .
        """
        memberships = [
            membership
            for membership in self._repository.list_universe_memberships(
                universe_code=str(universe_code)
            )
            if membership.is_visible_at(business_at=business_at, known_at=known_at)
        ]
        memberships.sort(key=lambda item: (item.rank is None, item.rank or 0, item.security_id))
        security_ids = tuple(membership.security_id for membership in memberships)
        membership_ids = tuple(membership.membership_id for membership in memberships)
        version_id = memberships[-1].universe_version_id if memberships else "empty"
        return UniverseSnapshot(
            universe_code=universe_code,
            universe_version_id=version_id,
            business_at=business_at,
            known_at=known_at,
            security_ids=security_ids,
            membership_ids=membership_ids,
        )

    def _snapshot_all_a(
        self,
        *,
        universe_code: UniverseCode | str,
        business_at: datetime,
        known_at: datetime,
    ) -> UniverseSnapshot:
        """Build a universe snapshot from listed securities for ALL_A.

        Args:
            universe_code: UniverseCode | str: .
            business_at: datetime: .
            known_at: datetime: .

        Returns:
            UniverseSnapshot: .
        """
        if self._security_source is None:
            listings: tuple[SecurityListing, ...] = ()
        else:
            listings = tuple(
                self._security_source.list_listed_securities(
                    business_at=business_at,
                    known_at=known_at,
                )
            )
        security_ids = tuple(sorted({listing.security_id for listing in listings}))
        return UniverseSnapshot(
            universe_code=universe_code,
            universe_version_id="ALL_A:listings",
            business_at=business_at,
            known_at=known_at,
            security_ids=security_ids,
        )
