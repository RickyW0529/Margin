"""Strategy configuration query factory."""

from __future__ import annotations

from typing import Any

from sqlalchemy import Select, select
from sqlalchemy.dialects.postgresql import insert

from margin.strategy.db_models import (
    IndicatorViewVersionRow,
    ProviderConfigVersionRow,
    QuantFeatureSetVersionRow,
    QuantStrategyVersionRow,
    ResearchScopeVersionRow,
    StrategyConfigAuditRow,
    ToolPolicyVersionRow,
    UniverseDefinitionVersionRow,
    UserStylePromptVersionRow,
)


def provider_configs_by_owner(owner_id: str) -> Select:
    """List provider config versions for an owner."""
    return (
        select(ProviderConfigVersionRow)
        .where(ProviderConfigVersionRow.owner_id == owner_id)
        .order_by(ProviderConfigVersionRow.version_id)
    )


def active_provider_configs_by_owner(owner_id: str, lifecycle_value: str) -> Select:
    """List enabled active provider config versions for an owner."""
    return (
        select(ProviderConfigVersionRow)
        .where(ProviderConfigVersionRow.owner_id == owner_id)
        .where(ProviderConfigVersionRow.lifecycle == lifecycle_value)
        .where(ProviderConfigVersionRow.enabled.is_(True))
        .order_by(ProviderConfigVersionRow.version_id)
    )


def active_provider_configs_by_owner_and_provider(
    owner_id: str,
    provider_name: str,
    lifecycle_value: str,
) -> Select:
    """List active provider config versions for an owner and provider name."""
    return (
        select(ProviderConfigVersionRow)
        .where(ProviderConfigVersionRow.owner_id == owner_id)
        .where(ProviderConfigVersionRow.provider_name == provider_name)
        .where(ProviderConfigVersionRow.lifecycle == lifecycle_value)
    )


def universe_definitions_by_owner(owner_id: str) -> Select:
    """List universe definition versions for an owner."""
    return (
        select(UniverseDefinitionVersionRow)
        .where(UniverseDefinitionVersionRow.owner_id == owner_id)
        .order_by(UniverseDefinitionVersionRow.version_id)
    )


def active_universe_definitions_by_owner(
    owner_id: str,
    lifecycle_value: str,
    universe_code: str | None = None,
) -> Select:
    """List active universe definitions for an owner, optionally filtered by code."""
    stmt = (
        select(UniverseDefinitionVersionRow)
        .where(UniverseDefinitionVersionRow.owner_id == owner_id)
        .where(UniverseDefinitionVersionRow.lifecycle == lifecycle_value)
    )
    if universe_code is not None:
        stmt = stmt.where(UniverseDefinitionVersionRow.universe_code == universe_code)
    return stmt.order_by(UniverseDefinitionVersionRow.version_id)


def indicator_views_by_owner(owner_id: str) -> Select:
    """List indicator view versions for an owner."""
    return (
        select(IndicatorViewVersionRow)
        .where(IndicatorViewVersionRow.owner_id == owner_id)
        .order_by(IndicatorViewVersionRow.version_id)
    )


def active_indicator_views_by_owner(owner_id: str, lifecycle_value: str) -> Select:
    """List active indicator view versions for an owner."""
    return (
        select(IndicatorViewVersionRow)
        .where(IndicatorViewVersionRow.owner_id == owner_id)
        .where(IndicatorViewVersionRow.lifecycle == lifecycle_value)
        .order_by(IndicatorViewVersionRow.version_id)
    )


def quant_feature_sets_by_owner(owner_id: str) -> Select:
    """List quant feature set versions for an owner."""
    return (
        select(QuantFeatureSetVersionRow)
        .where(QuantFeatureSetVersionRow.owner_id == owner_id)
        .order_by(QuantFeatureSetVersionRow.version_id)
    )


def active_quant_feature_sets_by_owner(owner_id: str, lifecycle_value: str) -> Select:
    """List active quant feature set versions for an owner."""
    return (
        select(QuantFeatureSetVersionRow)
        .where(QuantFeatureSetVersionRow.owner_id == owner_id)
        .where(QuantFeatureSetVersionRow.lifecycle == lifecycle_value)
        .order_by(QuantFeatureSetVersionRow.version_id)
    )


def quant_strategies_by_owner(owner_id: str) -> Select:
    """List quant strategy versions for an owner."""
    return (
        select(QuantStrategyVersionRow)
        .where(QuantStrategyVersionRow.owner_id == owner_id)
        .order_by(QuantStrategyVersionRow.version_id)
    )


def active_quant_strategies_by_owner_and_family(
    owner_id: str,
    strategy_family: str,
    lifecycle_value: str,
) -> Select:
    """List active quant strategy versions for an owner and family."""
    return (
        select(QuantStrategyVersionRow)
        .where(QuantStrategyVersionRow.owner_id == owner_id)
        .where(QuantStrategyVersionRow.strategy_family == strategy_family)
        .where(QuantStrategyVersionRow.lifecycle == lifecycle_value)
        .order_by(QuantStrategyVersionRow.version_id)
    )


def user_style_prompts_by_owner(owner_id: str) -> Select:
    """List user style prompt versions for an owner."""
    return (
        select(UserStylePromptVersionRow)
        .where(UserStylePromptVersionRow.owner_id == owner_id)
        .order_by(UserStylePromptVersionRow.version_id)
    )


def active_user_style_prompts_by_owner_and_name(
    owner_id: str,
    prompt_name: str,
    lifecycle_value: str,
) -> Select:
    """List active user style prompt versions for an owner and prompt name."""
    return (
        select(UserStylePromptVersionRow)
        .where(UserStylePromptVersionRow.owner_id == owner_id)
        .where(UserStylePromptVersionRow.prompt_name == prompt_name)
        .where(UserStylePromptVersionRow.lifecycle == lifecycle_value)
        .order_by(UserStylePromptVersionRow.version_id)
    )


def active_tool_policies_by_owner(owner_id: str, lifecycle_value: str) -> Select:
    """List active tool policy versions for an owner."""
    return (
        select(ToolPolicyVersionRow)
        .where(ToolPolicyVersionRow.owner_id == owner_id)
        .where(ToolPolicyVersionRow.lifecycle == lifecycle_value)
        .order_by(ToolPolicyVersionRow.version_id)
    )


def research_scopes_by_owner(owner_id: str) -> Select:
    """List research scope versions for an owner."""
    return (
        select(ResearchScopeVersionRow)
        .where(ResearchScopeVersionRow.owner_id == owner_id)
        .order_by(ResearchScopeVersionRow.version_id)
    )


def active_research_scopes_by_owner(owner_id: str, lifecycle_value: str) -> Select:
    """List active research scope versions for an owner."""
    return (
        select(ResearchScopeVersionRow)
        .where(ResearchScopeVersionRow.owner_id == owner_id)
        .where(ResearchScopeVersionRow.lifecycle == lifecycle_value)
        .order_by(ResearchScopeVersionRow.version_id)
    )


def config_audit_by_replay_key(
    actor_id: str,
    action: str,
    idempotency_key: str,
) -> Select:
    """Return a config audit event by actor, action and idempotency key."""
    return (
        select(StrategyConfigAuditRow)
        .where(StrategyConfigAuditRow.actor_id == actor_id)
        .where(StrategyConfigAuditRow.action == action)
        .where(StrategyConfigAuditRow.idempotency_key == idempotency_key)
    )


def insert_config_audit(
    *,
    audit_id: str,
    actor_id: str,
    resource_type: str,
    resource_version_id: str,
    action: str,
    idempotency_key: str,
    details: dict[str, object],
    created_at: Any,
) -> Any:
    """Insert one idempotent config audit event."""
    return (
        insert(StrategyConfigAuditRow)
        .values(
            audit_id=audit_id,
            actor_id=actor_id,
            resource_type=resource_type,
            resource_version_id=resource_version_id,
            action=action,
            idempotency_key=idempotency_key,
            details=details,
            created_at=created_at,
        )
        .on_conflict_do_nothing(
            index_elements=["actor_id", "action", "idempotency_key"],
            index_where=StrategyConfigAuditRow.idempotency_key.is_not(None),
        )
    )
