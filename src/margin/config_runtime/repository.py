"""Repository, resolver, and admin services for runtime config versions."""

from __future__ import annotations

from datetime import datetime
from typing import Protocol

from sqlalchemy import select

from margin.agent_runtime.context_store import stable_json_hash
from margin.config_runtime.db_models import (
    AgentFlowVersionRow,
    ConfigResolutionSnapshotEntryRow,
    ConfigResolutionSnapshotRow,
    QuantAgentProfileVersionRow,
)
from margin.config_runtime.models import (
    AgentFlowConfigVersion,
    ConfigReference,
    ConfigResolutionSnapshot,
    ConfigResolutionSnapshotEntry,
    QuantAgentProfileConfigVersion,
)
from margin.news.models import ensure_utc
from margin.strategy.models import ConfigLifecycle


class ConfigRepository(Protocol):
    """Persistence boundary for domain-specific runtime config tables."""

    def save_agent_flow(self, version: AgentFlowConfigVersion) -> AgentFlowConfigVersion:
        """Persist one Agent flow version."""

    def resolve_agent_flow(
        self,
        *,
        flow_id: str,
        owner_id: str,
        environment: str,
        decision_at: datetime,
    ) -> AgentFlowConfigVersion:
        """Resolve one active Agent flow version at a decision time."""

    def save_quant_agent_profile(
        self,
        version: QuantAgentProfileConfigVersion,
    ) -> QuantAgentProfileConfigVersion:
        """Persist one QuantAgent profile version."""

    def resolve_quant_agent_profile(
        self,
        *,
        profile_key: str,
        owner_id: str,
        environment: str,
        decision_at: datetime,
    ) -> QuantAgentProfileConfigVersion:
        """Resolve one active QuantAgent profile version at a decision time."""

    def save_resolution_snapshot(
        self,
        snapshot: ConfigResolutionSnapshot,
    ) -> ConfigResolutionSnapshot:
        """Persist one config resolution snapshot."""

    def get_resolution_snapshot(self, snapshot_id: str) -> ConfigResolutionSnapshot:
        """Return one config resolution snapshot."""


class ConfigAdminService:
    """Write-side facade for versioned runtime configuration."""

    def __init__(self, repository: ConfigRepository) -> None:
        """Initialize the admin service."""
        self._repository = repository

    def publish_agent_flow(
        self,
        version: AgentFlowConfigVersion,
    ) -> AgentFlowConfigVersion:
        """Publish one Agent flow version."""
        return self._repository.save_agent_flow(version)

    def publish_quant_agent_profile(
        self,
        version: QuantAgentProfileConfigVersion,
    ) -> QuantAgentProfileConfigVersion:
        """Publish one QuantAgent profile version."""
        return self._repository.save_quant_agent_profile(version)


class ConfigResolver:
    """Read-side facade for runtime configuration resolution."""

    def __init__(
        self,
        repository: ConfigRepository,
        *,
        owner_id: str = "local-admin",
        environment: str = "development",
    ) -> None:
        """Initialize the resolver."""
        self._repository = repository
        self._owner_id = owner_id
        self._environment = environment

    def resolve_agent_flow(
        self,
        *,
        flow_id: str,
        decision_at: datetime,
        owner_id: str | None = None,
        environment: str | None = None,
    ) -> AgentFlowConfigVersion:
        """Resolve an Agent flow version through the unified read entrance."""
        return self._repository.resolve_agent_flow(
            flow_id=flow_id,
            owner_id=owner_id or self._owner_id,
            environment=environment or self._environment,
            decision_at=decision_at,
        )

    def resolve_quant_agent_profile(
        self,
        *,
        profile_key: str,
        decision_at: datetime,
        owner_id: str | None = None,
        environment: str | None = None,
    ) -> QuantAgentProfileConfigVersion:
        """Resolve a QuantAgent profile version through the unified read entrance."""
        return self._repository.resolve_quant_agent_profile(
            profile_key=profile_key,
            owner_id=owner_id or self._owner_id,
            environment=environment or self._environment,
            decision_at=decision_at,
        )

    def create_resolution_snapshot(
        self,
        *,
        run_id: str,
        decision_at: datetime,
        references: tuple[ConfigReference, ...],
        owner_id: str | None = None,
        environment: str | None = None,
    ) -> ConfigResolutionSnapshot:
        """Persist the config versions used by one run."""
        snapshot_id = _snapshot_id(
            run_id=run_id,
            decision_at=decision_at,
            owner_id=owner_id or self._owner_id,
            environment=environment or self._environment,
            references=references,
        )
        snapshot = ConfigResolutionSnapshot(
            snapshot_id=snapshot_id,
            run_id=run_id,
            owner_id=owner_id or self._owner_id,
            environment=environment or self._environment,
            decision_at=decision_at,
            entries=tuple(
                ConfigResolutionSnapshotEntry(
                    snapshot_id=snapshot_id,
                    **reference.model_dump(),
                )
                for reference in references
            ),
        )
        return self._repository.save_resolution_snapshot(snapshot)


class MemoryConfigRepository:
    """In-memory runtime config repository for deterministic tests."""

    def __init__(self) -> None:
        """Initialize empty stores."""
        self._agent_flows: dict[str, AgentFlowConfigVersion] = {}
        self._quant_profiles: dict[str, QuantAgentProfileConfigVersion] = {}
        self._snapshots: dict[str, ConfigResolutionSnapshot] = {}

    def save_agent_flow(self, version: AgentFlowConfigVersion) -> AgentFlowConfigVersion:
        """Persist one Agent flow version."""
        self._ensure_new(version.version_id, self._agent_flows)
        self._agent_flows[version.version_id] = version
        return version

    def resolve_agent_flow(
        self,
        *,
        flow_id: str,
        owner_id: str,
        environment: str,
        decision_at: datetime,
    ) -> AgentFlowConfigVersion:
        """Resolve one active Agent flow version."""
        return _select_one(
            (
                version
                for version in self._agent_flows.values()
                if version.flow_id == flow_id
                and version.owner_id == owner_id
                and version.environment == environment
            ),
            decision_at=decision_at,
            label=f"agent flow {flow_id}",
        )

    def save_quant_agent_profile(
        self,
        version: QuantAgentProfileConfigVersion,
    ) -> QuantAgentProfileConfigVersion:
        """Persist one QuantAgent profile version."""
        self._ensure_new(version.version_id, self._quant_profiles)
        self._quant_profiles[version.version_id] = version
        return version

    def resolve_quant_agent_profile(
        self,
        *,
        profile_key: str,
        owner_id: str,
        environment: str,
        decision_at: datetime,
    ) -> QuantAgentProfileConfigVersion:
        """Resolve one active QuantAgent profile version."""
        return _select_one(
            (
                version
                for version in self._quant_profiles.values()
                if version.profile_key == profile_key
                and version.owner_id == owner_id
                and version.environment == environment
            ),
            decision_at=decision_at,
            label=f"quant agent profile {profile_key}",
        )

    def save_resolution_snapshot(
        self,
        snapshot: ConfigResolutionSnapshot,
    ) -> ConfigResolutionSnapshot:
        """Persist one config resolution snapshot."""
        existing = self._snapshots.get(snapshot.snapshot_id)
        if existing is not None and existing != snapshot:
            raise ValueError(f"conflicting config snapshot: {snapshot.snapshot_id}")
        self._snapshots[snapshot.snapshot_id] = snapshot
        return snapshot

    def get_resolution_snapshot(self, snapshot_id: str) -> ConfigResolutionSnapshot:
        """Return one config resolution snapshot."""
        try:
            return self._snapshots[snapshot_id]
        except KeyError as exc:
            raise KeyError(f"config snapshot not found: {snapshot_id}") from exc

    @staticmethod
    def _ensure_new(version_id: str, store: dict[str, object]) -> None:
        if version_id in store:
            raise ValueError(f"config version already exists: {version_id}")


class SQLAlchemyConfigRepository:
    """SQLAlchemy runtime config repository."""

    def __init__(self, session_factory) -> None:  # noqa: ANN001
        """Initialize with a SQLAlchemy session factory."""
        self._session_factory = session_factory

    def save_agent_flow(self, version: AgentFlowConfigVersion) -> AgentFlowConfigVersion:
        """Persist one Agent flow version."""
        with self._session_factory() as session:
            if session.get(AgentFlowVersionRow, version.version_id) is not None:
                raise ValueError(f"config version already exists: {version.version_id}")
            session.add(_agent_flow_to_row(version))
            session.commit()
        return version

    def resolve_agent_flow(
        self,
        *,
        flow_id: str,
        owner_id: str,
        environment: str,
        decision_at: datetime,
    ) -> AgentFlowConfigVersion:
        """Resolve one active Agent flow version."""
        resolved_at = ensure_utc(decision_at)
        with self._session_factory() as session:
            rows = session.scalars(
                select(AgentFlowVersionRow)
                .where(
                    AgentFlowVersionRow.flow_id == flow_id,
                    AgentFlowVersionRow.owner_id == owner_id,
                    AgentFlowVersionRow.environment == environment,
                    AgentFlowVersionRow.lifecycle == ConfigLifecycle.ACTIVE.value,
                    AgentFlowVersionRow.valid_from <= resolved_at,
                    AgentFlowVersionRow.valid_to > resolved_at,
                    AgentFlowVersionRow.available_at <= resolved_at,
                )
                .order_by(
                    AgentFlowVersionRow.valid_from.desc(),
                    AgentFlowVersionRow.created_at.desc(),
                )
            ).all()
        if not rows:
            raise LookupError(f"no active agent flow {flow_id} at {resolved_at}")
        return _agent_flow_from_row(rows[0])

    def save_quant_agent_profile(
        self,
        version: QuantAgentProfileConfigVersion,
    ) -> QuantAgentProfileConfigVersion:
        """Persist one QuantAgent profile version."""
        with self._session_factory() as session:
            if session.get(QuantAgentProfileVersionRow, version.version_id) is not None:
                raise ValueError(f"config version already exists: {version.version_id}")
            session.add(_quant_profile_to_row(version))
            session.commit()
        return version

    def resolve_quant_agent_profile(
        self,
        *,
        profile_key: str,
        owner_id: str,
        environment: str,
        decision_at: datetime,
    ) -> QuantAgentProfileConfigVersion:
        """Resolve one active QuantAgent profile version."""
        resolved_at = ensure_utc(decision_at)
        with self._session_factory() as session:
            rows = session.scalars(
                select(QuantAgentProfileVersionRow)
                .where(
                    QuantAgentProfileVersionRow.profile_key == profile_key,
                    QuantAgentProfileVersionRow.owner_id == owner_id,
                    QuantAgentProfileVersionRow.environment == environment,
                    QuantAgentProfileVersionRow.lifecycle == ConfigLifecycle.ACTIVE.value,
                    QuantAgentProfileVersionRow.valid_from <= resolved_at,
                    QuantAgentProfileVersionRow.valid_to > resolved_at,
                    QuantAgentProfileVersionRow.available_at <= resolved_at,
                )
                .order_by(
                    QuantAgentProfileVersionRow.valid_from.desc(),
                    QuantAgentProfileVersionRow.created_at.desc(),
                )
            ).all()
        if not rows:
            raise LookupError(
                f"no active quant agent profile {profile_key} at {resolved_at}"
            )
        return _quant_profile_from_row(rows[0])

    def save_resolution_snapshot(
        self,
        snapshot: ConfigResolutionSnapshot,
    ) -> ConfigResolutionSnapshot:
        """Persist one config resolution snapshot."""
        with self._session_factory() as session:
            existing = session.get(ConfigResolutionSnapshotRow, snapshot.snapshot_id)
            if existing is not None:
                current = self.get_resolution_snapshot(snapshot.snapshot_id)
                if current != snapshot:
                    raise ValueError(
                        f"conflicting config snapshot: {snapshot.snapshot_id}"
                    )
                return snapshot
            session.add(
                ConfigResolutionSnapshotRow(
                    snapshot_id=snapshot.snapshot_id,
                    run_id=snapshot.run_id,
                    owner_id=snapshot.owner_id,
                    environment=snapshot.environment,
                    decision_at=snapshot.decision_at,
                    created_at=snapshot.created_at,
                )
            )
            session.flush()
            for index, entry in enumerate(snapshot.entries):
                session.add(
                    ConfigResolutionSnapshotEntryRow(
                        entry_id=f"{snapshot.snapshot_id}:{index:03d}",
                        snapshot_id=snapshot.snapshot_id,
                        domain=entry.domain,
                        config_key=entry.config_key,
                        version_id=entry.version_id,
                        payload_hash=entry.payload_hash,
                    )
                )
            session.commit()
        return snapshot

    def get_resolution_snapshot(self, snapshot_id: str) -> ConfigResolutionSnapshot:
        """Return one config resolution snapshot."""
        with self._session_factory() as session:
            row = session.get(ConfigResolutionSnapshotRow, snapshot_id)
            if row is None:
                raise KeyError(f"config snapshot not found: {snapshot_id}")
            entries = session.scalars(
                select(ConfigResolutionSnapshotEntryRow)
                .where(ConfigResolutionSnapshotEntryRow.snapshot_id == snapshot_id)
                .order_by(ConfigResolutionSnapshotEntryRow.entry_id.asc())
            ).all()
            return ConfigResolutionSnapshot(
                snapshot_id=row.snapshot_id,
                run_id=row.run_id,
                owner_id=row.owner_id,
                environment=row.environment,
                decision_at=row.decision_at,
                created_at=row.created_at,
                entries=tuple(
                    ConfigResolutionSnapshotEntry(
                        snapshot_id=entry.snapshot_id,
                        domain=entry.domain,
                        config_key=entry.config_key,
                        version_id=entry.version_id,
                        payload_hash=entry.payload_hash,
                    )
                    for entry in entries
                ),
            )


def _select_one(
    versions,
    *,
    decision_at: datetime,
    label: str,
):
    resolved_at = ensure_utc(decision_at)
    candidates = [
        version
        for version in versions
        if version.lifecycle is ConfigLifecycle.ACTIVE
        and version.valid_from <= resolved_at < version.valid_to
        and version.available_at <= resolved_at
    ]
    if not candidates:
        raise LookupError(f"no active {label} at {resolved_at}")
    return sorted(candidates, key=lambda item: (item.valid_from, item.created_at))[-1]


def _snapshot_id(
    *,
    run_id: str,
    decision_at: datetime,
    owner_id: str,
    environment: str,
    references: tuple[ConfigReference, ...],
) -> str:
    payload_hash = stable_json_hash(
        {
            "run_id": run_id,
            "decision_at": ensure_utc(decision_at).isoformat(),
            "owner_id": owner_id,
            "environment": environment,
            "references": [reference.model_dump() for reference in references],
        }
    )
    return "crs_" + payload_hash.removeprefix("sha256:")[:24]


def _agent_flow_to_row(version: AgentFlowConfigVersion) -> AgentFlowVersionRow:
    return AgentFlowVersionRow(
        version_id=version.version_id,
        owner_id=version.owner_id,
        environment=version.environment,
        lifecycle=version.lifecycle.value,
        flow_id=version.flow_id,
        flow_version=version.flow_version,
        run_type=version.run_type,
        permission_mode=version.permission_mode,
        step_graph_json=version.step_graph_json,
        artifact_contract_json=version.artifact_contract_json,
        valid_from=version.valid_from,
        valid_to=version.valid_to,
        is_current=version.is_current,
        available_at=version.available_at,
        payload_hash=version.payload_hash,
        created_at=version.created_at,
        created_by=version.created_by,
        change_reason=version.change_reason,
        supersedes_version_id=version.supersedes_version_id,
        idempotency_key=version.idempotency_key,
    )


def _agent_flow_from_row(row: AgentFlowVersionRow) -> AgentFlowConfigVersion:
    return AgentFlowConfigVersion(
        version_id=row.version_id,
        owner_id=row.owner_id,
        environment=row.environment,
        lifecycle=ConfigLifecycle(row.lifecycle),
        flow_id=row.flow_id,
        flow_version=row.flow_version,
        run_type=row.run_type,
        permission_mode=row.permission_mode,
        step_graph_json=row.step_graph_json,
        artifact_contract_json=row.artifact_contract_json,
        valid_from=row.valid_from,
        valid_to=row.valid_to,
        is_current=row.is_current,
        available_at=row.available_at,
        payload_hash=row.payload_hash,
        created_at=row.created_at,
        created_by=row.created_by,
        change_reason=row.change_reason,
        supersedes_version_id=row.supersedes_version_id,
        idempotency_key=row.idempotency_key,
    )


def _quant_profile_to_row(
    version: QuantAgentProfileConfigVersion,
) -> QuantAgentProfileVersionRow:
    return QuantAgentProfileVersionRow(
        version_id=version.version_id,
        owner_id=version.owner_id,
        environment=version.environment,
        lifecycle=version.lifecycle.value,
        profile_key=version.profile_key,
        profile_id=version.profile_id,
        strategy_family=version.strategy_family,
        strategy_version=version.strategy_version,
        model_family=version.model_family,
        candidate_universe=version.candidate_universe,
        score_name=version.score_name,
        top_n=version.top_n,
        score_temperature=version.score_temperature,
        max_stock_exposure=version.max_stock_exposure,
        min_cash=version.min_cash,
        exposure_mode=version.exposure_mode,
        daily_stop_loss=version.daily_stop_loss,
        daily_drawdown_stop=version.daily_drawdown_stop,
        cash_annual=version.cash_annual,
        required_feature_groups=list(version.required_feature_groups),
        valid_from=version.valid_from,
        valid_to=version.valid_to,
        is_current=version.is_current,
        available_at=version.available_at,
        payload_hash=version.payload_hash,
        created_at=version.created_at,
        created_by=version.created_by,
        change_reason=version.change_reason,
        supersedes_version_id=version.supersedes_version_id,
        idempotency_key=version.idempotency_key,
    )


def _quant_profile_from_row(
    row: QuantAgentProfileVersionRow,
) -> QuantAgentProfileConfigVersion:
    return QuantAgentProfileConfigVersion(
        version_id=row.version_id,
        owner_id=row.owner_id,
        environment=row.environment,
        lifecycle=ConfigLifecycle(row.lifecycle),
        profile_key=row.profile_key,
        profile_id=row.profile_id,
        strategy_family=row.strategy_family,
        strategy_version=row.strategy_version,
        model_family=row.model_family,
        candidate_universe=row.candidate_universe,
        score_name=row.score_name,
        top_n=row.top_n,
        score_temperature=row.score_temperature,
        max_stock_exposure=row.max_stock_exposure,
        min_cash=row.min_cash,
        exposure_mode=row.exposure_mode,
        daily_stop_loss=row.daily_stop_loss,
        daily_drawdown_stop=row.daily_drawdown_stop,
        cash_annual=row.cash_annual,
        required_feature_groups=tuple(row.required_feature_groups),
        valid_from=row.valid_from,
        valid_to=row.valid_to,
        is_current=row.is_current,
        available_at=row.available_at,
        payload_hash=row.payload_hash,
        created_at=row.created_at,
        created_by=row.created_by,
        change_reason=row.change_reason,
        supersedes_version_id=row.supersedes_version_id,
        idempotency_key=row.idempotency_key,
    )
