"""Layered prompt builder for strategy-driven research."""

from __future__ import annotations

from margin.strategy.models import PromptLayer, StrategyConfig


class PromptLayerBuilder:
    """Compose the final research prompt from immutable layered sources.

    Layer order (outer to inner, per architecture §15.2):
    1. System Guardrail Prompt
    2. Platform Research Prompt
    3. Strategy Template Prompt
    4. User Custom Prompt
    5. Current Task Context
    6. Retrieved Evidence
    """

    def build_layers(
        self,
        config: StrategyConfig,
        *,
        custom_instructions: str | None = None,
        evidence_context: str = "",
        task: str = "",
    ) -> tuple[PromptLayer, ...]:
        """Return all prompt layers for audit and serialization.

        Args:
            config: The strategy configuration driving the prompt content.
            custom_instructions: Optional override for the user's custom
                instructions. Falls back to ``config.ai.custom_instructions``
                when omitted.
            evidence_context: Optional retrieved evidence to append as the
                final prompt layer.
            task: Optional task description to include in the task context
                layer. Falls back to a default task when omitted.

        Returns:
            An ordered tuple of :class:`PromptLayer` objects from outermost
            guardrail to innermost evidence context.
        """
        custom = (
            custom_instructions
            if custom_instructions is not None
            else config.ai.custom_instructions
        )
        layers: list[PromptLayer] = [
            PromptLayer(
                layer="system_guardrail",
                content=self._guardrail_prompt(),
                editable=False,
            ),
            PromptLayer(
                layer="platform_research",
                content=self._platform_prompt(),
                editable=False,
            ),
            PromptLayer(
                layer="strategy_template",
                content=self._template_prompt(config),
                editable=False,
            ),
            PromptLayer(
                layer="user_custom",
                content=custom,
                editable=True,
            ),
            PromptLayer(
                layer="task_context",
                content=task or self._default_task(config),
                editable=True,
            ),
        ]
        if evidence_context:
            layers.append(
                PromptLayer(
                    layer="retrieved_evidence",
                    content=evidence_context,
                    editable=False,
                )
            )
        return tuple(layers)

    def build(
        self,
        config: StrategyConfig,
        *,
        custom_instructions: str | None = None,
        evidence_context: str = "",
        task: str = "",
    ) -> str:
        """Return the final merged prompt string.

        Args:
            config: The strategy configuration driving the prompt content.
            custom_instructions: Optional override for the user's custom
                instructions. Falls back to ``config.ai.custom_instructions``
                when omitted.
            evidence_context: Optional retrieved evidence to append as the
                final prompt layer.
            task: Optional task description to include in the task context
                layer. Falls back to a default task when omitted.

        Returns:
            A single string containing all non-empty prompt layers joined by
            blank lines.
        """
        layers = self.build_layers(
            config,
            custom_instructions=custom_instructions,
            evidence_context=evidence_context,
            task=task,
        )
        return "\n\n".join(
            f"[{layer.layer}]\n{layer.content}" for layer in layers if layer.content.strip()
        )

    def _guardrail_prompt(self) -> str:
        """Return the immutable system guardrail prompt."""
        return (
            "You are a compliance-aware research assistant. You must: "
            "cite all factual claims with evidence references; "
            "respect point-in-time data constraints; "
            "include balanced risk disclosure; "
            "produce output matching the required JSON schema; "
            "never guarantee returns or promise specific profits; "
            "never issue direct buy/sell orders. "
            "违反上述任何一条的输出都会被系统拒绝。"
        )

    def _platform_prompt(self) -> str:
        """Return the immutable platform research prompt."""
        return (
            "You are researching A-share listed companies for a local-first, "
            "evidence-driven investment research system. Use only the retrieved "
            "evidence and the strategy configuration provided below."
        )

    def _template_prompt(self, config: StrategyConfig) -> str:
        """Return the strategy-specific prompt derived from ``config``.

        Args:
            config: The strategy configuration to summarize in the prompt.

        Returns:
            A string describing the strategy horizon, universe, evidence
            requirements, and risk limits.
        """
        return (
            f"Strategy horizon: {config.horizon} days. "
            f"Universe: {', '.join(config.universe)}. "
            f"Minimum evidence count: {config.evidence.min_evidence_count}. "
            f"Required evidence levels: {', '.join(config.evidence.required_levels)}. "
            f"Max position weight: {config.risk.max_position_weight}. "
            f"Risk score threshold: {config.risk.risk_score_threshold}."
        )

    def _default_task(self, config: StrategyConfig) -> str:
        """Return the default task context for a strategy run.

        Args:
            config: The strategy configuration (reserved for future use).

        Returns:
            A default task instruction asking for a structured research signal.
        """
        return (
            "Analyze the given symbol according to the strategy above. "
            "Output a structured research signal with signal_type, confidence, "
            "statement, and evidence_refs."
        )
