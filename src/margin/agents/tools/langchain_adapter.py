"""LangChain-facing adapter that only calls ToolGateway."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from margin.agents.security.capability import CapabilityToken
from margin.agents.tools.gateway import ToolGateway
from margin.agents.tools.specs import ToolCallRequest, ToolCallResult, ToolSpec


class LangChainRuntimeContext(BaseModel):
    """LangChainRuntimeContext.."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    run_id: str
    worker_task_id: str
    worker_agent: str
    capability_token: CapabilityToken
    context_pack_id: str | None = None
    idempotency_key: str
    deadline_ms: int = Field(ge=1)


class LangChainToolAdapter:
    """LangChainToolAdapter.."""

    def __init__(self, *, tool_spec: ToolSpec, gateway: ToolGateway) -> None:
        """Init .

        Args:
            tool_spec: ToolSpec: .
            gateway: ToolGateway: .

        Returns:
            None: .
        """
        self.tool_spec = tool_spec
        self.gateway = gateway

    def invoke(
        self,
        input_json: dict,
        runtime_context: LangChainRuntimeContext,
    ) -> ToolCallResult:
        """Invoke.

        Args:
            input_json: dict: .
            runtime_context: LangChainRuntimeContext: .

        Returns:
            ToolCallResult: .
        """
        return self.gateway.call(
            ToolCallRequest(
                tool_call_id=f"tc_{runtime_context.idempotency_key}",
                run_id=runtime_context.run_id,
                task_id=runtime_context.worker_task_id,
                caller_agent=runtime_context.worker_agent,
                tool_name=self.tool_spec.tool_name,
                tool_version=self.tool_spec.tool_version,
                input_json=input_json,
                capability_token=runtime_context.capability_token,
                context_pack_id=runtime_context.context_pack_id,
                idempotency_key=runtime_context.idempotency_key,
                deadline_ms=runtime_context.deadline_ms,
            )
        )
