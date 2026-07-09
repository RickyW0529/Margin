"""Backfill domain expert for v1 Agent runtime."""

from __future__ import annotations

from margin.agents.protocol.models import WorkerTaskRequest


class BackfillExpertAgent:
    """BackfillExpertAgent.."""

    name = "BackfillExpertAgent"
    domain = "backfill"

    def create_worker_tasks(
        self,
        *,
        run_id: str,
        domain_task_id: str,
        context_pack_ref: str,
        capability_token_ref: str,
    ) -> tuple[WorkerTaskRequest, ...]:
        """Create worker tasks.

        Args:
            run_id: str: .
            domain_task_id: str: .
            context_pack_ref: str: .
            capability_token_ref: str: .

        Returns:
            tuple[WorkerTaskRequest, ...]: .
        """
        workers = (
            (
                "BackfillPlannerWorker",
                "Plan the deterministic 20-year endpoint and partition campaign.",
                ("backfill_endpoint_plan",),
                2,
            ),
            (
                "BackfillExecutorWorker",
                "Execute or dry-run idempotent backfill partitions.",
                ("backfill_partition_result",),
                4,
            ),
            (
                "BackfillVerifierWorker",
                "Build the quality report and PIT validation capsule.",
                ("backfill_quality_report",),
                2,
            ),
        )
        return tuple(
            WorkerTaskRequest(
                run_id=run_id,
                domain_task_id=domain_task_id,
                worker_task_id=f"{domain_task_id}:{worker_name}",
                parent_agent=self.name,
                worker_agent=worker_name,
                skill_id="twenty_year_backfill",
                task_goal=goal,
                input_context_pack_ref=context_pack_ref,
                required_output_types=output_types,
                tool_policy_ref="tool-policy:backfill-v1",
                capability_token_ref=capability_token_ref,
                token_budget=2048,
                max_tool_calls=max_tool_calls,
                deadline_ms=120_000,
                idempotency_key=f"{run_id}:{domain_task_id}:{worker_name}",
            )
            for worker_name, goal, output_types, max_tool_calls in workers
        )
