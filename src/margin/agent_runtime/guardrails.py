"""Rule-based foundation guardrails for agent runtime."""

from __future__ import annotations

import hashlib
from enum import StrEnum

from margin.agent_runtime.models import (
    AgentFlowDefinition,
    AgentPermissionMode,
    AgentRunType,
    GuardrailDecision,
    GuardrailStage,
)

POLICY_VERSION = "agent-guardrails-v0.4.0"


class GuardrailDecisionType(StrEnum):
    """Guardrail decision values.."""

    ALLOW = "allow"
    DENY = "deny"
    NARROW = "narrow"
    REQUIRE_CONFIRMATION = "require_confirmation"
    REPAIR = "repair"


class InputGuardrail:
    """Fast rule-based input guardrail.."""

    _guarantee_terms = (
        "保证收益",
        "稳赚",
        "保本",
        "确定上涨",
        "必涨",
        "guaranteed return",
        "guaranteed profit",
    )
    _guarantee_verbs = ("保证", "保證")
    _return_terms = ("收益", "盈利", "赚钱", "回报", "利潤", "利润")
    _injection_terms = (
        "忽略系统规则",
        "忽略之前",
        "忽略以上",
        "直接调用",
        "hidden tool",
        "system prompt",
        "开发者消息",
    )

    def evaluate(self, user_input: str, *, run_id: str = "") -> GuardrailDecision:
        """Evaluate raw user input.

        Args:
            user_input: str: .
            run_id: str: .

        Returns:
            GuardrailDecision: .
        """
        normalized = user_input.lower()
        policies: list[str] = []
        if self._has_financial_guarantee(normalized):
            policies.append("financial_guarantee")
        if any(term.lower() in normalized for term in self._injection_terms):
            policies.append("prompt_injection")
        decision = GuardrailDecisionType.DENY if policies else GuardrailDecisionType.ALLOW
        message = (
            "不能保证收益。系统只能展示研究判断、证据、风险和不确定性。"
            if "financial_guarantee" in policies
            else ""
        )
        return GuardrailDecision(
            decision_id=f"gd_input_{_hash_text(f'{run_id}|{user_input}')[7:23]}",
            guardrail_id="input_guardrail",
            run_id=run_id,
            stage=GuardrailStage.INPUT,
            policy_version=POLICY_VERSION,
            decision=decision.value,
            allowed=decision == GuardrailDecisionType.ALLOW,
            evaluation_summary="input denied" if policies else "input allowed",
            triggered_policies=tuple(policies),
            input_hash=_hash_text(user_input),
            safe_summary="input denied" if policies else "input allowed",
            user_message=message,
        )

    def _has_financial_guarantee(self, normalized_input: str) -> bool:
        """Return whether input asks for guaranteed investment outcomes.

        Args:
            normalized_input: str: .

        Returns:
            bool: .
        """
        if any(term.lower() in normalized_input for term in self._guarantee_terms):
            return True
        return any(term in normalized_input for term in self._guarantee_verbs) and any(
            term in normalized_input for term in self._return_terms
        )


class PlanGuardrail:
    """Validate MainAgent plans.."""

    def validate_fixed_flow(
        self,
        *,
        run_type: AgentRunType,
        permission_mode: AgentPermissionMode,
        planned_step_ids: tuple[str, ...],
        fixed_flow: AgentFlowDefinition,
        run_id: str = "",
    ) -> GuardrailDecision:
        """Validate that a scheduled plan exactly matches the fixed JSON flow.

        Args:
            run_type: AgentRunType: .
            permission_mode: AgentPermissionMode: .
            planned_step_ids: tuple[str, ...]: .
            fixed_flow: AgentFlowDefinition: .
            run_id: str: .

        Returns:
            GuardrailDecision: .
        """
        expected = tuple(step.step_id for step in fixed_flow.steps)
        policies: list[str] = []
        if run_type != fixed_flow.run_type:
            policies.append("run_type_mismatch")
        if permission_mode != fixed_flow.permission_mode:
            policies.append("permission_mode_mismatch")
        if planned_step_ids != expected:
            policies.append("fixed_flow_mismatch")
        decision = GuardrailDecisionType.DENY if policies else GuardrailDecisionType.ALLOW
        serialized_plan = "|".join(planned_step_ids)
        return GuardrailDecision(
            decision_id=f"gd_plan_{_hash_text(f'{run_id}|{serialized_plan}')[7:23]}",
            guardrail_id="plan_guardrail",
            run_id=run_id,
            stage=GuardrailStage.PLAN,
            policy_version=POLICY_VERSION,
            decision=decision.value,
            allowed=decision == GuardrailDecisionType.ALLOW,
            evaluation_summary="plan denied" if policies else "plan allowed",
            triggered_policies=tuple(policies),
            input_hash=_hash_text(serialized_plan),
            safe_summary="plan denied" if policies else "plan allowed",
        )


def _hash_text(value: str) -> str:
    """Return a stable text hash.

    Args:
        value: str: .

    Returns:
        str: .
    """
    return f"sha256:{hashlib.sha256(value.encode()).hexdigest()}"
