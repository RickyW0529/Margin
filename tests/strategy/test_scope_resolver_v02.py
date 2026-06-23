"""v0.2 strategy scope and configuration model tests."""

from __future__ import annotations

from sqlalchemy.engine import make_url

from margin.strategy.models import (
    ConfigLifecycle,
    IndicatorSelectionMode,
    IndicatorViewVersion,
    QuantFeatureSetVersion,
    ResearchScopeVersion,
)
from scripts.verify_migrations import verify_clean_database


def test_strategy_config_v02_tables_exist(database_url: str) -> None:
    """strategy config v02 tables exist."""
    url = make_url(database_url)
    result = verify_clean_database(
        database_url,
        database_name=f"{url.database}_strategy_migration",
        drop_existing=True,
    )

    assert {
        "provider_config_versions",
        "provider_secret_versions",
        "universe_definition_versions",
        "indicator_view_versions",
        "quant_feature_set_versions",
        "quant_strategy_versions",
        "user_style_prompt_versions",
        "tool_policy_versions",
        "research_scope_versions",
        "strategy_config_audits",
    } <= set(result.tables)


def test_indicator_view_does_not_remove_required_quant_features() -> None:
    """indicator view does not remove required quant features."""
    view = IndicatorViewVersion(
        version_id="view-1",
        owner_id="local-admin",
        mode=IndicatorSelectionMode.EXCLUDE,
        excluded_indicators=("pb",),
    )
    feature_set = QuantFeatureSetVersion(
        version_id="feature-1",
        required_indicators=("roe_ttm", "pb"),
        optional_indicators=("dividend_yield",),
        history_days=750,
        fallback_policy="mark_missing",
    )

    assert view.visible_indicator_ids(("roe_ttm", "pb", "dividend_yield")) == (
        "roe_ttm",
        "dividend_yield",
    )
    assert feature_set.required_indicators == ("roe_ttm", "pb")


def test_research_scope_hash_is_deterministic() -> None:
    """research scope hash is deterministic."""
    scope = ResearchScopeVersion(
        version_id="scope-1",
        universe_version_id="univ-1",
        indicator_view_version_id="view-1",
        quant_feature_set_version_id="feature-1",
        quant_strategy_version_id="qstrat-1",
        ai_prompt_version_id="prompt-1",
        canonical_rule_version="canonical-v0.2.0",
        tool_policy_version_id="tool-policy-v0.2.0",
        provider_config_version_ids=("provider-tavily-1", "provider-tushare-1"),
    )
    same_scope = scope.model_copy()

    assert scope.lifecycle == ConfigLifecycle.DRAFT
    assert scope.scope_hash.startswith("sha256:")
    assert scope.scope_hash == same_scope.scope_hash
