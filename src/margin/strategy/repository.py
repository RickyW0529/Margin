"""Strategy persistence repositories."""

from __future__ import annotations

from collections.abc import Callable
from typing import Protocol

from sqlalchemy.orm import Session

from margin.strategy.db_models import StrategyProfileRow, StrategyVersionRow
from margin.strategy.models import (
    PromptLayer,
    StrategyConfig,
    StrategyProfile,
    StrategySandboxResult,
    StrategyState,
    StrategyVersion,
)


class StrategyRepository(Protocol):
    """Persistence contract consumed by :class:`StrategyService`."""

    def add_profile(self, profile: StrategyProfile) -> None:
        """Persist a new strategy profile."""

    def get_profile(self, strategy_id: str) -> StrategyProfile | None:
        """Return a profile by identifier."""

    def list_profiles(self, owner_id: str) -> list[StrategyProfile]:
        """Return all profiles owned by the given user."""

    def update_profile(self, profile: StrategyProfile) -> None:
        """Persist an updated profile, replacing the existing one."""


class MemoryStrategyRepository:
    """In-memory strategy repository for tests and local usage."""

    def __init__(self) -> None:
        self._profiles: dict[str, StrategyProfile] = {}

    def add_profile(self, profile: StrategyProfile) -> None:
        if profile.strategy_id in self._profiles:
            raise ValueError(f"strategy '{profile.strategy_id}' already exists")
        self._profiles[profile.strategy_id] = profile

    def get_profile(self, strategy_id: str) -> StrategyProfile | None:
        return self._profiles.get(strategy_id)

    def list_profiles(self, owner_id: str) -> list[StrategyProfile]:
        return [
            profile
            for profile in self._profiles.values()
            if profile.owner_id == owner_id
        ]

    def update_profile(self, profile: StrategyProfile) -> None:
        if profile.strategy_id not in self._profiles:
            raise KeyError(f"strategy '{profile.strategy_id}' not found")
        self._profiles[profile.strategy_id] = profile


class SQLAlchemyStrategyRepository:
    """PostgreSQL-backed strategy repository."""

    def __init__(self, session_factory: Callable[[], Session]) -> None:
        self._session_factory = session_factory

    def add_profile(self, profile: StrategyProfile) -> None:
        with self._session_factory.begin() as session:
            if session.get(StrategyProfileRow, profile.strategy_id) is not None:
                raise ValueError(f"strategy '{profile.strategy_id}' already exists")
            session.add(
                StrategyProfileRow(
                    strategy_id=profile.strategy_id,
                    owner_id=profile.owner_id,
                    name=profile.name,
                    active_version_id=profile.active_version_id,
                    created_at=profile.created_at,
                    updated_at=profile.updated_at,
                )
            )
            for version in profile.versions:
                session.add(
                    StrategyVersionRow(
                        version_id=version.version_id,
                        strategy_id=version.strategy_id,
                        name=version.name,
                        description=version.description,
                        config=version.config.model_dump(mode="json"),
                        prompt_layers=[
                            layer.model_dump(mode="json")
                            for layer in version.prompt_layers
                        ],
                        state=version.state.value,
                        prompt_version=version.prompt_version,
                        sandbox_result=(
                            version.sandbox_result.model_dump(mode="json")
                            if version.sandbox_result
                            else None
                        ),
                        created_at=version.created_at,
                    )
                )

    def get_profile(self, strategy_id: str) -> StrategyProfile | None:
        with self._session_factory() as session:
            row = session.get(StrategyProfileRow, strategy_id)
            if row is None:
                return None
            versions = [
                StrategyVersion(
                    strategy_id=v.strategy_id,
                    version_id=v.version_id,
                    name=v.name,
                    description=v.description,
                    config=StrategyConfig.model_validate(v.config),
                    prompt_layers=tuple(
                        PromptLayer.model_validate(layer)
                        for layer in v.prompt_layers
                    ),
                    state=StrategyState(v.state),
                    prompt_version=v.prompt_version,
                    sandbox_result=(
                        StrategySandboxResult.model_validate(v.sandbox_result)
                        if v.sandbox_result
                        else None
                    ),
                    created_at=v.created_at,
                )
                for v in row.versions
            ]
            return StrategyProfile(
                strategy_id=row.strategy_id,
                owner_id=row.owner_id,
                name=row.name,
                active_version_id=row.active_version_id,
                versions=tuple(versions),
                created_at=row.created_at,
                updated_at=row.updated_at,
            )

    def list_profiles(self, owner_id: str) -> list[StrategyProfile]:
        with self._session_factory() as session:
            rows = session.query(StrategyProfileRow).filter_by(owner_id=owner_id).all()
            profiles = [self.get_profile(row.strategy_id) for row in rows]
            return [profile for profile in profiles if profile is not None]

    def update_profile(self, profile: StrategyProfile) -> None:
        with self._session_factory.begin() as session:
            row = session.get(StrategyProfileRow, profile.strategy_id)
            if row is None:
                raise KeyError(f"strategy '{profile.strategy_id}' not found")
            row.name = profile.name
            row.active_version_id = profile.active_version_id
            row.updated_at = profile.updated_at
            existing_versions = {v.version_id: v for v in row.versions}
            for version in profile.versions:
                existing = existing_versions.get(version.version_id)
                if existing is not None:
                    existing.description = version.description
                    existing.state = version.state.value
                    existing.sandbox_result = (
                        version.sandbox_result.model_dump(mode="json")
                        if version.sandbox_result
                        else None
                    )
                    continue
                session.add(
                    StrategyVersionRow(
                        version_id=version.version_id,
                        strategy_id=version.strategy_id,
                        name=version.name,
                        description=version.description,
                        config=version.config.model_dump(mode="json"),
                        prompt_layers=[
                            layer.model_dump(mode="json")
                            for layer in version.prompt_layers
                        ],
                        state=version.state.value,
                        prompt_version=version.prompt_version,
                        sandbox_result=(
                            version.sandbox_result.model_dump(mode="json")
                            if version.sandbox_result
                            else None
                        ),
                        created_at=version.created_at,
                    )
                )
