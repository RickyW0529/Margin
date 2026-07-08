"""ExpertAgent executors for user-facing agent runtime flows."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from margin.agent_runtime.context_store import make_context_artifact
from margin.agent_runtime.models import AgentExecutionStatus, ContextArtifact
from margin.dashboard.models import DashboardFilters, DashboardSort, ResearchItem, ResearchRun
from margin.dashboard.repository import DashboardRepository
from margin.dashboard.service import DashboardServiceBundle
from margin.prompts.agent_runtime import agent_runtime_prompt_templates
from margin.prompts.models import RenderedPrompt
from margin.prompts.registry import PromptRegistry
from margin.prompts.renderer import PromptRenderer
from margin.research.llm import LLMProvider, LLMResult


@dataclass(frozen=True)
class DataAnalystQnaResult:
    """Result produced by DataAnalystAgent for user Q&A."""

    answer: str
    status: AgentExecutionStatus
    artifacts: tuple[ContextArtifact, ...]
    references: tuple[dict[str, str], ...]


@dataclass(frozen=True)
class GeneralQnaResult:
    """Result produced by GeneralQnaAgent for user Q&A."""

    answer: str
    status: AgentExecutionStatus
    artifacts: tuple[ContextArtifact, ...]
    references: tuple[dict[str, str], ...]


@dataclass(frozen=True)
class StockAnalystAdjustmentResult:
    """Result produced by StockAnalystAgent candidate adjustment."""

    status: AgentExecutionStatus
    artifacts: tuple[ContextArtifact, ...]
    adjustments: tuple[dict[str, Any], ...]
    removed_security_ids: tuple[str, ...]
    dashboard_run_id: str | None = None


class GeneralQnaAgent:
    """Read-only ExpertAgent that answers general Q&A through the real LLM."""

    name = "GeneralQnaAgent"
    skill_id = "answer_general_qna"

    def __init__(
        self,
        *,
        llm_provider: LLMProvider,
        write_context_artifact: Callable[[ContextArtifact], None],
        prompt_registry: PromptRegistry | None = None,
        prompt_renderer: PromptRenderer | None = None,
    ) -> None:
        self._llm_provider = llm_provider
        self._write_context_artifact = write_context_artifact
        self._prompt_registry = prompt_registry or PromptRegistry(
            templates=agent_runtime_prompt_templates()
        )
        self._prompt_renderer = prompt_renderer or PromptRenderer()

    def answer_general_question(
        self,
        *,
        run_id: str,
        message: str,
        language: str,
        conversation_context: list[dict[str, str]],
        available_artifacts: tuple[ContextArtifact, ...],
    ) -> GeneralQnaResult:
        """Answer a MainAgent-authorized general Q&A request with an LLM call."""
        template = self._prompt_registry.get("general_qna_agent_v0.4")
        rendered = self._prompt_renderer.render(
            template,
            variables={
                "language": language,
                "user_request": message,
                "conversation_context": conversation_context,
                "run_context": {
                    "run_id": run_id,
                    "run_type": "user_qna",
                    "permission_mode": "read_only",
                },
                "artifact_summaries": _artifact_summaries(available_artifacts),
            },
        )
        result = self._llm_provider.complete(
            rendered.text,
            temperature=rendered.temperature,
        )
        if not result.success:
            raise RuntimeError(result.error or "LLM completion failed")
        answer = str(result.output.get("content") or result.raw_response or "").strip()
        if not answer:
            raise RuntimeError("LLM returned an empty answer")

        artifact = make_context_artifact(
            artifact_id=f"ctx_{run_id}_explanation",
            run_id=run_id,
            artifact_type="explanation",
            producer_agent=self.name,
            payload_json={
                "answer": answer,
                "language": language,
                "prompt_id": rendered.prompt_id,
                "prompt_hash": rendered.prompt_hash,
                "rendered_input_hash": rendered.rendered_input_hash,
                "model": result.model,
                "latency_ms": result.latency_ms,
            },
            source_refs=(rendered.prompt_id,),
        )
        self._write_context_artifact(artifact)
        return GeneralQnaResult(
            answer=answer,
            status=AgentExecutionStatus.SUCCEEDED,
            artifacts=(artifact,),
            references=(),
        )


class DataAnalystAgent:
    """Read-only expert agent for recommendation Q&A.

    The MainAgent plans and authorizes this expert. This class performs the
    actual read-only data access, writes Context Store artifacts, and produces
    the user-visible answer.
    """

    name = "DataAnalystAgent"
    skill_id = "answer_with_analysis_artifacts"

    def __init__(
        self,
        *,
        llm_provider: LLMProvider,
        write_context_artifact: Callable[[ContextArtifact], None],
        prompt_registry: PromptRegistry | None = None,
        prompt_renderer: PromptRenderer | None = None,
    ) -> None:
        self._llm_provider = llm_provider
        self._write_context_artifact = write_context_artifact
        self._prompt_registry = prompt_registry or PromptRegistry(
            templates=agent_runtime_prompt_templates()
        )
        self._prompt_renderer = prompt_renderer or PromptRenderer()

    def answer_recommendation_question(
        self,
        *,
        run_id: str,
        message: str,
        scope_version_id: str,
        universe: str,
        language: str,
        conversation_context: list[dict[str, str]],
        services: DashboardServiceBundle,
    ) -> DataAnalystQnaResult:
        """Answer one recommendation question from read-only dashboard data."""
        candidates = services.query.list_research_candidates_v2(
            scope_version_id=scope_version_id,
            universe_code=universe,
            filters=DashboardFilters(),
            sort=DashboardSort(field="final_score", direction="desc"),
            cursor=None,
            limit=5,
        )
        rows = [
            {
                "symbol": item.symbol,
                "name": item.name,
                "final_score": item.final_score,
                "confidence": item.confidence,
                "screening_status": item.screening_status,
                "review_required": item.review_required,
            }
            for item in candidates.items
        ]
        references = (
            {
                "api": "GET /api/v1/research",
                "scope_version_id": scope_version_id,
                "universe": universe,
            },
        )
        table_artifact = make_context_artifact(
            artifact_id=f"ctx_{run_id}_analysis_table",
            run_id=run_id,
            artifact_type="analysis_table",
            producer_agent=self.name,
            payload_json={
                "scope_version_id": scope_version_id,
                "universe": universe,
                "question": message,
                "rows": rows,
            },
            source_refs=("GET /api/v1/research",),
        )
        answer, rendered_prompt, llm_result = self._answer_from_llm(
            rows=rows,
            message=message,
            scope_version_id=scope_version_id,
            universe=universe,
            language=language,
            conversation_context=conversation_context,
        )
        answer_artifact = make_context_artifact(
            artifact_id=f"ctx_{run_id}_explanation",
            run_id=run_id,
            artifact_type="explanation",
            producer_agent=self.name,
            payload_json={
                "answer": answer,
                "language": language,
                "source_artifact_id": table_artifact.artifact_id,
                "producer_prompt_id": rendered_prompt.prompt_id,
                "prompt_hash": rendered_prompt.prompt_hash,
                "rendered_input_hash": rendered_prompt.rendered_input_hash,
                "model": llm_result.model,
                "latency_ms": llm_result.latency_ms,
            },
            source_refs=("GET /api/v1/research", rendered_prompt.prompt_id),
        )
        self._write_context_artifact(table_artifact)
        self._write_context_artifact(answer_artifact)
        return DataAnalystQnaResult(
            answer=answer,
            status=(
                AgentExecutionStatus.SUCCEEDED
                if rows
                else AgentExecutionStatus.PARTIAL
            ),
            artifacts=(table_artifact, answer_artifact),
            references=references,
        )

    def _answer_from_llm(
        self,
        *,
        rows: list[dict[str, object]],
        message: str,
        scope_version_id: str,
        universe: str,
        language: str,
        conversation_context: list[dict[str, str]],
    ) -> tuple[str, RenderedPrompt, LLMResult]:
        template = self._prompt_registry.get("data_analyst_qna_agent_v0.4")
        rendered = self._prompt_renderer.render(
            template,
            variables={
                "language": language,
                "user_request": message,
                "conversation_context": conversation_context,
                "scope_version_id": scope_version_id,
                "universe": universe,
                "analysis_rows": rows,
            },
        )
        result = self._llm_provider.complete(
            rendered.text,
            temperature=rendered.temperature,
        )
        if not result.success:
            raise RuntimeError(result.error or "LLM completion failed")
        answer = str(result.output.get("content") or result.raw_response or "").strip()
        if not answer:
            raise RuntimeError("LLM returned an empty answer")
        return answer, rendered, result


class StockAnalystAgent:
    """Write-capable expert that adjusts quant candidates after evidence review.

    The agent is deterministic and artifact-first: it does not read raw/source
    tables and does not issue orders. It records how quant target weights were
    kept, reduced, or removed so downstream dashboard/Q&A layers can audit the
    expert overlay.
    """

    name = "StockAnalystAgent"
    skill_id = "analyze_quant_candidates"

    def __init__(
        self,
        *,
        write_context_artifact: Callable[[ContextArtifact], None],
        dashboard_repository: DashboardRepository | None = None,
    ) -> None:
        self._write_context_artifact = write_context_artifact
        self._dashboard_repository = dashboard_repository

    def adjust_quant_candidates(
        self,
        *,
        run_id: str,
        candidates: tuple[dict[str, Any], ...],
        max_stock_exposure: float = 0.80,
    ) -> StockAnalystAdjustmentResult:
        """Build and persist a portfolio-adjustment artifact for quant candidates."""
        raw_adjustments = tuple(_candidate_adjustment(candidate) for candidate in candidates)
        adjustments = _scale_adjustments_to_exposure(
            raw_adjustments,
            max_stock_exposure=max_stock_exposure,
        )
        removed = tuple(
            str(item["security_id"])
            for item in adjustments
            if item.get("action") == "delete"
        )
        dashboard_run_id = self._publish_dashboard_adjustment_projection(
            run_id=run_id,
            adjustments=adjustments,
        )
        artifact = make_context_artifact(
            artifact_id=f"ctx_{run_id}_portfolio_adjustment",
            run_id=run_id,
            artifact_type="portfolio_adjustment",
            producer_agent=self.name,
            payload_json={
                "max_stock_exposure": max_stock_exposure,
                "min_cash": round(1.0 - max_stock_exposure, 10),
                "removed_security_ids": list(removed),
                "adjustments": list(adjustments),
                "dashboard_projection_update": "portfolio_adjustment_ready",
                "dashboard_run_id": dashboard_run_id,
            },
            source_refs=("analysis_mart_snapshot", "quant_result"),
        )
        projection_event = make_context_artifact(
            artifact_id=f"ctx_{run_id}_dashboard_projection_event",
            run_id=run_id,
            artifact_type="dashboard_projection_event",
            producer_agent=self.name,
            payload_json={
                "dashboard_run_id": dashboard_run_id,
                "visible_item_count": sum(
                    1 for item in adjustments if item.get("action") != "delete"
                ),
                "removed_security_ids": list(removed),
                "adjustment_artifact_id": artifact.artifact_id,
                "projection_status": (
                    "published" if dashboard_run_id is not None else "not_configured"
                ),
            },
            source_refs=(artifact.artifact_id,),
        )
        self._write_context_artifact(artifact)
        self._write_context_artifact(projection_event)
        return StockAnalystAdjustmentResult(
            status=AgentExecutionStatus.SUCCEEDED,
            artifacts=(artifact, projection_event),
            adjustments=adjustments,
            removed_security_ids=removed,
            dashboard_run_id=dashboard_run_id,
        )

    def _publish_dashboard_adjustment_projection(
        self,
        *,
        run_id: str,
        adjustments: tuple[dict[str, Any], ...],
    ) -> str | None:
        """Write an adjusted dashboard projection when a repository is configured."""
        if self._dashboard_repository is None or not adjustments:
            return None
        source_items = _source_dashboard_items(
            self._dashboard_repository,
            adjustments,
        )
        if not source_items:
            return None
        source_run = self._dashboard_repository.get_run(source_items[0].run_id)
        if source_run is None:
            return None

        dashboard_run_id = f"dr_agent_{run_id}"
        adjustment_by_security_id = {
            str(adjustment.get("security_id")): adjustment
            for adjustment in adjustments
        }
        adjusted_items: list[ResearchItem] = []
        for item in source_items:
            adjustment = adjustment_by_security_id.get(item.symbol)
            if adjustment is None:
                continue
            if adjustment.get("action") == "delete":
                continue
            adjusted_items.append(
                item.model_copy(
                    update={
                        "item_id": f"{dashboard_run_id}_{item.symbol}",
                        "run_id": dashboard_run_id,
                        "adjusted_weight": _optional_float(
                            adjustment.get("adjusted_weight")
                        ),
                        "agent_adjustment": {
                            "source": self.name,
                            "run_id": run_id,
                            "action": str(adjustment.get("action") or "keep"),
                            "target_weight": _optional_float(
                                adjustment.get("target_weight")
                            ),
                            "adjusted_weight": _optional_float(
                                adjustment.get("adjusted_weight")
                            ),
                            "reasons": list(adjustment.get("reasons", ())),
                            "risk_flags": list(adjustment.get("risk_flags", ())),
                        },
                    }
                )
            )
        adjusted_run = _dashboard_adjusted_run(
            source_run=source_run,
            dashboard_run_id=dashboard_run_id,
            run_id=run_id,
            items=tuple(adjusted_items),
        )
        self._dashboard_repository.add_run(adjusted_run)
        self._dashboard_repository.add_items(adjusted_items)
        return dashboard_run_id


def _artifact_summaries(
    artifacts: tuple[ContextArtifact, ...],
) -> list[dict[str, object]]:
    """Return token-safe artifact summaries for prompt context."""
    return [
        {
            "artifact_id": artifact.artifact_id,
            "artifact_type": artifact.artifact_type,
            "producer_agent": artifact.producer_agent,
            "payload_hash": artifact.payload_hash,
            "source_refs": list(artifact.source_refs),
        }
        for artifact in artifacts
    ]


def _candidate_adjustment(candidate: dict[str, Any]) -> dict[str, Any]:
    """Return one deterministic post-quant adjustment row."""
    security_id = str(candidate.get("security_id") or candidate.get("symbol") or "")
    item_id = str(candidate.get("item_id") or "")
    target_weight = _optional_float(candidate.get("target_weight")) or 0.0
    risk_flags = tuple(str(flag) for flag in candidate.get("risk_flags", ()) or ())
    review_required = bool(candidate.get("review_required", False))
    screening_status = str(candidate.get("screening_status") or "")
    delete_reasons: list[str] = []
    if screening_status not in {"pass", "near_threshold", "watchlist"}:
        delete_reasons.append("screening_status_not_researchable")
    if review_required:
        delete_reasons.append("review_required")
    if "short_term_overheat" in risk_flags:
        delete_reasons.append("short_term_overheat")
    if delete_reasons:
        return {
            "item_id": item_id,
            "security_id": security_id,
            "action": "delete",
            "target_weight": target_weight,
            "adjusted_weight": 0.0,
            "reasons": delete_reasons,
            "risk_flags": list(risk_flags),
        }
    return {
        "item_id": item_id,
        "security_id": security_id,
        "action": "keep",
        "target_weight": target_weight,
        "adjusted_weight": target_weight,
        "reasons": [],
        "risk_flags": list(risk_flags),
    }


def _scale_adjustments_to_exposure(
    adjustments: tuple[dict[str, Any], ...],
    *,
    max_stock_exposure: float,
) -> tuple[dict[str, Any], ...]:
    """Scale kept/reduced weights so actual projected exposure respects the cap."""
    total = sum(
        _optional_float(item.get("adjusted_weight")) or 0.0
        for item in adjustments
        if item.get("action") != "delete"
    )
    if total <= max_stock_exposure or total <= 0.0:
        return adjustments
    scale = max_stock_exposure / total
    scaled: list[dict[str, Any]] = []
    for item in adjustments:
        if item.get("action") == "delete":
            scaled.append(dict(item))
            continue
        adjusted = round((_optional_float(item.get("adjusted_weight")) or 0.0) * scale, 10)
        reasons = list(item.get("reasons", ()))
        reasons.append("exposure_cap_scaling")
        scaled.append(
            {
                **item,
                "action": "reduce_weight",
                "adjusted_weight": adjusted,
                "reasons": reasons,
            }
        )
    return tuple(scaled)


def _optional_float(value: Any) -> float | None:
    """Return a float when conversion is possible."""
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _source_dashboard_items(
    repository: DashboardRepository,
    adjustments: tuple[dict[str, Any], ...],
) -> tuple[ResearchItem, ...]:
    """Load source dashboard items referenced by adjustment rows."""
    item_ids = tuple(
        str(adjustment.get("item_id") or "")
        for adjustment in adjustments
        if adjustment.get("item_id")
    )
    if item_ids:
        items = tuple(
            item
            for item_id in item_ids
            if (item := repository.get_item(item_id)) is not None
        )
        if items:
            return items
    source_run_id = next(
        (
            str(adjustment.get("run_id"))
            for adjustment in adjustments
            if adjustment.get("run_id")
        ),
        "",
    )
    if source_run_id:
        items = repository.list_items(source_run_id)
        security_ids = {
            str(adjustment.get("security_id"))
            for adjustment in adjustments
            if adjustment.get("security_id")
        }
        return tuple(item for item in items if item.symbol in security_ids)
    return ()


def _dashboard_adjusted_run(
    *,
    source_run: ResearchRun,
    dashboard_run_id: str,
    run_id: str,
    items: tuple[ResearchItem, ...],
) -> ResearchRun:
    """Build the latest dashboard run representing StockAnalystAgent overlay."""
    published_count = sum(1 for item in items if item.status.value == "published")
    return source_run.model_copy(
        update={
            "run_id": dashboard_run_id,
            "strategy_id": f"{source_run.strategy_id}:agent_adjusted",
            "universe": [item.symbol for item in items],
            "summary": f"StockAnalystAgent adjusted projection for {run_id}",
            "item_count": len(items),
            "published_count": published_count,
            "abstained_count": len(items) - published_count,
            "aborted_count": 0,
            "created_at": datetime.now(UTC),
        }
    )
