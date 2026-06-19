"""High-level strategy configuration service."""

from __future__ import annotations

from typing import Any

from margin.strategy.lifecycle import StrategyLifecycle
from margin.strategy.models import (
    StrategyConfig,
    StrategyProfile,
    StrategyState,
    StrategyTemplateMeta,
    StrategyVersion,
)
from margin.strategy.prompt import PromptLayerBuilder
from margin.strategy.repository import MemoryStrategyRepository, StrategyRepository
from margin.strategy.sandbox import StrategySandbox
from margin.strategy.templates import BUILTIN_TEMPLATES, list_templates
from margin.strategy.validator import StrategyValidator


def _deep_merge_config_delta(
    base: dict[str, Any],
    delta: dict[str, Any],
) -> dict[str, Any]:
    """Return ``base`` updated by recursively merging nested mapping values."""
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
    ) -> None:
        self._repository = repository or MemoryStrategyRepository()
        self._validator = validator or StrategyValidator()
        self._lifecycle = lifecycle or StrategyLifecycle()
        self._sandbox = sandbox or StrategySandbox(self._validator)
        self._prompt_builder = prompt_builder or PromptLayerBuilder()

    def create_from_template(
        self,
        owner_id: str,
        template_id: str,
        name: str = "",
        description: str = "",
    ) -> StrategyProfile:
        """Create a new strategy profile from a built-in template."""
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
        """Create a new strategy profile from a user-supplied config."""
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
        """Create a new version of an existing strategy."""
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
        """Run validation and sandbox on a version, advancing to backtesting."""
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
        """Mark a version as ready for paper trading."""
        profile = self._must_get_profile(strategy_id)
        version = self._must_get_version(profile, version_id)
        version = self._lifecycle.transition(version, StrategyState.PAPER_TRADING)
        updated = self._replace_version(profile, version)
        self._repository.update_profile(updated)
        return updated

    def paper_trade_version(self, strategy_id: str, version_id: str) -> StrategyProfile:
        """Record paper-trading readiness without activating the strategy."""
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
        """Activate a version for live research runs."""
        profile = self._must_get_profile(strategy_id)
        version = self._must_get_version(profile, version_id)
        if version.state != StrategyState.ACTIVE:
            version = self._lifecycle.transition(version, StrategyState.ACTIVE)
        updated = self._replace_version(profile, version)
        updated = updated.with_active_version(version_id)
        self._repository.update_profile(updated)
        return updated

    def suspend_version(
        self,
        strategy_id: str,
        version_id: str,
        reason: str = "",
    ) -> StrategyProfile:
        """Suspend an active version due to data or risk anomalies."""
        profile = self._must_get_profile(strategy_id)
        version = self._must_get_version(profile, version_id)
        version = self._lifecycle.transition(version, StrategyState.SUSPENDED, reason)
        updated = self._replace_version(profile, version)
        self._repository.update_profile(updated)
        return updated

    def archive_strategy(self, strategy_id: str) -> StrategyProfile:
        """Archive the active version of a strategy."""
        profile = self._must_get_profile(strategy_id)
        if not profile.active_version_id:
            raise ValueError("strategy has no active version")
        version = self._must_get_version(profile, profile.active_version_id)
        version = self._lifecycle.transition(version, StrategyState.ARCHIVED)
        updated = self._replace_version(profile, version)
        self._repository.update_profile(updated)
        return updated

    def get_profile(self, strategy_id: str) -> StrategyProfile:
        """Return a profile by identifier."""
        return self._must_get_profile(strategy_id)

    def list_profiles(self, owner_id: str) -> list[StrategyProfile]:
        """Return all profiles for an owner."""
        return self._repository.list_profiles(owner_id)

    def get_prompt(
        self,
        strategy_id: str,
        version_id: str,
        task: str = "",
        evidence_context: str = "",
    ) -> str:
        """Return the merged prompt for a strategy version."""
        profile = self._must_get_profile(strategy_id)
        version = self._must_get_version(profile, version_id)
        return self._prompt_builder.build(
            version.config,
            task=task,
            evidence_context=evidence_context,
        )

    def list_templates(self) -> list[StrategyTemplateMeta]:
        """Return metadata for built-in strategy templates."""
        return list_templates()

    def _create_version(
        self,
        owner_id: str,
        name: str,
        description: str,
        config: StrategyConfig,
        prompt_layers: tuple,
    ) -> StrategyProfile:
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
        profile = self._repository.get_profile(strategy_id)
        if profile is None:
            raise KeyError(f"strategy '{strategy_id}' not found")
        return profile

    def _must_get_version(
        self,
        profile: StrategyProfile,
        version_id: str,
    ) -> StrategyVersion:
        for version in profile.versions:
            if version.version_id == version_id:
                return version
        raise KeyError(f"version '{version_id}' not found in strategy '{profile.strategy_id}'")

    def _replace_version(
        self,
        profile: StrategyProfile,
        version: StrategyVersion,
    ) -> StrategyProfile:
        versions = tuple(
            version if v.version_id == version.version_id else v
            for v in profile.versions
        )
        return profile.model_copy(update={"versions": versions})
