"""ExpertAgent card registry."""

from __future__ import annotations

from collections.abc import Iterable

from margin.agent_runtime.models import (
    AgentCard,
    AgentPermissionMode,
    AgentSkill,
)


class AgentCardRegistry:
    """Registry of ExpertAgent cards visible to MainAgent."""

    def __init__(self, cards: Iterable[AgentCard]) -> None:
        card_tuple = tuple(cards)
        self._cards = {card.name: card for card in card_tuple}
        if len(self._cards) != len(card_tuple):
            raise ValueError("duplicate agent card")

    def get(self, name: str) -> AgentCard:
        """Return a card by name."""
        return self._cards[name]

    def list_names(self) -> tuple[str, ...]:
        """Return agent names in stable order."""
        return tuple(sorted(self._cards))

    def list_cards(self) -> tuple[AgentCard, ...]:
        """Return cards in stable order."""
        return tuple(self._cards[name] for name in self.list_names())


def default_agent_card_registry() -> AgentCardRegistry:
    """Return default v0.4 ExpertAgent cards."""
    common = {
        "version": "v0.4.0",
        "capabilities": {
            "streaming": False,
            "pushNotifications": False,
            "stateTransitionHistory": True,
        },
        "authentication": {"schemes": ["internal"]},
    }
    return AgentCardRegistry(
        [
            AgentCard(
                name="DataInspectionAgent",
                description=(
                    "Checks data readiness and runs required deterministic sync."
                ),
                url="margin://agents/data-inspection",
                skills=(
                    AgentSkill(
                        skill_id="inspect_data_readiness",
                        name="Inspect Data Readiness",
                        description=(
                            "Check freshness, completeness, PIT validity, and "
                            "provider state."
                        ),
                        tags=("data", "freshness", "quality"),
                        produced_context_artifacts=(
                            "data_readiness",
                            "sync_result",
                        ),
                        write_policy=AgentPermissionMode.WRITE_ALLOWED,
                        schedule_allowed=True,
                        qa_allowed=False,
                    ),
                ),
                **common,
            ),
            AgentCard(
                name="QuantAgent",
                description="Runs the fixed ML lifecycle quant strategy profile.",
                url="margin://agents/quant",
                skills=(
                    AgentSkill(
                        skill_id="run_ml_lifecycle_quant_analysis",
                        name="Run ML Lifecycle Quant Analysis",
                        description=(
                            "Run the QuantAgent-owned ML lifecycle profile and "
                            "publish quant plus Analysis Mart artifacts."
                        ),
                        tags=("quant", "analysis", "deterministic"),
                        required_context_artifacts=("data_readiness",),
                        produced_context_artifacts=(
                            "quant_result",
                            "analysis_mart_snapshot",
                        ),
                        write_policy=AgentPermissionMode.WRITE_ALLOWED,
                        schedule_allowed=True,
                        qa_allowed=False,
                    ),
                ),
                **common,
            ),
            AgentCard(
                name="NewsAcquisitionAgent",
                description="Acquires and indexes news for quant-selected targets.",
                url="margin://agents/news-acquisition",
                skills=(
                    AgentSkill(
                        skill_id="acquire_news_for_quant_targets",
                        name="Acquire News For Quant Targets",
                        description=(
                            "Acquire filings, news, public materials, snapshots, "
                            "dedup records, and indexing events."
                        ),
                        tags=("news", "filings", "indexing"),
                        required_context_artifacts=("quant_result",),
                        produced_context_artifacts=(
                            "news_context_bundle",
                            "indexed_document_batch",
                        ),
                        write_policy=AgentPermissionMode.WRITE_ALLOWED,
                        schedule_allowed=True,
                        qa_allowed=False,
                    ),
                ),
                **common,
            ),
            AgentCard(
                name="StockAnalystAgent",
                description=(
                    "Runs evidence-bound stock analysis and publishes dashboard "
                    "projections."
                ),
                url="margin://agents/stock-analyst",
                skills=(
                    AgentSkill(
                        skill_id="analyze_quant_candidates",
                        name="Analyze Quant Candidates",
                        description=(
                            "Build evidence packages, validate citations and "
                            "claims, publish valuation assessments and front-end "
                            "projection events."
                        ),
                        tags=("stock-analysis", "evidence", "valuation"),
                        required_context_artifacts=(
                            "quant_result",
                            "analysis_mart_snapshot",
                            "news_context_bundle",
                            "indexed_document_batch",
                        ),
                        produced_context_artifacts=(
                            "evidence_package",
                            "citation_validation_report",
                            "stock_analysis_result",
                            "valuation_assessment",
                            "dashboard_projection_event",
                        ),
                        write_policy=AgentPermissionMode.WRITE_ALLOWED,
                        schedule_allowed=True,
                        qa_allowed=False,
                    ),
                ),
                **common,
            ),
            AgentCard(
                name="GeneralQnaAgent",
                description=(
                    "Answers greetings, product usage questions, and ordinary "
                    "conversation through the configured LLM."
                ),
                url="margin://agents/general-qna",
                skills=(
                    AgentSkill(
                        skill_id="answer_general_qna",
                        name="Answer General Q&A",
                        description=(
                            "Use the configured LLM to answer MainAgent-authorized "
                            "general Q&A without reading or writing production data."
                        ),
                        tags=("qna", "llm", "conversation"),
                        produced_context_artifacts=("explanation",),
                        write_policy=AgentPermissionMode.READ_ONLY,
                        schedule_allowed=False,
                        qa_allowed=True,
                    ),
                ),
                **common,
            ),
            AgentCard(
                name="DataAnalystAgent",
                description=(
                    "Answers user Q&A by reading scoped quant, news, and evidence "
                    "artifacts and returning analysis artifacts."
                ),
                url="margin://agents/data-analyst",
                skills=(
                    AgentSkill(
                        skill_id="answer_with_analysis_artifacts",
                        name="Answer With Analysis Artifacts",
                        description=(
                            "Read MainAgent-authorized context artifacts and "
                            "return tables, chart specs, metrics, explanations, "
                            "or generated file references."
                        ),
                        tags=("qna", "analysis", "visualization"),
                        produced_context_artifacts=(
                            "analysis_table",
                            "chart_spec",
                            "computed_metric",
                            "explanation",
                            "generated_file_ref",
                        ),
                        write_policy=AgentPermissionMode.READ_ONLY,
                        schedule_allowed=False,
                        qa_allowed=True,
                    ),
                ),
                **common,
            ),
            AgentCard(
                name="CodeSandboxAgent",
                description=(
                    "Runs sandboxed analysis code only during user Q&A with "
                    "audited inputs and outputs."
                ),
                url="margin://agents/code-sandbox",
                skills=(
                    AgentSkill(
                        skill_id="run_sandboxed_analysis_code",
                        name="Run Sandboxed Analysis Code",
                        description=(
                            "Execute allowlisted Python analysis packages against "
                            "MainAgent-authorized artifacts or read-only views, "
                            "then write only Context Store output artifacts."
                        ),
                        tags=("qna", "sandbox", "code-execution"),
                        produced_context_artifacts=(
                            "analysis_table",
                            "chart_spec",
                            "computed_metric",
                            "explanation",
                            "generated_file_ref",
                        ),
                        write_policy=AgentPermissionMode.READ_ONLY,
                        schedule_allowed=False,
                        qa_allowed=True,
                    ),
                ),
                **common,
            ),
        ]
    )
