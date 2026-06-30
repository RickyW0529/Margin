"""High-level strategy configuration service."""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from margin.strategy.lifecycle import StrategyLifecycle
from margin.strategy.models import (
    IndicatorViewVersion,
    ProviderConfigVersion,
    QuantFeatureSetVersion,
    QuantStrategyVersion,
    ResearchScopeVersion,
    StrategyConfig,
    StrategyProfile,
    StrategyState,
    StrategyTemplateMeta,
    StrategyVersion,
    ToolPolicyVersionRef,
    UniverseDefinitionVersion,
    UserStylePromptVersion,
)
from margin.strategy.prompt import PromptLayerBuilder
from margin.strategy.provider_router import enrich_provider_config_metadata
from margin.strategy.repository import MemoryStrategyRepository, StrategyRepository
from margin.strategy.sandbox import StrategySandbox
from margin.strategy.templates import BUILTIN_TEMPLATES, list_templates
from margin.strategy.validator import (
    ActivationError,
    StrategyActivationValidator,
    StrategyValidator,
)

if TYPE_CHECKING:
    from margin.core.secret_store import SecretMetadata, SecretStore
    from margin.strategy.provider_config import ProviderConfigHealthService


def _deep_merge_config_delta(
    base: dict[str, Any],
    delta: dict[str, Any],
) -> dict[str, Any]:
    """Return ``base`` updated by recursively merging nested mapping values.

    Args:
        base: The original configuration dictionary.
        delta: The changes to merge into ``base``.

    Returns:
        A new dictionary containing ``base`` values overwritten or merged with
        ``delta`` values.
    """
    merged = dict(base)
    for key, value in delta.items():
        existing = merged.get(key)
        if isinstance(existing, dict) and isinstance(value, dict):
            merged[key] = _deep_merge_config_delta(existing, value)
        else:
            merged[key] = value
    return merged


class StrategyService:
    """Entry point for creating, validating, and activating strategies."""

    def __init__(
        self,
        repository: StrategyRepository | None = None,
        validator: StrategyValidator | None = None,
        lifecycle: StrategyLifecycle | None = None,
        sandbox: StrategySandbox | None = None,
        prompt_builder: PromptLayerBuilder | None = None,
        activation_validator: StrategyActivationValidator | None = None,
    ) -> None:
        """Initialize the service with optional collaborators.

        Args:
            repository: Strategy persistence implementation. Defaults to an
                in-memory repository.
            validator: Configuration validator. Defaults to a
                :class:`StrategyValidator`.
            lifecycle: Lifecycle state machine. Defaults to a
                :class:`StrategyLifecycle`.
            sandbox: Sandbox evaluator. Defaults to a :class:`StrategySandbox`
                using the service validator.
            prompt_builder: Prompt layer builder. Defaults to a
                :class:`PromptLayerBuilder`.
        """
        self._repository = repository or MemoryStrategyRepository()
        self._validator = validator or StrategyValidator()
        self._lifecycle = lifecycle or StrategyLifecycle()
        self._sandbox = sandbox or StrategySandbox(self._validator)
        self._prompt_builder = prompt_builder or PromptLayerBuilder()
        self._activation_validator = activation_validator or StrategyActivationValidator()

    def create_from_template(
        self,
        owner_id: str,
        template_id: str,
        name: str = "",
        description: str = "",
    ) -> StrategyProfile:
        """Create a new strategy profile from a built-in template.

        Args:
            owner_id: The identifier of the profile owner.
            template_id: The built-in template identifier.
            name: Optional profile name. Defaults to the template name.
            description: Optional profile description.

        Returns:
            The newly created and persisted :class:`StrategyProfile`.

        Raises:
            ValueError: If ``template_id`` is not a known built-in template.
        """
        template = BUILTIN_TEMPLATES.get(template_id)
        if template is None:
            raise ValueError(f"unknown template: {template_id}")
        config = self._validator.merge_with_guardrails(template.config)
        return self._create_version(
            owner_id=owner_id,
            name=name or template.meta.name,
            description=description,
            config=config,
            prompt_layers=self._prompt_builder.build_layers(config),
        )

    def create_custom(
        self,
        owner_id: str,
        config: StrategyConfig,
        name: str,
        description: str = "",
    ) -> StrategyProfile:
        """Create a new strategy profile from a user-supplied config.

        Args:
            owner_id: The identifier of the profile owner.
            config: The user-provided strategy configuration.
            name: The profile name.
            description: Optional profile description.

        Returns:
            The newly created and persisted :class:`StrategyProfile`.

        Raises:
            ValueError: If ``config`` fails guardrail validation.
        """
        ok, errors = self._validator.validate(config)
        if not ok:
            raise ValueError("; ".join(errors))
        config = self._validator.merge_with_guardrails(config)
        return self._create_version(
            owner_id=owner_id,
            name=name,
            description=description,
            config=config,
            prompt_layers=self._prompt_builder.build_layers(config),
        )

    def update_strategy(
        self,
        strategy_id: str,
        config_delta: dict[str, Any] | None = None,
        name: str | None = None,
        description: str | None = None,
    ) -> StrategyProfile:
        """Create a new version of an existing strategy.

        Args:
            strategy_id: The identifier of the strategy to update.
            config_delta: Optional nested dictionary of configuration changes
                merged into the latest version's config.
            name: Optional new profile/version name.
            description: Optional new version description.

        Returns:
            The updated :class:`StrategyProfile` with a new immutable version.

        Raises:
            KeyError: If ``strategy_id`` does not exist.
            ValueError: If the merged configuration fails guardrail validation.
        """
        profile = self._must_get_profile(strategy_id)
        latest = profile.versions[-1] if profile.versions else None
        base_config = latest.config if latest else StrategyConfig()
        data = base_config.model_dump()
        if config_delta:
            data = _deep_merge_config_delta(data, config_delta)
        config = StrategyConfig.model_validate(data)
        config = self._validator.merge_with_guardrails(config)
        new_version = StrategyVersion(
            strategy_id=strategy_id,
            name=name or latest.name if latest else config.ai.system_prompt_template,
            description=description or (latest.description if latest else ""),
            config=config,
            prompt_layers=self._prompt_builder.build_layers(config),
            prompt_version=latest.prompt_version if latest else "",
        )
        updated = profile.with_version(new_version)
        if name:
            updated = updated.model_copy(update={"name": name})
        self._repository.update_profile(updated)
        return updated

    def validate_version(self, strategy_id: str, version_id: str) -> StrategyProfile:
        """Run validation and sandbox on a version, advancing to backtesting.

        Args:
            strategy_id: The identifier of the strategy containing the version.
            version_id: The identifier of the version to validate.

        Returns:
            The updated :class:`StrategyProfile` with the version state moved
            to ``BACKTESTING`` on success or ``INVALID`` on failure.

        Raises:
            KeyError: If the strategy or version is not found.
        """
        profile = self._must_get_profile(strategy_id)
        version = self._must_get_version(profile, version_id)
        ok, errors = self._validator.validate(version.config)
        sandbox_result = self._sandbox.evaluate(version.config)
        sandbox_result = sandbox_result.model_copy(
            update={"validation_ok": ok}
        )
        if not ok:
            version = version.model_copy(
                update={
                    "sandbox_result": sandbox_result,
                    "description": "\n".join(errors),
                }
            )
            version = self._lifecycle.transition(version, StrategyState.INVALID)
        else:
            version = version.model_copy(update={"sandbox_result": sandbox_result})
            version = self._lifecycle.transition(version, StrategyState.VALIDATING)
            version = self._lifecycle.transition(version, StrategyState.BACKTESTING)
        updated = self._replace_version(profile, version)
        self._repository.update_profile(updated)
        return updated

    def backtest_version(self, strategy_id: str, version_id: str) -> StrategyProfile:
        """Mark a version as ready for paper trading.

        Args:
            strategy_id: The identifier of the strategy containing the version.
            version_id: The identifier of the version to advance.

        Returns:
            The updated :class:`StrategyProfile` with the version state moved
            to ``PAPER_TRADING``.

        Raises:
            KeyError: If the strategy or version is not found.
            ValueError: If the lifecycle transition is not allowed.
        """
        profile = self._must_get_profile(strategy_id)
        version = self._must_get_version(profile, version_id)
        version = self._lifecycle.transition(version, StrategyState.PAPER_TRADING)
        updated = self._replace_version(profile, version)
        self._repository.update_profile(updated)
        return updated

    def paper_trade_version(self, strategy_id: str, version_id: str) -> StrategyProfile:
        """Record paper-trading readiness without activating the strategy.

        Args:
            strategy_id: The identifier of the strategy containing the version.
            version_id: The identifier of the version to advance.

        Returns:
            The updated :class:`StrategyProfile` with the version state moved
            to ``PAPER_TRADING`` if it was in ``BACKTESTING``.

        Raises:
            KeyError: If the strategy or version is not found.
            ValueError: If the version is not in ``BACKTESTING`` or
                ``PAPER_TRADING`` state.
        """
        profile = self._must_get_profile(strategy_id)
        version = self._must_get_version(profile, version_id)
        if version.state == StrategyState.BACKTESTING:
            version = self._lifecycle.transition(version, StrategyState.PAPER_TRADING)
        elif version.state != StrategyState.PAPER_TRADING:
            raise ValueError(
                "paper trading requires a version in backtesting or paper_trading"
            )
        updated = self._replace_version(profile, version)
        self._repository.update_profile(updated)
        return updated

    def activate_version(self, strategy_id: str, version_id: str) -> StrategyProfile:
        """Activate a version for live research runs.

        Args:
            strategy_id: The identifier of the strategy containing the version.
            version_id: The identifier of the version to activate.

        Returns:
            The updated :class:`StrategyProfile` with the version state set to
            ``ACTIVE`` and ``active_version_id`` updated.

        Raises:
            KeyError: If the strategy or version is not found.
            ValueError: If the lifecycle transition is not allowed.
        """
        profile = self._must_get_profile(strategy_id)
        version = self._must_get_version(profile, version_id)
        if version.state != StrategyState.ACTIVE:
            version = self._lifecycle.transition(version, StrategyState.ACTIVE)
        updated = self._replace_version(profile, version)
        updated = updated.with_active_version(version_id)
        self._repository.update_profile(updated)
        return updated

    def activate_quant_strategy(
        self,
        version_id: str,
        *,
        actor_id: str | None = None,
        idempotency_key: str | None = None,
    ) -> QuantStrategyVersion:
        """Activate a v0.2 quant strategy version after calibration validation."""
        replay = self._config_mutation_replay(
            actor_id=actor_id,
            action="quant_strategy.activate",
            idempotency_key=idempotency_key,
            getter=self._repository.get_quant_strategy,
        )
        if replay is not None:
            return replay
        version = self._repository.get_quant_strategy(version_id)
        if version is None:
            raise KeyError(f"quant strategy '{version_id}' not found")
        self._activation_validator.validate_quant_strategy_activation(version)
        activated = self._repository.activate_quant_strategy(version_id)
        self._record_config_mutation(
            actor_id=actor_id,
            action="quant_strategy.activate",
            idempotency_key=idempotency_key,
            resource_type="quant_strategy",
            resource_version_id=version_id,
            details={"lifecycle": activated.lifecycle.value},
        )
        return activated

    def activate_provider_config(
        self,
        version_id: str,
        *,
        health_service: ProviderConfigHealthService,
        actor_id: str | None = None,
        idempotency_key: str | None = None,
    ) -> ProviderConfigVersion:
        """Activate a provider config after schema and secret-reference validation."""
        replay = self._config_mutation_replay(
            actor_id=actor_id,
            action="provider_config.activate",
            idempotency_key=idempotency_key,
            getter=self._repository.get_provider_config,
        )
        if replay is not None:
            return replay
        version = self._repository.get_provider_config(version_id)
        if version is None:
            raise KeyError(f"provider config '{version_id}' not found")
        self._activation_validator.validate_provider_config_activation(version)
        secret_required = bool(
            version.non_sensitive_config.get("secret_required", True)
        )
        if secret_required and not version.secret_version_id:
            raise ValueError("provider config activation requires an active secret")
        try:
            health = health_service.test_connection(version_id)
        except (KeyError, ValueError) as exc:
            raise ActivationError(
                "provider activation health check failed: secret/config invalid"
            ) from exc
        if health.status != "ok":
            raise ActivationError(
                "provider activation health check must succeed before activation"
            )
        activated = self._repository.activate_provider_config(version_id)
        self._record_config_mutation(
            actor_id=actor_id,
            action="provider_config.activate",
            idempotency_key=idempotency_key,
            resource_type="provider_config",
            resource_version_id=version_id,
            details={
                "provider_name": activated.provider_name,
                "health_status": health.status,
                "lifecycle": activated.lifecycle.value,
            },
        )
        return activated

    def activate_research_scope(
        self,
        version_id: str,
        *,
        actor_id: str | None = None,
        idempotency_key: str | None = None,
    ) -> ResearchScopeVersion:
        """Activate a v0.2 research scope after validating frozen references."""
        replay = self._config_mutation_replay(
            actor_id=actor_id,
            action="research_scope.activate",
            idempotency_key=idempotency_key,
            getter=self._repository.get_research_scope,
        )
        if replay is not None:
            return replay
        scope = self._repository.get_research_scope(version_id)
        if scope is None:
            raise KeyError(f"research scope '{version_id}' not found")
        self._activation_validator.validate_research_scope_activation(
            scope,
            self._repository,
        )
        activated = self._repository.activate_research_scope(version_id)
        self._record_config_mutation(
            actor_id=actor_id,
            action="research_scope.activate",
            idempotency_key=idempotency_key,
            resource_type="research_scope",
            resource_version_id=version_id,
            details={
                "scope_hash": activated.scope_hash,
                "lifecycle": activated.lifecycle.value,
            },
        )
        return activated

    def activate_universe_definition(
        self,
        version_id: str,
        *,
        actor_id: str | None = None,
        idempotency_key: str | None = None,
    ) -> UniverseDefinitionVersion:
        """Activate a universe definition version."""
        replay = self._config_mutation_replay(
            actor_id=actor_id,
            action="universe_definition.activate",
            idempotency_key=idempotency_key,
            getter=self._repository.get_universe_definition,
        )
        if replay is not None:
            return replay
        version = self._repository.get_universe_definition(version_id)
        if version is None:
            raise KeyError(f"universe '{version_id}' not found")
        self._activation_validator.validate_simple_activation(
            version,
            "universe definition",
        )
        activated = self._repository.activate_universe_definition(version_id)
        self._record_config_mutation(
            actor_id=actor_id,
            action="universe_definition.activate",
            idempotency_key=idempotency_key,
            resource_type="universe_definition",
            resource_version_id=version_id,
            details={
                "universe_code": activated.universe_code,
                "lifecycle": activated.lifecycle.value,
            },
        )
        return activated

    def activate_indicator_view(
        self,
        version_id: str,
        *,
        actor_id: str | None = None,
        idempotency_key: str | None = None,
    ) -> IndicatorViewVersion:
        """Activate an indicator view version."""
        replay = self._config_mutation_replay(
            actor_id=actor_id,
            action="indicator_view.activate",
            idempotency_key=idempotency_key,
            getter=self._repository.get_indicator_view,
        )
        if replay is not None:
            return replay
        version = self._repository.get_indicator_view(version_id)
        if version is None:
            raise KeyError(f"indicator view '{version_id}' not found")
        self._activation_validator.validate_simple_activation(
            version,
            "indicator view",
        )
        activated = self._repository.activate_indicator_view(version_id)
        self._record_config_mutation(
            actor_id=actor_id,
            action="indicator_view.activate",
            idempotency_key=idempotency_key,
            resource_type="indicator_view",
            resource_version_id=version_id,
            details={
                "mode": activated.mode.value,
                "lifecycle": activated.lifecycle.value,
            },
        )
        return activated

    def activate_quant_feature_set(
        self,
        version_id: str,
        *,
        actor_id: str | None = None,
        idempotency_key: str | None = None,
    ) -> QuantFeatureSetVersion:
        """Activate a quant feature set version."""
        replay = self._config_mutation_replay(
            actor_id=actor_id,
            action="quant_feature_set.activate",
            idempotency_key=idempotency_key,
            getter=self._repository.get_quant_feature_set,
        )
        if replay is not None:
            return replay
        version = self._repository.get_quant_feature_set(version_id)
        if version is None:
            raise KeyError(f"quant feature set '{version_id}' not found")
        self._activation_validator.validate_simple_activation(
            version,
            "quant feature set",
        )
        activated = self._repository.activate_quant_feature_set(version_id)
        self._record_config_mutation(
            actor_id=actor_id,
            action="quant_feature_set.activate",
            idempotency_key=idempotency_key,
            resource_type="quant_feature_set",
            resource_version_id=version_id,
            details={
                "required_indicator_count": len(activated.required_indicators),
                "lifecycle": activated.lifecycle.value,
            },
        )
        return activated

    def activate_user_style_prompt(
        self,
        version_id: str,
        *,
        actor_id: str | None = None,
        idempotency_key: str | None = None,
    ) -> UserStylePromptVersion:
        """Activate a style prompt after protected-boundary validation."""
        replay = self._config_mutation_replay(
            actor_id=actor_id,
            action="style_prompt.activate",
            idempotency_key=idempotency_key,
            getter=self._repository.get_user_style_prompt,
        )
        if replay is not None:
            return replay
        version = self._repository.get_user_style_prompt(version_id)
        if version is None:
            raise KeyError(f"style prompt '{version_id}' not found")
        self._activation_validator.validate_style_prompt_activation(version)
        activated = self._repository.activate_user_style_prompt(version_id)
        self._record_config_mutation(
            actor_id=actor_id,
            action="style_prompt.activate",
            idempotency_key=idempotency_key,
            resource_type="style_prompt",
            resource_version_id=version_id,
            details={
                "prompt_name": activated.prompt_name,
                "lifecycle": activated.lifecycle.value,
            },
        )
        return activated

    def activate_tool_policy(
        self,
        version_id: str,
        *,
        actor_id: str | None = None,
        idempotency_key: str | None = None,
    ) -> ToolPolicyVersionRef:
        """Activate a tool policy after allow/deny compatibility validation."""
        replay = self._config_mutation_replay(
            actor_id=actor_id,
            action="tool_policy.activate",
            idempotency_key=idempotency_key,
            getter=self._repository.get_tool_policy,
        )
        if replay is not None:
            return replay
        version = self._repository.get_tool_policy(version_id)
        if version is None:
            raise KeyError(f"tool policy '{version_id}' not found")
        self._activation_validator.validate_tool_policy_activation(version)
        activated = self._repository.activate_tool_policy(version_id)
        self._record_config_mutation(
            actor_id=actor_id,
            action="tool_policy.activate",
            idempotency_key=idempotency_key,
            resource_type="tool_policy",
            resource_version_id=version_id,
            details={
                "allowed_tool_count": len(activated.allowed_tool_names),
                "denied_tool_count": len(activated.denied_tool_names),
                "lifecycle": activated.lifecycle.value,
            },
        )
        return activated

    def create_tool_policy(
        self,
        version: ToolPolicyVersionRef,
        *,
        actor_id: str | None = None,
        idempotency_key: str | None = None,
    ) -> ToolPolicyVersionRef:
        """Persist a new append-only tool-policy version."""
        replay = self._config_mutation_replay(
            actor_id=actor_id,
            action="tool_policy.create",
            idempotency_key=idempotency_key,
            getter=self._repository.get_tool_policy,
        )
        if replay is not None:
            return replay
        self._repository.save_tool_policy(version)
        self._record_config_mutation(
            actor_id=actor_id,
            action="tool_policy.create",
            idempotency_key=idempotency_key,
            resource_type="tool_policy",
            resource_version_id=version.version_id,
            details={
                "allowed_tool_count": len(version.allowed_tool_names),
                "denied_tool_count": len(version.denied_tool_names),
                "lifecycle": version.lifecycle.value,
            },
        )
        return version

    def create_provider_config(
        self,
        version: ProviderConfigVersion,
        *,
        actor_id: str | None = None,
        idempotency_key: str | None = None,
    ) -> ProviderConfigVersion:
        """Persist a new provider configuration version."""
        replay = self._config_mutation_replay(
            actor_id=actor_id,
            action="provider_config.create",
            idempotency_key=idempotency_key,
            getter=self._repository.get_provider_config,
        )
        if replay is not None:
            return replay
        enriched = version.model_copy(
            update={
                "non_sensitive_config": enrich_provider_config_metadata(version),
            }
        )
        self._repository.save_provider_config(enriched)
        self._record_config_mutation(
            actor_id=actor_id,
            action="provider_config.create",
            idempotency_key=idempotency_key,
            resource_type="provider_config",
            resource_version_id=enriched.version_id,
            details={
                "provider_name": enriched.provider_name,
                "provider_type": enriched.provider_type,
                "provider_category": enriched.non_sensitive_config.get(
                    "provider_category"
                ),
                "detected_provider": enriched.non_sensitive_config.get(
                    "detected_provider"
                ),
                "lifecycle": enriched.lifecycle.value,
            },
        )
        return enriched

    def list_provider_configs(self, owner_id: str) -> list[ProviderConfigVersion]:
        """List provider configuration versions for an owner."""
        return self._repository.list_provider_configs(owner_id)

    def write_provider_secret(
        self,
        *,
        provider_config_version_id: str,
        secret_name: str,
        secret_value: str,
        actor_id: str,
        idempotency_key: str,
        secret_store: SecretStore,
    ) -> SecretMetadata:
        """Encrypt a provider secret and bind it to a non-active config version."""
        from margin.core.secret_store import WriteSecretCommand

        config = self._repository.get_provider_config(provider_config_version_id)
        if config is None:
            raise KeyError(
                f"provider config '{provider_config_version_id}' not found"
            )
        metadata = secret_store.create_or_replace(
            WriteSecretCommand(
                provider_name=config.provider_name,
                secret_name=secret_name,
                secret_value=secret_value,
                actor_id=actor_id,
                idempotency_key=idempotency_key,
            )
        )
        self._repository.attach_provider_secret(
            provider_config_version_id,
            metadata.version_id,
        )
        self._repository.record_config_audit(
            actor_id=actor_id,
            resource_type="provider_secret",
            resource_version_id=metadata.version_id,
            action="provider_secret.write",
            idempotency_key=idempotency_key,
            details={
                "provider_config_version_id": provider_config_version_id,
                "provider_name": config.provider_name,
                "secret_name": secret_name,
                "secret_version_id": metadata.version_id,
                "last_four": metadata.last_four,
                "status": metadata.status,
            },
        )
        return metadata

    def create_universe_definition(
        self,
        version: UniverseDefinitionVersion,
        *,
        actor_id: str | None = None,
        idempotency_key: str | None = None,
    ) -> UniverseDefinitionVersion:
        """Persist a new universe definition version."""
        replay = self._config_mutation_replay(
            actor_id=actor_id,
            action="universe_definition.create",
            idempotency_key=idempotency_key,
            getter=self._repository.get_universe_definition,
        )
        if replay is not None:
            return replay
        self._repository.save_universe_definition(version)
        self._record_config_mutation(
            actor_id=actor_id,
            action="universe_definition.create",
            idempotency_key=idempotency_key,
            resource_type="universe_definition",
            resource_version_id=version.version_id,
            details={
                "universe_code": version.universe_code,
                "lifecycle": version.lifecycle.value,
            },
        )
        return version

    def list_universe_definitions(
        self,
        owner_id: str,
    ) -> list[UniverseDefinitionVersion]:
        """List universe definition versions for an owner."""
        return self._repository.list_universe_definitions(owner_id)

    def create_indicator_view(
        self,
        version: IndicatorViewVersion,
        *,
        actor_id: str | None = None,
        idempotency_key: str | None = None,
    ) -> IndicatorViewVersion:
        """Persist a new indicator view version."""
        replay = self._config_mutation_replay(
            actor_id=actor_id,
            action="indicator_view.create",
            idempotency_key=idempotency_key,
            getter=self._repository.get_indicator_view,
        )
        if replay is not None:
            return replay
        self._repository.save_indicator_view(version)
        self._record_config_mutation(
            actor_id=actor_id,
            action="indicator_view.create",
            idempotency_key=idempotency_key,
            resource_type="indicator_view",
            resource_version_id=version.version_id,
            details={"mode": version.mode.value, "lifecycle": version.lifecycle.value},
        )
        return version

    def list_indicator_views(self, owner_id: str) -> list[IndicatorViewVersion]:
        """List indicator view versions for an owner."""
        return self._repository.list_indicator_views(owner_id)

    def create_quant_feature_set(
        self,
        version: QuantFeatureSetVersion,
        *,
        actor_id: str | None = None,
        idempotency_key: str | None = None,
    ) -> QuantFeatureSetVersion:
        """Persist a new quant feature set version."""
        replay = self._config_mutation_replay(
            actor_id=actor_id,
            action="quant_feature_set.create",
            idempotency_key=idempotency_key,
            getter=self._repository.get_quant_feature_set,
        )
        if replay is not None:
            return replay
        self._repository.save_quant_feature_set(version)
        self._record_config_mutation(
            actor_id=actor_id,
            action="quant_feature_set.create",
            idempotency_key=idempotency_key,
            resource_type="quant_feature_set",
            resource_version_id=version.version_id,
            details={
                "required_indicator_count": len(version.required_indicators),
                "optional_indicator_count": len(version.optional_indicators),
                "lifecycle": version.lifecycle.value,
            },
        )
        return version

    def list_quant_feature_sets(self, owner_id: str) -> list[QuantFeatureSetVersion]:
        """List quant feature set versions for an owner."""
        return self._repository.list_quant_feature_sets(owner_id)

    def create_quant_strategy(
        self,
        version: QuantStrategyVersion,
        *,
        actor_id: str | None = None,
        idempotency_key: str | None = None,
    ) -> QuantStrategyVersion:
        """Persist a new quant strategy version."""
        replay = self._config_mutation_replay(
            actor_id=actor_id,
            action="quant_strategy.create",
            idempotency_key=idempotency_key,
            getter=self._repository.get_quant_strategy,
        )
        if replay is not None:
            return replay
        self._repository.save_quant_strategy(version)
        self._record_config_mutation(
            actor_id=actor_id,
            action="quant_strategy.create",
            idempotency_key=idempotency_key,
            resource_type="quant_strategy",
            resource_version_id=version.version_id,
            details={
                "strategy_family": version.strategy_family,
                "calibration_report_id": version.calibration_report_id,
                "lifecycle": version.lifecycle.value,
            },
        )
        return version

    def list_quant_strategies(self, owner_id: str) -> list[QuantStrategyVersion]:
        """List quant strategy versions for an owner."""
        return self._repository.list_quant_strategies(owner_id)

    def create_user_style_prompt(
        self,
        version: UserStylePromptVersion,
        *,
        actor_id: str | None = None,
        idempotency_key: str | None = None,
    ) -> UserStylePromptVersion:
        """Persist a new user style prompt version."""
        replay = self._config_mutation_replay(
            actor_id=actor_id,
            action="style_prompt.create",
            idempotency_key=idempotency_key,
            getter=self._repository.get_user_style_prompt,
        )
        if replay is not None:
            return replay
        self._repository.save_user_style_prompt(version)
        self._record_config_mutation(
            actor_id=actor_id,
            action="style_prompt.create",
            idempotency_key=idempotency_key,
            resource_type="style_prompt",
            resource_version_id=version.version_id,
            details={
                "prompt_name": version.prompt_name,
                "content_length": len(version.content),
                "lifecycle": version.lifecycle.value,
            },
        )
        return version

    def list_user_style_prompts(
        self,
        owner_id: str,
    ) -> list[UserStylePromptVersion]:
        """List user style prompt versions for an owner."""
        return self._repository.list_user_style_prompts(owner_id)

    def create_research_scope(
        self,
        version: ResearchScopeVersion,
        *,
        actor_id: str | None = None,
        idempotency_key: str | None = None,
    ) -> ResearchScopeVersion:
        """Persist a new frozen research scope version."""
        replay = self._config_mutation_replay(
            actor_id=actor_id,
            action="research_scope.create",
            idempotency_key=idempotency_key,
            getter=self._repository.get_research_scope,
        )
        if replay is not None:
            return replay
        self._repository.save_research_scope(version)
        self._record_config_mutation(
            actor_id=actor_id,
            action="research_scope.create",
            idempotency_key=idempotency_key,
            resource_type="research_scope",
            resource_version_id=version.version_id,
            details={
                "scope_hash": version.scope_hash,
                "provider_config_count": len(version.provider_config_version_ids),
                "lifecycle": version.lifecycle.value,
            },
        )
        return version

    def list_research_scopes(self, owner_id: str) -> list[ResearchScopeVersion]:
        """List research scope versions for an owner."""
        return self._repository.list_research_scopes(owner_id)

    def suspend_version(
        self,
        strategy_id: str,
        version_id: str,
        reason: str = "",
    ) -> StrategyProfile:
        """Suspend an active version due to data or risk anomalies.

        Args:
            strategy_id: The identifier of the strategy containing the version.
            version_id: The identifier of the version to suspend.
            reason: Optional human-readable reason for suspension.

        Returns:
            The updated :class:`StrategyProfile` with the version state moved
            to ``SUSPENDED``.

        Raises:
            KeyError: If the strategy or version is not found.
            ValueError: If the lifecycle transition is not allowed.
        """
        profile = self._must_get_profile(strategy_id)
        version = self._must_get_version(profile, version_id)
        version = self._lifecycle.transition(version, StrategyState.SUSPENDED, reason)
        updated = self._replace_version(profile, version)
        self._repository.update_profile(updated)
        return updated

    def archive_strategy(self, strategy_id: str) -> StrategyProfile:
        """Archive the active version of a strategy.

        Args:
            strategy_id: The identifier of the strategy to archive.

        Returns:
            The updated :class:`StrategyProfile` with the active version moved
            to ``ARCHIVED``.

        Raises:
            KeyError: If the strategy or active version is not found.
            ValueError: If the strategy has no active version.
        """
        profile = self._must_get_profile(strategy_id)
        if not profile.active_version_id:
            raise ValueError("strategy has no active version")
        version = self._must_get_version(profile, profile.active_version_id)
        version = self._lifecycle.transition(version, StrategyState.ARCHIVED)
        updated = self._replace_version(profile, version)
        self._repository.update_profile(updated)
        return updated

    def get_profile(self, strategy_id: str) -> StrategyProfile:
        """Return a profile by identifier.

        Args:
            strategy_id: The unique strategy identifier.

        Returns:
            The matching :class:`StrategyProfile`.

        Raises:
            KeyError: If ``strategy_id`` does not exist.
        """
        return self._must_get_profile(strategy_id)

    def list_profiles(self, owner_id: str) -> list[StrategyProfile]:
        """Return all profiles for an owner.

        Args:
            owner_id: The identifier of the profile owner.

        Returns:
            A list of :class:`StrategyProfile` objects belonging to ``owner_id``.
        """
        return self._repository.list_profiles(owner_id)

    def get_prompt(
        self,
        strategy_id: str,
        version_id: str,
        task: str = "",
        evidence_context: str = "",
    ) -> str:
        """Return the merged prompt for a strategy version.

        Args:
            strategy_id: The identifier of the strategy containing the version.
            version_id: The identifier of the version whose config drives the prompt.
            task: Optional task description to include in the prompt.
            evidence_context: Optional retrieved evidence to append to the prompt.

        Returns:
            The merged prompt string for the requested strategy version.

        Raises:
            KeyError: If the strategy or version is not found.
        """
        profile = self._must_get_profile(strategy_id)
        version = self._must_get_version(profile, version_id)
        return self._prompt_builder.build(
            version.config,
            task=task,
            evidence_context=evidence_context,
        )

    def list_templates(self) -> list[StrategyTemplateMeta]:
        """Return metadata for built-in strategy templates.

        Returns:
            A list of :class:`StrategyTemplateMeta` objects for all built-in
            templates.
        """
        return list_templates()

    def _config_mutation_replay(
        self,
        *,
        actor_id: str | None,
        action: str,
        idempotency_key: str | None,
        getter: Callable[[str], Any | None],
    ) -> Any | None:
        """Return a prior mutation resource for the same replay key."""
        if actor_id is None and idempotency_key is None:
            return None
        if not actor_id or not idempotency_key:
            raise ValueError(
                "actor_id and idempotency_key must be provided together"
            )
        audit = self._repository.get_config_audit(
            actor_id=actor_id,
            action=action,
            idempotency_key=idempotency_key,
        )
        if audit is None:
            return None
        if isinstance(audit, dict):
            resource_version_id = str(audit["resource_version_id"])
        else:
            resource_version_id = str(audit.resource_version_id)
        resource = getter(resource_version_id)
        if resource is None:
            raise RuntimeError(
                "config audit replay references a missing resource version"
            )
        return resource

    def _record_config_mutation(
        self,
        *,
        actor_id: str | None,
        action: str,
        idempotency_key: str | None,
        resource_type: str,
        resource_version_id: str,
        details: dict[str, object],
    ) -> None:
        """Append a safe mutation audit when called from an authenticated API."""
        if actor_id is None and idempotency_key is None:
            return
        if not actor_id or not idempotency_key:
            raise ValueError(
                "actor_id and idempotency_key must be provided together"
            )
        self._repository.record_config_audit(
            actor_id=actor_id,
            resource_type=resource_type,
            resource_version_id=resource_version_id,
            action=action,
            idempotency_key=idempotency_key,
            details=details,
        )

    def _create_version(
        self,
        owner_id: str,
        name: str,
        description: str,
        config: StrategyConfig,
        prompt_layers: tuple,
    ) -> StrategyProfile:
        """Create and persist a new profile with a single initial version.

        Args:
            owner_id: The identifier of the profile owner.
            name: The profile and initial version name.
            description: The initial version description.
            config: The validated strategy configuration.
            prompt_layers: The ordered prompt layers for the initial version.

        Returns:
            The newly created and persisted :class:`StrategyProfile`.
        """
        version = StrategyVersion(
            strategy_id="",
            name=name,
            description=description,
            config=config,
            prompt_layers=prompt_layers,
            prompt_version="1.0.0",
        )
        profile = StrategyProfile(
            owner_id=owner_id,
            name=name,
            versions=(version,),
        )
        version = version.model_copy(update={"strategy_id": profile.strategy_id})
        profile = profile.model_copy(update={"versions": (version,)})
        self._repository.add_profile(profile)
        return profile

    def _must_get_profile(self, strategy_id: str) -> StrategyProfile:
        """Return a profile or raise a ``KeyError``.

        Args:
            strategy_id: The unique strategy identifier.

        Returns:
            The matching :class:`StrategyProfile`.

        Raises:
            KeyError: If ``strategy_id`` does not exist.
        """
        profile = self._repository.get_profile(strategy_id)
        if profile is None:
            raise KeyError(f"strategy '{strategy_id}' not found")
        return profile

    def _must_get_version(
        self,
        profile: StrategyProfile,
        version_id: str,
    ) -> StrategyVersion:
        """Return a version from a profile or raise a ``KeyError``.

        Args:
            profile: The strategy profile to search.
            version_id: The unique version identifier.

        Returns:
            The matching :class:`StrategyVersion`.

        Raises:
            KeyError: If ``version_id`` is not found in ``profile``.
        """
        for version in profile.versions:
            if version.version_id == version_id:
                return version
        raise KeyError(f"version '{version_id}' not found in strategy '{profile.strategy_id}'")

    def _replace_version(
        self,
        profile: StrategyProfile,
        version: StrategyVersion,
    ) -> StrategyProfile:
        """Return a profile with ``version`` replacing its earlier copy.

        Args:
            profile: The strategy profile containing the version to replace.
            version: The updated strategy version.

        Returns:
            A new :class:`StrategyProfile` where the version matching
            ``version.version_id`` has been replaced by ``version``.
        """
        versions = tuple(
            version if v.version_id == version.version_id else v
            for v in profile.versions
        )
        return profile.model_copy(update={"versions": versions})
