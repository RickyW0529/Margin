"""Idempotent bootstrap for the single-user v0.3 research configuration."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from margin.agent_runtime.quant_agent import current_quant_agent_strategy_profile
from margin.strategy.models import (
    ConfigLifecycle,
    IndicatorSelectionMode,
    IndicatorViewVersion,
    ProviderConfigVersion,
    QuantFeatureSetVersion,
    QuantStrategyVersion,
    ResearchScopeVersion,
    ToolPolicyVersionRef,
    UniverseDefinitionVersion,
    UserStylePromptVersion,
)
from margin.strategy.provider_config import ProviderConfigHealthService
from margin.strategy.service import StrategyService
from margin.strategy.validator import ActivationError

OWNER_ID = "local-admin"
DEFAULT_QUANT_FEATURE_SET_VERSION_ID = "quant-feature-default-v0.4.1"
DEFAULT_QUANT_STRATEGY_VERSION_ID = "quant-strategy-ml-lifecycle-v0.4.1"
DEFAULT_SCOPE_VERSION_ID = "scope-default-v0.4.1"

DEFAULT_INDEX_UNIVERSES = {
    "CSI300": {
        "index_code": "000300.SH",
        "name": "沪深300",
        "version_id": "universe-csi300-default-v0.3.0",
    },
    "CSI500": {
        "index_code": "000905.SH",
        "name": "中证500",
        "version_id": "universe-csi500-default-v0.3.0",
    },
}


@dataclass(frozen=True)
class ProviderBootstrapSpec:
    """Non-sensitive Provider definition created before secret entry.."""

    provider_name: str
    provider_type: str
    base_url: str | None = None
    model_name: str | None = None
    secret_required: bool = True
    non_sensitive_config: dict[str, Any] = field(default_factory=dict)
    config_revision: str = "v0.2.0"

    @property
    def version_id(self) -> str:
        """Return the stable default config version ID.

        Returns:
            str: .
        """
        normalized = self.provider_name.strip().lower().replace("_", "-")
        return f"provider-{normalized}-default-{self.config_revision}"


@dataclass(frozen=True)
class BootstrapResult:
    """Configuration bootstrap summary safe for logs and API responses.."""

    scope_version_id: str | None
    provider_version_ids: tuple[str, ...]
    missing_provider_names: tuple[str, ...]


class StrategyBootstrapService:
    """Create default versioned config without overwriting user versions.."""

    def __init__(
        self,
        *,
        repository: object,
        strategy_service: StrategyService,
        health_service: ProviderConfigHealthService | None = None,
    ) -> None:
        """Initialize the bootstrap service.

        Args:
            repository: object: .
            strategy_service: StrategyService: .
            health_service: ProviderConfigHealthService | None: .

        Returns:
            None: .
        """
        self._repository = repository
        self._service = strategy_service
        self._health_service = health_service

    def ensure_defaults(
        self,
        *,
        member_security_ids: tuple[str, ...],
        providers: tuple[ProviderBootstrapSpec, ...],
        required_provider_names: tuple[str, ...],
    ) -> BootstrapResult:
        """Ensure one complete default config set and activate it when executable.

        Args:
            member_security_ids: tuple[str, ...]: .
            providers: tuple[ProviderBootstrapSpec, ...]: .
            required_provider_names: tuple[str, ...]: .

        Returns:
            BootstrapResult: .
        """
        self._ensure_universe(member_security_ids)
        self._ensure_indicator_view()
        self._ensure_quant_feature_set()
        self._ensure_quant_strategy()
        self._ensure_style_prompt()
        self._ensure_tool_policy()

        provider_ids = tuple(self._ensure_provider(spec) for spec in providers)
        active_by_name = {
            config.provider_name.strip().lower(): config
            for config in self._repository.list_active_provider_configs(OWNER_ID)
        }
        missing = tuple(
            name for name in required_provider_names if name.strip().lower() not in active_by_name
        )
        if missing:
            return BootstrapResult(
                scope_version_id=None,
                provider_version_ids=provider_ids,
                missing_provider_names=missing,
            )

        scope_id = DEFAULT_SCOPE_VERSION_ID
        scope = self._repository.get_research_scope(scope_id)
        if scope is None:
            scope = self._service.create_research_scope(
                ResearchScopeVersion(
                    version_id=scope_id,
                    owner_id=OWNER_ID,
                    universe_version_id="universe-all-a-default-v0.2.0",
                    indicator_view_version_id="indicator-view-default-v0.2.0",
                    quant_feature_set_version_id=DEFAULT_QUANT_FEATURE_SET_VERSION_ID,
                    quant_strategy_version_id=DEFAULT_QUANT_STRATEGY_VERSION_ID,
                    ai_prompt_version_id="style-prompt-default-v0.2.0",
                    canonical_rule_version="canonical-v0.3.0",
                    tool_policy_version_id="tool-policy-default-v0.2.0",
                    provider_config_version_ids=tuple(
                        sorted(
                            active_by_name[name.strip().lower()].version_id
                            for name in required_provider_names
                        )
                    ),
                    lifecycle=ConfigLifecycle.REVIEW,
                ),
                actor_id=OWNER_ID,
                idempotency_key="bootstrap-scope-create-v0.4.1",
            )
        if scope.lifecycle is not ConfigLifecycle.ACTIVE:
            self._service.activate_research_scope(
                scope.version_id,
                actor_id=OWNER_ID,
                idempotency_key="bootstrap-scope-activate-v0.4.1",
            )
        return BootstrapResult(
            scope_version_id=scope_id,
            provider_version_ids=provider_ids,
            missing_provider_names=(),
        )

    def ensure_default_index_universes(
        self,
        *,
        index_members_by_code: Mapping[str, tuple[str, ...]],
    ) -> tuple[str, ...]:
        """Ensure default CSI300/CSI500 universe versions without activating them.

        Args:
            index_members_by_code: Mapping[str, tuple[str, ...]]: .

        Returns:
            tuple[str, ...]: .
        """
        ensured_ids: list[str] = []
        for universe_code in ("CSI300", "CSI500"):
            spec = DEFAULT_INDEX_UNIVERSES[universe_code]
            members = tuple(sorted(set(index_members_by_code.get(universe_code, ()))))
            if not members:
                continue
            version_id = spec["version_id"]
            version = self._repository.get_universe_definition(version_id)
            if version is None:
                self._service.create_universe_definition(
                    UniverseDefinitionVersion(
                        version_id=version_id,
                        owner_id=OWNER_ID,
                        universe_code=universe_code,
                        name=spec["name"],
                        selection_rule={
                            "type": "index_membership",
                            "index_code": spec["index_code"],
                        },
                        member_security_ids=members,
                        lifecycle=ConfigLifecycle.REVIEW,
                    ),
                    actor_id=OWNER_ID,
                    idempotency_key=f"bootstrap-{version_id}-create",
                )
            ensured_ids.append(version_id)
        return tuple(ensured_ids)

    def _ensure_universe(self, members: tuple[str, ...]) -> None:
        """Ensure the data-driven ALL_A universe.

        Args:
            members: tuple[str, ...]: .

        Returns:
            None: .
        """
        version_id = "universe-all-a-default-v0.2.0"
        version = self._repository.get_universe_definition(version_id)
        if version is None:
            version = self._service.create_universe_definition(
                UniverseDefinitionVersion(
                    version_id=version_id,
                    owner_id=OWNER_ID,
                    universe_code="ALL_A",
                    name="全 A",
                    selection_rule={"type": "listed_security"},
                    member_security_ids=tuple(sorted(set(members))),
                    lifecycle=ConfigLifecycle.REVIEW,
                ),
                actor_id=OWNER_ID,
                idempotency_key="bootstrap-universe-create-v0.2.0",
            )
        if version.lifecycle is not ConfigLifecycle.ACTIVE:
            self._service.activate_universe_definition(
                version_id,
                actor_id=OWNER_ID,
                idempotency_key="bootstrap-universe-activate-v0.2.0",
            )

    def _ensure_indicator_view(self) -> None:
        """Ensure the default all-indicator user view.

        Returns:
            None: .
        """
        version_id = "indicator-view-default-v0.2.0"
        version = self._repository.get_indicator_view(version_id)
        if version is None:
            version = self._service.create_indicator_view(
                IndicatorViewVersion(
                    version_id=version_id,
                    owner_id=OWNER_ID,
                    mode=IndicatorSelectionMode.ALL,
                    lifecycle=ConfigLifecycle.REVIEW,
                ),
                actor_id=OWNER_ID,
                idempotency_key="bootstrap-indicator-view-create-v0.2.0",
            )
        if version.lifecycle is not ConfigLifecycle.ACTIVE:
            self._service.activate_indicator_view(
                version_id,
                actor_id=OWNER_ID,
                idempotency_key="bootstrap-indicator-view-activate-v0.2.0",
            )

    def _ensure_quant_feature_set(self) -> None:
        """Ensure the PIT quant input contract.

        Returns:
            None: .
        """
        version_id = DEFAULT_QUANT_FEATURE_SET_VERSION_ID
        version = self._repository.get_quant_feature_set(version_id)
        if version is None:
            version = self._service.create_quant_feature_set(
                QuantFeatureSetVersion(
                    version_id=version_id,
                    owner_id=OWNER_ID,
                    required_indicators=("roe_ttm", "pe_ttm"),
                    optional_indicators=(
                        "n_income_attr_p",
                        "net_profit_y1",
                        "net_profit_y2",
                        "roic_ttm",
                        "gross_margin_ttm",
                        "net_margin_ttm",
                        "ocf_to_net_profit",
                        "liability_ratio",
                        "interest_coverage",
                        "pb",
                        "ps",
                        "market_cap",
                        "fcf_yield",
                        "dividend_yield",
                        "revenue_yoy",
                        "profit_yoy",
                        "revenue_cagr_3y",
                        "profit_cagr_3y",
                        "margin_trend",
                        "roe_trend",
                        "return_20d",
                        "return_6m_ex_1m",
                        "return_12m_ex_1m",
                        "industry_relative_momentum",
                        "index_relative_momentum",
                        "ma_trend",
                        "volatility_120d",
                        "max_drawdown_250d",
                        "avg_amount_20d",
                        "volume_ratio",
                        "circ_mv",
                        "float_share",
                        "free_share",
                        "mf_lg_net_amount",
                        "mf_elg_net_amount",
                        "net_mf_amount",
                        "margin_rzye",
                        "margin_rzmre",
                        "margin_rqye",
                        "forecast_p_change_mid",
                        "express_yoy_net_profit",
                        "limit_flag",
                        "limit_trade_blocked",
                        "goodwill_to_equity",
                        "receivable_risk",
                        "inventory_risk",
                        "pledge_ratio",
                    ),
                    history_days=750,
                    fallback_policy="mark_missing",
                    lifecycle=ConfigLifecycle.REVIEW,
                ),
                actor_id=OWNER_ID,
                idempotency_key="bootstrap-quant-feature-create-v0.4.1",
            )
        if version.lifecycle is not ConfigLifecycle.ACTIVE:
            self._service.activate_quant_feature_set(
                version_id,
                actor_id=OWNER_ID,
                idempotency_key="bootstrap-quant-feature-activate-v0.4.1",
            )

    def _ensure_quant_strategy(self) -> None:
        """Ensure the approved QuantAgent ML lifecycle policy.

        Returns:
            None: .
        """
        version_id = DEFAULT_QUANT_STRATEGY_VERSION_ID
        version = self._repository.get_quant_strategy(version_id)
        if version is None:
            profile = current_quant_agent_strategy_profile()
            thresholds = dict(profile.to_quant_strategy_metadata()["thresholds"])
            thresholds.update(
                {
                    "pass_threshold": 70.0,
                    "near_threshold": 60.0,
                    "watch_threshold": 50.0,
                }
            )
            version = self._service.create_quant_strategy(
                QuantStrategyVersion(
                    version_id=version_id,
                    owner_id=OWNER_ID,
                    strategy_family=profile.strategy_family,
                    factor_weights={},
                    thresholds=thresholds,
                    calibration_report_id=profile.profile_id,
                    lifecycle=ConfigLifecycle.REVIEW,
                ),
                actor_id=OWNER_ID,
                idempotency_key="bootstrap-quant-strategy-create-v0.4.1",
            )
        if version.lifecycle is not ConfigLifecycle.ACTIVE:
            self._service.activate_quant_strategy(
                version_id,
                actor_id=OWNER_ID,
                idempotency_key="bootstrap-quant-strategy-activate-v0.4.1",
            )

    def _ensure_style_prompt(self) -> None:
        """Ensure the default evidence-first output style.

        Returns:
            None: .
        """
        version_id = "style-prompt-default-v0.2.0"
        version = self._repository.get_user_style_prompt(version_id)
        if version is None:
            version = self._service.create_user_style_prompt(
                UserStylePromptVersion(
                    version_id=version_id,
                    owner_id=OWNER_ID,
                    prompt_name="default",
                    content=(
                        "使用简洁中文，区分事实、推断与不确定性；所有关键判断"
                        "必须引用冻结证据，不输出直接买卖指令。"
                    ),
                    lifecycle=ConfigLifecycle.REVIEW,
                ),
                actor_id=OWNER_ID,
                idempotency_key="bootstrap-style-prompt-create-v0.2.0",
            )
        if version.lifecycle is not ConfigLifecycle.ACTIVE:
            self._service.activate_user_style_prompt(
                version_id,
                actor_id=OWNER_ID,
                idempotency_key="bootstrap-style-prompt-activate-v0.2.0",
            )

    def _ensure_tool_policy(self) -> None:
        """Ensure the read-only AI delta-review tool boundary.

        Returns:
            None: .
        """
        version_id = "tool-policy-default-v0.2.0"
        version = self._repository.get_tool_policy(version_id)
        if version is None:
            version = self._service.create_tool_policy(
                ToolPolicyVersionRef(
                    version_id=version_id,
                    owner_id=OWNER_ID,
                    allowed_tool_names=(
                        "research_context.load",
                        "evidence.retrieve",
                        "evidence.validate",
                        "quant_result.load",
                        "previous_assessment.load",
                    ),
                    denied_tool_names=(
                        "websearch.live",
                        "provider.call",
                        "data.sync",
                        "order.write",
                    ),
                    lifecycle=ConfigLifecycle.REVIEW,
                ),
                actor_id=OWNER_ID,
                idempotency_key="bootstrap-tool-policy-create-v0.2.0",
            )
        if version.lifecycle is not ConfigLifecycle.ACTIVE:
            self._service.activate_tool_policy(
                version_id,
                actor_id=OWNER_ID,
                idempotency_key="bootstrap-tool-policy-activate-v0.2.0",
            )

    def _ensure_provider(self, spec: ProviderBootstrapSpec) -> str:
        """Ensure one non-sensitive Provider config and activate if possible.

        Args:
            spec: ProviderBootstrapSpec: .

        Returns:
            str: .
        """
        version = self._repository.get_provider_config(spec.version_id)
        if version is None:
            config = dict(spec.non_sensitive_config)
            config["secret_required"] = spec.secret_required
            version = self._service.create_provider_config(
                ProviderConfigVersion(
                    version_id=spec.version_id,
                    provider_name=spec.provider_name,
                    provider_type=spec.provider_type,
                    owner_id=OWNER_ID,
                    base_url=spec.base_url,
                    model_name=spec.model_name,
                    non_sensitive_config=config,
                    lifecycle=ConfigLifecycle.REVIEW,
                ),
                actor_id=OWNER_ID,
                idempotency_key=f"bootstrap-{spec.version_id}-create",
            )
        if (
            version.lifecycle is not ConfigLifecycle.ACTIVE
            and not spec.secret_required
            and self._health_service is not None
        ):
            try:
                self._service.activate_provider_config(
                    version.version_id,
                    health_service=self._health_service,
                    actor_id=OWNER_ID,
                    idempotency_key=f"bootstrap-{spec.version_id}-activate",
                )
            except ActivationError:
                pass
        return version.version_id
