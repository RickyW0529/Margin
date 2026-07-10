"""Layer-2 Domain ExpertAgent runtime for v1 Agent protocol."""

from __future__ import annotations

from margin.agents.protocol.models import DomainTaskRequest, WorkerTaskRequest
from margin.agents.security.capability import CapabilityToken, derive_capability_token


class DomainRuntime:
    """DomainRuntime.."""

    def __init__(self, *, expert_agent_name: str) -> None:
        """Init .

        Args:
            expert_agent_name: str: .

        Returns:
            None: .
        """
        self.expert_agent_name = expert_agent_name
        self.issued_tokens: dict[str, CapabilityToken] = {}

    def create_worker_tasks(
        self,
        *,
        domain_request: DomainTaskRequest,
        parent_token: CapabilityToken,
        worker_agent_name: str,
        skill_id: str,
        required_output_types: tuple[str, ...],
        task_goal: str | None = None,
        constraints: dict[str, object] | None = None,
        worker_task_id: str | None = None,
        depends_on: tuple[str, ...] = (),
        allowed_tool_names: tuple[str, ...] | None = None,
        allowed_artifact_types: tuple[str, ...] | None = None,
        max_tool_calls: int | None = None,
    ) -> tuple[WorkerTaskRequest, ...]:
        """Create worker tasks.

        Args:
            domain_request: DomainTaskRequest: .
            parent_token: CapabilityToken: .
            worker_agent_name: str: .
            skill_id: str: .
            required_output_types: tuple[str, ...]: .

        Returns:
            tuple[WorkerTaskRequest, ...]: .
        """
        if domain_request.to_domain_agent != self.expert_agent_name:
            raise ValueError("domain request addressed to a different expert")
        resolved_worker_task_id = (
            worker_task_id or f"wt_{domain_request.domain_task_id.removeprefix('dt_')}"
        )
        child_token = derive_capability_token(
            parent_token,
            token_id=(
                f"{parent_token.token_id}:{resolved_worker_task_id}:"
                f"{worker_agent_name}:{skill_id}"
            ),
            issued_to=worker_agent_name,
            data_access=parent_token.data_access,
            production_write=parent_token.production_write,
            tool_policy=parent_token.tool_policy,
            allowed_artifact_types=tuple(
                artifact_type
                for artifact_type in (
                    required_output_types
                    if allowed_artifact_types is None
                    else allowed_artifact_types
                )
                if artifact_type in parent_token.allowed_artifact_types
            ),
            allowed_tool_names=(
                parent_token.allowed_tool_names
                if allowed_tool_names is None
                else tuple(
                    tool_name
                    for tool_name in allowed_tool_names
                    if tool_name in parent_token.allowed_tool_names
                )
            ),
            max_tool_calls=(
                parent_token.max_tool_calls
                if max_tool_calls is None
                else min(max_tool_calls, parent_token.max_tool_calls)
            ),
            max_result_bytes=parent_token.max_result_bytes,
            domain=domain_request.domain,
            bound_task_id=resolved_worker_task_id,
            bound_context_pack_id=domain_request.input_context_pack_ref,
        )
        self.issued_tokens[child_token.token_id] = child_token
        worker_task = WorkerTaskRequest(
            run_id=domain_request.run_id,
            domain_task_id=domain_request.domain_task_id,
            worker_task_id=resolved_worker_task_id,
            parent_agent=self.expert_agent_name,
            worker_agent=worker_agent_name,
            skill_id=skill_id,
            task_goal=task_goal or domain_request.task_goal,
            input_context_pack_ref=domain_request.input_context_pack_ref,
            input_artifact_refs=domain_request.input_artifact_refs,
            required_output_types=required_output_types,
            constraints=constraints or {},
            depends_on=depends_on,
            tool_policy_ref=child_token.token_id,
            capability_token_ref=child_token.token_id,
            token_budget=domain_request.token_budget,
            max_tool_calls=child_token.max_tool_calls,
            deadline_ms=domain_request.deadline_ms,
            idempotency_key=f"{domain_request.idempotency_key}:{worker_agent_name}:{skill_id}",
        )
        return (worker_task,)
