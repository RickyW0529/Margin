"""Built-in strategy templates for the strategy configuration module."""

from __future__ import annotations

from dataclasses import dataclass

from margin.strategy.models import (
    AIConfig,
    DecisionConfig,
    EvidenceConfig,
    QualityConfig,
    RiskConfig,
    StrategyConfig,
    StrategyTemplateMeta,
    ValuationConfig,
)


@dataclass(frozen=True)
class StrategyTemplate:
    """A built-in strategy template with metadata and default config."""

    meta: StrategyTemplateMeta
    config: StrategyConfig


def _value_quality() -> StrategyTemplate:
    """Return the "value quality" built-in strategy template."""
    return StrategyTemplate(
        meta=StrategyTemplateMeta(
            template_id="value_quality",
            name="价值质量",
            description="精选低估值、高质量龙头，注重 ROE 与现金流稳定性。",
            category="value",
        ),
        config=StrategyConfig(
            universe=["000001.SZ", "000002.SZ", "600519.SH"],
            horizon=180,
            valuation=ValuationConfig(method="pe", eps=1.0, pe=15.0),
            quality=QualityConfig(min_source_level="L2", require_primary_source=True),
            risk=RiskConfig(max_position_weight=0.1, max_sector_weight=0.25),
            ai=AIConfig(
                system_prompt_template="value_quality",
                custom_instructions="重点关注 ROE、经营现金流和自由现金流。",
            ),
            evidence=EvidenceConfig(required_levels=["L1", "L2"], min_evidence_count=3),
            decision=DecisionConfig(
                research_states=["research_candidate", "watch", "abstained"],
                position_review_states=["hold", "review", "close"],
                prohibited_outputs=[],
            ),
        ),
    )


def _undervalued_recovery() -> StrategyTemplate:
    """Return the "undervalued recovery" built-in strategy template."""
    return StrategyTemplate(
        meta=StrategyTemplateMeta(
            template_id="undervalued_recovery",
            name="低估修复",
            description="寻找短期利空导致估值压制、具备修复弹性的标的。",
            category="value",
        ),
        config=StrategyConfig(
            universe=["000001.SZ", "000858.SZ", "601318.SH"],
            horizon=90,
            valuation=ValuationConfig(method="pe", eps=1.0, pe=12.0),
            quality=QualityConfig(min_source_level="L2", require_primary_source=True),
            risk=RiskConfig(max_position_weight=0.08, max_sector_weight=0.2),
            ai=AIConfig(
                system_prompt_template="undervalued_recovery",
                custom_instructions="关注利空是否已充分定价、资产负债表修复能力。",
            ),
            evidence=EvidenceConfig(required_levels=["L1", "L2", "L3"], min_evidence_count=4),
            decision=DecisionConfig(
                research_states=["research_candidate", "watch", "abstained"],
                position_review_states=["hold", "review", "close"],
                prohibited_outputs=[],
            ),
        ),
    )


def _high_dividend() -> StrategyTemplate:
    """Return the "high dividend" built-in strategy template."""
    return StrategyTemplate(
        meta=StrategyTemplateMeta(
            template_id="high_dividend",
            name="高股息",
            description="筛选连续分红、股息率稳定、现金流充裕的防御型标的。",
            category="income",
        ),
        config=StrategyConfig(
            universe=["600519.SH", "000001.SZ", "601988.SH"],
            horizon=365,
            valuation=ValuationConfig(method="dividend_yield", eps=1.0, pe=10.0),
            quality=QualityConfig(min_source_level="L2", require_primary_source=True),
            risk=RiskConfig(max_position_weight=0.12, max_sector_weight=0.3),
            ai=AIConfig(
                system_prompt_template="high_dividend",
                custom_instructions="重点分析分红持续性、派息率与自由现金流覆盖。",
            ),
            evidence=EvidenceConfig(required_levels=["L1", "L2"], min_evidence_count=3),
            decision=DecisionConfig(
                research_states=["research_candidate", "watch", "abstained"],
                position_review_states=["hold", "review", "close"],
                prohibited_outputs=[],
            ),
        ),
    )


def _growth_at_reasonable_price() -> StrategyTemplate:
    """Return the "growth at reasonable price" built-in strategy template."""
    return StrategyTemplate(
        meta=StrategyTemplateMeta(
            template_id="growth_at_reasonable_price",
            name="成长合理估值",
            description="在合理估值范围内寻找具备可持续成长能力的公司。",
            category="growth",
        ),
        config=StrategyConfig(
            universe=["002594.SZ", "300750.SZ", "000858.SZ"],
            horizon=120,
            valuation=ValuationConfig(method="peg", eps=1.0, pe=25.0),
            quality=QualityConfig(min_source_level="L2", require_primary_source=True),
            risk=RiskConfig(max_position_weight=0.08, max_sector_weight=0.2),
            ai=AIConfig(
                system_prompt_template="growth_at_reasonable_price",
                custom_instructions="关注收入增长质量、利润率趋势与资本回报率。",
            ),
            evidence=EvidenceConfig(required_levels=["L1", "L2"], min_evidence_count=4),
            decision=DecisionConfig(
                research_states=["research_candidate", "watch", "abstained"],
                position_review_states=["hold", "review", "close"],
                prohibited_outputs=[],
            ),
        ),
    )


def _cyclical_reversal() -> StrategyTemplate:
    """Return the "cyclical reversal" built-in strategy template."""
    return StrategyTemplate(
        meta=StrategyTemplateMeta(
            template_id="cyclical_reversal",
            name="周期反转",
            description="跟踪周期行业供需拐点，捕捉反转初期的投资机会。",
            category="cyclical",
        ),
        config=StrategyConfig(
            universe=["601899.SH", "600028.SH", "000933.SZ"],
            horizon=180,
            valuation=ValuationConfig(method="pb", eps=1.0, pe=8.0),
            quality=QualityConfig(min_source_level="L2", require_primary_source=True),
            risk=RiskConfig(max_position_weight=0.06, max_sector_weight=0.15),
            ai=AIConfig(
                system_prompt_template="cyclical_reversal",
                custom_instructions="重点分析产能利用率、库存周期与价格弹性。",
            ),
            evidence=EvidenceConfig(required_levels=["L1", "L2", "L3"], min_evidence_count=5),
            decision=DecisionConfig(
                research_states=["research_candidate", "watch", "abstained"],
                position_review_states=["hold", "review", "close"],
                prohibited_outputs=[],
            ),
        ),
    )


def _custom() -> StrategyTemplate:
    """Return the blank "custom" built-in strategy template."""
    return StrategyTemplate(
        meta=StrategyTemplateMeta(
            template_id="custom",
            name="用户完全自定义",
            description="从空白模板开始，完全自定义所有配置项。",
            category="custom",
        ),
        config=StrategyConfig(),
    )


BUILTIN_TEMPLATES: dict[str, StrategyTemplate] = {
    "value_quality": _value_quality(),
    "undervalued_recovery": _undervalued_recovery(),
    "high_dividend": _high_dividend(),
    "growth_at_reasonable_price": _growth_at_reasonable_price(),
    "cyclical_reversal": _cyclical_reversal(),
    "custom": _custom(),
}


def list_templates() -> list[StrategyTemplateMeta]:
    """Return metadata for all built-in strategy templates.

    Returns:
        A list of :class:`StrategyTemplateMeta` objects, one per built-in
        template.
    """
    return [template.meta for template in BUILTIN_TEMPLATES.values()]
