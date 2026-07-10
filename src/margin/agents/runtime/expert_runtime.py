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
        if _has_step_cycle(self.steps):
            raise ValueError("worker plan contains a dependency cycle")
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
        skills_by_pair = {
            (card.name, skill.skill_id): skill
            for card in worker_cards
            for skill in card.skills
            if not skill.planned_only
        }
        steps = tuple(WorkerPlanStepDraft.model_validate(item) for item in raw_steps)
        for step in steps:
            if step.kind is not PlanActionKind.EXECUTE:
                continue
            skill = skills_by_pair.get((step.worker_agent, step.skill_id))
            if skill is None:
                raise RuntimeError(
                    "ExpertAgent selected unavailable WorkerAgent skill: "
                    f"{step.worker_agent}.{step.skill_id}"
                )
            unsupported_outputs = tuple(
                output
                for output in step.required_output_types
                if output not in skill.output_artifact_types
            )
            if unsupported_outputs:
                raise RuntimeError(
                    "ExpertAgent requested unsupported WorkerAgent outputs: "
                    + ", ".join(unsupported_outputs)
                )
        audit_requirements = result.output.get("audit_requirements")
        if not isinstance(audit_requirements, list):
            audit_requirements = ["verify_artifacts_before_returning"]
        return ExpertWorkerPlanDraft(
            steps=steps,
            audit_requirements=tuple(str(item) for item in audit_requirements),
            prompt_text=prompt_text,
        )


class CapabilityExpertPlanner:
    """Deterministic fallback that composes visible skills from their contracts."""

    def plan(
        self,
        *,
        domain_task: DomainTaskRequest,
        worker_cards: tuple[WorkerAgentCard, ...],
        context_pack: ContextPack,
    ) -> ExpertWorkerPlanDraft:
        """Cover required outputs without relying on worker names or domain recipes."""
        del context_pack
        candidates = [
            (card, skill)
            for card in worker_cards
            for skill in card.skills
            if not skill.planned_only
        ]
        required = set(domain_task.required_output_types)
        uncovered = set(required)
        selected: list[tuple[WorkerAgentCard, Any]] = []
        while candidates and (uncovered or not selected):
            card, skill = max(
                candidates,
                key=lambda item: len(set(item[1].output_artifact_types) & uncovered),
            )
            coverage = set(skill.output_artifact_types) & uncovered
            if required and not coverage:
                break
            selected.append((card, skill))
            uncovered -= coverage
            candidates.remove((card, skill))
            if not uncovered:
                break
        if uncovered or not selected:
            return _blocked_capability_plan(
                "No executable worker skill covers: " + ", ".join(sorted(uncovered or required))
            )
        if any(_required_input_fields(skill) for _card, skill in selected):
            return _blocked_capability_plan(
                "Worker input fields require LLM planning or user clarification."
            )
        steps: list[WorkerPlanStepDraft] = []
        produced_by_step: dict[str, set[str]] = {}
        for index, (card, skill) in enumerate(selected, start=1):
            step_id = f"worker_{index}"
            inputs = set(skill.input_artifact_types)
            dependencies = tuple(
                previous_step_id
                for previous_step_id, outputs in produced_by_step.items()
                if inputs & outputs
            )
            steps.append(
                WorkerPlanStepDraft(
                    step_id=step_id,
                    worker_agent=card.name,
                    skill_id=skill.skill_id,
                    task=domain_task.task_goal,
                    required_output_types=tuple(
                        output
                        for output in domain_task.required_output_types
                        if output in skill.output_artifact_types
                    )
                    or skill.output_artifact_types,
                    depends_on=dependencies,
                    constraints={"planned_by": "capability_fallback"},
                )
            )
            produced_by_step[step_id] = set(skill.output_artifact_types)
        return ExpertWorkerPlanDraft(steps=tuple(steps), prompt_text="capability_fallback")


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
                "Populate worker_inputs only from each selected skill's input_contract. "
                "Do not use worker names, remembered examples, or domain keywords as "
                "implicit input rules."
            ),
            domain_task.model_dump_json(),
            context_pack.model_dump_json(),
            json.dumps(worker_catalog, ensure_ascii=False),
        )
    )


def _has_step_cycle(steps: tuple[WorkerPlanStepDraft, ...]) -> bool:
    dependencies = {step.step_id: set(step.depends_on) for step in steps}
    remaining = set(dependencies)
    while remaining:
        ready = {
            step_id
            for step_id in remaining
            if not (dependencies[step_id] & remaining)
        }
        if not ready:
            return True
        remaining -= ready
    return False


def _required_input_fields(skill: Any) -> tuple[str, ...]:
    fields = skill.input_contract.get("required_fields", ())
    if isinstance(fields, str):
        return (fields,)
    if isinstance(fields, list | tuple):
        return tuple(str(field) for field in fields)
    return ()


def _blocked_capability_plan(reason: str) -> ExpertWorkerPlanDraft:
    return ExpertWorkerPlanDraft(
        steps=(
            WorkerPlanStepDraft(
                step_id="capability_blocked",
                kind=PlanActionKind.BLOCKED,
                reason=reason,
                user_safe_message=reason,
            ),
        ),
        prompt_text="capability_fallback",
    )
