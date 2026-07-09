"""Production LLM handlers for the v0.2 AI delta-review graph."""

from __future__ import annotations

import json
from typing import Any

from margin.research.execution.llm_service import LLMService
from margin.research.execution.node_runner import (
    DeterministicValidation,
    NodeExecutionRunner,
)
from margin.research.graph.nodes.analysis import AnalysisHandler, AnalysisRequest
from margin.research.graph.state import AIDeltaGraphState, ReviewOutcome
from margin.research.llm import StructuredOutputGuardrail
from margin.research.prompts.factory import PromptFactory, PromptKind
from margin.research.service import ResearchContextSnapshot
from margin.research.tools.factory import ScopedToolSession
from margin.research.tools.manifests import ToolManifest

ANALYSIS_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "summary": {"type": "string"},
        "key_points": {"type": "array", "items": {"type": "string"}},
        "evidence_ids": {"type": "array", "items": {"type": "string"}},
        "evidence_gaps": {"type": "array", "items": {"type": "string"}},
        "confidence": {"type": "number"},
    },
    "required": [
        "summary",
        "key_points",
        "evidence_ids",
        "evidence_gaps",
        "confidence",
    ],
}

DECISION_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "outcome": {
            "type": "string",
            "enum": [
                ReviewOutcome.UPDATE_ASSESSMENT.value,
                ReviewOutcome.DOWNGRADE_CONFIDENCE.value,
                ReviewOutcome.INVALIDATE.value,
                ReviewOutcome.ABSTAIN.value,
            ],
        },
        "confidence": {"type": "number"},
        "conclusion": {"type": "string"},
        "valuation_view": {
            "type": "string",
            "enum": ["undervalued", "fair", "overvalued", "uncertain"],
        },
        "evidence_ids": {"type": "array", "items": {"type": "string"}},
        "changed_assumptions": {
            "type": "array",
            "items": {"type": "object"},
        },
    },
    "required": [
        "outcome",
        "confidence",
        "conclusion",
        "valuation_view",
        "evidence_ids",
        "changed_assumptions",
    ],
}


class EvidenceBoundOutputValidator:
    """Validate schema and prevent LLM-created evidence identifiers.."""

    def __init__(self, allowed_evidence_ids: set[str]) -> None:
        """Initialize the validator with the frozen evidence boundary.

        Args:
            allowed_evidence_ids: set[str]: .

        Returns:
            None: .
        """
        self._allowed_evidence_ids = allowed_evidence_ids

    def validate(
        self,
        *,
        node_name: str,
        output: dict[str, Any],
        output_schema: dict[str, Any],
    ) -> DeterministicValidation:
        """Validate JSON shape, evidence references, and confidence bounds.

        Args:
            node_name: str: .
            output: dict[str, Any]: .
            output_schema: dict[str, Any]: .

        Returns:
            DeterministicValidation: .
        """
        del node_name
        valid_schema, schema_error = StructuredOutputGuardrail(output_schema).validate(output)
        issues: list[str] = []
        if not valid_schema:
            issues.append(schema_error or "schema_invalid")
        referenced = {str(value) for value in output.get("evidence_ids", ())}
        if not referenced <= self._allowed_evidence_ids:
            issues.append("unknown_evidence_id")
        confidence = output.get("confidence")
        if confidence is not None:
            try:
                numeric_confidence = float(confidence)
            except (TypeError, ValueError):
                issues.append("confidence_invalid")
            else:
                if not 0.0 <= numeric_confidence <= 1.0:
                    issues.append("confidence_out_of_range")
        return DeterministicValidation(
            valid=not issues,
            issues=tuple(issues),
        )


def build_production_analysis_handlers(
    *,
    context: ResearchContextSnapshot,
    llm_service: LLMService,
    prompt_factory: PromptFactory | None = None,
) -> dict[str, AnalysisHandler]:
    """Build real LLM-backed handlers for every parallel analysis node.

    Args:
        context: ResearchContextSnapshot: .
        llm_service: LLMService: .
        prompt_factory: PromptFactory | None: .

    Returns:
        dict[str, AnalysisHandler]: .
    """
    factory = prompt_factory or PromptFactory()
    return {
        node_name: _analysis_handler(
            node_name=node_name,
            context=context,
            llm_service=llm_service,
            prompt_factory=factory,
        )
        for node_name in (
            "fundamental_analysis",
            "valuation_analysis",
            "risk_review",
            "counter_argument",
            "targeted_reanalysis",
        )
    }


def build_production_decision_handler(
    *,
    context: ResearchContextSnapshot,
    llm_service: LLMService,
    prompt_factory: PromptFactory | None = None,
):
    """Build a real LLM-backed handler for the delta decision composer node.

    Args:
        context: ResearchContextSnapshot: .
        llm_service: LLMService: .
        prompt_factory: PromptFactory | None: .

    Returns:
        Any: .
    """
    factory = prompt_factory or PromptFactory()

    def handler(state: AIDeltaGraphState) -> dict[str, Any]:
        """Process handler.

        Args:
            state: AIDeltaGraphState: .

        Returns:
            dict[str, Any]: .
        """
        allowed_evidence_ids = _allowed_evidence_ids(context)
        prompt = factory.build(
            node_name="delta_decision",
            kind=PromptKind.DRAFT,
            strategy_params=_strategy_params(context),
            context_summary=_context_summary(context),
            evidence_package={
                "analysis_outputs": {
                    key: value
                    for key, value in state.node_outputs.items()
                    if key
                    in {
                        "fundamental_analysis",
                        "valuation_analysis",
                        "risk_review",
                        "counter_argument",
                        "targeted_reanalysis",
                    }
                },
                "allowed_evidence_ids": sorted(allowed_evidence_ids),
            },
            tool_manifest=_empty_manifest(state, "delta_decision"),
            untrusted_blocks=_untrusted_blocks(context),
            output_schema=DECISION_SCHEMA,
            budget={"max_calls": 3, "one_revision": True},
        )
        result = NodeExecutionRunner(
            llm=llm_service,
            validator=EvidenceBoundOutputValidator(allowed_evidence_ids),
        ).run_llm_node(
            graph_run_id=state.graph_run_id,
            node_name="delta_decision",
            prompt=prompt,
            output_schema=DECISION_SCHEMA,
            reflection_policy="forced",
        )
        if result.abstained:
            return {
                "outcome": ReviewOutcome.ABSTAIN.value,
                "confidence": 0.0,
                "conclusion": "证据不足，当前结论保持审慎并等待补证。",
                "valuation_view": "uncertain",
                "evidence_ids": [],
                "changed_assumptions": [],
                "llm_call_ids": list(result.llm_call_ids),
            }
        return {
            **result.output,
            "llm_call_ids": list(result.llm_call_ids),
        }

    return handler


def build_production_citation_validator(
    context: ResearchContextSnapshot,
):
    """Build a real citation validator that checks evidence ID membership.

    Args:
        context: ResearchContextSnapshot: .

    Returns:
        Any: .
    """
    allowed = _allowed_evidence_ids(context)

    def validator(
        draft: dict[str, Any],
        state: AIDeltaGraphState,
    ) -> dict[str, Any]:
        """Process validator.

        Args:
            draft: dict[str, Any]: .
            state: AIDeltaGraphState: .

        Returns:
            dict[str, Any]: .
        """
        del state
        referenced = tuple(str(value) for value in draft.get("evidence_ids", ()))
        invalid = tuple(value for value in referenced if value not in allowed)
        return {
            "valid": bool(referenced) and not invalid,
            "repairable": bool(referenced) and len(invalid) < len(referenced),
            "invalid_evidence_ids": invalid,
            "reason": (None if referenced and not invalid else "unknown_or_missing_evidence"),
        }

    return validator


def _analysis_handler(
    *,
    node_name: str,
    context: ResearchContextSnapshot,
    llm_service: LLMService,
    prompt_factory: PromptFactory,
) -> AnalysisHandler:
    """Create one node-specific real LLM analysis handler.

    Args:
        node_name: str: .
        context: ResearchContextSnapshot: .
        llm_service: LLMService: .
        prompt_factory: PromptFactory: .

    Returns:
        AnalysisHandler: .
    """

    def handler(
        request: AnalysisRequest,
        session: ScopedToolSession,
    ) -> dict[str, Any]:
        """Execute one analysis node via the bounded LLM execution runner.

        Args:
            request: AnalysisRequest: .
            session: ScopedToolSession: .

        Returns:
            dict[str, Any]: .
        """
        allowed_evidence_ids = _allowed_evidence_ids(context)
        prompt = prompt_factory.build(
            node_name=node_name,
            kind=PromptKind.DRAFT,
            strategy_params=_strategy_params(context),
            context_summary=_context_summary(context),
            evidence_package={
                "package_ids": list(request.evidence_package_ids),
                "package_summaries": request.package_summaries,
                "allowed_evidence_ids": sorted(allowed_evidence_ids),
                "requested_gaps": list(request.evidence_gaps),
            },
            tool_manifest=session.manifest(),
            untrusted_blocks=_untrusted_blocks(context),
            output_schema=ANALYSIS_SCHEMA,
            budget={"max_calls": 3, "one_revision": True},
        )
        reflection_policy = (
            "forced" if node_name in {"risk_review", "counter_argument"} else "conditional"
        )
        result = NodeExecutionRunner(
            llm=llm_service,
            validator=EvidenceBoundOutputValidator(allowed_evidence_ids),
        ).run_llm_node(
            graph_run_id=_graph_run_id_from_manifest(session.manifest()),
            node_name=node_name,
            prompt=prompt,
            output_schema=ANALYSIS_SCHEMA,
            reflection_policy=reflection_policy,
        )
        if result.abstained:
            return {
                "summary": "当前节点证据不足，已停止扩展结论。",
                "key_points": [],
                "evidence_ids": [],
                "evidence_gaps": [result.error_code or "analysis_abstained"],
                "confidence": 0.0,
                "llm_call_ids": list(result.llm_call_ids),
            }
        return {
            **result.output,
            "llm_call_ids": list(result.llm_call_ids),
        }

    return handler


def _allowed_evidence_ids(context: ResearchContextSnapshot) -> set[str]:
    """Extract the frozen set of allowed evidence IDs from context.

    Args:
        context: ResearchContextSnapshot: .

    Returns:
        set[str]: .
    """
    return {str(value) for value in context.payload.get("evidence_ids", ())}


def _strategy_params(context: ResearchContextSnapshot) -> dict[str, Any]:
    """Build strategy parameters for prompt rendering.

    Args:
        context: ResearchContextSnapshot: .

    Returns:
        dict[str, Any]: .
    """
    return {
        "scope_version_id": context.scope_version_id,
        "screening_status": context.payload.get("screening_status"),
        "final_score": context.payload.get("final_score"),
        "rule": "研究结论，不输出自动交易指令",
    }


def _context_summary(context: ResearchContextSnapshot) -> str:
    """Render a deterministic JSON context summary for prompts.

    Args:
        context: ResearchContextSnapshot: .

    Returns:
        str: .
    """
    return json.dumps(
        {
            "security_id": context.security_id,
            "decision_at": context.decision_at.isoformat(),
            "previous_effective_assessment_id": context.payload.get(
                "previous_effective_assessment_id"
            ),
            "analysis_snapshot_id": context.payload.get("analysis_snapshot_id"),
            "analysis_summary": context.payload.get("analysis_summary", {}),
            "material_quant_change": context.payload.get("material_quant_change"),
            "material_news_change": context.payload.get("material_news_change"),
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _untrusted_blocks(context: ResearchContextSnapshot) -> list[str]:
    """Extract untrusted evidence text blocks from context.

    Args:
        context: ResearchContextSnapshot: .

    Returns:
        list[str]: .
    """
    return [
        str(block.get("content", ""))
        for block in context.payload.get("evidence_blocks", ())
        if isinstance(block, dict) and block.get("content")
    ]


def _empty_manifest(
    state: AIDeltaGraphState,
    node_name: str,
) -> ToolManifest:
    """Build a tool manifest with no tools for decision-only nodes.

    Args:
        state: AIDeltaGraphState: .
        node_name: str: .

    Returns:
        ToolManifest: .
    """
    return ToolManifest(
        graph_run_id=state.graph_run_id,
        node_name=node_name,
        security_id=state.security_id,
        decision_at=state.decision_at.isoformat(),
        policy_version="tool-policy-v0.2.0",
        tools=(),
        max_calls=0,
        max_result_bytes=0,
    )


def _graph_run_id_from_manifest(manifest: ToolManifest) -> str:
    """Extract the graph run ID from a tool manifest.

    Args:
        manifest: ToolManifest: .

    Returns:
        str: .
    """
    return manifest.graph_run_id


__all__ = [
    "ANALYSIS_SCHEMA",
    "DECISION_SCHEMA",
    "EvidenceBoundOutputValidator",
    "build_production_analysis_handlers",
    "build_production_citation_validator",
    "build_production_decision_handler",
]
