"""Final audit helpers for v1 Agent runtime."""

from __future__ import annotations

from margin.agents.protocol.models import FinalAuditReport


class FinalAuditor:
    """Deterministic final auditor used before user-visible answers.."""

    def audit_answer_refs(
        self,
        *,
        run_id: str,
        required_domain_task_ids: tuple[str, ...],
        completed_domain_task_ids: tuple[str, ...],
        approved_artifact_refs: tuple[str, ...],
        approved_capsule_refs: tuple[str, ...],
        used_artifact_refs: tuple[str, ...],
        used_capsule_refs: tuple[str, ...],
        evidence_refs: tuple[str, ...],
        source_refs: tuple[str, ...],
    ) -> FinalAuditReport:
        """Audit that final answer references are approved and complete.

        Args:
            run_id: str: .
            required_domain_task_ids: tuple[str, ...]: .
            completed_domain_task_ids: tuple[str, ...]: .
            approved_artifact_refs: tuple[str, ...]: .
            approved_capsule_refs: tuple[str, ...]: .
            used_artifact_refs: tuple[str, ...]: .
            used_capsule_refs: tuple[str, ...]: .
            evidence_refs: tuple[str, ...]: .
            source_refs: tuple[str, ...]: .

        Returns:
            FinalAuditReport: .
        """
        blocking: list[str] = []
        missing_domains = tuple(
            domain_task_id
            for domain_task_id in required_domain_task_ids
            if domain_task_id not in completed_domain_task_ids
        )
        if missing_domains:
            blocking.append("missing domain tasks: " + ", ".join(missing_domains))
        unapproved_artifacts = tuple(
            ref for ref in used_artifact_refs if ref not in approved_artifact_refs
        )
        if unapproved_artifacts:
            blocking.append("unapproved artifact refs: " + ", ".join(unapproved_artifacts))
        unapproved_capsules = tuple(
            ref for ref in used_capsule_refs if ref not in approved_capsule_refs
        )
        if unapproved_capsules:
            blocking.append("unapproved capsule refs: " + ", ".join(unapproved_capsules))
        decision = "blocked" if blocking else "complete"
        return FinalAuditReport(
            audit_report_id=f"ctx_audit_{run_id}_final",
            run_id=run_id,
            decision=decision,
            summary="final audit blocked" if blocking else "final audit passed",
            blocking_reasons=tuple(blocking),
            missing_artifacts=(),
            final_answer_allowed=not blocking,
            final_user_message_constraints=("do not present research output as investment advice",),
            checked_artifact_refs=used_artifact_refs,
            checked_capsule_refs=used_capsule_refs,
            evidence_refs=evidence_refs,
            source_refs=source_refs,
        )
