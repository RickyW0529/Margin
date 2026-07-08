"""MainAgent runtime foundation."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

from margin.agent_runtime.cards import AgentCardRegistry
from margin.agent_runtime.context_store import (
    AgentContextStore,
    make_context_artifact,
    stable_json_hash,
)
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
from margin.agents.context.lineage import ArtifactLineageValidator
from margin.agents.protocol.models import ContextPack
from margin.agents.runtime.executor_registry import (
    ExecutorRegistry,
    default_qna_executor_registry,
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
        executor_registry: ExecutorRegistry | None = None,
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
        self._executor_registry = executor_registry or default_qna_executor_registry()
        self._lineage_validator = ArtifactLineageValidator()

    @property
    def scheduled_flow(self) -> AgentFlowDefinition:
        """Return the default scheduled flow configured for this runtime."""
        return self._scheduled_flow

    def create_scheduled_stock_analysis_plan(
        self,
        *,
        run_id: str,
        user_intent_summary: str,
        scheduled_flow: AgentFlowDefinition | None = None,
    ) -> MainAgentPlanResult:
        """Create the fixed scheduled stock-analysis plan."""
        flow = scheduled_flow or self._scheduled_flow
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
            for definition in flow.steps
        )
        plan_decision = self._plan_guardrail.validate_fixed_flow(
            run_type=run.run_type,
            permission_mode=run.permission_mode,
            planned_step_ids=tuple(step.step_id for step in steps),
            fixed_flow=flow,
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
        context_pack: ContextPack | None = None,
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
            context_pack=context_pack,
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

    def final_review(
        self,
        *,
        run_id: str,
        scheduled_flow: AgentFlowDefinition | None = None,
    ) -> MainAgentReviewResult:
        """Review required scheduled artifacts for a run."""
        flow = scheduled_flow or self._scheduled_flow
        artifacts = self._context_store.list_artifacts(run_id)
        artifact_types = {artifact.artifact_type for artifact in artifacts}
        required = set(self._final_review_step(flow).required_artifacts)
        missing = tuple(sorted(required - artifact_types))
        expected_producers = _expected_producers(flow)
        invalid = []
        checked_artifact_ids = []
        evidence_refs = []
        source_refs = []
        for artifact in artifacts:
            if artifact.artifact_type not in required:
                continue
            checked_artifact_ids.append(artifact.artifact_id)
            evidence_refs.extend(artifact.evidence_refs)
            source_refs.extend(artifact.source_refs)
            check = self._lineage_validator.validate(
                artifact,
                expected_producer=expected_producers.get(artifact.artifact_type),
                expected_artifact_type=artifact.artifact_type,
            )
            invalid.extend(
                f"{artifact.artifact_id}:{problem}" for problem in check.problems
            )
        audit_payload = {
            "required_artifacts": sorted(required),
            "missing_artifacts": list(missing),
            "invalid_artifacts": sorted(invalid),
            "checked_artifact_refs": checked_artifact_ids,
            "evidence_refs": tuple(dict.fromkeys(evidence_refs)),
            "source_refs": tuple(dict.fromkeys(source_refs)),
        }
        audit_ref = self._write_final_audit_artifact(
            run_id=run_id,
            payload=audit_payload,
        )
        if missing or invalid:
            expert, skill = self._retry_target_for_artifact(
                missing[0],
                scheduled_flow=flow,
            ) if missing else (None, None)
            return MainAgentReviewResult(
                decision="blocked",
                summary="Missing required scheduled stock-analysis artifacts.",
                missing_artifacts=missing,
                invalid_artifacts=tuple(sorted(invalid)),
                audit_report_ref=audit_ref,
                expert_to_retry=expert,
                skill_to_retry=skill,
            )
        return MainAgentReviewResult(
            decision="complete",
            summary="Scheduled stock-analysis artifacts are complete.",
            audit_report_ref=audit_ref,
            frontend_trace_summary=tuple(
                step.frontend_projection.label
                for step in flow.steps
                if step.frontend_projection.visible
            ),
        )

    def add_context_artifact(self, artifact: ContextArtifact) -> None:
        """Persist an expert-agent output artifact in the Shared Context Store."""
        self._context_store.add_artifact(artifact)

    def list_context_artifacts(self, run_id: str) -> list[ContextArtifact]:
        """List Context Store artifacts for a run."""
        return self._context_store.list_artifacts(run_id)

    def get_context_artifact(self, artifact_id: str) -> ContextArtifact | None:
        """Return one Context Store artifact by ID."""
        return self._context_store.get_artifact(artifact_id)

    def scheduled_flow_summary(
        self,
        *,
        scheduled_flow: AgentFlowDefinition | None = None,
    ) -> dict[str, Any]:
        """Return a compact DAG summary for orchestration metadata and UI."""
        flow = scheduled_flow or self._scheduled_flow
        return {
            "flow_id": flow.flow_id,
            "version": flow.version,
            "dependency_waves": [
                [step.step_id for step in wave]
                for wave in flow.dependency_waves()
            ],
            "branches": {
                "quant": ["quant_analysis"],
                "fundamental": [
                    "performance_growth_scout",
                    "rag_coverage_gate",
                    "fundamental_analysis",
                    "sentiment_monitor",
                ],
                "fusion": ["fusion_research"],
            },
            "quant_branch_uses_websearch": False,
        }

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

    def _final_review_step(
        self,
        scheduled_flow: AgentFlowDefinition,
    ) -> AgentStepDefinition:
        for step in scheduled_flow.steps:
            if step.step_id == "main_agent_final_review":
                return step
        raise ValueError("scheduled flow missing main_agent_final_review step")

    def _retry_target_for_artifact(
        self,
        artifact_type: str,
        *,
        scheduled_flow: AgentFlowDefinition,
    ) -> tuple[str | None, str | None]:
        for step in scheduled_flow.steps:
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
        context_pack: ContextPack | None,
    ) -> tuple[str, ...]:
        return self._select_user_qna_agents_with_llm(
            user_input=user_input,
            run_id=run_id,
            conversation_context=conversation_context,
            context_pack=context_pack,
        )

    def _select_user_qna_agents_with_llm(
        self,
        *,
        user_input: str,
        run_id: str,
        conversation_context: list[dict[str, str]],
        context_pack: ContextPack | None,
    ) -> tuple[str, ...]:
        if self._llm_provider_factory is None:
            raise MainAgentPlanningError("LLM planner is not configured")

        template = self._prompt_registry.get("main_agent_qna_planner_v0.4")
        rendered = self._prompt_renderer.render(
            template,
            variables={
                "user_request": user_input,
                "conversation_context": conversation_context,
                "context_pack": (
                    context_pack.model_dump(mode="json") if context_pack else {}
                ),
                "run_context": {
                    "run_id": run_id,
                    "run_type": AgentRunType.USER_QNA.value,
                    "permission_mode": AgentPermissionMode.READ_ONLY.value,
                },
                "expert_agent_cards": [
                    card.model_dump(mode="json")
                    for card in self._executor_registry.planner_visible_agent_cards(
                        self._cards.list_cards()
                    )
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
            return any(
                self._executor_registry.has(agent_name, skill.skill_id)
                for skill in qa_skills
            )
        return any(
            skill.skill_id == skill_id
            and self._executor_registry.has(agent_name, skill.skill_id)
            for skill in qa_skills
        )

    def _write_final_audit_artifact(
        self,
        *,
        run_id: str,
        payload: dict[str, object],
    ) -> str:
        payload_hash = stable_json_hash(payload).removeprefix("sha256:")[:16]
        artifact = make_context_artifact(
            artifact_id=f"ctx_{run_id}_final_audit_{payload_hash}",
            run_id=run_id,
            artifact_type="final_audit_report",
            producer_agent="MainAgent",
            payload_json=payload,
            source_refs=tuple(payload.get("checked_artifact_refs", ())),
            evidence_refs=tuple(payload.get("evidence_refs", ())),
        )
        self._context_store.add_artifact(artifact)
        return artifact.artifact_id


def _coerce_agent_name(step: dict[str, object]) -> str:
    for key in ("expert_agent_name", "expert_agent", "agent_name", "name"):
        value = step.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def _expected_producers(flow: AgentFlowDefinition) -> dict[str, str]:
    return {
        artifact_type: step.expert_agent
        for step in flow.steps
        for artifact_type in step.produced_artifacts
    }
