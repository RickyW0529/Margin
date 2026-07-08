"""Bootstrap defaults for domain-specific runtime configuration."""

from __future__ import annotations

from datetime import UTC, datetime

from margin.agent_runtime.quant_agent import CURRENT_QUANT_AGENT_ML_PROFILE
from margin.agent_runtime.step_definitions import load_scheduled_stock_analysis_flow
from margin.config_runtime.models import (
    AgentFlowConfigVersion,
    QuantAgentProfileConfigVersion,
)
from margin.config_runtime.repository import ConfigAdminService, ConfigResolver

DEFAULT_AGENT_FLOW_VERSION_ID = "agent-flow-scheduled-stock-analysis-v0.5.0"
DEFAULT_QUANT_AGENT_PROFILE_VERSION_ID = "quant-agent-profile-scheduled-v0.4.1"
SCHEDULED_QUANT_PROFILE_KEY = "scheduled_stock_analysis"
DEFAULT_VALID_FROM = datetime(2020, 1, 1, tzinfo=UTC)


class RuntimeConfigBootstrapService:
    """Seed runtime config domain tables without overwriting active user versions."""

    def __init__(
        self,
        *,
        admin_service: ConfigAdminService,
        resolver: ConfigResolver,
    ) -> None:
        """Initialize the bootstrap service."""
        self._admin = admin_service
        self._resolver = resolver

    def ensure_defaults(self) -> tuple[str, str]:
        """Ensure active defaults for Agent flow and QuantAgent profile."""
        flow_version_id = self._ensure_agent_flow()
        profile_version_id = self._ensure_quant_profile()
        return flow_version_id, profile_version_id

    def _ensure_agent_flow(self) -> str:
        try:
            resolved = self._resolver.resolve_agent_flow(
                flow_id="scheduled_stock_analysis",
                decision_at=datetime.now(UTC),
            )
            return resolved.version_id
        except LookupError:
            version = self._admin.publish_agent_flow(
                AgentFlowConfigVersion.from_flow(
                    version_id=DEFAULT_AGENT_FLOW_VERSION_ID,
                    flow=load_scheduled_stock_analysis_flow(),
                    valid_from=DEFAULT_VALID_FROM,
                    available_at=DEFAULT_VALID_FROM,
                    created_by="bootstrap",
                    change_reason="default scheduled stock analysis flow",
                    idempotency_key="bootstrap-agent-flow-v0.5.0",
                )
            )
            return version.version_id

    def _ensure_quant_profile(self) -> str:
        try:
            resolved = self._resolver.resolve_quant_agent_profile(
                profile_key=SCHEDULED_QUANT_PROFILE_KEY,
                decision_at=datetime.now(UTC),
            )
            return resolved.version_id
        except LookupError:
            version = self._admin.publish_quant_agent_profile(
                QuantAgentProfileConfigVersion.from_profile(
                    version_id=DEFAULT_QUANT_AGENT_PROFILE_VERSION_ID,
                    profile_key=SCHEDULED_QUANT_PROFILE_KEY,
                    profile=CURRENT_QUANT_AGENT_ML_PROFILE,
                    valid_from=DEFAULT_VALID_FROM,
                    available_at=DEFAULT_VALID_FROM,
                    created_by="bootstrap",
                    change_reason="default scheduled QuantAgent ML profile",
                    idempotency_key="bootstrap-quant-agent-profile-v0.4.1",
                )
            )
            return version.version_id
