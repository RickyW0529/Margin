"""Idempotent production configuration bootstrap tests.

This module validates that the strategy bootstrap service creates default
configuration idempotently, handles missing required providers gracefully,
and tolerates optional provider health failures.
"""

from __future__ import annotations

import os

from margin.core.secret_store import SecretStore, SQLAlchemySecretRepository
from margin.storage.base import Base
from margin.storage.database import (
    DatabaseSettings,
    create_database_engine,
    create_session_factory,
)
from margin.strategy.bootstrap import (
    ProviderBootstrapSpec,
    StrategyBootstrapService,
)
from margin.strategy.models import (
    ConfigLifecycle,
    IndicatorSelectionMode,
    IndicatorViewVersion,
    QuantFeatureSetVersion,
    QuantStrategyVersion,
    ResearchScopeVersion,
    ToolPolicyVersionRef,
    UniverseDefinitionVersion,
    UserStylePromptVersion,
)
from margin.strategy.provider_config import ProviderConfigHealthService
from margin.strategy.repository import MemoryStrategyRepository
from margin.strategy.service import StrategyService


def test_bootstrap_creates_one_executable_default_scope_idempotently(
    database_url: str,
) -> None:
    """Verify bootstrap produces an active base config without duplicating versions.

    Args:
        database_url: str: .

    Returns:
        None: .
    """
    engine = create_database_engine(DatabaseSettings(url=database_url))
    Base.metadata.create_all(engine)
    secret_store = SecretStore(
        SQLAlchemySecretRepository(create_session_factory(engine)),
        master_key=os.urandom(32),
    )
    repository = MemoryStrategyRepository()
    health_service = ProviderConfigHealthService(
        repository,
        secret_store,
        health_adapters={"akshare": lambda _config, _secret: None},
    )
    bootstrap = StrategyBootstrapService(
        repository=repository,
        strategy_service=StrategyService(repository=repository),
        health_service=health_service,
    )
    providers = (
        ProviderBootstrapSpec(
            provider_name="akshare",
            provider_type="market_data",
            secret_required=False,
        ),
    )

    first = bootstrap.ensure_defaults(
        member_security_ids=("sec-1", "sec-2"),
        providers=providers,
        required_provider_names=("akshare",),
    )
    second = bootstrap.ensure_defaults(
        member_security_ids=("sec-1", "sec-2"),
        providers=providers,
        required_provider_names=("akshare",),
    )

    assert first.scope_version_id == "scope-default-v0.4.1"
    assert second.scope_version_id == first.scope_version_id
    assert len(repository.list_provider_configs("local-admin")) == 1
    assert len(repository.list_universe_definitions("local-admin")) == 1
    assert len(repository.list_research_scopes("local-admin")) == 1
    assert repository.get_active_research_scope("local-admin") is not None
    engine.dispose()


def test_bootstrap_creates_v03_defaults_when_v02_history_exists(
    database_url: str,
) -> None:
    """Verify v0.3 bootstrap does not reuse stale v0.2 quant versions.

    Args:
        database_url: str: .

    Returns:
        None: .
    """
    engine = create_database_engine(DatabaseSettings(url=database_url))
    Base.metadata.create_all(engine)
    secret_store = SecretStore(
        SQLAlchemySecretRepository(create_session_factory(engine)),
        master_key=os.urandom(32),
    )
    repository = MemoryStrategyRepository()
    repository.save_universe_definition(
        UniverseDefinitionVersion(
            version_id="universe-all-a-default-v0.2.0",
            universe_code="ALL_A",
            name="全部A股",
            member_security_ids=("sec-1",),
            lifecycle=ConfigLifecycle.ACTIVE,
        )
    )
    repository.save_indicator_view(
        IndicatorViewVersion(
            version_id="indicator-view-default-v0.2.0",
            owner_id="local-admin",
            mode=IndicatorSelectionMode.ALL,
            lifecycle=ConfigLifecycle.ACTIVE,
        )
    )
    repository.save_quant_feature_set(
        QuantFeatureSetVersion(
            version_id="quant-feature-default-v0.2.0",
            required_indicators=("net_profit_ttm", "pe_ttm"),
            lifecycle=ConfigLifecycle.ACTIVE,
        )
    )
    repository.save_quant_strategy(
        QuantStrategyVersion(
            version_id="quant-strategy-default-v0.2.0",
            factor_weights={"quality": 0.35, "value": 0.25},
            thresholds={"pass": 80, "near_threshold": 70},
            lifecycle=ConfigLifecycle.ACTIVE,
        )
    )
    repository.save_user_style_prompt(
        UserStylePromptVersion(
            version_id="style-prompt-default-v0.2.0",
            owner_id="local-admin",
            content="保持克制。",
            lifecycle=ConfigLifecycle.ACTIVE,
        )
    )
    repository.save_tool_policy(
        ToolPolicyVersionRef(
            version_id="tool-policy-default-v0.2.0",
            lifecycle=ConfigLifecycle.ACTIVE,
        )
    )
    repository.save_research_scope(
        ResearchScopeVersion(
            version_id="scope-default-v0.2.0",
            universe_version_id="universe-all-a-default-v0.2.0",
            indicator_view_version_id="indicator-view-default-v0.2.0",
            quant_feature_set_version_id="quant-feature-default-v0.2.0",
            quant_strategy_version_id="quant-strategy-default-v0.2.0",
            ai_prompt_version_id="style-prompt-default-v0.2.0",
            canonical_rule_version="canonical-v0.2.0",
            tool_policy_version_id="tool-policy-default-v0.2.0",
            lifecycle=ConfigLifecycle.ACTIVE,
        )
    )
    health_service = ProviderConfigHealthService(
        repository,
        secret_store,
        health_adapters={"akshare": lambda _config, _secret: None},
    )
    bootstrap = StrategyBootstrapService(
        repository=repository,
        strategy_service=StrategyService(repository=repository),
        health_service=health_service,
    )

    result = bootstrap.ensure_defaults(
        member_security_ids=("sec-1",),
        providers=(
            ProviderBootstrapSpec(
                provider_name="akshare",
                provider_type="market_data",
                secret_required=False,
            ),
        ),
        required_provider_names=("akshare",),
    )

    active_scope = repository.get_active_research_scope("local-admin")
    feature_set = repository.get_quant_feature_set("quant-feature-default-v0.4.1")
    strategy = repository.get_quant_strategy("quant-strategy-ml-lifecycle-v0.4.1")
    assert result.scope_version_id == "scope-default-v0.4.1"
    assert active_scope is not None
    assert active_scope.quant_feature_set_version_id == "quant-feature-default-v0.4.1"
    assert active_scope.quant_strategy_version_id == "quant-strategy-ml-lifecycle-v0.4.1"
    assert feature_set is not None
    assert feature_set.required_indicators == ("roe_ttm", "pe_ttm")
    assert "n_income_attr_p" in feature_set.optional_indicators
    assert "net_profit_y1" in feature_set.optional_indicators
    assert "mf_lg_net_amount" in feature_set.optional_indicators
    assert "limit_trade_blocked" in feature_set.optional_indicators
    assert strategy is not None
    assert strategy.strategy_family == "ml_lgbm_lifecycle"
    assert strategy.thresholds["top_n"] == 40
    assert strategy.thresholds["max_stock_exposure"] == 0.8
    assert repository.get_research_scope("scope-default-v0.2.0") is not None
    engine.dispose()


def test_bootstrap_does_not_activate_scope_when_required_provider_is_missing() -> None:
    """Verify a partial Provider setup remains visible but is not executable.

    Returns:
        None: .
    """
    repository = MemoryStrategyRepository()
    bootstrap = StrategyBootstrapService(
        repository=repository,
        strategy_service=StrategyService(repository=repository),
    )

    result = bootstrap.ensure_defaults(
        member_security_ids=("sec-1",),
        providers=(),
        required_provider_names=("llm",),
    )

    assert result.scope_version_id is None
    assert result.missing_provider_names == ("llm",)
    assert repository.get_active_research_scope("local-admin") is None


def test_bootstrap_creates_default_index_universes_without_switching_scope() -> None:
    """Verify CSI300/CSI500 defaults are visible but do not change scope.

    Returns:
        None: .
    """
    repository = MemoryStrategyRepository()
    bootstrap = StrategyBootstrapService(
        repository=repository,
        strategy_service=StrategyService(repository=repository),
    )

    first = bootstrap.ensure_default_index_universes(
        index_members_by_code={
            "CSI300": ("000002.SZ", "000001.SZ", "000001.SZ"),
            "CSI500": ("600000.SH",),
        }
    )
    second = bootstrap.ensure_default_index_universes(
        index_members_by_code={
            "CSI300": ("000002.SZ", "000001.SZ"),
            "CSI500": ("600000.SH",),
        }
    )

    csi300 = repository.get_universe_definition("universe-csi300-default-v0.3.0")
    csi500 = repository.get_universe_definition("universe-csi500-default-v0.3.0")
    assert first == (
        "universe-csi300-default-v0.3.0",
        "universe-csi500-default-v0.3.0",
    )
    assert second == first
    assert csi300 is not None
    assert csi300.lifecycle.value == "review"
    assert csi300.selection_rule == {
        "type": "index_membership",
        "index_code": "000300.SH",
    }
    assert csi300.member_security_ids == ("000001.SZ", "000002.SZ")
    assert csi500 is not None
    assert csi500.member_security_ids == ("600000.SH",)
    assert len(repository.list_universe_definitions("local-admin")) == 2
    assert repository.get_active_research_scope("local-admin") is None


def test_optional_provider_health_failure_does_not_abort_bootstrap(
    database_url: str,
) -> None:
    """Verify a failed optional adapter stays in review while base config remains usable.

    Args:
        database_url: str: .

    Returns:
        None: .
    """
    engine = create_database_engine(DatabaseSettings(url=database_url))
    Base.metadata.create_all(engine)
    secret_store = SecretStore(
        SQLAlchemySecretRepository(create_session_factory(engine)),
        master_key=os.urandom(32),
    )
    repository = MemoryStrategyRepository()
    health_service = ProviderConfigHealthService(
        repository,
        secret_store,
        health_adapters={
            "akshare": lambda _config, _secret: (_ for _ in ()).throw(
                RuntimeError("upstream unavailable")
            )
        },
    )
    bootstrap = StrategyBootstrapService(
        repository=repository,
        strategy_service=StrategyService(repository=repository),
        health_service=health_service,
    )

    result = bootstrap.ensure_defaults(
        member_security_ids=("sec-1",),
        providers=(
            ProviderBootstrapSpec(
                provider_name="akshare",
                provider_type="market_data",
                secret_required=False,
            ),
        ),
        required_provider_names=("llm",),
    )

    assert result.scope_version_id is None
    assert (
        repository.get_provider_config("provider-akshare-default-v0.2.0").lifecycle.value
        == "review"
    )
    engine.dispose()
