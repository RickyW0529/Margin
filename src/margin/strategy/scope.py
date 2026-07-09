"""Research scope resolution for v0.2 strategy configuration."""

from __future__ import annotations

import uuid
from typing import TypeVar

from margin.strategy.models import ConfigLifecycle, ResearchScopeVersion
from margin.strategy.validator import ActivationError, StrategyActivationValidator

T = TypeVar("T")


class ScopeResolver:
    """Resolve the immutable config version set used by downstream runs.."""

    def __init__(
        self,
        repository: object,
        *,
        validator: StrategyActivationValidator | None = None,
    ) -> None:
        """Initialize the instance.

        Args:
            repository: object: .
            validator: StrategyActivationValidator | None: .

        Returns:
            None: .
        """
        self._repository = repository
        self._validator = validator or StrategyActivationValidator()

    def resolve_active_scope(
        self,
        *,
        owner_id: str,
        universe_code: str | None = None,
        strategy_family: str = "default",
        prompt_name: str = "default",
        canonical_rule_version: str = "canonical-v0.2.0",
    ) -> ResearchScopeVersion:
        """Return a frozen scope from the active versioned configuration.

        Args:
            owner_id: str: .
            universe_code: str | None: .
            strategy_family: str: .
            prompt_name: str: .
            canonical_rule_version: str: .

        Returns:
            ResearchScopeVersion: .
        """
        active_scope = self._repository.get_active_research_scope(owner_id)
        if active_scope is not None:
            self._validator.validate_research_scope_activation(
                active_scope,
                self._repository,
            )
            return active_scope

        universe = self._resolve_single_active_universe(owner_id, universe_code)
        indicator_view = self._require(
            self._repository.get_active_indicator_view(owner_id),
            "active indicator view",
        )
        feature_set = self._require(
            self._repository.get_active_quant_feature_set(owner_id),
            "active quant feature set",
        )
        quant_strategy = self._require(
            self._repository.get_active_quant_strategy(
                owner_id,
                strategy_family=strategy_family,
            ),
            "active quant strategy",
        )
        style_prompt = self._require(
            self._repository.get_active_user_style_prompt(
                owner_id,
                prompt_name=prompt_name,
            ),
            "active style prompt",
        )
        tool_policy = self._require(
            self._repository.get_active_tool_policy(owner_id),
            "active tool policy",
        )
        provider_configs = tuple(
            version.version_id
            for version in self._repository.list_active_provider_configs(owner_id)
        )
        if not provider_configs:
            raise ActivationError("active provider config not found")

        scope = ResearchScopeVersion(
            version_id=f"scope_{uuid.uuid4().hex[:12]}",
            owner_id=owner_id,
            universe_version_id=universe.version_id,
            indicator_view_version_id=indicator_view.version_id,
            quant_feature_set_version_id=feature_set.version_id,
            quant_strategy_version_id=quant_strategy.version_id,
            ai_prompt_version_id=style_prompt.version_id,
            canonical_rule_version=canonical_rule_version,
            tool_policy_version_id=tool_policy.version_id,
            provider_config_version_ids=provider_configs,
            lifecycle=ConfigLifecycle.ACTIVE,
        )
        self._validator.validate_research_scope_activation(scope, self._repository)
        return scope

    def _resolve_single_active_universe(
        self,
        owner_id: str,
        universe_code: str | None,
    ) -> object:
        """resolve single active universe.

        Args:
            owner_id: str: .
            universe_code: str | None: .

        Returns:
            object: .
        """
        universes = self._repository.list_active_universe_definitions(
            owner_id,
            universe_code=universe_code,
        )
        if not universes:
            raise ActivationError("active universe definition not found")
        if len(universes) > 1:
            raise ActivationError("multiple active universe definitions found; pass universe_code")
        return universes[0]

    @staticmethod
    def _require(value: T | None, resource_name: str) -> T:
        """require.

        Args:
            value: T | None: .
            resource_name: str: .

        Returns:
            T: .
        """
        if value is None:
            raise ActivationError(f"{resource_name} not found")
        return value
