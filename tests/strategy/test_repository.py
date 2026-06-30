"""Tests for strategy repository.

This module validates the in-memory strategy repository's ability to store,
list, and update strategy profiles.
"""

from __future__ import annotations

from margin.strategy.models import StrategyConfig, StrategyProfile, StrategyVersion
from margin.strategy.repository import MemoryStrategyRepository


def test_memory_repository_stores_profile():
    """Verify the memory repository stores and retrieves a strategy profile.

    Returns:
        None.
    """
    repo = MemoryStrategyRepository()
    profile = StrategyProfile(owner_id="user_1", name="Test")
    repo.add_profile(profile)
    assert repo.get_profile(profile.strategy_id) == profile


def test_memory_repository_lists_profiles_for_owner():
    """Verify the memory repository lists profiles filtered by owner.

    Returns:
        None.
    """
    repo = MemoryStrategyRepository()
    p1 = StrategyProfile(owner_id="user_1", name="A")
    p2 = StrategyProfile(owner_id="user_1", name="B")
    p3 = StrategyProfile(owner_id="user_2", name="C")
    repo.add_profile(p1)
    repo.add_profile(p2)
    repo.add_profile(p3)
    profiles = repo.list_profiles("user_1")
    assert len(profiles) == 2


def test_memory_repository_updates_profile():
    """Verify the memory repository updates an existing profile with new versions.

    Returns:
        None.
    """
    repo = MemoryStrategyRepository()
    profile = StrategyProfile(owner_id="user_1", name="Test")
    repo.add_profile(profile)
    version = StrategyVersion(
        strategy_id=profile.strategy_id,
        name="V1",
        config=StrategyConfig(),
    )
    updated = profile.with_version(version)
    repo.update_profile(updated)
    fetched = repo.get_profile(profile.strategy_id)
    assert len(fetched.versions) == 1
