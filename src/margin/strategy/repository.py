"""Strategy persistence repositories."""

from __future__ import annotations

import uuid
from collections.abc import Callable, Iterable
from typing import Protocol, TypeVar

from sqlalchemy.orm import Session

from margin.news.models import utc_now
from margin.sql.strategy_queries import (
    active_indicator_views_by_owner,
    active_provider_configs_by_owner,
    active_quant_feature_sets_by_owner,
    active_quant_strategies_by_owner_and_family,
    active_research_scopes_by_owner,
    active_tool_policies_by_owner,
    active_universe_definitions_by_owner,
    active_user_style_prompts_by_owner_and_name,
    config_audit_by_replay_key,
    indicator_views_by_owner,
    insert_config_audit,
    provider_configs_by_owner,
    quant_feature_sets_by_owner,
    quant_strategies_by_owner,
    research_scopes_by_owner,
    universe_definitions_by_owner,
    user_style_prompts_by_owner,
)
from margin.strategy.db_models import (
    IndicatorViewVersionRow,
    ProviderConfigVersionRow,
    QuantFeatureSetVersionRow,
    QuantStrategyVersionRow,
    ResearchScopeVersionRow,
    StrategyConfigAuditRow,
    StrategyProfileRow,
    StrategyVersionRow,
    ToolPolicyVersionRow,
    UniverseDefinitionVersionRow,
    UserStylePromptVersionRow,
)
from margin.strategy.models import (
    ConfigLifecycle,
    IndicatorSelectionMode,
    IndicatorViewVersion,
    PromptLayer,
    ProviderConfigVersion,
    QuantFeatureSetVersion,
    QuantStrategyVersion,
    ResearchScopeVersion,
    StrategyConfig,
    StrategyProfile,
    StrategySandboxResult,
    StrategyState,
    StrategyVersion,
    ToolPolicyVersionRef,
    UniverseDefinitionVersion,
    UserStylePromptVersion,
)
from margin.strategy.provider_router import provider_category_for_config

T = TypeVar("T")


class StrategyRepository(Protocol):
    """Persistence contract consumed by :class:`StrategyService`.."""

    def add_profile(self, profile: StrategyProfile) -> None:
        """Persist a new strategy profile.

        Args:
            profile: StrategyProfile: .

        Returns:
            None: .
        """

    def get_profile(self, strategy_id: str) -> StrategyProfile | None:
        """Return a profile by identifier.

        Args:
            strategy_id: str: .

        Returns:
            StrategyProfile | None: .
        """

    def list_profiles(self, owner_id: str) -> list[StrategyProfile]:
        """Return all profiles owned by the given user.

        Args:
            owner_id: str: .

        Returns:
            list[StrategyProfile]: .
        """

    def update_profile(self, profile: StrategyProfile) -> None:
        """Persist an updated profile, replacing the existing one.

        Args:
            profile: StrategyProfile: .

        Returns:
            None: .
        """


class MemoryStrategyRepository:
    """In-memory strategy repository for tests and local usage.."""

    def __init__(self) -> None:
        """Initialize an empty in-memory profile store.

        Returns:
            None: .
        """
        self._profiles: dict[str, StrategyProfile] = {}
        self._provider_configs: dict[str, ProviderConfigVersion] = {}
        self._universes: dict[str, UniverseDefinitionVersion] = {}
        self._indicator_views: dict[str, IndicatorViewVersion] = {}
        self._quant_feature_sets: dict[str, QuantFeatureSetVersion] = {}
        self._quant_strategies: dict[str, QuantStrategyVersion] = {}
        self._style_prompts: dict[str, UserStylePromptVersion] = {}
        self._tool_policies: dict[str, ToolPolicyVersionRef] = {}
        self._research_scopes: dict[str, ResearchScopeVersion] = {}
        self._config_audits: dict[
            tuple[str, str, str],
            dict[str, object],
        ] = {}

    def add_profile(self, profile: StrategyProfile) -> None:
        """Persist a new strategy profile in memory.

        Args:
            profile: StrategyProfile: .

        Returns:
            None: .
        """
        if profile.strategy_id in self._profiles:
            raise ValueError(f"strategy '{profile.strategy_id}' already exists")
        self._profiles[profile.strategy_id] = profile

    def get_profile(self, strategy_id: str) -> StrategyProfile | None:
        """Return a profile by identifier.

        Args:
            strategy_id: str: .

        Returns:
            StrategyProfile | None: .
        """
        return self._profiles.get(strategy_id)

    def list_profiles(self, owner_id: str) -> list[StrategyProfile]:
        """Return all profiles owned by the given user.

        Args:
            owner_id: str: .

        Returns:
            list[StrategyProfile]: .
        """
        return [profile for profile in self._profiles.values() if profile.owner_id == owner_id]

    def update_profile(self, profile: StrategyProfile) -> None:
        """Persist an updated profile, replacing the existing one.

        Args:
            profile: StrategyProfile: .

        Returns:
            None: .
        """
        if profile.strategy_id not in self._profiles:
            raise KeyError(f"strategy '{profile.strategy_id}' not found")
        self._profiles[profile.strategy_id] = profile

    def save_provider_config(self, version: ProviderConfigVersion) -> None:
        """Append a provider configuration version.

        Args:
            version: ProviderConfigVersion: .

        Returns:
            None: .
        """
        _ensure_new(self._provider_configs, version.version_id, "provider config")
        self._provider_configs[version.version_id] = version

    def get_provider_config(self, version_id: str) -> ProviderConfigVersion | None:
        """Return a provider configuration version.

        Args:
            version_id: str: .

        Returns:
            ProviderConfigVersion | None: .
        """
        return self._provider_configs.get(version_id)

    def list_provider_configs(self, owner_id: str) -> list[ProviderConfigVersion]:
        """List provider configuration versions for an owner.

        Args:
            owner_id: str: .

        Returns:
            list[ProviderConfigVersion]: .
        """
        return _sorted_versions(
            version for version in self._provider_configs.values() if version.owner_id == owner_id
        )

    def list_active_provider_configs(self, owner_id: str) -> list[ProviderConfigVersion]:
        """List enabled active provider configuration versions for an owner.

        Args:
            owner_id: str: .

        Returns:
            list[ProviderConfigVersion]: .
        """
        return [
            version
            for version in self.list_provider_configs(owner_id)
            if version.lifecycle is ConfigLifecycle.ACTIVE and version.enabled
        ]

    def attach_provider_secret(
        self,
        version_id: str,
        secret_version_id: str,
    ) -> ProviderConfigVersion:
        """Bind a secret version to a non-active provider config.

        Args:
            version_id: str: .
            secret_version_id: str: .

        Returns:
            ProviderConfigVersion: .
        """
        version = self._must_get(self._provider_configs, version_id, "provider config")
        if version.lifecycle is ConfigLifecycle.ACTIVE:
            raise ValueError("active provider config is immutable; create a new config version")
        updated = version.model_copy(update={"secret_version_id": secret_version_id})
        self._provider_configs[version_id] = updated
        return updated

    def activate_provider_config(self, version_id: str) -> ProviderConfigVersion:
        """Activate a provider config and deprecate older active sibling versions.

        Args:
            version_id: str: .

        Returns:
            ProviderConfigVersion: .
        """
        version = self._must_get(self._provider_configs, version_id, "provider config")
        self._deprecate_provider_configs(version)
        activated = version.model_copy(update={"lifecycle": ConfigLifecycle.ACTIVE})
        self._provider_configs[version_id] = activated
        return activated

    def save_universe_definition(self, version: UniverseDefinitionVersion) -> None:
        """Append a universe definition version.

        Args:
            version: UniverseDefinitionVersion: .

        Returns:
            None: .
        """
        _ensure_new(self._universes, version.version_id, "universe")
        self._universes[version.version_id] = version

    def get_universe_definition(self, version_id: str) -> UniverseDefinitionVersion | None:
        """Return a universe definition version.

        Args:
            version_id: str: .

        Returns:
            UniverseDefinitionVersion | None: .
        """
        return self._universes.get(version_id)

    def list_active_universe_definitions(
        self,
        owner_id: str,
        *,
        universe_code: str | None = None,
    ) -> list[UniverseDefinitionVersion]:
        """List active universe definitions for an owner.

        Args:
            owner_id: str: .
            universe_code: str | None: .

        Returns:
            list[UniverseDefinitionVersion]: .
        """
        versions = [
            version
            for version in self._universes.values()
            if version.owner_id == owner_id and version.lifecycle is ConfigLifecycle.ACTIVE
        ]
        if universe_code is not None:
            versions = [version for version in versions if version.universe_code == universe_code]
        return _sorted_versions(versions)

    def list_universe_definitions(self, owner_id: str) -> list[UniverseDefinitionVersion]:
        """List all universe definition versions for an owner.

        Args:
            owner_id: str: .

        Returns:
            list[UniverseDefinitionVersion]: .
        """
        return _sorted_versions(
            version for version in self._universes.values() if version.owner_id == owner_id
        )

    def activate_universe_definition(
        self,
        version_id: str,
    ) -> UniverseDefinitionVersion:
        """Activate a universe and deprecate the prior active family version.

        Args:
            version_id: str: .

        Returns:
            UniverseDefinitionVersion: .
        """
        version = self._must_get(self._universes, version_id, "universe")
        for candidate in list(self._universes.values()):
            if (
                candidate.owner_id == version.owner_id
                and candidate.universe_code == version.universe_code
                and candidate.lifecycle is ConfigLifecycle.ACTIVE
            ):
                self._universes[candidate.version_id] = candidate.model_copy(
                    update={"lifecycle": ConfigLifecycle.DEPRECATED}
                )
        activated = version.model_copy(update={"lifecycle": ConfigLifecycle.ACTIVE})
        self._universes[version_id] = activated
        return activated

    def save_indicator_view(self, version: IndicatorViewVersion) -> None:
        """Append an indicator view version.

        Args:
            version: IndicatorViewVersion: .

        Returns:
            None: .
        """
        _ensure_new(self._indicator_views, version.version_id, "indicator view")
        self._indicator_views[version.version_id] = version

    def get_indicator_view(self, version_id: str) -> IndicatorViewVersion | None:
        """Return an indicator view version.

        Args:
            version_id: str: .

        Returns:
            IndicatorViewVersion | None: .
        """
        return self._indicator_views.get(version_id)

    def get_active_indicator_view(self, owner_id: str) -> IndicatorViewVersion | None:
        """Return the active indicator view for an owner.

        Args:
            owner_id: str: .

        Returns:
            IndicatorViewVersion | None: .
        """
        return _single_or_none(
            version
            for version in self._indicator_views.values()
            if version.owner_id == owner_id and version.lifecycle is ConfigLifecycle.ACTIVE
        )

    def list_indicator_views(self, owner_id: str) -> list[IndicatorViewVersion]:
        """List all indicator view versions for an owner.

        Args:
            owner_id: str: .

        Returns:
            list[IndicatorViewVersion]: .
        """
        return _sorted_versions(
            version for version in self._indicator_views.values() if version.owner_id == owner_id
        )

    def activate_indicator_view(self, version_id: str) -> IndicatorViewVersion:
        """Activate an indicator view and deprecate the prior active version.

        Args:
            version_id: str: .

        Returns:
            IndicatorViewVersion: .
        """
        version = self._must_get(self._indicator_views, version_id, "indicator view")
        for candidate in list(self._indicator_views.values()):
            if (
                candidate.owner_id == version.owner_id
                and candidate.lifecycle is ConfigLifecycle.ACTIVE
            ):
                self._indicator_views[candidate.version_id] = candidate.model_copy(
                    update={"lifecycle": ConfigLifecycle.DEPRECATED}
                )
        activated = version.model_copy(update={"lifecycle": ConfigLifecycle.ACTIVE})
        self._indicator_views[version_id] = activated
        return activated

    def save_quant_feature_set(self, version: QuantFeatureSetVersion) -> None:
        """Append a quant feature set version.

        Args:
            version: QuantFeatureSetVersion: .

        Returns:
            None: .
        """
        _ensure_new(self._quant_feature_sets, version.version_id, "quant feature set")
        self._quant_feature_sets[version.version_id] = version

    def get_quant_feature_set(self, version_id: str) -> QuantFeatureSetVersion | None:
        """Return a quant feature set version.

        Args:
            version_id: str: .

        Returns:
            QuantFeatureSetVersion | None: .
        """
        return self._quant_feature_sets.get(version_id)

    def get_active_quant_feature_set(self, owner_id: str) -> QuantFeatureSetVersion | None:
        """Return the active quant feature set for an owner.

        Args:
            owner_id: str: .

        Returns:
            QuantFeatureSetVersion | None: .
        """
        return _single_or_none(
            version
            for version in self._quant_feature_sets.values()
            if version.owner_id == owner_id and version.lifecycle is ConfigLifecycle.ACTIVE
        )

    def list_quant_feature_sets(self, owner_id: str) -> list[QuantFeatureSetVersion]:
        """List all quant feature set versions for an owner.

        Args:
            owner_id: str: .

        Returns:
            list[QuantFeatureSetVersion]: .
        """
        return _sorted_versions(
            version for version in self._quant_feature_sets.values() if version.owner_id == owner_id
        )

    def activate_quant_feature_set(
        self,
        version_id: str,
    ) -> QuantFeatureSetVersion:
        """Activate a quant feature set and deprecate the prior active version.

        Args:
            version_id: str: .

        Returns:
            QuantFeatureSetVersion: .
        """
        version = self._must_get(
            self._quant_feature_sets,
            version_id,
            "quant feature set",
        )
        for candidate in list(self._quant_feature_sets.values()):
            if (
                candidate.owner_id == version.owner_id
                and candidate.lifecycle is ConfigLifecycle.ACTIVE
            ):
                self._quant_feature_sets[candidate.version_id] = candidate.model_copy(
                    update={"lifecycle": ConfigLifecycle.DEPRECATED}
                )
        activated = version.model_copy(update={"lifecycle": ConfigLifecycle.ACTIVE})
        self._quant_feature_sets[version_id] = activated
        return activated

    def save_quant_strategy(self, version: QuantStrategyVersion) -> None:
        """Append a quant strategy version.

        Args:
            version: QuantStrategyVersion: .

        Returns:
            None: .
        """
        _ensure_new(self._quant_strategies, version.version_id, "quant strategy")
        self._quant_strategies[version.version_id] = version

    def get_quant_strategy(self, version_id: str) -> QuantStrategyVersion | None:
        """Return a quant strategy version.

        Args:
            version_id: str: .

        Returns:
            QuantStrategyVersion | None: .
        """
        return self._quant_strategies.get(version_id)

    def get_active_quant_strategy(
        self,
        owner_id: str,
        *,
        strategy_family: str = "default",
    ) -> QuantStrategyVersion | None:
        """Return the active quant strategy for an owner and family.

        Args:
            owner_id: str: .
            strategy_family: str: .

        Returns:
            QuantStrategyVersion | None: .
        """
        return _single_or_none(
            version
            for version in self._quant_strategies.values()
            if version.owner_id == owner_id
            and version.strategy_family == strategy_family
            and version.lifecycle is ConfigLifecycle.ACTIVE
        )

    def list_quant_strategies(self, owner_id: str) -> list[QuantStrategyVersion]:
        """List all quant strategy versions for an owner.

        Args:
            owner_id: str: .

        Returns:
            list[QuantStrategyVersion]: .
        """
        return _sorted_versions(
            version for version in self._quant_strategies.values() if version.owner_id == owner_id
        )

    def activate_quant_strategy(self, version_id: str) -> QuantStrategyVersion:
        """Activate a quant strategy and deprecate older active sibling versions.

        Args:
            version_id: str: .

        Returns:
            QuantStrategyVersion: .
        """
        version = self._must_get(self._quant_strategies, version_id, "quant strategy")
        for candidate in list(self._quant_strategies.values()):
            if (
                candidate.owner_id == version.owner_id
                and candidate.strategy_family == version.strategy_family
                and candidate.lifecycle is ConfigLifecycle.ACTIVE
            ):
                self._quant_strategies[candidate.version_id] = candidate.model_copy(
                    update={"lifecycle": ConfigLifecycle.DEPRECATED}
                )
        activated = version.model_copy(update={"lifecycle": ConfigLifecycle.ACTIVE})
        self._quant_strategies[version_id] = activated
        return activated

    def save_user_style_prompt(self, version: UserStylePromptVersion) -> None:
        """Append a user style prompt version.

        Args:
            version: UserStylePromptVersion: .

        Returns:
            None: .
        """
        _ensure_new(self._style_prompts, version.version_id, "style prompt")
        self._style_prompts[version.version_id] = version

    def get_user_style_prompt(self, version_id: str) -> UserStylePromptVersion | None:
        """Return a user style prompt version.

        Args:
            version_id: str: .

        Returns:
            UserStylePromptVersion | None: .
        """
        return self._style_prompts.get(version_id)

    def get_active_user_style_prompt(
        self,
        owner_id: str,
        *,
        prompt_name: str = "default",
    ) -> UserStylePromptVersion | None:
        """Return the active user style prompt for an owner and prompt name.

        Args:
            owner_id: str: .
            prompt_name: str: .

        Returns:
            UserStylePromptVersion | None: .
        """
        return _single_or_none(
            version
            for version in self._style_prompts.values()
            if version.owner_id == owner_id
            and version.prompt_name == prompt_name
            and version.lifecycle is ConfigLifecycle.ACTIVE
        )

    def list_user_style_prompts(self, owner_id: str) -> list[UserStylePromptVersion]:
        """List all user style prompt versions for an owner.

        Args:
            owner_id: str: .

        Returns:
            list[UserStylePromptVersion]: .
        """
        return _sorted_versions(
            version for version in self._style_prompts.values() if version.owner_id == owner_id
        )

    def activate_user_style_prompt(
        self,
        version_id: str,
    ) -> UserStylePromptVersion:
        """Activate a style prompt and deprecate its prior active sibling.

        Args:
            version_id: str: .

        Returns:
            UserStylePromptVersion: .
        """
        version = self._must_get(self._style_prompts, version_id, "style prompt")
        for candidate in list(self._style_prompts.values()):
            if (
                candidate.owner_id == version.owner_id
                and candidate.prompt_name == version.prompt_name
                and candidate.lifecycle is ConfigLifecycle.ACTIVE
            ):
                self._style_prompts[candidate.version_id] = candidate.model_copy(
                    update={"lifecycle": ConfigLifecycle.DEPRECATED}
                )
        activated = version.model_copy(update={"lifecycle": ConfigLifecycle.ACTIVE})
        self._style_prompts[version_id] = activated
        return activated

    def save_tool_policy(self, version: ToolPolicyVersionRef) -> None:
        """Append a tool policy version.

        Args:
            version: ToolPolicyVersionRef: .

        Returns:
            None: .
        """
        _ensure_new(self._tool_policies, version.version_id, "tool policy")
        self._tool_policies[version.version_id] = version

    def get_tool_policy(self, version_id: str) -> ToolPolicyVersionRef | None:
        """Return a tool policy version.

        Args:
            version_id: str: .

        Returns:
            ToolPolicyVersionRef | None: .
        """
        return self._tool_policies.get(version_id)

    def get_active_tool_policy(self, owner_id: str) -> ToolPolicyVersionRef | None:
        """Return the active tool policy for an owner.

        Args:
            owner_id: str: .

        Returns:
            ToolPolicyVersionRef | None: .
        """
        return _single_or_none(
            version
            for version in self._tool_policies.values()
            if version.owner_id == owner_id and version.lifecycle is ConfigLifecycle.ACTIVE
        )

    def activate_tool_policy(self, version_id: str) -> ToolPolicyVersionRef:
        """Activate a tool policy and deprecate the prior active version.

        Args:
            version_id: str: .

        Returns:
            ToolPolicyVersionRef: .
        """
        version = self._must_get(self._tool_policies, version_id, "tool policy")
        for candidate in list(self._tool_policies.values()):
            if (
                candidate.owner_id == version.owner_id
                and candidate.lifecycle is ConfigLifecycle.ACTIVE
            ):
                self._tool_policies[candidate.version_id] = candidate.model_copy(
                    update={"lifecycle": ConfigLifecycle.DEPRECATED}
                )
        activated = version.model_copy(update={"lifecycle": ConfigLifecycle.ACTIVE})
        self._tool_policies[version_id] = activated
        return activated

    def save_research_scope(self, version: ResearchScopeVersion) -> None:
        """Append a research scope version.

        Args:
            version: ResearchScopeVersion: .

        Returns:
            None: .
        """
        _ensure_new(self._research_scopes, version.version_id, "research scope")
        self._research_scopes[version.version_id] = version

    def get_research_scope(self, version_id: str) -> ResearchScopeVersion | None:
        """Return a research scope version.

        Args:
            version_id: str: .

        Returns:
            ResearchScopeVersion | None: .
        """
        return self._research_scopes.get(version_id)

    def get_active_research_scope(self, owner_id: str) -> ResearchScopeVersion | None:
        """Return the active research scope for an owner.

        Args:
            owner_id: str: .

        Returns:
            ResearchScopeVersion | None: .
        """
        return _single_or_none(
            version
            for version in self._research_scopes.values()
            if version.owner_id == owner_id and version.lifecycle is ConfigLifecycle.ACTIVE
        )

    def list_research_scopes(self, owner_id: str) -> list[ResearchScopeVersion]:
        """List all research scope versions for an owner.

        Args:
            owner_id: str: .

        Returns:
            list[ResearchScopeVersion]: .
        """
        return _sorted_versions(
            version for version in self._research_scopes.values() if version.owner_id == owner_id
        )

    def activate_research_scope(self, version_id: str) -> ResearchScopeVersion:
        """Activate a research scope and deprecate older active scopes.

        Args:
            version_id: str: .

        Returns:
            ResearchScopeVersion: .
        """
        version = self._must_get(self._research_scopes, version_id, "research scope")
        for candidate in list(self._research_scopes.values()):
            if (
                candidate.owner_id == version.owner_id
                and candidate.lifecycle is ConfigLifecycle.ACTIVE
            ):
                self._research_scopes[candidate.version_id] = candidate.model_copy(
                    update={"lifecycle": ConfigLifecycle.DEPRECATED}
                )
        activated = version.model_copy(update={"lifecycle": ConfigLifecycle.ACTIVE})
        self._research_scopes[version_id] = activated
        return activated

    def record_config_audit(
        self,
        *,
        actor_id: str,
        resource_type: str,
        resource_version_id: str,
        action: str,
        idempotency_key: str,
        details: dict[str, object],
    ) -> dict[str, object]:
        """Append one idempotent config audit event.

        Args:
            actor_id: str: .
            resource_type: str: .
            resource_version_id: str: .
            action: str: .
            idempotency_key: str: .
            details: dict[str, object]: .

        Returns:
            dict[str, object]: .
        """
        key = (actor_id, action, idempotency_key)
        existing = self._config_audits.get(key)
        if existing is not None:
            return existing
        audit = {
            "audit_id": f"audit_{uuid.uuid4().hex[:12]}",
            "actor_id": actor_id,
            "resource_type": resource_type,
            "resource_version_id": resource_version_id,
            "action": action,
            "idempotency_key": idempotency_key,
            "details": dict(details),
            "created_at": utc_now(),
        }
        self._config_audits[key] = audit
        return audit

    def get_config_audit(
        self,
        *,
        actor_id: str,
        action: str,
        idempotency_key: str,
    ) -> dict[str, object] | None:
        """Return a prior config mutation audit by replay key.

        Args:
            actor_id: str: .
            action: str: .
            idempotency_key: str: .

        Returns:
            dict[str, object] | None: .
        """
        return self._config_audits.get((actor_id, action, idempotency_key))

    def _deprecate_provider_configs(self, version: ProviderConfigVersion) -> None:
        """deprecate provider configs.

        Args:
            version: ProviderConfigVersion: .

        Returns:
            None: .
        """
        category = provider_category_for_config(
            version.provider_type,
            version.provider_name,
            version.non_sensitive_config,
        )
        for candidate in list(self._provider_configs.values()):
            if (
                candidate.owner_id == version.owner_id
                and provider_category_for_config(
                    candidate.provider_type,
                    candidate.provider_name,
                    candidate.non_sensitive_config,
                )
                == category
                and candidate.lifecycle is ConfigLifecycle.ACTIVE
            ):
                self._provider_configs[candidate.version_id] = candidate.model_copy(
                    update={"lifecycle": ConfigLifecycle.DEPRECATED}
                )

    @staticmethod
    def _must_get(
        mapping: dict[str, object],
        version_id: str,
        resource_type: str,
    ) -> object:
        """must get.

        Args:
            mapping: dict[str, object]: .
            version_id: str: .
            resource_type: str: .

        Returns:
            object: .
        """
        version = mapping.get(version_id)
        if version is None:
            raise KeyError(f"{resource_type} '{version_id}' not found")
        return version


class SQLAlchemyStrategyRepository:
    """PostgreSQL-backed strategy repository.."""

    def __init__(self, session_factory: Callable[[], Session]) -> None:
        """Initialize the repository with a SQLAlchemy session factory.

        Args:
            session_factory: Callable[[], Session]: .

        Returns:
            None: .
        """
        self._session_factory = session_factory

    def add_profile(self, profile: StrategyProfile) -> None:
        """Persist a new strategy profile and all its versions to PostgreSQL.

        Args:
            profile: StrategyProfile: .

        Returns:
            None: .
        """
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
                            layer.model_dump(mode="json") for layer in version.prompt_layers
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
        """Return a profile by identifier, reconstructing domain models from rows.

        Args:
            strategy_id: str: .

        Returns:
            StrategyProfile | None: .
        """
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
                        PromptLayer.model_validate(layer) for layer in v.prompt_layers
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
        """Return all profiles owned by the given user.

        Args:
            owner_id: str: .

        Returns:
            list[StrategyProfile]: .
        """
        with self._session_factory() as session:
            rows = session.query(StrategyProfileRow).filter_by(owner_id=owner_id).all()
            profiles = [self.get_profile(row.strategy_id) for row in rows]
            return [profile for profile in profiles if profile is not None]

    def update_profile(self, profile: StrategyProfile) -> None:
        """Persist an updated profile and any new versions to PostgreSQL.

        Args:
            profile: StrategyProfile: .

        Returns:
            None: .
        """
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
                            layer.model_dump(mode="json") for layer in version.prompt_layers
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

    def save_provider_config(self, version: ProviderConfigVersion) -> None:
        """Append a provider configuration version.

        Args:
            version: ProviderConfigVersion: .

        Returns:
            None: .
        """
        with self._session_factory.begin() as session:
            if session.get(ProviderConfigVersionRow, version.version_id) is not None:
                raise ValueError(f"provider config '{version.version_id}' already exists")
            session.add(_provider_config_to_row(version))

    def get_provider_config(self, version_id: str) -> ProviderConfigVersion | None:
        """Return a provider configuration version.

        Args:
            version_id: str: .

        Returns:
            ProviderConfigVersion | None: .
        """
        with self._session_factory() as session:
            row = session.get(ProviderConfigVersionRow, version_id)
            return _provider_config_from_row(row) if row is not None else None

    def list_provider_configs(self, owner_id: str) -> list[ProviderConfigVersion]:
        """List provider configuration versions for an owner.

        Args:
            owner_id: str: .

        Returns:
            list[ProviderConfigVersion]: .
        """
        with self._session_factory() as session:
            rows = session.scalars(provider_configs_by_owner(owner_id)).all()
            return [_provider_config_from_row(row) for row in rows]

    def list_active_provider_configs(self, owner_id: str) -> list[ProviderConfigVersion]:
        """List enabled active provider configuration versions for an owner.

        Args:
            owner_id: str: .

        Returns:
            list[ProviderConfigVersion]: .
        """
        with self._session_factory() as session:
            rows = session.scalars(
                active_provider_configs_by_owner(owner_id, ConfigLifecycle.ACTIVE.value)
            ).all()
            return [_provider_config_from_row(row) for row in rows]

    def attach_provider_secret(
        self,
        version_id: str,
        secret_version_id: str,
    ) -> ProviderConfigVersion:
        """Bind a secret version to a non-active provider config.

        Args:
            version_id: str: .
            secret_version_id: str: .

        Returns:
            ProviderConfigVersion: .
        """
        with self._session_factory.begin() as session:
            row = session.get(ProviderConfigVersionRow, version_id)
            if row is None:
                raise KeyError(f"provider config '{version_id}' not found")
            if row.lifecycle == ConfigLifecycle.ACTIVE.value:
                raise ValueError("active provider config is immutable; create a new config version")
            row.secret_version_id = secret_version_id
            return _provider_config_from_row(row)

    def activate_provider_config(self, version_id: str) -> ProviderConfigVersion:
        """Activate a provider config and deprecate older active sibling versions.

        Args:
            version_id: str: .

        Returns:
            ProviderConfigVersion: .
        """
        with self._session_factory.begin() as session:
            row = session.get(ProviderConfigVersionRow, version_id)
            if row is None:
                raise KeyError(f"provider config '{version_id}' not found")
            category = provider_category_for_config(
                row.provider_type,
                row.provider_name,
                row.non_sensitive_config,
            )
            active_rows = session.scalars(
                active_provider_configs_by_owner(row.owner_id, ConfigLifecycle.ACTIVE.value)
            ).all()
            deprecated_existing = False
            for active in active_rows:
                active_category = provider_category_for_config(
                    active.provider_type,
                    active.provider_name,
                    active.non_sensitive_config,
                )
                if active.version_id != version_id and active_category == category:
                    active.lifecycle = ConfigLifecycle.DEPRECATED.value
                    deprecated_existing = True
            if deprecated_existing:
                session.flush()
            row.lifecycle = ConfigLifecycle.ACTIVE.value
            return _provider_config_from_row(row)

    def save_universe_definition(self, version: UniverseDefinitionVersion) -> None:
        """Append a universe definition version.

        Args:
            version: UniverseDefinitionVersion: .

        Returns:
            None: .
        """
        with self._session_factory.begin() as session:
            if session.get(UniverseDefinitionVersionRow, version.version_id) is not None:
                raise ValueError(f"universe '{version.version_id}' already exists")
            session.add(_universe_to_row(version))

    def get_universe_definition(self, version_id: str) -> UniverseDefinitionVersion | None:
        """Return a universe definition version.

        Args:
            version_id: str: .

        Returns:
            UniverseDefinitionVersion | None: .
        """
        with self._session_factory() as session:
            row = session.get(UniverseDefinitionVersionRow, version_id)
            return _universe_from_row(row) if row is not None else None

    def list_active_universe_definitions(
        self,
        owner_id: str,
        *,
        universe_code: str | None = None,
    ) -> list[UniverseDefinitionVersion]:
        """List active universe definitions for an owner.

        Args:
            owner_id: str: .
            universe_code: str | None: .

        Returns:
            list[UniverseDefinitionVersion]: .
        """
        with self._session_factory() as session:
            rows = session.scalars(
                active_universe_definitions_by_owner(
                    owner_id,
                    ConfigLifecycle.ACTIVE.value,
                    universe_code=universe_code,
                )
            ).all()
            return [_universe_from_row(row) for row in rows]

    def list_universe_definitions(self, owner_id: str) -> list[UniverseDefinitionVersion]:
        """List all universe definition versions for an owner.

        Args:
            owner_id: str: .

        Returns:
            list[UniverseDefinitionVersion]: .
        """
        with self._session_factory() as session:
            rows = session.scalars(universe_definitions_by_owner(owner_id)).all()
            return [_universe_from_row(row) for row in rows]

    def activate_universe_definition(
        self,
        version_id: str,
    ) -> UniverseDefinitionVersion:
        """Activate a universe and deprecate the prior active family version.

        Args:
            version_id: str: .

        Returns:
            UniverseDefinitionVersion: .
        """
        with self._session_factory.begin() as session:
            row = session.get(UniverseDefinitionVersionRow, version_id)
            if row is None:
                raise KeyError(f"universe '{version_id}' not found")
            active_rows = session.scalars(
                active_universe_definitions_by_owner(
                    row.owner_id,
                    ConfigLifecycle.ACTIVE.value,
                    universe_code=row.universe_code,
                )
            ).all()
            for active in active_rows:
                if active.version_id != version_id:
                    active.lifecycle = ConfigLifecycle.DEPRECATED.value
            row.lifecycle = ConfigLifecycle.ACTIVE.value
            return _universe_from_row(row)

    def save_indicator_view(self, version: IndicatorViewVersion) -> None:
        """Append an indicator view version.

        Args:
            version: IndicatorViewVersion: .

        Returns:
            None: .
        """
        with self._session_factory.begin() as session:
            if session.get(IndicatorViewVersionRow, version.version_id) is not None:
                raise ValueError(f"indicator view '{version.version_id}' already exists")
            session.add(_indicator_view_to_row(version))

    def get_indicator_view(self, version_id: str) -> IndicatorViewVersion | None:
        """Return an indicator view version.

        Args:
            version_id: str: .

        Returns:
            IndicatorViewVersion | None: .
        """
        with self._session_factory() as session:
            row = session.get(IndicatorViewVersionRow, version_id)
            return _indicator_view_from_row(row) if row is not None else None

    def get_active_indicator_view(self, owner_id: str) -> IndicatorViewVersion | None:
        """Return the active indicator view for an owner.

        Args:
            owner_id: str: .

        Returns:
            IndicatorViewVersion | None: .
        """
        with self._session_factory() as session:
            rows = session.scalars(
                active_indicator_views_by_owner(owner_id, ConfigLifecycle.ACTIVE.value)
            ).all()
            return _single_or_none(_indicator_view_from_row(row) for row in rows)

    def list_indicator_views(self, owner_id: str) -> list[IndicatorViewVersion]:
        """List all indicator view versions for an owner.

        Args:
            owner_id: str: .

        Returns:
            list[IndicatorViewVersion]: .
        """
        with self._session_factory() as session:
            rows = session.scalars(indicator_views_by_owner(owner_id)).all()
            return [_indicator_view_from_row(row) for row in rows]

    def activate_indicator_view(self, version_id: str) -> IndicatorViewVersion:
        """Activate an indicator view and deprecate the prior active version.

        Args:
            version_id: str: .

        Returns:
            IndicatorViewVersion: .
        """
        with self._session_factory.begin() as session:
            row = session.get(IndicatorViewVersionRow, version_id)
            if row is None:
                raise KeyError(f"indicator view '{version_id}' not found")
            active_rows = session.scalars(
                active_indicator_views_by_owner(row.owner_id, ConfigLifecycle.ACTIVE.value)
            ).all()
            for active in active_rows:
                if active.version_id != version_id:
                    active.lifecycle = ConfigLifecycle.DEPRECATED.value
            row.lifecycle = ConfigLifecycle.ACTIVE.value
            return _indicator_view_from_row(row)

    def save_quant_feature_set(self, version: QuantFeatureSetVersion) -> None:
        """Append a quant feature set version.

        Args:
            version: QuantFeatureSetVersion: .

        Returns:
            None: .
        """
        with self._session_factory.begin() as session:
            if session.get(QuantFeatureSetVersionRow, version.version_id) is not None:
                raise ValueError(f"quant feature set '{version.version_id}' already exists")
            session.add(_quant_feature_set_to_row(version))

    def get_quant_feature_set(self, version_id: str) -> QuantFeatureSetVersion | None:
        """Return a quant feature set version.

        Args:
            version_id: str: .

        Returns:
            QuantFeatureSetVersion | None: .
        """
        with self._session_factory() as session:
            row = session.get(QuantFeatureSetVersionRow, version_id)
            return _quant_feature_set_from_row(row) if row is not None else None

    def get_active_quant_feature_set(self, owner_id: str) -> QuantFeatureSetVersion | None:
        """Return the active quant feature set for an owner.

        Args:
            owner_id: str: .

        Returns:
            QuantFeatureSetVersion | None: .
        """
        with self._session_factory() as session:
            rows = session.scalars(
                active_quant_feature_sets_by_owner(owner_id, ConfigLifecycle.ACTIVE.value)
            ).all()
            return _single_or_none(_quant_feature_set_from_row(row) for row in rows)

    def list_quant_feature_sets(self, owner_id: str) -> list[QuantFeatureSetVersion]:
        """List all quant feature set versions for an owner.

        Args:
            owner_id: str: .

        Returns:
            list[QuantFeatureSetVersion]: .
        """
        with self._session_factory() as session:
            rows = session.scalars(quant_feature_sets_by_owner(owner_id)).all()
            return [_quant_feature_set_from_row(row) for row in rows]

    def activate_quant_feature_set(
        self,
        version_id: str,
    ) -> QuantFeatureSetVersion:
        """Activate a quant feature set and deprecate the prior active version.

        Args:
            version_id: str: .

        Returns:
            QuantFeatureSetVersion: .
        """
        with self._session_factory.begin() as session:
            row = session.get(QuantFeatureSetVersionRow, version_id)
            if row is None:
                raise KeyError(f"quant feature set '{version_id}' not found")
            active_rows = session.scalars(
                active_quant_feature_sets_by_owner(row.owner_id, ConfigLifecycle.ACTIVE.value)
            ).all()
            deprecated_existing = False
            for active in active_rows:
                if active.version_id != version_id:
                    active.lifecycle = ConfigLifecycle.DEPRECATED.value
                    deprecated_existing = True
            if deprecated_existing:
                session.flush()
            row.lifecycle = ConfigLifecycle.ACTIVE.value
            return _quant_feature_set_from_row(row)

    def save_quant_strategy(self, version: QuantStrategyVersion) -> None:
        """Append a quant strategy version.

        Args:
            version: QuantStrategyVersion: .

        Returns:
            None: .
        """
        with self._session_factory.begin() as session:
            if session.get(QuantStrategyVersionRow, version.version_id) is not None:
                raise ValueError(f"quant strategy '{version.version_id}' already exists")
            session.add(_quant_strategy_to_row(version))

    def get_quant_strategy(self, version_id: str) -> QuantStrategyVersion | None:
        """Return a quant strategy version.

        Args:
            version_id: str: .

        Returns:
            QuantStrategyVersion | None: .
        """
        with self._session_factory() as session:
            row = session.get(QuantStrategyVersionRow, version_id)
            return _quant_strategy_from_row(row) if row is not None else None

    def get_active_quant_strategy(
        self,
        owner_id: str,
        *,
        strategy_family: str = "default",
    ) -> QuantStrategyVersion | None:
        """Return the active quant strategy for an owner and family.

        Args:
            owner_id: str: .
            strategy_family: str: .

        Returns:
            QuantStrategyVersion | None: .
        """
        with self._session_factory() as session:
            rows = session.scalars(
                active_quant_strategies_by_owner_and_family(
                    owner_id,
                    strategy_family,
                    ConfigLifecycle.ACTIVE.value,
                )
            ).all()
            return _single_or_none(_quant_strategy_from_row(row) for row in rows)

    def list_quant_strategies(self, owner_id: str) -> list[QuantStrategyVersion]:
        """List all quant strategy versions for an owner.

        Args:
            owner_id: str: .

        Returns:
            list[QuantStrategyVersion]: .
        """
        with self._session_factory() as session:
            rows = session.scalars(quant_strategies_by_owner(owner_id)).all()
            return [_quant_strategy_from_row(row) for row in rows]

    def activate_quant_strategy(self, version_id: str) -> QuantStrategyVersion:
        """Activate a quant strategy and deprecate older active sibling versions.

        Args:
            version_id: str: .

        Returns:
            QuantStrategyVersion: .
        """
        with self._session_factory.begin() as session:
            row = session.get(QuantStrategyVersionRow, version_id)
            if row is None:
                raise KeyError(f"quant strategy '{version_id}' not found")
            active_rows = session.scalars(
                active_quant_strategies_by_owner_and_family(
                    row.owner_id,
                    row.strategy_family,
                    ConfigLifecycle.ACTIVE.value,
                )
            ).all()
            deprecated_existing = False
            for active in active_rows:
                if active.version_id != version_id:
                    active.lifecycle = ConfigLifecycle.DEPRECATED.value
                    deprecated_existing = True
            if deprecated_existing:
                session.flush()
            row.lifecycle = ConfigLifecycle.ACTIVE.value
            return _quant_strategy_from_row(row)

    def save_user_style_prompt(self, version: UserStylePromptVersion) -> None:
        """Append a user style prompt version.

        Args:
            version: UserStylePromptVersion: .

        Returns:
            None: .
        """
        with self._session_factory.begin() as session:
            if session.get(UserStylePromptVersionRow, version.version_id) is not None:
                raise ValueError(f"style prompt '{version.version_id}' already exists")
            session.add(_user_style_prompt_to_row(version))

    def get_user_style_prompt(self, version_id: str) -> UserStylePromptVersion | None:
        """Return a user style prompt version.

        Args:
            version_id: str: .

        Returns:
            UserStylePromptVersion | None: .
        """
        with self._session_factory() as session:
            row = session.get(UserStylePromptVersionRow, version_id)
            return _user_style_prompt_from_row(row) if row is not None else None

    def get_active_user_style_prompt(
        self,
        owner_id: str,
        *,
        prompt_name: str = "default",
    ) -> UserStylePromptVersion | None:
        """Return the active user style prompt for an owner and prompt name.

        Args:
            owner_id: str: .
            prompt_name: str: .

        Returns:
            UserStylePromptVersion | None: .
        """
        with self._session_factory() as session:
            rows = session.scalars(
                active_user_style_prompts_by_owner_and_name(
                    owner_id,
                    prompt_name,
                    ConfigLifecycle.ACTIVE.value,
                )
            ).all()
            return _single_or_none(_user_style_prompt_from_row(row) for row in rows)

    def list_user_style_prompts(self, owner_id: str) -> list[UserStylePromptVersion]:
        """List all user style prompt versions for an owner.

        Args:
            owner_id: str: .

        Returns:
            list[UserStylePromptVersion]: .
        """
        with self._session_factory() as session:
            rows = session.scalars(user_style_prompts_by_owner(owner_id)).all()
            return [_user_style_prompt_from_row(row) for row in rows]

    def activate_user_style_prompt(
        self,
        version_id: str,
    ) -> UserStylePromptVersion:
        """Activate a style prompt and deprecate its prior active sibling.

        Args:
            version_id: str: .

        Returns:
            UserStylePromptVersion: .
        """
        with self._session_factory.begin() as session:
            row = session.get(UserStylePromptVersionRow, version_id)
            if row is None:
                raise KeyError(f"style prompt '{version_id}' not found")
            active_rows = session.scalars(
                active_user_style_prompts_by_owner_and_name(
                    row.owner_id,
                    row.prompt_name,
                    ConfigLifecycle.ACTIVE.value,
                )
            ).all()
            for active in active_rows:
                if active.version_id != version_id:
                    active.lifecycle = ConfigLifecycle.DEPRECATED.value
            row.lifecycle = ConfigLifecycle.ACTIVE.value
            return _user_style_prompt_from_row(row)

    def save_tool_policy(self, version: ToolPolicyVersionRef) -> None:
        """Append a tool policy version.

        Args:
            version: ToolPolicyVersionRef: .

        Returns:
            None: .
        """
        with self._session_factory.begin() as session:
            if session.get(ToolPolicyVersionRow, version.version_id) is not None:
                raise ValueError(f"tool policy '{version.version_id}' already exists")
            session.add(_tool_policy_to_row(version))

    def get_tool_policy(self, version_id: str) -> ToolPolicyVersionRef | None:
        """Return a tool policy version.

        Args:
            version_id: str: .

        Returns:
            ToolPolicyVersionRef | None: .
        """
        with self._session_factory() as session:
            row = session.get(ToolPolicyVersionRow, version_id)
            return _tool_policy_from_row(row) if row is not None else None

    def get_active_tool_policy(self, owner_id: str) -> ToolPolicyVersionRef | None:
        """Return the active tool policy for an owner.

        Args:
            owner_id: str: .

        Returns:
            ToolPolicyVersionRef | None: .
        """
        with self._session_factory() as session:
            rows = session.scalars(
                active_tool_policies_by_owner(owner_id, ConfigLifecycle.ACTIVE.value)
            ).all()
            return _single_or_none(_tool_policy_from_row(row) for row in rows)

    def activate_tool_policy(self, version_id: str) -> ToolPolicyVersionRef:
        """Activate a tool policy and deprecate the prior active version.

        Args:
            version_id: str: .

        Returns:
            ToolPolicyVersionRef: .
        """
        with self._session_factory.begin() as session:
            row = session.get(ToolPolicyVersionRow, version_id)
            if row is None:
                raise KeyError(f"tool policy '{version_id}' not found")
            active_rows = session.scalars(
                active_tool_policies_by_owner(row.owner_id, ConfigLifecycle.ACTIVE.value)
            ).all()
            for active in active_rows:
                if active.version_id != version_id:
                    active.lifecycle = ConfigLifecycle.DEPRECATED.value
            row.lifecycle = ConfigLifecycle.ACTIVE.value
            return _tool_policy_from_row(row)

    def save_research_scope(self, version: ResearchScopeVersion) -> None:
        """Append a research scope version.

        Args:
            version: ResearchScopeVersion: .

        Returns:
            None: .
        """
        with self._session_factory.begin() as session:
            if session.get(ResearchScopeVersionRow, version.version_id) is not None:
                raise ValueError(f"research scope '{version.version_id}' already exists")
            session.add(_research_scope_to_row(version))

    def get_research_scope(self, version_id: str) -> ResearchScopeVersion | None:
        """Return a research scope version.

        Args:
            version_id: str: .

        Returns:
            ResearchScopeVersion | None: .
        """
        with self._session_factory() as session:
            row = session.get(ResearchScopeVersionRow, version_id)
            return _research_scope_from_row(row) if row is not None else None

    def get_active_research_scope(self, owner_id: str) -> ResearchScopeVersion | None:
        """Return the active research scope for an owner.

        Args:
            owner_id: str: .

        Returns:
            ResearchScopeVersion | None: .
        """
        with self._session_factory() as session:
            rows = session.scalars(
                active_research_scopes_by_owner(owner_id, ConfigLifecycle.ACTIVE.value)
            ).all()
            return _single_or_none(_research_scope_from_row(row) for row in rows)

    def list_research_scopes(self, owner_id: str) -> list[ResearchScopeVersion]:
        """List all research scope versions for an owner.

        Args:
            owner_id: str: .

        Returns:
            list[ResearchScopeVersion]: .
        """
        with self._session_factory() as session:
            rows = session.scalars(research_scopes_by_owner(owner_id)).all()
            return [_research_scope_from_row(row) for row in rows]

    def activate_research_scope(self, version_id: str) -> ResearchScopeVersion:
        """Activate a research scope and deprecate older active scopes.

        Args:
            version_id: str: .

        Returns:
            ResearchScopeVersion: .
        """
        with self._session_factory.begin() as session:
            row = session.get(ResearchScopeVersionRow, version_id)
            if row is None:
                raise KeyError(f"research scope '{version_id}' not found")
            active_rows = session.scalars(
                active_research_scopes_by_owner(row.owner_id, ConfigLifecycle.ACTIVE.value)
            ).all()
            deprecated_existing = False
            for active in active_rows:
                if active.version_id != version_id:
                    active.lifecycle = ConfigLifecycle.DEPRECATED.value
                    deprecated_existing = True
            if deprecated_existing:
                session.flush()
            row.lifecycle = ConfigLifecycle.ACTIVE.value
            row.scope_hash = _research_scope_from_row(row).scope_hash
            return _research_scope_from_row(row)

    def record_config_audit(
        self,
        *,
        actor_id: str,
        resource_type: str,
        resource_version_id: str,
        action: str,
        idempotency_key: str,
        details: dict[str, object],
    ) -> StrategyConfigAuditRow:
        """Append one idempotent config audit event.

        Args:
            actor_id: str: .
            resource_type: str: .
            resource_version_id: str: .
            action: str: .
            idempotency_key: str: .
            details: dict[str, object]: .

        Returns:
            StrategyConfigAuditRow: .
        """
        with self._session_factory.begin() as session:
            statement = insert_config_audit(
                audit_id=f"audit_{uuid.uuid4().hex[:12]}",
                actor_id=actor_id,
                resource_type=resource_type,
                resource_version_id=resource_version_id,
                action=action,
                idempotency_key=idempotency_key,
                details=details,
                created_at=utc_now(),
            )
            session.execute(statement)
            row = session.scalar(config_audit_by_replay_key(actor_id, action, idempotency_key))
            if row is None:
                raise RuntimeError("failed to persist strategy config audit")
            return row

    def get_config_audit(
        self,
        *,
        actor_id: str,
        action: str,
        idempotency_key: str,
    ) -> StrategyConfigAuditRow | None:
        """Return a prior config mutation audit by replay key.

        Args:
            actor_id: str: .
            action: str: .
            idempotency_key: str: .

        Returns:
            StrategyConfigAuditRow | None: .
        """
        with self._session_factory() as session:
            return session.scalar(config_audit_by_replay_key(actor_id, action, idempotency_key))


def _ensure_new(mapping: dict[str, object], version_id: str, resource_type: str) -> None:
    """ensure new.

    Args:
        mapping: dict[str, object]: .
        version_id: str: .
        resource_type: str: .

    Returns:
        None: .
    """
    if version_id in mapping:
        raise ValueError(f"{resource_type} '{version_id}' already exists")


def _sorted_versions(versions: Iterable[T]) -> list[T]:
    """sorted versions.

    Args:
        versions: Iterable[T]: .

    Returns:
        list[T]: .
    """
    return sorted(versions, key=lambda item: getattr(item, "version_id"))


def _single_or_none(versions: Iterable[T]) -> T | None:
    """single or none.

    Args:
        versions: Iterable[T]: .

    Returns:
        T | None: .
    """
    items = list(versions)
    if not items:
        return None
    if len(items) > 1:
        ids = ", ".join(getattr(item, "version_id", "<unknown>") for item in items)
        raise ValueError(f"expected one active version, found {len(items)}: {ids}")
    return items[0]


def _provider_config_to_row(version: ProviderConfigVersion) -> ProviderConfigVersionRow:
    """provider config to row.

    Args:
        version: ProviderConfigVersion: .

    Returns:
        ProviderConfigVersionRow: .
    """
    return ProviderConfigVersionRow(
        version_id=version.version_id,
        owner_id=version.owner_id,
        provider_name=version.provider_name,
        provider_type=version.provider_type,
        base_url=version.base_url,
        model_name=version.model_name,
        enabled=version.enabled,
        non_sensitive_config=version.non_sensitive_config,
        secret_version_id=version.secret_version_id,
        lifecycle=version.lifecycle.value,
        created_at=version.created_at,
    )


def _provider_config_from_row(row: ProviderConfigVersionRow) -> ProviderConfigVersion:
    """provider config from row.

    Args:
        row: ProviderConfigVersionRow: .

    Returns:
        ProviderConfigVersion: .
    """
    return ProviderConfigVersion(
        version_id=row.version_id,
        owner_id=row.owner_id,
        provider_name=row.provider_name,
        provider_type=row.provider_type,
        base_url=row.base_url,
        model_name=row.model_name,
        enabled=row.enabled,
        non_sensitive_config=row.non_sensitive_config,
        secret_version_id=row.secret_version_id,
        lifecycle=ConfigLifecycle(row.lifecycle),
        created_at=row.created_at,
    )


def _universe_to_row(version: UniverseDefinitionVersion) -> UniverseDefinitionVersionRow:
    """universe to row.

    Args:
        version: UniverseDefinitionVersion: .

    Returns:
        UniverseDefinitionVersionRow: .
    """
    return UniverseDefinitionVersionRow(
        version_id=version.version_id,
        owner_id=version.owner_id,
        universe_code=version.universe_code,
        name=version.name,
        selection_rule=version.selection_rule,
        member_security_ids=list(version.member_security_ids),
        lifecycle=version.lifecycle.value,
        created_at=version.created_at,
    )


def _universe_from_row(row: UniverseDefinitionVersionRow) -> UniverseDefinitionVersion:
    """universe from row.

    Args:
        row: UniverseDefinitionVersionRow: .

    Returns:
        UniverseDefinitionVersion: .
    """
    return UniverseDefinitionVersion(
        version_id=row.version_id,
        owner_id=row.owner_id,
        universe_code=row.universe_code,
        name=row.name,
        selection_rule=row.selection_rule,
        member_security_ids=tuple(row.member_security_ids),
        lifecycle=ConfigLifecycle(row.lifecycle),
        created_at=row.created_at,
    )


def _indicator_view_to_row(version: IndicatorViewVersion) -> IndicatorViewVersionRow:
    """indicator view to row.

    Args:
        version: IndicatorViewVersion: .

    Returns:
        IndicatorViewVersionRow: .
    """
    return IndicatorViewVersionRow(
        version_id=version.version_id,
        owner_id=version.owner_id,
        mode=version.mode.value,
        included_indicators=list(version.included_indicators),
        excluded_indicators=list(version.excluded_indicators),
        lifecycle=version.lifecycle.value,
        created_at=version.created_at,
    )


def _indicator_view_from_row(row: IndicatorViewVersionRow) -> IndicatorViewVersion:
    """indicator view from row.

    Args:
        row: IndicatorViewVersionRow: .

    Returns:
        IndicatorViewVersion: .
    """
    return IndicatorViewVersion(
        version_id=row.version_id,
        owner_id=row.owner_id,
        mode=IndicatorSelectionMode(row.mode),
        included_indicators=tuple(row.included_indicators),
        excluded_indicators=tuple(row.excluded_indicators),
        lifecycle=ConfigLifecycle(row.lifecycle),
        created_at=row.created_at,
    )


def _quant_feature_set_to_row(
    version: QuantFeatureSetVersion,
) -> QuantFeatureSetVersionRow:
    """quant feature set to row.

    Args:
        version: QuantFeatureSetVersion: .

    Returns:
        QuantFeatureSetVersionRow: .
    """
    return QuantFeatureSetVersionRow(
        version_id=version.version_id,
        owner_id=version.owner_id,
        required_indicators=list(version.required_indicators),
        optional_indicators=list(version.optional_indicators),
        history_days=version.history_days,
        fallback_policy=version.fallback_policy,
        lifecycle=version.lifecycle.value,
        created_at=version.created_at,
    )


def _quant_feature_set_from_row(
    row: QuantFeatureSetVersionRow,
) -> QuantFeatureSetVersion:
    """quant feature set from row.

    Args:
        row: QuantFeatureSetVersionRow: .

    Returns:
        QuantFeatureSetVersion: .
    """
    return QuantFeatureSetVersion(
        version_id=row.version_id,
        owner_id=row.owner_id,
        required_indicators=tuple(row.required_indicators),
        optional_indicators=tuple(row.optional_indicators),
        history_days=row.history_days,
        fallback_policy=row.fallback_policy,
        lifecycle=ConfigLifecycle(row.lifecycle),
        created_at=row.created_at,
    )


def _quant_strategy_to_row(version: QuantStrategyVersion) -> QuantStrategyVersionRow:
    """quant strategy to row.

    Args:
        version: QuantStrategyVersion: .

    Returns:
        QuantStrategyVersionRow: .
    """
    return QuantStrategyVersionRow(
        version_id=version.version_id,
        owner_id=version.owner_id,
        strategy_family=version.strategy_family,
        factor_weights=version.factor_weights,
        thresholds=version.thresholds,
        calibration_report_id=version.calibration_report_id,
        lifecycle=version.lifecycle.value,
        created_at=version.created_at,
    )


def _quant_strategy_from_row(row: QuantStrategyVersionRow) -> QuantStrategyVersion:
    """quant strategy from row.

    Args:
        row: QuantStrategyVersionRow: .

    Returns:
        QuantStrategyVersion: .
    """
    return QuantStrategyVersion(
        version_id=row.version_id,
        owner_id=row.owner_id,
        strategy_family=row.strategy_family,
        factor_weights=row.factor_weights,
        thresholds=row.thresholds,
        calibration_report_id=row.calibration_report_id,
        lifecycle=ConfigLifecycle(row.lifecycle),
        created_at=row.created_at,
    )


def _user_style_prompt_to_row(
    version: UserStylePromptVersion,
) -> UserStylePromptVersionRow:
    """user style prompt to row.

    Args:
        version: UserStylePromptVersion: .

    Returns:
        UserStylePromptVersionRow: .
    """
    return UserStylePromptVersionRow(
        version_id=version.version_id,
        owner_id=version.owner_id,
        prompt_name=version.prompt_name,
        content=version.content,
        lifecycle=version.lifecycle.value,
        created_at=version.created_at,
    )


def _user_style_prompt_from_row(
    row: UserStylePromptVersionRow,
) -> UserStylePromptVersion:
    """user style prompt from row.

    Args:
        row: UserStylePromptVersionRow: .

    Returns:
        UserStylePromptVersion: .
    """
    return UserStylePromptVersion(
        version_id=row.version_id,
        owner_id=row.owner_id,
        prompt_name=row.prompt_name,
        content=row.content,
        lifecycle=ConfigLifecycle(row.lifecycle),
        created_at=row.created_at,
    )


def _tool_policy_to_row(version: ToolPolicyVersionRef) -> ToolPolicyVersionRow:
    """tool policy to row.

    Args:
        version: ToolPolicyVersionRef: .

    Returns:
        ToolPolicyVersionRow: .
    """
    return ToolPolicyVersionRow(
        version_id=version.version_id,
        owner_id=version.owner_id,
        allowed_tool_names=list(version.allowed_tool_names),
        denied_tool_names=list(version.denied_tool_names),
        lifecycle=version.lifecycle.value,
        created_at=version.created_at,
    )


def _tool_policy_from_row(row: ToolPolicyVersionRow) -> ToolPolicyVersionRef:
    """tool policy from row.

    Args:
        row: ToolPolicyVersionRow: .

    Returns:
        ToolPolicyVersionRef: .
    """
    return ToolPolicyVersionRef(
        version_id=row.version_id,
        owner_id=row.owner_id,
        allowed_tool_names=tuple(row.allowed_tool_names),
        denied_tool_names=tuple(row.denied_tool_names),
        lifecycle=ConfigLifecycle(row.lifecycle),
        created_at=row.created_at,
    )


def _research_scope_to_row(version: ResearchScopeVersion) -> ResearchScopeVersionRow:
    """research scope to row.

    Args:
        version: ResearchScopeVersion: .

    Returns:
        ResearchScopeVersionRow: .
    """
    return ResearchScopeVersionRow(
        version_id=version.version_id,
        owner_id=version.owner_id,
        universe_version_id=version.universe_version_id,
        indicator_view_version_id=version.indicator_view_version_id,
        quant_feature_set_version_id=version.quant_feature_set_version_id,
        quant_strategy_version_id=version.quant_strategy_version_id,
        ai_prompt_version_id=version.ai_prompt_version_id,
        canonical_rule_version=version.canonical_rule_version,
        tool_policy_version_id=version.tool_policy_version_id,
        provider_config_version_ids=list(version.provider_config_version_ids),
        scope_hash=version.scope_hash,
        lifecycle=version.lifecycle.value,
        created_at=version.created_at,
    )


def _research_scope_from_row(row: ResearchScopeVersionRow) -> ResearchScopeVersion:
    """research scope from row.

    Args:
        row: ResearchScopeVersionRow: .

    Returns:
        ResearchScopeVersion: .
    """
    return ResearchScopeVersion(
        version_id=row.version_id,
        owner_id=row.owner_id,
        universe_version_id=row.universe_version_id,
        indicator_view_version_id=row.indicator_view_version_id,
        quant_feature_set_version_id=row.quant_feature_set_version_id,
        quant_strategy_version_id=row.quant_strategy_version_id,
        ai_prompt_version_id=row.ai_prompt_version_id,
        canonical_rule_version=row.canonical_rule_version,
        tool_policy_version_id=row.tool_policy_version_id,
        provider_config_version_ids=tuple(row.provider_config_version_ids),
        lifecycle=ConfigLifecycle(row.lifecycle),
        created_at=row.created_at,
    )
