"""Feature capability reporting from active provider configuration."""

from __future__ import annotations

from dataclasses import dataclass

from margin.strategy.models import ConfigLifecycle, ProviderConfigVersion
from margin.strategy.provider_router import provider_category_for_config
from margin.strategy.provider_runtime import provider_capabilities_for_config


@dataclass(frozen=True)
class FeatureCapabilityStatus:
    """One feature's local availability status."""

    name: str
    enabled: bool
    missing: tuple[str, ...] = ()


_FEATURE_REQUIREMENTS: dict[str, tuple[str, ...]] = {
    "api": (),
    "market_data": ("data_source.market_quote",),
    "news": ("web_search",),
    "agent_runtime": ("llm",),
    "valuation_discovery": (
        "data_source.quant_required_financials",
        "web_search",
        "embedding",
        "llm",
    ),
}


def build_feature_capabilities(
    provider_configs: tuple[ProviderConfigVersion, ...],
) -> dict[str, FeatureCapabilityStatus]:
    """Build feature availability from active Provider config metadata."""
    active_configs = tuple(
        config
        for config in provider_configs
        if config.lifecycle is ConfigLifecycle.ACTIVE
    )
    available = _available_requirements(active_configs)
    return {
        feature_name: FeatureCapabilityStatus(
            name=feature_name,
            enabled=all(requirement in available for requirement in requirements),
            missing=tuple(
                _missing_requirement(requirement, available)
                for requirement in requirements
                if requirement not in available
            ),
        )
        for feature_name, requirements in _FEATURE_REQUIREMENTS.items()
    }


def _available_requirements(
    provider_configs: tuple[ProviderConfigVersion, ...],
) -> frozenset[str]:
    """Return provider category and capability requirements that are satisfied."""
    available: set[str] = set()
    for config in provider_configs:
        category = provider_category_for_config(
            config.provider_type,
            config.provider_name,
            config.non_sensitive_config,
        )
        secret_required = bool(
            config.non_sensitive_config.get("secret_required", True)
        )
        if secret_required and config.secret_version_id is None:
            available.add(f"{category}.missing_secret")
            continue
        available.add(category)
        for capability in provider_capabilities_for_config(config):
            available.add(f"{category}.{capability}")
    return frozenset(available)


def _missing_requirement(requirement: str, available: frozenset[str]) -> str:
    """Return a user-actionable missing requirement label."""
    category = requirement.split(".", maxsplit=1)[0]
    if f"{category}.missing_secret" in available:
        return f"{category}.secret"
    return requirement
