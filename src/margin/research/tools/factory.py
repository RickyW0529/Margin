"""Scoped tool-session factory for controlled graph nodes."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from margin.research.tools.definitions import (
    ToolCapability,
    ToolDefinitionRegistry,
)
from margin.research.tools.executor import (
    ScopedToolResult,
    ToolCallAuditRepository,
    ToolExecutor,
)
from margin.research.tools.manifests import ToolManifest, ToolManifestEntry
from margin.research.tools.policy import ToolPolicyEngine


class ScopedToolFactory:
    """Create least-privilege tool sessions for one graph node."""

    def __init__(
        self,
        *,
        tool_registry: ToolDefinitionRegistry,
        policy: ToolPolicyEngine,
        audit_repository: ToolCallAuditRepository | None = None,
    ) -> None:
        """Initialize the instance."""
        self._registry = tool_registry
        self._policy = policy
        self._audit = audit_repository

    def create_session(
        self,
        *,
        graph_run_id: str,
        node_name: str,
        security_id: str,
        decision_at: datetime,
        grants: set[ToolCapability],
        max_calls: int = 8,
        max_result_bytes: int = 65_536,
        deadline: datetime | None = None,
    ) -> ScopedToolSession:
        """Create one scoped session with immutable limits."""
        return ScopedToolSession(
            graph_run_id=graph_run_id,
            node_name=node_name,
            security_id=security_id,
            decision_at=decision_at,
            grants=frozenset(grants),
            max_calls=max_calls,
            max_result_bytes=max_result_bytes,
            deadline=deadline,
            registry=self._registry,
            policy=self._policy,
            executor=ToolExecutor(self._audit),
        )


class ScopedToolSession:
    """Node-scoped manifest and execution boundary."""

    def __init__(
        self,
        *,
        graph_run_id: str,
        node_name: str,
        security_id: str,
        decision_at: datetime,
        grants: frozenset[ToolCapability],
        max_calls: int,
        max_result_bytes: int,
        deadline: datetime | None,
        registry: ToolDefinitionRegistry,
        policy: ToolPolicyEngine,
        executor: ToolExecutor,
    ) -> None:
        """Initialize the instance."""
        self._graph_run_id = graph_run_id
        self._node_name = node_name
        self._security_id = security_id
        self._decision_at = decision_at
        self._grants = grants
        self._max_calls = max_calls
        self._max_result_bytes = max_result_bytes
        self._deadline = deadline
        self._registry = registry
        self._policy = policy
        self._executor = executor
        self._call_count = 0
        self._call_ids: list[str] = []

    def manifest(self) -> ToolManifest:
        """Return only allowed and node-granted tool definitions."""
        entries = tuple(
            ToolManifestEntry(
                name=definition.name,
                capability=definition.capability,
                version=definition.version,
                description=definition.description,
                input_schema=definition.input_schema,
            )
            for definition in self._registry.list_definitions()
            if self._policy.is_exposable(definition.capability, self._grants)
        )
        return ToolManifest(
            graph_run_id=self._graph_run_id,
            node_name=self._node_name,
            security_id=self._security_id,
            decision_at=self._decision_at.isoformat(),
            policy_version=self._policy.policy_version,
            tools=entries,
            max_calls=self._max_calls,
            max_result_bytes=self._max_result_bytes,
        )

    def call(self, tool_name: str, args: dict[str, Any]) -> ScopedToolResult:
        """Authorize and execute one tool call."""
        definition = self._registry.get(tool_name)
        if definition is None:
            result = self._executor.unknown(
                graph_run_id=self._graph_run_id,
                node_name=self._node_name,
                tool_name=tool_name,
                args=args,
                policy_version=self._policy.policy_version,
            )
            self._call_ids.append(result.call_id)
            return result
        decision = self._policy.authorize(
            node_name=self._node_name,
            capability=definition.capability,
            security_id=self._security_id,
            decision_at=self._decision_at,
            node_grants=self._grants,
            requested_security_id=_optional_string(args.get("security_id")),
            requested_decision_at=args.get("decision_at"),
            call_count=self._call_count,
            max_calls=self._max_calls,
            estimated_result_bytes=definition.estimated_result_bytes,
            max_result_bytes=self._max_result_bytes,
            deadline=self._deadline,
        )
        if not decision.allowed:
            result = self._executor.denied(
                graph_run_id=self._graph_run_id,
                node_name=self._node_name,
                definition=definition,
                args=args,
                decision=decision,
            )
            self._call_ids.append(result.call_id)
            return result
        self._call_count += 1
        result = self._executor.execute(
            graph_run_id=self._graph_run_id,
            node_name=self._node_name,
            definition=definition,
            args=args,
            decision=decision,
            max_result_bytes=self._max_result_bytes,
        )
        self._call_ids.append(result.call_id)
        return result

    @property
    def call_ids(self) -> tuple[str, ...]:
        """Return all allowed and denied call IDs made by this session."""
        return tuple(self._call_ids)


def _optional_string(value: Any) -> str | None:
    """optional string."""
    return str(value) if value is not None else None
