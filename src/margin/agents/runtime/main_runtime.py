"""Layer-1 MainAgent runtime for v1 Agent protocol."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator

from margin.agents.cards.domain_cards import DomainAgentCard
from margin.agents.context.turn_context import ResolvedTurnContext
from margin.agents.prompts.main_agent import (
    MAIN_AGENT_QNA_PLANNER_V1,
    MAIN_AGENT_SCHEDULED_PLANNER_V1,
    MAIN_AGENT_SYSTEM_V1,
)
from margin.agents.protocol.models import ContextPack, DomainTaskRequest
from margin.agents.protocol.planning import NON_EXECUTION_KINDS, PlanActionKind
from margin.agents.runtime.capability_registry import CapabilityRegistry
from margin.agents.security.capability import CapabilityToken, derive_capability_token
from margin.research.llm import LLMProvider


class GlobalPlan(BaseModel):
    """GlobalPlan.."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    run_id: str
    run_type: str
    user_intent: str
    domain_tasks: tuple[DomainTaskRequest, ...]
    final_answer_requirements: tuple[str, ...] = ()
    planning_mode: str = "prompt_dynamic"
    planning_prompt_ref: str = ""
    planning_prompt_hash: str = ""
    domain_dependency_edges: tuple[dict[str, str], ...] = ()
    planner_messages: tuple[dict[str, Any], ...] = ()
    created_by: str = "MainAgent"


class MainPlanningContext(BaseModel):
    """Bounded runtime context passed to MainAgent planning."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    run_id: str
    run_type: str
    user_goal: str
    context_pack_ref: str
    conversation_context: tuple[dict[str, str], ...] = ()
    resolved_turn_context: ResolvedTurnContext | None = None
    domain_agent_names: tuple[str, ...]
    domain_agent_catalog: tuple[dict[str, object], ...] = ()
    context_status: tuple[dict[str, object], ...] = ()
    capability_snapshot: dict[str, object] = Field(default_factory=dict)
    data_readiness_refs: tuple[str, ...] = ()
    policy_summary: tuple[str, ...] = (
        "MainAgent cannot call tools directly",
        "MainAgent must delegate through Domain ExpertAgents",
        "scheduled tasks are intents, not fixed flows",
        "financial outputs are research support, not investment advice",
    )


class MainPlanValidationResult(BaseModel):
    """Safe validation result for one MainAgent GlobalPlan."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    valid: bool
    error_codes: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()


class MainPlanStepDraft(BaseModel):
    """One MainAgent-planned Domain Expert step."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    step_id: str
    kind: PlanActionKind = PlanActionKind.DELEGATE
    agent: str | None = None
    domain: str | None = None
    task: str = ""
    required_output_types: tuple[str, ...] = ()
    depends_on: tuple[str, ...] = ()
    constraints: dict[str, Any] = Field(default_factory=dict)
    reason: str = ""
    missing_inputs: tuple[str, ...] = ()
    user_safe_message: str = ""

    @model_validator(mode="after")
    def validate_by_kind(self) -> MainPlanStepDraft:
        """Validate fields required by this action kind."""
        if self.kind is PlanActionKind.DELEGATE:
            if not self.agent:
                raise ValueError("delegate step requires agent")
            if not self.task:
                raise ValueError("delegate step requires task")
        if self.kind in NON_EXECUTION_KINDS and not (
            self.reason or self.user_safe_message
        ):
            raise ValueError(f"{self.kind} requires reason or user_safe_message")
        return self


class MainPlanDraft(BaseModel):
    """Structured MainAgent plan before runtime capability derivation."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    steps: tuple[MainPlanStepDraft, ...]
    final_answer_requirements: tuple[str, ...] = ("use_approved_capsules_only",)
    prompt_text: str = ""

    @model_validator(mode="after")
    def validate_steps(self) -> MainPlanDraft:
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


class LLMMainAgentPlanner:
    """Prompt-driven MainAgent planner that selects ExpertAgents from cards."""

    def __init__(self, *, llm_provider: LLMProvider) -> None:
        """Initialize with the LLM provider used for structured planning."""
        self._llm_provider = llm_provider

    def plan(
        self,
        *,
        prompt_ref: str,
        planning_context: MainPlanningContext,
    ) -> MainPlanDraft:
        """Return a structured A2A domain plan produced by MainAgent."""
        prompt_text = _build_planning_prompt(
            prompt_ref=prompt_ref,
            planning_context=planning_context,
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
                                        "delegate",
                                        "inspect_context",
                                        "ask_clarification",
                                        "blocked",
                                        "insufficient_evidence",
                                        "synthesize",
                                    ]
                                },
                                "agent": {"type": ["string", "null"]},
                                "domain": {"type": ["string", "null"]},
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
                    "final_answer_requirements": {"type": "array"},
                },
            },
            temperature=0.0,
        )
        if not result.success:
            raise RuntimeError(result.error or "MainAgent planning failed")
        raw_steps = result.output.get("steps")
        if not isinstance(raw_steps, list) or not raw_steps:
            raise RuntimeError("MainAgent planning returned no steps")
        steps = tuple(MainPlanStepDraft.model_validate(item) for item in raw_steps)
        final_requirements = result.output.get("final_answer_requirements")
        if not isinstance(final_requirements, list):
            final_requirements = ["use_approved_capsules_only"]
        return MainPlanDraft(
            steps=steps,
            final_answer_requirements=tuple(str(item) for item in final_requirements),
            prompt_text=prompt_text,
        )


class MainPlanValidator:
    """Validate MainAgent plans before any runtime execution."""

    def __init__(self, domain_cards: tuple[DomainAgentCard, ...]) -> None:
        """Initialize with the currently registered Domain ExpertAgent cards."""
        self._domain_cards_by_name = {card.name: card for card in domain_cards}

    def validate(self, plan: GlobalPlan) -> MainPlanValidationResult:
        """Return whether the plan uses only allowed experts and dependencies."""
        errors: list[str] = []
        task_ids = {task.domain_task_id for task in plan.domain_tasks}
        for task in plan.domain_tasks:
            card = self._domain_cards_by_name.get(task.to_domain_agent)
            if card is None:
                errors.append("unknown_domain_agent")
                continue
            if task.domain != card.domain:
                errors.append("domain_mismatch")
            if not task.required_output_types:
                errors.append("missing_required_outputs")
            if any(dependency_id not in task_ids for dependency_id in task.depends_on):
                errors.append("unknown_dependency_task")
        if _has_dependency_cycle(plan.domain_tasks):
            errors.append("dependency_cycle")
        return MainPlanValidationResult(valid=not errors, error_codes=tuple(dict.fromkeys(errors)))


class MainRuntime:
    """MainRuntime.."""

    def __init__(
        self,
        *,
        domain_cards: tuple[DomainAgentCard, ...],
        planner: LLMMainAgentPlanner,
        capability_registry: CapabilityRegistry | None = None,
    ) -> None:
        """Init .

        Args:
            domain_cards: tuple[DomainAgentCard, ...]: .
            capability_registry: Registry used to expose only executable agents.

        Returns:
            None: .
        """
        self._domain_cards = domain_cards
        self._domain_cards_by_name = {card.name: card for card in domain_cards}
        self._planner = planner
        self._capability_registry = capability_registry
        self.issued_tokens: dict[str, CapabilityToken] = {}

    def create_global_plan(
        self,
        *,
        run_id: str,
        run_type: str,
        user_goal: str,
        context_pack: ContextPack,
        capability_token: CapabilityToken,
        conversation_context: tuple[dict[str, str], ...] = (),
    ) -> GlobalPlan:
        """Create global plan.

        Args:
            run_id: str: .
            run_type: str: .
            user_goal: str: .
            context_pack: ContextPack: .
            capability_token: CapabilityToken: .

        Returns:
            GlobalPlan: .
        """
        visible_domain_cards = self._visible_domain_cards(capability_token)
        visible_cards_by_name = {card.name: card for card in visible_domain_cards}
        planning_context = MainPlanningContext(
            run_id=run_id,
            run_type=run_type,
            user_goal=user_goal,
            context_pack_ref=context_pack.context_pack_id,
            conversation_context=tuple(conversation_context[-8:]),
            resolved_turn_context=context_pack.resolved_turn_context,
            domain_agent_names=tuple(card.name for card in visible_domain_cards),
            domain_agent_catalog=tuple(_card_catalog_item(card) for card in visible_domain_cards),
            context_status=_context_status_from_pack(context_pack),
            capability_snapshot=self._capability_snapshot(capability_token),
            data_readiness_refs=tuple(
                ref for ref in context_pack.included_artifact_refs if "data_readiness" in ref
            ),
        )
        planning_prompt_ref = _planning_prompt_ref(run_type)
        plan_draft = self._planner.plan(
            prompt_ref=planning_prompt_ref,
            planning_context=planning_context,
        )
        dependency_edges = _dependency_edges_from_plan(plan_draft)
        tasks: list[DomainTaskRequest] = []
        planner_messages: list[dict[str, Any]] = []
        for step in plan_draft.steps:
            if step.kind is not PlanActionKind.DELEGATE:
                planner_messages.append(
                    {
                        "step_id": step.step_id,
                        "kind": step.kind,
                        "domain": step.domain,
                        "reason": step.reason,
                        "missing_inputs": list(step.missing_inputs),
                        "user_safe_message": step.user_safe_message,
                    }
                )
                continue
            card = visible_cards_by_name.get(step.agent or "")
            if card is None:
                fallback_card = self._domain_cards_by_name.get(step.agent or "")
                planner_messages.append(
                    {
                        "step_id": step.step_id,
                        "kind": PlanActionKind.BLOCKED,
                        "domain": step.domain or (fallback_card.domain if fallback_card else None),
                        "reason": (
                            f"{step.agent or step.domain or 'selected domain'} is not "
                            "executable in the current capability snapshot"
                        ),
                        "missing_inputs": list(step.missing_inputs),
                        "user_safe_message": step.user_safe_message
                        or "当前环境没有开放该能力。",
                    }
                )
                continue
            domain_task_id = f"dt_{step.step_id}"
            required_output_types = tuple(
                dict.fromkeys((*card.required_output_types, *step.required_output_types))
            )
            unsupported_outputs = self._unsupported_outputs(
                card=card,
                required_output_types=required_output_types,
                capability_token=capability_token,
            )
            if unsupported_outputs:
                planner_messages.append(
                    {
                        "step_id": step.step_id,
                        "kind": PlanActionKind.BLOCKED,
                        "domain": card.domain,
                        "reason": (
                            "selected expert cannot produce authorized outputs: "
                            + ", ".join(unsupported_outputs)
                        ),
                        "missing_inputs": [],
                        "user_safe_message": (
                            "当前能力无法产出计划要求的结果类型。"
                        ),
                    }
                )
                continue
            child_token = derive_capability_token(
                capability_token,
                token_id=f"{capability_token.token_id}:{step.step_id}:{card.name}",
                issued_to=card.name,
                data_access=tuple(
                    policy
                    for policy in card.data_access_policy
                    if policy in capability_token.data_access
                ),
                production_write=tuple(
                    policy
                    for policy in card.production_write_policy
                    if policy in capability_token.production_write
                ),
                tool_policy=tuple(
                    policy for policy in card.tool_policy if policy in capability_token.tool_policy
                ),
                allowed_artifact_types=capability_token.allowed_artifact_types,
                max_tool_calls=min(
                    capability_token.max_tool_calls,
                    getattr(card, "max_tool_calls", capability_token.max_tool_calls),
                ),
                can_delegate=True,
                delegation_depth_remaining=1,
                domain=card.domain,
                bound_task_id=domain_task_id,
                bound_context_pack_id=context_pack.context_pack_id,
                bound_context_pack_hash=context_pack.content_hash,
            )
            self.issued_tokens[child_token.token_id] = child_token
            constraints = dict(step.constraints)
            constraints.setdefault("planned_by", "MainAgent")
            constraints.setdefault("main_agent_direct_tool_access", False)
            tasks.append(
                DomainTaskRequest(
                    run_id=run_id,
                    domain_task_id=domain_task_id,
                    to_domain_agent=card.name,
                    domain=card.domain,
                    user_intent_summary=user_goal,
                    task_goal=step.task,
                    required_output_types=required_output_types,
                    input_context_pack_ref=context_pack.context_pack_id,
                    capability_token_ref=child_token.token_id,
                    constraints=constraints,
                    depends_on=tuple(f"dt_{dependency_id}" for dependency_id in step.depends_on),
                    token_budget=min(context_pack.token_budget, card.max_context_tokens),
                    deadline_ms=30_000,
                    idempotency_key=(
                        f"{run_id}:{step.step_id}:{card.name}:{context_pack.payload_hash}"
                    ),
                )
            )
        tasks, dependency_messages = _prune_unavailable_dependency_tasks(tasks)
        planner_messages.extend(dependency_messages)
        retained_token_refs = {task.capability_token_ref for task in tasks}
        self.issued_tokens = {
            token_ref: token
            for token_ref, token in self.issued_tokens.items()
            if token.run_id != run_id or token_ref in retained_token_refs
        }
        task_ids = {task.domain_task_id for task in tasks}
        dependency_edges = tuple(
            edge
            for edge in dependency_edges
            if edge.get("from") in task_ids and edge.get("to") in task_ids
        )
        plan = GlobalPlan(
            run_id=run_id,
            run_type=run_type,
            user_intent=user_goal,
            domain_tasks=tuple(tasks),
            final_answer_requirements=plan_draft.final_answer_requirements,
            planning_prompt_ref=planning_prompt_ref,
            planning_prompt_hash=_stable_short_hash(plan_draft.prompt_text),
            domain_dependency_edges=dependency_edges,
            planner_messages=tuple(planner_messages),
        )
        validation = MainPlanValidator(visible_domain_cards).validate(plan)
        if not validation.valid:
            raise RuntimeError(
                "MainAgent plan validation failed: " + ",".join(validation.error_codes)
            )
        return plan

    def _visible_domain_cards(
        self,
        capability_token: CapabilityToken,
    ) -> tuple[DomainAgentCard, ...]:
        if self._capability_registry is None:
            return self._domain_cards
        return self._capability_registry.visible_domain_cards(
            capability_token=capability_token,
            require_executable_worker=True,
        )

    def _capability_snapshot(self, capability_token: CapabilityToken) -> dict[str, object]:
        if self._capability_registry is None:
            return {}
        return self._capability_registry.snapshot(
            capability_token=capability_token,
        ).model_dump(mode="json")

    def _unsupported_outputs(
        self,
        *,
        card: DomainAgentCard,
        required_output_types: tuple[str, ...],
        capability_token: CapabilityToken,
    ) -> tuple[str, ...]:
        authorized = set(capability_token.allowed_artifact_types)
        denied = tuple(
            output for output in required_output_types if output not in authorized
        )
        if self._capability_registry is None:
            return denied
        producible = set(
            self._capability_registry.producible_output_types(
                domain=card.domain,
                capability_token=capability_token,
            )
        )
        return tuple(
            output
            for output in required_output_types
            if output not in authorized or output not in producible
        )


def _planning_prompt_ref(run_type: str) -> str:
    """Return the prompt ID used for this MainAgent planning mode."""
    if run_type == "scheduled_stock_analysis":
        return "main_agent_scheduled_planner_v1"
    return "main_agent_qna_planner_v1"


def _build_planning_prompt(
    *,
    prompt_ref: str,
    planning_context: MainPlanningContext,
) -> str:
    """Build a bounded planning prompt for hash/lineage without calling tools."""
    planner_text = (
        MAIN_AGENT_SCHEDULED_PLANNER_V1
        if prompt_ref == "main_agent_scheduled_planner_v1"
        else MAIN_AGENT_QNA_PLANNER_V1
    )
    return "\n".join(
        (
            MAIN_AGENT_SYSTEM_V1,
            planner_text,
            (
                "Current-turn authority rule: planning_context.user_goal plus "
                "resolved_turn_context are the only query authority. The resolved "
                "state contains user-confirmed inherited slots. conversation_context "
                "is background only and must never supply lookup keys."
            ),
            (
                "Use each visible capability's input contract to decide whether the "
                "current user_goal has enough input. Ask for missing fields instead of "
                "routing by remembered examples or domain keywords."
            ),
            planning_context.model_dump_json(),
        )
    )


def _dependency_edges_from_plan(plan_draft: MainPlanDraft) -> tuple[dict[str, str], ...]:
    """Return dependency edges declared by MainAgent plan steps."""
    step_by_id = {step.step_id: step for step in plan_draft.steps}
    edges: list[dict[str, str]] = []
    for step in plan_draft.steps:
        for dependency_id in step.depends_on:
            dependency = step_by_id.get(dependency_id)
            if dependency is None:
                continue
            if not dependency.agent or not step.agent:
                continue
            edges.append(
                {
                    "from": f"dt_{dependency_id}",
                    "to": f"dt_{step.step_id}",
                    "reason": f"{dependency_id}->{step.step_id}",
                }
            )
    return tuple(edges)


def _prune_unavailable_dependency_tasks(
    tasks: list[DomainTaskRequest],
) -> tuple[list[DomainTaskRequest], list[dict[str, Any]]]:
    remaining = {task.domain_task_id: task for task in tasks}
    messages: list[dict[str, Any]] = []
    while True:
        blocked = tuple(
            task
            for task in remaining.values()
            if any(dependency_id not in remaining for dependency_id in task.depends_on)
        )
        if not blocked:
            break
        for task in blocked:
            missing_dependencies = tuple(
                dependency_id
                for dependency_id in task.depends_on
                if dependency_id not in remaining
            )
            remaining.pop(task.domain_task_id, None)
            messages.append(
                {
                    "step_id": task.domain_task_id.removeprefix("dt_"),
                    "kind": PlanActionKind.BLOCKED,
                    "domain": task.domain,
                    "reason": (
                        "required plan dependencies are not executable: "
                        + ", ".join(missing_dependencies)
                    ),
                    "missing_inputs": [],
                    "user_safe_message": "当前请求的前置能力不可用，本轮未继续执行。",
                }
            )
    return (
        [task for task in tasks if task.domain_task_id in remaining],
        messages,
    )


def _card_catalog_item(card: DomainAgentCard) -> dict[str, object]:
    """Return a compact card view supplied to MainAgent planning prompts."""
    return {
        "name": card.name,
        "domain": card.domain,
        "description": card.description,
        "worker_agent_names": list(card.worker_agent_names),
        "capability_manifest": list(card.capability_manifest),
        "required_output_types": list(card.required_output_types),
    }


def _context_status_from_pack(context_pack: ContextPack) -> tuple[dict[str, object], ...]:
    """Return data-status facts in a compact planner-safe shape."""
    return tuple(
        {
            "subject_id": fact.subject_id,
            "statement": fact.statement,
            "value_json": fact.value_json or {},
            "artifact_refs": list(fact.artifact_refs),
        }
        for fact in context_pack.facts
        if fact.fact_type == "data_status"
    )


def _stable_short_hash(value: str) -> str:
    """Return a stable short sha256 hash for prompt lineage."""
    import hashlib

    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:16]


def _has_dependency_cycle(tasks: tuple[DomainTaskRequest, ...]) -> bool:
    dependencies = {task.domain_task_id: set(task.depends_on) for task in tasks}
    remaining = set(dependencies)
    while remaining:
        ready = {
            task_id
            for task_id in remaining
            if not (dependencies[task_id] & remaining)
        }
        if not ready:
            return True
        remaining -= ready
    return False
