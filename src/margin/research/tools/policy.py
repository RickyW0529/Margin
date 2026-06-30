"""Fail-closed authorization policy for v0.2 graph tools."""

from __future__ import annotations

from datetime import UTC, datetime

from pydantic import BaseModel

from margin.news.models import ensure_utc
from margin.research.tools.definitions import ToolCapability

GRAPH_ALLOWED_CAPABILITIES = frozenset(
    {
        ToolCapability.CONTEXT_READ,
        ToolCapability.QUANT_READ,
        ToolCapability.FINANCIAL_READ,
        ToolCapability.NEWS_READ,
        ToolCapability.FILING_READ,
        ToolCapability.EVIDENCE_RETRIEVE,
        ToolCapability.DETERMINISTIC_VALUATION,
        ToolCapability.RESTRICTED_CALCULATION,
        ToolCapability.CITATION_VALIDATION,
    }
)


class ToolPolicyDecision(BaseModel):
    """Deterministic authorization result."""

    allowed: bool
    reason_code: str
    policy_version: str

    model_config = {"frozen": True}


class ToolPolicyEngine:
    """Authorize scoped calls without relying on LLM judgment."""

    def __init__(self, policy_version: str = "tool-policy-v0.2.0") -> None:
        """Initialize the policy engine.

        Args:
            policy_version: Version string included in every policy decision.
        """
        self.policy_version = policy_version

    def authorize(
        self,
        *,
        node_name: str,
        capability: ToolCapability,
        security_id: str,
        decision_at: datetime,
        node_grants: set[ToolCapability] | frozenset[ToolCapability],
        requested_security_id: str | None = None,
        requested_decision_at: datetime | str | None = None,
        call_count: int = 0,
        max_calls: int = 8,
        estimated_result_bytes: int = 0,
        max_result_bytes: int = 65_536,
        deadline: datetime | None = None,
    ) -> ToolPolicyDecision:
        """Return a fail-closed decision for one requested tool capability.

        Args:
            node_name: Name of the calling node (unused).
            capability: Capability requested by the tool call.
            security_id: Security scoped to this session.
            decision_at: Point-in-time decision timestamp.
            node_grants: Capabilities granted to the calling node.
            requested_security_id: Security ID in the tool arguments, if any.
            requested_decision_at: Decision time in the tool arguments, if any.
            call_count: Current number of calls made by this session.
            max_calls: Maximum allowed calls for this session.
            estimated_result_bytes: Estimated result size for the tool.
            max_result_bytes: Maximum allowed result size for this session.
            deadline: Optional deadline for tool calls.

        Returns:
            A ``ToolPolicyDecision`` that is allowed only if all checks pass.
        """
        del node_name
        if capability not in node_grants:
            return self._deny("capability_not_granted")
        if capability not in GRAPH_ALLOWED_CAPABILITIES:
            return self._deny("capability_forbidden")
        if requested_security_id is not None and requested_security_id != security_id:
            return self._deny("security_scope_violation")
        if requested_decision_at is not None:
            try:
                requested = _parse_datetime(requested_decision_at)
            except (TypeError, ValueError):
                return self._deny("invalid_decision_at")
            if requested > ensure_utc(decision_at):
                return self._deny("pit_violation")
        if call_count >= max_calls:
            return self._deny("call_budget_exceeded")
        if estimated_result_bytes > max_result_bytes:
            return self._deny("estimated_result_too_large")
        if deadline is not None and datetime.now(UTC) >= ensure_utc(deadline):
            return self._deny("deadline_exceeded")
        return ToolPolicyDecision(
            allowed=True,
            reason_code="allowed",
            policy_version=self.policy_version,
        )

    def is_exposable(
        self,
        capability: ToolCapability,
        grants: set[ToolCapability] | frozenset[ToolCapability],
    ) -> bool:
        """Return whether a capability may appear in a node manifest.

        Args:
            capability: Capability to check.
            grants: Capabilities granted to the node.

        Returns:
            True if the capability is both granted and allowed by the graph policy.
        """
        return capability in grants and capability in GRAPH_ALLOWED_CAPABILITIES

    def _deny(self, reason_code: str) -> ToolPolicyDecision:
        """Return a denied policy decision with the given reason code."""
        return ToolPolicyDecision(
            allowed=False,
            reason_code=reason_code,
            policy_version=self.policy_version,
        )


def _parse_datetime(value: datetime | str) -> datetime:
    """Parse a datetime or ISO string into a UTC-aware datetime."""
    if isinstance(value, datetime):
        return ensure_utc(value)
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(UTC)
