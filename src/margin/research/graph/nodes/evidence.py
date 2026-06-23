"""Centralized evidence planning and bounded retrieval nodes."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from margin.research.graph.state import AIDeltaGraphState, ReviewMode
from margin.research.tools.definitions import ToolCapability
from margin.research.tools.factory import ScopedToolFactory


class RetrievedEvidencePackage(BaseModel):
    """Validated payload returned by the evidence retrieval tool."""

    package_id: str
    summary: dict[str, Any] = Field(default_factory=dict)

    model_config = {"frozen": True}


class EvidencePlanNode:
    """Create deterministic questions and scope constraints."""

    def __call__(self, state: AIDeltaGraphState) -> dict[str, Any]:
        """Call the instance."""
        questions = [
            "核心基本面较上一有效结论发生了什么变化？",
            "当前估值假设是否仍然成立？",
            "有哪些风险或反方证据可能推翻原结论？",
        ]
        if state.review_mode == ReviewMode.DELTA_REVIEW:
            questions.insert(0, "本轮实质变化对上一有效结论有什么影响？")
        return {
            "evidence_plan": {
                "questions": tuple(questions),
                "security_id": state.security_id,
                "decision_at": state.decision_at.isoformat(),
                "change_set": state.change_set,
            },
            "graph_step_count": 1,
        }


class RetrieveEvidenceNode:
    """Only initial node allowed to perform broad evidence retrieval."""

    node_name = "retrieve_evidence"

    def __init__(self, tool_factory: ScopedToolFactory) -> None:
        """Initialize the instance."""
        self._tool_factory = tool_factory

    def __call__(self, state: AIDeltaGraphState) -> dict[str, Any]:
        """Call the instance."""
        return self._retrieve(state, supplemental=False, node_name=self.node_name)

    def _retrieve(
        self,
        state: AIDeltaGraphState,
        *,
        supplemental: bool,
        node_name: str,
    ) -> dict[str, Any]:
        """retrieve."""
        session = self._tool_factory.create_session(
            graph_run_id=state.graph_run_id,
            node_name=node_name,
            security_id=state.security_id,
            decision_at=state.decision_at,
            grants={ToolCapability.EVIDENCE_RETRIEVE},
            max_calls=1,
            max_result_bytes=262_144,
        )
        result = session.call(
            "evidence_retrieve",
            {
                "security_id": state.security_id,
                "decision_at": state.decision_at,
                "questions": tuple(state.evidence_plan.get("questions", ())),
                "evidence_gaps": state.evidence_gaps if supplemental else (),
                "supplemental": supplemental,
            },
        )
        base_update: dict[str, Any] = {
            "retrieval_count": 1,
            "graph_step_count": 1,
            "tool_call_ids": session.call_ids,
        }
        if not result.success:
            return {
                **base_update,
                "errors": (
                    f"{node_name}:{result.error_code or 'retrieval_failed'}",
                ),
            }
        package = RetrievedEvidencePackage.model_validate(result.data)
        return {
            **base_update,
            "evidence_package_ids": (package.package_id,),
            "node_outputs": {
                "evidence_packages": {
                    package.package_id: package.summary,
                },
                node_name: {
                    "package_id": package.package_id,
                    "supplemental": supplemental,
                },
            },
        }


class AdditionalEvidenceRetrievalNode(RetrieveEvidenceNode):
    """Perform the only allowed targeted supplemental retrieval."""

    node_name = "additional_evidence_retrieval"

    def __call__(self, state: AIDeltaGraphState) -> dict[str, Any]:
        """Call the instance."""
        if state.retrieval_count != 1 or not state.evidence_gaps:
            return {
                "errors": ("supplemental_retrieval_not_allowed",),
                "graph_step_count": 1,
            }
        return self._retrieve(
            state,
            supplemental=True,
            node_name=self.node_name,
        )
