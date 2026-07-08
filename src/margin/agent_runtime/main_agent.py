"""MainAgent runtime foundation."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

from margin.agent_runtime.cards import AgentCardRegistry
from margin.agent_runtime.context_store import AgentContextStore
from margin.agent_runtime.guardrails import (
    GuardrailDecisionType,
    InputGuardrail,
    PlanGuardrail,
)
from margin.agent_runtime.models import (
    AgentExecutionStatus,
    AgentFlowDefinition,
    AgentPermissionMode,
    AgentPlan,
    AgentRun,
    AgentRunType,
    AgentStep,
    AgentStepDefinition,
    ContextArtifact,
    MainAgentPlanResult,
    MainAgentReviewResult,
)
from margin.prompts.agent_runtime import agent_runtime_prompt_templates
from margin.prompts.registry import PromptRegistry
from margin.prompts.renderer import PromptRenderer
from margin.research.llm import LLMProvider


class MainAgentPlanningError(RuntimeError):
    """Raised when MainAgent cannot produce a valid LLM-backed Q&A plan."""


class MainAgentRuntime:
    """MainAgent planner and reviewer.

    This foundation class does not execute ExpertAgents. It creates plans from
    flow definitions and reviews Context Store artifacts.
    """

    def __init__(
        self,
        *,
        context_store: AgentContextStore,
        card_registry: AgentCardRegistry,
        scheduled_flow: AgentFlowDefinition,
        input_guardrail: InputGuardrail | None = None,
        plan_guardrail: PlanGuardrail | None = None,
        llm_provider_factory: Callable[[], LLMProvider] | None = None,
        prompt_registry: PromptRegistry | None = None,
        prompt_renderer: PromptRenderer | None = None,
    ) -> None:
        self._context_store = context_store
        self._cards = card_registry
        self._scheduled_flow = scheduled_flow
        self._input_guardrail = input_guardrail or InputGuardrail()
        self._plan_guardrail = plan_guardrail or PlanGuardrail()
        self._llm_provider_factory = llm_provider_factory
        self._prompt_registry = prompt_registry or PromptRegistry(
            templates=agent_runtime_prompt_templates()
        )
        self._prompt_renderer = prompt_renderer or PromptRenderer()

    def create_scheduled_stock_analysis_plan(
        self,
        *,
        run_id: str,
        user_intent_summary: str,
    ) -> MainAgentPlanResult:
        """Create the fixed scheduled stock-analysis plan."""
        input_decision = self._input_guardrail.evaluate(
            user_intent_summary,
            run_id=run_id,
        )
        self._context_store.add_guardrail_decision(input_decision)
        if input_decision.decision != GuardrailDecisionType.ALLOW:
            self._context_store.add_run(
                AgentRun(
                    run_id=run_id,
                    run_type=AgentRunType.SCHEDULED_STOCK_ANALYSIS,
                    status=AgentExecutionStatus.BLOCKED,
                    permission_mode=AgentPermissionMode.WRITE_ALLOWED,
                    trigger_source="scheduler",
                    user_intent_summary=user_intent_summary,
                    started_at=datetime.now(UTC),
                    finished_at=datetime.now(UTC),
                )
            )
            return MainAgentPlanResult(
                plan=AgentPlan(
                    plan_id=f"plan_{run_id}",
                    run_id=run_id,
                    fixed_flow=True,
                    steps=(),
                ),
                guardrail_decision=input_decision,
            )

        run = AgentRun(
            run_id=run_id,
            run_type=AgentRunType.SCHEDULED_STOCK_ANALYSIS,
            status=AgentExecutionStatus.RUNNING,
            permission_mode=AgentPermissionMode.WRITE_ALLOWED,
            trigger_source="scheduler",
            user_intent_summary=user_intent_summary,
            started_at=datetime.now(UTC),
        )
        self._context_store.add_run(run)
        steps = tuple(
            self._step_from_definition(definition, run_id=run_id)
            for definition in self._scheduled_flow.steps
        )
        plan_decision = self._plan_guardrail.validate_fixed_flow(
            run_type=run.run_type,
            permission_mode=run.permission_mode,
            planned_step_ids=tuple(step.step_id for step in steps),
            fixed_flow=self._scheduled_flow,
            run_id=run_id,
        )
        self._context_store.add_guardrail_decision(plan_decision)
        if plan_decision.decision != GuardrailDecisionType.ALLOW:
            steps = ()
        for step in steps:
            self._context_store.add_step(step)
        return MainAgentPlanResult(
            plan=AgentPlan(
                plan_id=f"plan_{run_id}",
                run_id=run_id,
                fixed_flow=True,
                steps=steps,
            ),
            guardrail_decision=plan_decision,
        )

    def create_user_qna_plan(
        self,
        *,
        run_id: str,
        user_input: str,
        conversation_context: list[dict[str, str]] | None = None,
    ) -> MainAgentPlanResult:
        """Create a dynamic read-only user-Q&A plan from exposed ExpertAgent cards."""
        input_decision = self._input_guardrail.evaluate(user_input, run_id=run_id)
        self._context_store.add_guardrail_decision(input_decision)
        if input_decision.decision != GuardrailDecisionType.ALLOW:
            self._context_store.add_run(
                AgentRun(
                    run_id=run_id,
                    run_type=AgentRunType.USER_QNA,
                    status=AgentExecutionStatus.BLOCKED,
                    permission_mode=AgentPermissionMode.READ_ONLY,
                    trigger_source="user_qna",
                    user_intent_summary=user_input,
                    started_at=datetime.now(UTC),
                    finished_at=datetime.now(UTC),
                )
            )
            return MainAgentPlanResult(
                plan=AgentPlan(
                    plan_id=f"plan_{run_id}",
                    run_id=run_id,
                    fixed_flow=False,
                    steps=(),
                ),
                guardrail_decision=input_decision,
            )

        self._context_store.add_run(
            AgentRun(
                run_id=run_id,
                run_type=AgentRunType.USER_QNA,
                status=AgentExecutionStatus.RUNNING,
                permission_mode=AgentPermissionMode.READ_ONLY,
                trigger_source="user_qna",
                user_intent_summary=user_input,
                started_at=datetime.now(UTC),
            )
        )
        selected_agents = self._select_user_qna_agents(
            user_input=user_input,
            run_id=run_id,
            conversation_context=conversation_context or [],
        )

        steps = tuple(
            self._qna_step(agent_name, run_id=run_id, index=index + 1)
            for index, agent_name in enumerate(selected_agents)
        )
        for step in steps:
            self._context_store.add_step(step)
        return MainAgentPlanResult(
            plan=AgentPlan(
                plan_id=f"plan_{run_id}",
                run_id=run_id,
                fixed_flow=False,
                steps=steps,
            ),
            guardrail_decision=input_decision,
        )

    def final_review(self, *, run_id: str) -> MainAgentReviewResult:
        """Review required scheduled artifacts for a run."""
        artifacts = self._context_store.list_artifacts(run_id)
        artifact_types = {artifact.artifact_type for artifact in artifacts}
        required = set(self._final_review_step().required_artifacts)
        missing = tuple(sorted(required - artifact_types))
        if missing:
            expert, skill = self._retry_target_for_artifact(missing[0])
            return MainAgentReviewResult(
                decision="blocked",
                summary="Missing required scheduled stock-analysis artifacts.",
                missing_artifacts=missing,
                expert_to_retry=expert,
                skill_to_retry=skill,
            )
        return MainAgentReviewResult(
            decision="complete",
            summary="Scheduled stock-analysis artifacts are complete.",
            frontend_trace_summary=tuple(
                step.frontend_projection.label
                for step in self._scheduled_flow.steps
                if step.frontend_projection.visible
            ),
        )

    def add_context_artifact(self, artifact: ContextArtifact) -> None:
        """Persist an expert-agent output artifact in the Shared Context Store."""
        self._context_store.add_artifact(artifact)

    def list_context_artifacts(self, run_id: str) -> list[ContextArtifact]:
        """List Context Store artifacts for a run."""
        return self._context_store.list_artifacts(run_id)

    @staticmethod
    def _step_from_definition(
        definition: AgentStepDefinition,
        *,
        run_id: str,
    ) -> AgentStep:
        return AgentStep(
            step_id=definition.step_id,
            run_id=run_id,
            expert_agent_name=definition.expert_agent,
            skill_id=definition.skill_id,
            status=AgentExecutionStatus.PENDING,
            input_artifact_refs=definition.required_artifacts,
        )

    def _final_review_step(self) -> AgentStepDefinition:
        for step in self._scheduled_flow.steps:
            if step.step_id == "main_agent_final_review":
                return step
        raise ValueError("scheduled flow missing main_agent_final_review step")

    def _retry_target_for_artifact(
        self,
        artifact_type: str,
    ) -> tuple[str | None, str | None]:
        for step in self._scheduled_flow.steps:
            if artifact_type in step.produced_artifacts:
                return step.expert_agent, step.skill_id
        return None, None

    def _qna_step(self, agent_name: str, *, run_id: str, index: int) -> AgentStep:
        card = self._cards.get(agent_name)
        skill = next(
            (
                candidate
                for candidate in card.skills
                if candidate.qa_allowed
                and candidate.write_policy == AgentPermissionMode.READ_ONLY
            ),
            None,
        )
        if skill is None:
            raise ValueError(f"agent '{agent_name}' has no Q&A skill")
        step_slug = agent_name.removesuffix("Agent").lower()
        return AgentStep(
            step_id=f"qna_{index}_{step_slug}",
            run_id=run_id,
            expert_agent_name=card.name,
            skill_id=skill.skill_id,
            status=AgentExecutionStatus.PENDING,
            input_artifact_refs=skill.required_context_artifacts,
        )

    def _select_user_qna_agents(
        self,
        *,
        user_input: str,
        run_id: str,
        conversation_context: list[dict[str, str]],
    ) -> tuple[str, ...]:
        return self._select_user_qna_agents_with_llm(
            user_input=user_input,
            run_id=run_id,
            conversation_context=conversation_context,
        )

    def _select_user_qna_agents_with_llm(
        self,
        *,
        user_input: str,
        run_id: str,
        conversation_context: list[dict[str, str]],
    ) -> tuple[str, ...]:
        if self._llm_provider_factory is None:
            raise MainAgentPlanningError("LLM planner is not configured")

        template = self._prompt_registry.get("main_agent_qna_planner_v0.4")
        rendered = self._prompt_renderer.render(
            template,
            variables={
                "user_request": user_input,
                "conversation_context": conversation_context,
                "run_context": {
                    "run_id": run_id,
                    "run_type": AgentRunType.USER_QNA.value,
                    "permission_mode": AgentPermissionMode.READ_ONLY.value,
                },
                "expert_agent_cards": [
                    card.model_dump(mode="json")
                    for card in self._cards.list_cards()
                ],
                "artifact_summaries": [],
                "guardrail_decisions": [],
            },
        )
        try:
            llm_provider = self._llm_provider_factory()
            result = llm_provider.complete(
                rendered.text,
                response_schema=rendered.output_schema,
                temperature=rendered.temperature,
            )
        except Exception as exc:
            raise MainAgentPlanningError(
                f"LLM planner failed: {type(exc).__name__}: {exc}"
            ) from exc
        if not result.success:
            raise MainAgentPlanningError(
                result.error or "LLM planner completion failed"
            )
        selected = self._agent_names_from_plan_output(result.output)
        if not selected:
            raise MainAgentPlanningError("LLM planner produced no valid Q&A expert")
        return selected

    def _agent_names_from_plan_output(self, output: dict[str, Any]) -> tuple[str, ...]:
        raw_steps = output.get("steps")
        if not isinstance(raw_steps, list):
            return ()
        selected: list[str] = []
        for raw_step in raw_steps:
            if not isinstance(raw_step, dict):
                continue
            agent_name = _coerce_agent_name(raw_step)
            if not agent_name or agent_name in selected:
                continue
            if self._is_allowed_qna_agent(agent_name, raw_step.get("skill_id")):
                selected.append(agent_name)
        return tuple(selected)

    def _is_allowed_qna_agent(
        self,
        agent_name: str,
        skill_id: object,
    ) -> bool:
        try:
            card = self._cards.get(agent_name)
        except KeyError:
            return False
        qa_skills = [
            skill
            for skill in card.skills
            if skill.qa_allowed
            and skill.write_policy == AgentPermissionMode.READ_ONLY
        ]
        if not qa_skills:
            return False
        if skill_id in (None, ""):
            return True
        return any(skill.skill_id == skill_id for skill in qa_skills)


def _coerce_agent_name(step: dict[str, object]) -> str:
    for key in ("expert_agent_name", "expert_agent", "agent_name", "name"):
        value = step.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""
