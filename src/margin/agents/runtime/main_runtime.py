"""Layer-1 MainAgent runtime for v1 Agent protocol."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from margin.agents.cards.domain_cards import DomainAgentCard
from margin.agents.prompts.main_agent import (
    MAIN_AGENT_QNA_PLANNER_V1,
    MAIN_AGENT_SCHEDULED_PLANNER_V1,
    MAIN_AGENT_SYSTEM_V1,
)
from margin.agents.protocol.models import ContextPack, DomainTaskRequest
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
    created_by: str = "MainAgent"


class MainPlanningContext(BaseModel):
    """Bounded runtime context passed to MainAgent planning."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    run_id: str
    run_type: str
    user_goal: str
    context_pack_ref: str
    conversation_context: tuple[dict[str, str], ...] = ()
    domain_agent_names: tuple[str, ...]
    domain_agent_catalog: tuple[dict[str, object], ...] = ()
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
    agent: str
    task: str
    required_output_types: tuple[str, ...] = ()
    depends_on: tuple[str, ...] = ()
    constraints: dict[str, Any] = Field(default_factory=dict)


class MainPlanDraft(BaseModel):
    """Structured MainAgent plan before runtime capability derivation."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    steps: tuple[MainPlanStepDraft, ...]
    final_answer_requirements: tuple[str, ...] = ("use_approved_capsules_only",)
    prompt_text: str = ""


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
                    "steps": {"type": "array"},
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
        task_agents = [task.to_domain_agent for task in plan.domain_tasks]
        for task in plan.domain_tasks:
            card = self._domain_cards_by_name.get(task.to_domain_agent)
            if card is None:
                errors.append("unknown_domain_agent")
                continue
            if task.domain != card.domain:
                errors.append("domain_mismatch")
            if not task.required_output_types:
                errors.append("missing_required_outputs")
        known_agents = set(task_agents)
        if "unknown_domain_agent" not in errors:
            for edge in plan.domain_dependency_edges:
                if edge.get("from") not in known_agents or edge.get("to") not in known_agents:
                    errors.append("unknown_dependency_agent")
        if len(task_agents) != len(set(task_agents)):
            errors.append("duplicate_domain_agent")
        return MainPlanValidationResult(valid=not errors, error_codes=tuple(dict.fromkeys(errors)))


class MainRuntime:
    """MainRuntime.."""

    def __init__(
        self,
        *,
        domain_cards: tuple[DomainAgentCard, ...],
        planner: LLMMainAgentPlanner,
        tool_gateway: object | None = None,
    ) -> None:
        """Init .

        Args:
            domain_cards: tuple[DomainAgentCard, ...]: .
            tool_gateway: object | None: .

        Returns:
            None: .
        """
        self._domain_cards = domain_cards
        self._domain_cards_by_name = {card.name: card for card in domain_cards}
        self._planner = planner
        self._tool_gateway = tool_gateway
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
        planning_context = MainPlanningContext(
            run_id=run_id,
            run_type=run_type,
            user_goal=user_goal,
            context_pack_ref=context_pack.context_pack_id,
            conversation_context=tuple(conversation_context[-8:]),
            domain_agent_names=tuple(card.name for card in self._domain_cards),
            domain_agent_catalog=tuple(_card_catalog_item(card) for card in self._domain_cards),
        )
        planning_prompt_ref = _planning_prompt_ref(run_type)
        plan_draft = self._planner.plan(
            prompt_ref=planning_prompt_ref,
            planning_context=planning_context,
        )
        dependency_edges = _dependency_edges_from_plan(plan_draft)
        tasks: list[DomainTaskRequest] = []
        for step in plan_draft.steps:
            card = self._domain_cards_by_name.get(step.agent)
            if card is None:
                raise RuntimeError(f"MainAgent selected unknown ExpertAgent: {step.agent}")
            child_token = derive_capability_token(
                capability_token,
                token_id=f"{capability_token.token_id}:{card.name}",
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
                allowed_artifact_types=tuple(
                    artifact_type
                    for artifact_type in capability_token.allowed_artifact_types
                    if artifact_type in set(card.required_output_types)
                ),
                max_tool_calls=min(capability_token.max_tool_calls, 2),
                can_delegate=True,
                delegation_depth_remaining=1,
            )
            self.issued_tokens[child_token.token_id] = child_token
            required_output_types = step.required_output_types or card.required_output_types
            constraints = dict(step.constraints)
            constraints.setdefault("planned_by", "MainAgent")
            constraints.setdefault("main_agent_direct_tool_access", False)
            tasks.append(
                DomainTaskRequest(
                    run_id=run_id,
                    domain_task_id=f"dt_{step.step_id}",
                    to_domain_agent=card.name,
                    domain=card.domain,
                    user_intent_summary=user_goal,
                    task_goal=step.task,
                    required_output_types=required_output_types,
                    input_context_pack_ref=context_pack.context_pack_id,
                    capability_token_ref=child_token.token_id,
                    constraints=constraints,
                    token_budget=min(context_pack.token_budget, card.max_context_tokens),
                    deadline_ms=30_000,
                    idempotency_key=f"{run_id}:{card.name}:{context_pack.payload_hash}",
                )
            )
        return GlobalPlan(
            run_id=run_id,
            run_type=run_type,
            user_intent=user_goal,
            domain_tasks=tuple(tasks),
            final_answer_requirements=plan_draft.final_answer_requirements,
            planning_prompt_ref=planning_prompt_ref,
            planning_prompt_hash=_stable_short_hash(plan_draft.prompt_text),
            domain_dependency_edges=dependency_edges,
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
            edges.append(
                {
                    "from": dependency.agent,
                    "to": step.agent,
                    "reason": f"{dependency_id}->{step.step_id}",
                }
            )
    return tuple(edges)


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

def _stable_short_hash(value: str) -> str:
    """Return a stable short sha256 hash for prompt lineage."""
    import hashlib

    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:16]
