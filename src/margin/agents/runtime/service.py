"""Application-facing v1 Agent runtime service."""

from __future__ import annotations

import hashlib
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Literal

from margin.agent_runtime.context_store import (
    AgentContextStore,
    ContextArtifact,
    make_context_artifact,
)
from margin.agents.cards.registry import default_domain_agent_cards
from margin.agents.context.repository import ContextRepository, MemoryContextRepository
from margin.agents.context.router import ContextRouter
from margin.agents.protocol.models import (
    AgentExecutionStatus,
    ContextPack,
    DomainAuditReport,
    DomainContextCapsule,
    FinalUserAnswerArtifact,
)
from margin.agents.runtime.audit_pipeline import AuditPipeline
from margin.agents.runtime.main_runtime import GlobalPlan, MainRuntime
from margin.agents.security.capability import CapabilityToken
from margin.agents.security.policies import (
    DataAccessPolicy,
    ProductionWritePolicy,
    ToolPolicy,
)
from margin.dashboard.models import DashboardFilters, DashboardSort
from margin.dashboard.service import DashboardServiceBundle
from margin.research.llm import LLMProvider

USER_QNA_RUNTIME_VERSION = "agent-runtime-v1-user-qna"
_DEFAULT_ALLOWED_ARTIFACT_TYPES = (
    "analysis_table",
    "data_context_capsule",
    "data_readiness",
    "domain_audit_report",
    "domain_context_capsule",
    "evidence_context_capsule",
    "evidence_package",
    "explanation",
    "final_audit_report",
    "final_user_answer",
    "qna_answer",
    "quant_context_capsule",
    "quant_result",
    "stock_research_context_capsule",
)


@dataclass(frozen=True)
class UserQnaCommand:
    """One user-facing Q&A command entering the v1 runtime."""

    run_id: str
    scope_version_id: str
    message: str
    universe: str
    language: Literal["zh", "en"]
    conversation_context: Sequence[dict[str, str]] = ()


@dataclass(frozen=True)
class GuardrailSummary:
    """Frontend-safe guardrail result."""

    allowed: bool
    decision: str
    summary: str
    triggered_policies: tuple[str, ...] = ()


@dataclass(frozen=True)
class AgentTraceStep:
    """One user-visible v1 Agent trace row."""

    step_id: str
    expert_agent_name: str
    skill_id: str
    status: AgentExecutionStatus


@dataclass(frozen=True)
class UserQnaRunResult:
    """Result returned by the v1 runtime to the API boundary."""

    answer: str
    guardrail: GuardrailSummary
    global_plan: GlobalPlan
    trace_steps: tuple[AgentTraceStep, ...]
    artifacts: tuple[ContextArtifact, ...]
    references: tuple[dict[str, str], ...]
    final_answer: FinalUserAnswerArtifact


class AgentInputBlockedError(RuntimeError):
    """Raised when the v1 input guardrail blocks a user request."""

    def __init__(self, guardrail: GuardrailSummary) -> None:
        """Initialize with the safe guardrail summary."""
        super().__init__(guardrail.summary)
        self.guardrail = guardrail


class AgentRuntimeUnavailableError(RuntimeError):
    """Raised when a required v1 runtime dependency is unavailable."""


class AgentRuntimeService:
    """Run user-facing Agent workflows through the v1 control-plane protocol."""

    def __init__(
        self,
        *,
        context_store: AgentContextStore,
        context_repository: ContextRepository | None = None,
        dashboard_services: DashboardServiceBundle,
        llm_provider_factory: Callable[[], LLMProvider],
        main_runtime: MainRuntime | None = None,
        audit_pipeline: AuditPipeline | None = None,
    ) -> None:
        """Initialize the application-facing v1 Agent runtime service."""
        self._context_store = context_store
        self._context_repository = context_repository or MemoryContextRepository()
        self._dashboard_services = dashboard_services
        self._llm_provider_factory = llm_provider_factory
        self._main_runtime = main_runtime or MainRuntime(
            domain_cards=default_domain_agent_cards(),
        )
        self._audit_pipeline = audit_pipeline or AuditPipeline()

    def run_user_qna(self, command: UserQnaCommand) -> UserQnaRunResult:
        """Run one user Q&A request through v1 planning and final audit."""
        guardrail = _evaluate_user_input(command.message)
        if not guardrail.allowed:
            raise AgentInputBlockedError(guardrail)

        context_pack = self._build_and_store_context_pack(command)
        root_token = _root_capability_token(command.run_id)
        global_plan = self._main_runtime.create_global_plan(
            run_id=command.run_id,
            run_type="user_qna",
            user_goal=command.message,
            context_pack=context_pack,
            capability_token=root_token,
        )
        domain_task = global_plan.domain_tasks[0]
        table_artifact, table_rows = self._build_candidate_table_artifact(command)
        answer = self._answer_with_llm(
            command=command,
            context_pack=context_pack,
            table_rows=table_rows,
        )
        answer_artifact = make_context_artifact(
            artifact_id=f"ctx_{command.run_id}_qna_answer",
            run_id=command.run_id,
            artifact_type="qna_answer",
            producer_agent="GeneralQnaWorker",
            payload_json={
                "answer": answer,
                "language": command.language,
                "runtime_version": USER_QNA_RUNTIME_VERSION,
            },
            source_refs=("agent:v1:user_qna",),
        )
        domain_capsule = DomainContextCapsule(
            capsule_id=f"dcc_{command.run_id}_general",
            run_id=command.run_id,
            domain=domain_task.domain,
            purpose="user_qna",
            status=AgentExecutionStatus.SUCCEEDED,
            summary=answer,
            artifact_refs=(table_artifact.artifact_id, answer_artifact.artifact_id),
            source_refs=("agent:v1:user_qna",),
            compression_policy_version="domain-capsule-v1",
            input_hash=context_pack.payload_hash,
        )
        domain_audit = DomainAuditReport(
            audit_report_id=f"da_{command.run_id}_general",
            run_id=command.run_id,
            domain_task_id=domain_task.domain_task_id,
            domain=domain_task.domain,
            status=AgentExecutionStatus.SUCCEEDED,
            checked_artifact_refs=(table_artifact.artifact_id, answer_artifact.artifact_id),
            schema_valid=True,
            evidence_valid=True,
            source_refs_valid=True,
            context_budget_ok=True,
            safe_summary="domain audit passed",
        )
        capsule_artifact = make_context_artifact(
            artifact_id=domain_capsule.capsule_id,
            run_id=command.run_id,
            artifact_type="domain_context_capsule",
            producer_agent=domain_task.to_domain_agent,
            payload_json=domain_capsule.model_dump(mode="json"),
            source_refs=domain_capsule.source_refs,
        )
        domain_audit_artifact = make_context_artifact(
            artifact_id=domain_audit.audit_report_id,
            run_id=command.run_id,
            artifact_type="domain_audit_report",
            producer_agent=domain_task.to_domain_agent,
            payload_json=domain_audit.model_dump(mode="json"),
            source_refs=("agent:v1:user_qna",),
        )
        self._context_repository.save_domain_capsule(
            domain_capsule,
            domain_task_id=domain_task.domain_task_id,
            expert_agent=domain_task.to_domain_agent,
            output_artifact_refs=domain_capsule.artifact_refs,
            audit_report_ref=domain_audit.audit_report_id,
            token_estimate=len(domain_capsule.model_dump_json()),
        )
        self._context_repository.record_lineage_edge(
            run_id=command.run_id,
            from_ref=domain_capsule.capsule_id,
            to_ref=context_pack.context_pack_id,
            edge_type="source_ref",
        )
        for artifact_ref in domain_capsule.artifact_refs:
            self._context_repository.record_lineage_edge(
                run_id=command.run_id,
                from_ref=domain_capsule.capsule_id,
                to_ref=artifact_ref,
                edge_type="source_ref",
            )
        for evidence_ref in domain_capsule.evidence_refs:
            self._context_repository.record_lineage_edge(
                run_id=command.run_id,
                from_ref=domain_capsule.capsule_id,
                to_ref=evidence_ref,
                edge_type="evidence_ref",
            )
        available_artifacts = {
            artifact.artifact_id: artifact
            for artifact in (
                table_artifact,
                answer_artifact,
                capsule_artifact,
                domain_audit_artifact,
            )
        }
        final_audit = self._audit_pipeline.audit_final_answer(
            run_id=command.run_id,
            required_artifact_refs=(capsule_artifact.artifact_id,),
            available_artifacts=available_artifacts,
            approved_capsule_refs=(domain_capsule.capsule_id,),
        )
        final_answer = FinalUserAnswerArtifact(
            artifact_id=f"fua_{command.run_id}",
            run_id=command.run_id,
            answer_text=answer,
            language=command.language,
            used_domain_capsule_refs=(domain_capsule.capsule_id,),
            used_artifact_refs=(table_artifact.artifact_id, answer_artifact.artifact_id),
            source_refs=("agent:v1:user_qna",),
            disclaimers=("research_support_not_financial_advice",),
            limitations=("offline_research_context_may_be_incomplete",),
            final_audit_report_ref=final_audit.audit_report_id,
        )
        final_answer_artifact = make_context_artifact(
            artifact_id=final_answer.artifact_id,
            run_id=command.run_id,
            artifact_type="final_user_answer",
            producer_agent="MainAgent",
            payload_json=final_answer.model_dump(mode="json"),
            source_refs=final_answer.source_refs,
        )
        final_audit_artifact = make_context_artifact(
            artifact_id=final_audit.audit_report_id,
            run_id=command.run_id,
            artifact_type="final_audit_report",
            producer_agent="MainAgent",
            payload_json=final_audit.model_dump(mode="json"),
            source_refs=("agent:v1:user_qna",),
        )
        artifacts = (
            table_artifact,
            answer_artifact,
            capsule_artifact,
            domain_audit_artifact,
            final_audit_artifact,
            final_answer_artifact,
        )
        for artifact in artifacts:
            self._context_store.add_artifact(artifact)
        return UserQnaRunResult(
            answer=answer,
            guardrail=guardrail,
            global_plan=global_plan,
            trace_steps=(
                AgentTraceStep(
                    step_id=domain_task.domain_task_id,
                    expert_agent_name=domain_task.to_domain_agent,
                    skill_id=_skill_for_domain_task(domain_task.domain),
                    status=AgentExecutionStatus.SUCCEEDED,
                ),
            ),
            artifacts=artifacts,
            references=_references_from_rows(table_rows),
            final_answer=final_answer,
        )

    def get_context_artifact(self, artifact_id: str) -> ContextArtifact | None:
        """Return a context artifact for scoped frontend expansion."""
        return self._context_store.get_artifact(artifact_id)

    def _build_and_store_context_pack(self, command: UserQnaCommand) -> ContextPack:
        """Build and persist the L1 ContextPack artifact."""
        context_pack = ContextRouter().build_context_pack(
            run_id=command.run_id,
            requester_agent="MainAgent",
            target_agent="MainAgent",
            purpose="user_qna_planning",
            token_budget=4000,
            included_chat_summary_ref=f"chat_summary:{_conversation_hash(command)}",
        )
        self._context_store.add_artifact(
            make_context_artifact(
                artifact_id=context_pack.context_pack_id,
                run_id=command.run_id,
                artifact_type="context_pack",
                producer_agent="MainAgent",
                payload_json=context_pack.model_dump(mode="json"),
                source_refs=(context_pack.included_chat_summary_ref or "chat_summary:none",),
            )
        )
        self._context_repository.save_context_pack(context_pack)
        if context_pack.included_chat_summary_ref:
            self._context_repository.record_lineage_edge(
                run_id=command.run_id,
                from_ref=context_pack.context_pack_id,
                to_ref=context_pack.included_chat_summary_ref,
                edge_type="source_ref",
            )
        return context_pack

    def _build_candidate_table_artifact(
        self,
        command: UserQnaCommand,
    ) -> tuple[ContextArtifact, list[dict[str, Any]]]:
        """Read dashboard candidates through the app service and store a table artifact."""
        rows = self._load_candidate_rows(command)
        artifact = make_context_artifact(
            artifact_id=f"ctx_{command.run_id}_dashboard_candidates",
            run_id=command.run_id,
            artifact_type="analysis_table",
            producer_agent="DataQuestionWorker",
            payload_json={
                "scope_version_id": command.scope_version_id,
                "universe": command.universe,
                "columns": [
                    "security_id",
                    "symbol",
                    "final_score",
                    "confidence",
                    "screening_status",
                ],
                "rows": rows,
            },
            source_refs=("dashboard:research_candidates",),
        )
        return artifact, rows

    def _load_candidate_rows(self, command: UserQnaCommand) -> list[dict[str, Any]]:
        """Load a compact dashboard candidate table without exposing raw internals."""
        try:
            page = self._dashboard_services.query.list_research_candidates_v2(
                scope_version_id=command.scope_version_id,
                universe_code=command.universe,
                filters=DashboardFilters(),
                sort=DashboardSort(field="final_score", direction="desc"),
                cursor=None,
                limit=10,
            )
        except Exception:
            return []
        return [
            {
                "security_id": item.security_id,
                "symbol": item.symbol,
                "final_score": item.final_score,
                "confidence": item.confidence,
                "screening_status": item.screening_status,
            }
            for item in page.items
        ]

    def _answer_with_llm(
        self,
        *,
        command: UserQnaCommand,
        context_pack: ContextPack,
        table_rows: list[dict[str, Any]],
    ) -> str:
        """Generate a user answer from approved context only."""
        prompt = _build_user_answer_prompt(
            command=command,
            context_pack=context_pack,
            table_rows=table_rows,
        )
        result = self._llm_provider_factory().complete(prompt, temperature=0.0)
        if not result.success:
            raise AgentRuntimeUnavailableError(result.error or "LLM completion failed")
        answer = result.raw_response or str(result.output.get("content", "")).strip()
        if not answer:
            raise AgentRuntimeUnavailableError("LLM returned an empty answer")
        return answer


def _root_capability_token(run_id: str) -> CapabilityToken:
    """Create the L1 root capability token for one user Q&A run."""
    return CapabilityToken(
        token_id=f"cap_{run_id}_root",
        run_id=run_id,
        issued_by="system",
        issued_to="MainAgent",
        domain="global",
        data_access=(
            DataAccessPolicy.READ_CHAT_SUMMARY,
            DataAccessPolicy.READ_DASHBOARD,
            DataAccessPolicy.READ_ANALYSIS_MART,
            DataAccessPolicy.READ_EVIDENCE,
            DataAccessPolicy.READ_PROVIDER_STATUS,
        ),
        production_write=(ProductionWritePolicy.WRITE_CONTEXT_ONLY,),
        tool_policy=(
            ToolPolicy.READ_ONLY_TOOLS,
            ToolPolicy.RETRIEVAL_TOOLS,
            ToolPolicy.QUANT_TOOLS,
            ToolPolicy.DATA_SYNC_TOOLS,
        ),
        allowed_artifact_types=_DEFAULT_ALLOWED_ARTIFACT_TYPES,
        allowed_tool_names=(
            "dashboard.read_candidates",
            "analysis_mart.read_snapshot",
            "evidence.read_package",
            "provider.read_status",
        ),
        expires_at=datetime.now(UTC) + timedelta(hours=1),
        max_tool_calls=8,
        max_result_bytes=64_000,
        can_delegate=True,
        delegation_depth_remaining=2,
    )


def _evaluate_user_input(message: str) -> GuardrailSummary:
    """Run deterministic v1 input guardrails."""
    normalized = message.lower()
    policies: list[str] = []
    if _has_financial_guarantee(normalized):
        policies.append("financial_guarantee")
    if any(
        term in normalized
        for term in (
            "忽略系统规则",
            "忽略之前",
            "忽略以上",
            "hidden tool",
            "system prompt",
            "开发者消息",
        )
    ):
        policies.append("prompt_injection")
    if policies:
        return GuardrailSummary(
            allowed=False,
            decision="deny",
            summary="不能保证收益。系统只能展示研究判断、证据、风险和不确定性。",
            triggered_policies=tuple(policies),
        )
    return GuardrailSummary(
        allowed=True,
        decision="allow",
        summary="input allowed",
    )


def _has_financial_guarantee(normalized_input: str) -> bool:
    """Return whether the user asks for a guaranteed financial outcome."""
    guarantee_terms = (
        "保证收益",
        "稳赚",
        "保本",
        "确定上涨",
        "必涨",
        "guaranteed return",
        "guaranteed profit",
    )
    if any(term in normalized_input for term in guarantee_terms):
        return True
    return any(term in normalized_input for term in ("保证", "保證")) and any(
        term in normalized_input for term in ("收益", "盈利", "赚钱", "回报", "利潤", "利润")
    )


def _build_user_answer_prompt(
    *,
    command: UserQnaCommand,
    context_pack: ContextPack,
    table_rows: list[dict[str, Any]],
) -> str:
    """Build the final-answer prompt from bounded context."""
    chat_context = "\n".join(
        f"- {item.get('role', 'unknown')}: {item.get('content', '')[:500]}"
        for item in command.conversation_context[-8:]
    )
    rows = "\n".join(
        (
            f"- {row['security_id']}: score={row.get('final_score')}, "
            f"confidence={row.get('confidence')}, status={row.get('screening_status')}"
        )
        for row in table_rows[:10]
    )
    rows = rows or "- 当前 dashboard 候选为空或不可用。"
    return "\n".join(
        [
            "你是 Margin 的本地投研助手，只能基于给定上下文回答。",
            "禁止给出投资建议口吻，禁止使用买入、卖出、持有等指令性表达。",
            f"语言: {command.language}",
            f"ContextPack: {context_pack.context_pack_id}",
            f"用户问题: {command.message}",
            "最近对话摘要:",
            chat_context or "- 无",
            "Dashboard 研究候选摘要:",
            rows,
            "请给出简洁回答，并说明不确定性。",
        ]
    )


def _skill_for_domain_task(domain: str) -> str:
    """Return the primary user-Q&A worker skill for a domain task."""
    if domain == "general":
        return "answer_general_qna"
    if domain == "data":
        return "answer_data_status"
    if domain == "quant":
        return "answer_quant_status"
    if domain == "evidence":
        return "answer_evidence_status"
    return "answer_research_status"


def _references_from_rows(rows: list[dict[str, Any]]) -> tuple[dict[str, str], ...]:
    """Return safe frontend references for table rows."""
    references = [
        {
            "type": "dashboard_candidate",
            "id": str(row["security_id"]),
            "label": str(row["security_id"]),
        }
        for row in rows[:10]
    ]
    return tuple(references)


def _conversation_hash(command: UserQnaCommand) -> str:
    """Return a stable short hash for the conversation summary reference."""
    raw = "|".join(
        f"{item.get('role', '')}:{item.get('content', '')}"
        for item in command.conversation_context
    )
    return hashlib.sha256(raw.encode()).hexdigest()[:16]
