"""Layer-1 MainAgent runtime for v1 Agent protocol."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict

from margin.agents.cards.domain_cards import DomainAgentCard
from margin.agents.protocol.models import ContextPack, DomainTaskRequest
from margin.agents.security.capability import CapabilityToken, derive_capability_token


class GlobalPlan(BaseModel):
    """GlobalPlan.."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    run_id: str
    run_type: str
    user_intent: str
    domain_tasks: tuple[DomainTaskRequest, ...]
    final_answer_requirements: tuple[str, ...] = ()
    created_by: str = "MainAgent"


class MainRuntime:
    """MainRuntime.."""

    def __init__(
        self,
        *,
        domain_cards: tuple[DomainAgentCard, ...],
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
        selected_cards = self._select_domain_cards(user_goal)
        tasks: list[DomainTaskRequest] = []
        for card in selected_cards:
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
            )
            self.issued_tokens[child_token.token_id] = child_token
            tasks.append(
                DomainTaskRequest(
                    run_id=run_id,
                    domain_task_id=f"dt_{card.domain}",
                    to_domain_agent=card.name,
                    domain=card.domain,
                    user_intent_summary=user_goal,
                    task_goal=user_goal,
                    required_output_types=card.required_output_types,
                    input_context_pack_ref=context_pack.context_pack_id,
                    capability_token_ref=child_token.token_id,
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
            final_answer_requirements=("use_approved_capsules_only",),
        )

    def _select_domain_cards(self, user_goal: str) -> tuple[DomainAgentCard, ...]:
        """Select domain cards.

        Args:
            user_goal: str: .

        Returns:
            tuple[DomainAgentCard, ...]: .
        """
        normalized = user_goal.lower()
        if any(keyword in normalized for keyword in ("数据", "fresh", "新鲜")):
            return tuple(card for card in self._domain_cards if card.domain == "data")
        if any(keyword in normalized for keyword in ("量化", "quant", "backtest")):
            return tuple(card for card in self._domain_cards if card.domain == "quant")
        if any(keyword in normalized for keyword in ("证据", "rag", "公告", "研报")):
            return tuple(card for card in self._domain_cards if card.domain == "evidence")
        return tuple(card for card in self._domain_cards if card.domain == "general")
