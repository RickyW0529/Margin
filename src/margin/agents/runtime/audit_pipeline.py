"""Audit pipeline for v1 Agent runtime outputs."""

from __future__ import annotations

from collections.abc import Mapping

from margin.agents.protocol.models import FinalAuditReport


class AuditPipeline:
    """AuditPipeline.."""

    def audit_final_answer(
        self,
        *,
        run_id: str,
        required_artifact_refs: tuple[str, ...],
        available_artifacts: Mapping[str, object],
        approved_capsule_refs: tuple[str, ...],
    ) -> FinalAuditReport:
        """Audit final answer.

        Args:
            run_id: str: .
            required_artifact_refs: tuple[str, ...]: .
            available_artifacts: Mapping[str, object]: .
            approved_capsule_refs: tuple[str, ...]: .

        Returns:
            FinalAuditReport: .
        """
        missing = tuple(
            artifact_ref
            for artifact_ref in required_artifact_refs
            if artifact_ref not in available_artifacts
        )
        final_allowed = not missing
        return FinalAuditReport(
            audit_report_id=f"fa_{run_id}",
            run_id=run_id,
            decision="complete" if final_allowed else "blocked",
            summary="final audit passed" if final_allowed else "missing required artifacts",
            blocking_reasons=() if final_allowed else ("missing_artifact_lineage",),
            missing_artifacts=missing,
            final_answer_allowed=final_allowed,
            final_user_message_constraints=("research_support_not_advice",),
            checked_artifact_refs=tuple(required_artifact_refs),
            checked_capsule_refs=approved_capsule_refs,
        )
