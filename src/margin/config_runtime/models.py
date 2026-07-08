"""Domain-specific runtime configuration models."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from margin.agent_runtime.context_store import stable_json_hash
from margin.agent_runtime.models import AgentFlowDefinition
from margin.agent_runtime.quant_agent import QuantAgentStrategyProfile
from margin.news.models import ensure_utc, utc_now
from margin.strategy.models import ConfigLifecycle

OPEN_ENDED_VALID_TO = datetime(9999, 12, 31, tzinfo=UTC)


class AgentFlowConfigVersion(BaseModel):
    """Versioned Agent flow configuration stored in ``agent_flow_versions``."""

    model_config = ConfigDict(extra="forbid")

    version_id: str
    owner_id: str = "local-admin"
    environment: str = "development"
    lifecycle: ConfigLifecycle = ConfigLifecycle.ACTIVE
    flow_id: str
    flow_version: str
    run_type: str
    permission_mode: str
    step_graph_json: dict[str, Any]
    artifact_contract_json: dict[str, Any]
    valid_from: datetime
    valid_to: datetime = OPEN_ENDED_VALID_TO
    is_current: bool = True
    available_at: datetime
    payload_hash: str
    created_at: datetime = Field(default_factory=utc_now)
    created_by: str = "system"
    change_reason: str = ""
    supersedes_version_id: str | None = None
    idempotency_key: str = ""

    @field_validator("valid_from", "valid_to", "available_at", "created_at")
    @classmethod
    def normalize_datetime(cls, value: datetime) -> datetime:
        """Normalize timestamps to UTC."""
        return ensure_utc(value)

    @classmethod
    def from_flow(
        cls,
        *,
        version_id: str,
        flow: AgentFlowDefinition,
        valid_from: datetime,
        available_at: datetime,
        valid_to: datetime = OPEN_ENDED_VALID_TO,
        owner_id: str = "local-admin",
        environment: str = "development",
        lifecycle: ConfigLifecycle = ConfigLifecycle.ACTIVE,
        is_current: bool = True,
        created_by: str = "system",
        change_reason: str = "",
        supersedes_version_id: str | None = None,
        idempotency_key: str = "",
    ) -> AgentFlowConfigVersion:
        """Build a config version from an AgentFlowDefinition."""
        step_graph = {
            "flow": flow.model_dump(mode="json"),
            "dependency_waves": [
                [step.step_id for step in wave] for wave in flow.dependency_waves()
            ],
        }
        artifact_contract = {
            step.step_id: {
                "required_artifacts": list(step.required_artifacts),
                "produced_artifacts": list(step.produced_artifacts),
            }
            for step in flow.steps
        }
        payload_hash = stable_json_hash(
            {
                "flow_id": flow.flow_id,
                "flow_version": flow.version,
                "run_type": flow.run_type.value,
                "permission_mode": flow.permission_mode.value,
                "step_graph_json": step_graph,
                "artifact_contract_json": artifact_contract,
            }
        )
        return cls(
            version_id=version_id,
            owner_id=owner_id,
            environment=environment,
            lifecycle=lifecycle,
            flow_id=flow.flow_id,
            flow_version=flow.version,
            run_type=flow.run_type.value,
            permission_mode=flow.permission_mode.value,
            step_graph_json=step_graph,
            artifact_contract_json=artifact_contract,
            valid_from=valid_from,
            valid_to=valid_to,
            is_current=is_current,
            available_at=available_at,
            payload_hash=payload_hash,
            created_by=created_by,
            change_reason=change_reason,
            supersedes_version_id=supersedes_version_id,
            idempotency_key=idempotency_key,
        )

    def to_flow(self) -> AgentFlowDefinition:
        """Return the typed Agent flow definition."""
        return AgentFlowDefinition.model_validate(self.step_graph_json["flow"])


class QuantAgentProfileConfigVersion(BaseModel):
    """Versioned QuantAgent profile stored in ``quant_agent_profile_versions``."""

    model_config = ConfigDict(extra="forbid")

    version_id: str
    owner_id: str = "local-admin"
    environment: str = "development"
    lifecycle: ConfigLifecycle = ConfigLifecycle.ACTIVE
    profile_key: str
    profile_id: str
    strategy_family: str
    strategy_version: str
    model_family: str
    candidate_universe: str
    score_name: str
    top_n: int
    score_temperature: float
    max_stock_exposure: float
    min_cash: float
    exposure_mode: str
    daily_stop_loss: float
    daily_drawdown_stop: float
    cash_annual: float
    required_feature_groups: tuple[str, ...]
    valid_from: datetime
    valid_to: datetime = OPEN_ENDED_VALID_TO
    is_current: bool = True
    available_at: datetime
    payload_hash: str
    created_at: datetime = Field(default_factory=utc_now)
    created_by: str = "system"
    change_reason: str = ""
    supersedes_version_id: str | None = None
    idempotency_key: str = ""

    @field_validator("valid_from", "valid_to", "available_at", "created_at")
    @classmethod
    def normalize_datetime(cls, value: datetime) -> datetime:
        """Normalize timestamps to UTC."""
        return ensure_utc(value)

    @classmethod
    def from_profile(
        cls,
        *,
        version_id: str,
        profile_key: str,
        profile: QuantAgentStrategyProfile,
        valid_from: datetime,
        available_at: datetime,
        valid_to: datetime = OPEN_ENDED_VALID_TO,
        owner_id: str = "local-admin",
        environment: str = "development",
        lifecycle: ConfigLifecycle = ConfigLifecycle.ACTIVE,
        is_current: bool = True,
        created_by: str = "system",
        change_reason: str = "",
        supersedes_version_id: str | None = None,
        idempotency_key: str = "",
    ) -> QuantAgentProfileConfigVersion:
        """Build a config version from a QuantAgentStrategyProfile."""
        payload = {
            "profile_key": profile_key,
            "profile": profile.to_metadata(),
        }
        return cls(
            version_id=version_id,
            owner_id=owner_id,
            environment=environment,
            lifecycle=lifecycle,
            profile_key=profile_key,
            profile_id=profile.profile_id,
            strategy_family=profile.strategy_family,
            strategy_version=profile.strategy_version,
            model_family=profile.model_family,
            candidate_universe=profile.candidate_universe,
            score_name=profile.score_name,
            top_n=profile.top_n,
            score_temperature=profile.score_temperature,
            max_stock_exposure=profile.max_stock_exposure,
            min_cash=profile.min_cash,
            exposure_mode=profile.exposure_mode,
            daily_stop_loss=profile.daily_stop_loss,
            daily_drawdown_stop=profile.daily_drawdown_stop,
            cash_annual=profile.cash_annual,
            required_feature_groups=profile.required_feature_groups,
            valid_from=valid_from,
            valid_to=valid_to,
            is_current=is_current,
            available_at=available_at,
            payload_hash=stable_json_hash(payload),
            created_by=created_by,
            change_reason=change_reason,
            supersedes_version_id=supersedes_version_id,
            idempotency_key=idempotency_key,
        )

    def to_profile(self) -> QuantAgentStrategyProfile:
        """Return the typed QuantAgent strategy profile."""
        return QuantAgentStrategyProfile(
            profile_id=self.profile_id,
            strategy_family=self.strategy_family,
            strategy_version=self.strategy_version,
            model_family=self.model_family,
            candidate_universe=self.candidate_universe,
            score_name=self.score_name,
            top_n=self.top_n,
            score_temperature=self.score_temperature,
            max_stock_exposure=self.max_stock_exposure,
            min_cash=self.min_cash,
            exposure_mode=self.exposure_mode,
            daily_stop_loss=self.daily_stop_loss,
            daily_drawdown_stop=self.daily_drawdown_stop,
            cash_annual=self.cash_annual,
            required_feature_groups=self.required_feature_groups,
        )


class ConfigReference(BaseModel):
    """A resolved domain config reference stored in a run snapshot."""

    model_config = ConfigDict(extra="forbid")

    domain: str
    config_key: str
    version_id: str
    payload_hash: str

    @classmethod
    def from_version(
        cls,
        domain: str,
        version: AgentFlowConfigVersion | QuantAgentProfileConfigVersion,
    ) -> ConfigReference:
        """Build a reference from one resolved domain config version."""
        config_key = (
            version.flow_id
            if isinstance(version, AgentFlowConfigVersion)
            else version.profile_key
        )
        return cls(
            domain=domain,
            config_key=config_key,
            version_id=version.version_id,
            payload_hash=version.payload_hash,
        )


class ConfigResolutionSnapshotEntry(ConfigReference):
    """One resolved config entry in a runtime snapshot."""

    snapshot_id: str


class ConfigResolutionSnapshot(BaseModel):
    """Resolved runtime configuration lineage for one run."""

    model_config = ConfigDict(extra="forbid")

    snapshot_id: str
    run_id: str
    owner_id: str = "local-admin"
    environment: str = "development"
    decision_at: datetime
    created_at: datetime = Field(default_factory=utc_now)
    entries: tuple[ConfigResolutionSnapshotEntry, ...]

    @field_validator("decision_at", "created_at")
    @classmethod
    def normalize_datetime(cls, value: datetime) -> datetime:
        """Normalize timestamps to UTC."""
        return ensure_utc(value)
