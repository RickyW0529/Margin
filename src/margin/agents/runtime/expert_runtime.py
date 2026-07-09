"""Layer-2 ExpertAgent runtime for dynamic worker planning."""

from __future__ import annotations

import json
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator

from margin.agents.cards.worker_cards import WorkerAgentCard
from margin.agents.prompts.domain_experts import DOMAIN_EXPERT_SYSTEM_V1
from margin.agents.protocol.models import ContextPack, DomainTaskRequest
from margin.agents.protocol.planning import NON_EXECUTION_KINDS, PlanActionKind
from margin.research.llm import LLMProvider


class WorkerPlanStepDraft(BaseModel):
    """One ExpertAgent-planned WorkerAgent step."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    step_id: str
    kind: PlanActionKind = PlanActionKind.EXECUTE
    worker_agent: str | None = None
    skill_id: str | None = None
    task: str = ""
    required_output_types: tuple[str, ...] = ()
    depends_on: tuple[str, ...] = ()
    constraints: dict[str, Any] = Field(default_factory=dict)
    reason: str = ""
    missing_inputs: tuple[str, ...] = ()
    user_safe_message: str = ""

    @model_validator(mode="after")
    def validate_by_kind(self) -> WorkerPlanStepDraft:
        """Validate fields required by this action kind."""
        if self.kind is PlanActionKind.EXECUTE:
            if not self.worker_agent or not self.skill_id:
                raise ValueError("execute step requires worker_agent and skill_id")
            if not self.task:
                raise ValueError("execute step requires task")
        if self.kind in NON_EXECUTION_KINDS and not (
            self.reason or self.user_safe_message
        ):
            raise ValueError(f"{self.kind} requires reason or user_safe_message")
        return self


class ExpertWorkerPlanDraft(BaseModel):
    """Structured WorkerAgent plan produced by one ExpertAgent."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    steps: tuple[WorkerPlanStepDraft, ...]
    audit_requirements: tuple[str, ...] = ("verify_artifacts_before_returning",)
    prompt_text: str = ""

    @model_validator(mode="after")
    def validate_steps(self) -> ExpertWorkerPlanDraft:
        """Validate step identity and dependencies."""
        if not self.steps:
            raise ValueError("steps required")
        step_ids = [step.step_id for step in self.steps]
        if len(step_ids) != len(set(step_ids)):
            raise ValueError("duplicate step_id")
        known_ids = set(step_ids)
        for step in self.steps:
            for dependency_id in step.depends_on:
                if dependency_id not in known_ids:
                    raise ValueError(f"unknown depends_on: {dependency_id}")
        return self


class LLMExpertAgentPlanner:
    """Prompt-driven ExpertAgent planner that selects WorkerAgents from cards."""

    def __init__(self, *, llm_provider: LLMProvider) -> None:
        """Initialize with the LLM provider used for structured planning."""
        self._llm_provider = llm_provider

    def plan(
        self,
        *,
        domain_task: DomainTaskRequest,
        worker_cards: tuple[WorkerAgentCard, ...],
        context_pack: ContextPack,
    ) -> ExpertWorkerPlanDraft:
        """Return a structured worker plan for one domain task."""
        prompt_text = _build_expert_planning_prompt(
            domain_task=domain_task,
            worker_cards=worker_cards,
            context_pack=context_pack,
        )
        result = self._llm_provider.complete(
            prompt_text,
            response_schema={
                "type": "object",
                "required": ["steps"],
                "properties": {
                    "steps": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "required": ["step_id"],
                            "properties": {
                                "step_id": {"type": "string"},
                                "kind": {
                                    "enum": [
                                        "execute",
                                        "ask_clarification",
                                        "blocked",
                                        "insufficient_evidence",
                                    ]
                                },
                                "worker_agent": {"type": ["string", "null"]},
                                "skill_id": {"type": ["string", "null"]},
                                "task": {"type": "string"},
                                "required_output_types": {
                                    "type": "array",
                                    "items": {"type": "string"},
                                },
                                "depends_on": {
                                    "type": "array",
                                    "items": {"type": "string"},
                                },
                                "constraints": {"type": "object"},
                                "reason": {"type": "string"},
                                "missing_inputs": {
                                    "type": "array",
                                    "items": {"type": "string"},
                                },
                                "user_safe_message": {"type": "string"},
                            },
                            "additionalProperties": False,
                        },
                    },
                    "audit_requirements": {"type": "array"},
                },
            },
            temperature=0.0,
        )
        if not result.success:
            raise RuntimeError(result.error or "ExpertAgent planning failed")
        raw_steps = result.output.get("steps")
        if not isinstance(raw_steps, list) or not raw_steps:
            raise RuntimeError("ExpertAgent planning returned no worker steps")
        allowed_pairs = {
            (card.name, skill.skill_id)
            for card in worker_cards
            for skill in card.skills
            if not skill.planned_only
        }
        steps = tuple(WorkerPlanStepDraft.model_validate(item) for item in raw_steps)
        for step in steps:
            if step.kind is not PlanActionKind.EXECUTE:
                continue
            if (step.worker_agent, step.skill_id) not in allowed_pairs:
                raise RuntimeError(
                    "ExpertAgent selected unavailable WorkerAgent skill: "
                    f"{step.worker_agent}.{step.skill_id}"
                )
        audit_requirements = result.output.get("audit_requirements")
        if not isinstance(audit_requirements, list):
            audit_requirements = ["verify_artifacts_before_returning"]
        return ExpertWorkerPlanDraft(
            steps=steps,
            audit_requirements=tuple(str(item) for item in audit_requirements),
            prompt_text=prompt_text,
        )


def _build_expert_planning_prompt(
    *,
    domain_task: DomainTaskRequest,
    worker_cards: tuple[WorkerAgentCard, ...],
    context_pack: ContextPack,
) -> str:
    """Build the bounded ExpertAgent planning prompt from A2A inputs."""
    worker_catalog = [
        {
            "name": card.name,
            "domain": card.domain,
            "description": card.description,
            "skills": [
                {
                    "skill_id": skill.skill_id,
                    "description": skill.description,
                    "input_contract": skill.input_contract,
                    "tool_allowlist": list(skill.tool_allowlist),
                    "tool_contracts": list(skill.tool_contracts),
                    "output_artifact_types": list(skill.output_artifact_types),
                    "supported_runtimes": list(card.supported_runtimes),
                }
                for skill in card.skills
                if not skill.planned_only
            ],
        }
        for card in worker_cards
    ]
    return "\n".join(
        (
            DOMAIN_EXPERT_SYSTEM_V1,
            "Plan worker steps dynamically from the worker cards below.",
            "Do not execute tools. Do not answer the user directly.",
            (
                "Return JSON with steps[].constraints.worker_inputs for executable "
                "workers when the selected skill declares an input_contract."
            ),
            (
                "Treat worker cards as the only source of executable capabilities. "
                "If no visible worker skill can satisfy the task contract, return a "
                "blocked or clarification step instead of inventing a route."
            ),
            (
                "Input-safety rule: worker_inputs must be scalar fields from the "
                "current user turn, never copied conversation_context, prior assistant "
                "answers, ContextPack JSON, or DomainTask JSON."
            ),
            (
                "For DataQuestionWorker.answer_financial_metric, user_query must be "
                "the exact current user question; security_query must be only the "
                "standalone security name or code such as 中国平安 or 601318.SH; "
                "indicator_id must be a supported id such as roe_ttm. If the current "
                "user turn does not contain both a financial metric and a target, "
                "return ask_clarification instead of reusing earlier turns."
            ),
            domain_task.model_dump_json(),
            context_pack.model_dump_json(),
            json.dumps(worker_catalog, ensure_ascii=False),
        )
    )
