"""Build data_readiness artifacts for Agent runtime planning."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from margin.agent_runtime.context_store import ContextArtifact, make_context_artifact
from margin.agents.context.readiness import (
    DataReadinessArtifactPayload,
    ReadinessStatus,
    SourceReadiness,
)
from margin.agents.runtime.capability_registry import CapabilityRegistry, CapabilityStatus
from margin.agents.security.capability import CapabilityToken
from margin.dashboard.models import DashboardFilters, DashboardSort
from margin.dashboard.service import DashboardServiceBundle


class DataReadinessBuilder:
    """Build a compact data readiness artifact for user Q&A runs."""

    def __init__(
        self,
        *,
        dashboard_services: DashboardServiceBundle | None,
        warehouse_repository: Any | None,
        quant_repository: Any | None = None,
        evidence_repository: Any | None = None,
        capability_registry: CapabilityRegistry | None = None,
        capability_token: CapabilityToken | None = None,
    ) -> None:
        self._dashboard_services = dashboard_services
        self._warehouse_repository = warehouse_repository
        self._quant_repository = quant_repository
        self._evidence_repository = evidence_repository
        self._capability_registry = capability_registry
        self._capability_token = capability_token

    def build_for_user_qna(self, command: Any) -> ContextArtifact:
        """Build one data_readiness artifact for the current user command."""
        generated_at = datetime.now(UTC)
        sources = (
            self._dashboard_readiness(command),
            self._warehouse_readiness(),
            self._provider_status_readiness(),
            self._quant_readiness(),
            self._evidence_readiness(),
        )
        payload = DataReadinessArtifactPayload(
            run_id=command.run_id,
            user_goal=command.message,
            scope_version_id=command.scope_version_id,
            generated_at=generated_at,
            sources=sources,
            missing_for_goal=_missing_for_goal(command.message, sources),
            recommended_actions=_recommended_actions(sources),
        )
        return make_context_artifact(
            artifact_id=f"ctx_{command.run_id}_data_readiness",
            run_id=command.run_id,
            artifact_type="data_readiness",
            producer_agent="ContextReadinessBuilder",
            payload_json=payload.model_dump(mode="json"),
            source_refs=("agent:v1:data_readiness",),
        )

    def _dashboard_readiness(self, command: Any) -> SourceReadiness:
        if self._dashboard_services is None:
            return SourceReadiness(
                source_name="dashboard_candidates",
                status=ReadinessStatus.NOT_CONFIGURED,
                safe_summary="Dashboard services are not configured.",
            )
        try:
            page = self._dashboard_services.query.list_research_candidates_v2(
                scope_version_id=command.scope_version_id,
                universe_code=command.universe,
                filters=DashboardFilters(),
                sort=DashboardSort(field="final_score", direction="desc"),
                cursor=None,
                limit=10,
            )
        except PermissionError as exc:
            return SourceReadiness(
                source_name="dashboard_candidates",
                status=ReadinessStatus.PERMISSION_DENIED,
                error_code=type(exc).__name__,
                retryable=False,
                safe_summary="Dashboard candidate source is not permitted.",
            )
        except Exception as exc:
            return SourceReadiness(
                source_name="dashboard_candidates",
                status=ReadinessStatus.ERROR,
                error_code=type(exc).__name__,
                retryable=True,
                safe_summary="Dashboard candidate source failed to load.",
            )
        row_count = len(page.items)
        status = ReadinessStatus.READY if row_count else ReadinessStatus.EMPTY
        return SourceReadiness(
            source_name="dashboard_candidates",
            status=status,
            as_of=page.as_of,
            row_count=row_count,
            coverage_summary={
                "scope_version_id": page.scope_version_id,
                "facets": page.facets,
            },
            safe_summary=(
                f"Dashboard candidate source has {row_count} rows."
                if row_count
                else "Dashboard candidate source is empty for current scope."
            ),
        )

    def _warehouse_readiness(self) -> SourceReadiness:
        if self._warehouse_repository is None:
            return SourceReadiness(
                source_name="warehouse",
                status=ReadinessStatus.NOT_CONFIGURED,
                safe_summary="Warehouse repository is not configured.",
            )
        return SourceReadiness(
            source_name="warehouse",
            status=ReadinessStatus.READY,
            safe_summary="Warehouse repository is configured for read-only data questions.",
        )

    def _provider_status_readiness(self) -> SourceReadiness:
        if self._dashboard_services is None:
            return SourceReadiness(
                source_name="provider_status",
                status=ReadinessStatus.NOT_CONFIGURED,
                safe_summary="Provider status service is not configured.",
            )
        try:
            statuses = self._dashboard_services.providers.list_status()
        except Exception as exc:
            return SourceReadiness(
                source_name="provider_status",
                status=ReadinessStatus.ERROR,
                error_code=type(exc).__name__,
                retryable=True,
                safe_summary="Provider status failed to load.",
            )
        unhealthy = tuple(item for item in statuses if item.status not in {"healthy", "ready"})
        return SourceReadiness(
            source_name="provider_status",
            status=ReadinessStatus.READY if not unhealthy else ReadinessStatus.UNAVAILABLE,
            row_count=len(statuses),
            coverage_summary={
                "providers": [
                    {
                        "provider": item.provider,
                        "status": item.status,
                        "message": item.message,
                    }
                    for item in statuses
                ]
            },
            safe_summary="Provider status is available.",
        )

    def _quant_readiness(self) -> SourceReadiness:
        capability = self._domain_capability("QuantExpertAgent")
        if capability is not None and capability.status is not CapabilityStatus.EXECUTABLE:
            return SourceReadiness(
                source_name="quant_result",
                status=ReadinessStatus.NOT_CONFIGURED,
                safe_summary="Quant capability is not executable: " + capability.reason,
            )
        if self._quant_repository is None:
            return SourceReadiness(
                source_name="quant_result",
                status=ReadinessStatus.NOT_CONFIGURED,
                safe_summary="Quant result repository/tool is not configured.",
            )
        return SourceReadiness(
            source_name="quant_result",
            status=ReadinessStatus.UNKNOWN,
            safe_summary="Quant repository is configured but latest result was not inspected.",
        )

    def _evidence_readiness(self) -> SourceReadiness:
        capability = self._domain_capability("EvidenceRagExpertAgent")
        if capability is not None and capability.status is not CapabilityStatus.EXECUTABLE:
            return SourceReadiness(
                source_name="evidence",
                status=ReadinessStatus.NOT_CONFIGURED,
                safe_summary="Evidence capability is not executable: " + capability.reason,
            )
        if self._evidence_repository is None:
            return SourceReadiness(
                source_name="evidence",
                status=ReadinessStatus.NOT_CONFIGURED,
                safe_summary="Evidence repository/tool is not configured.",
            )
        return SourceReadiness(
            source_name="evidence",
            status=ReadinessStatus.UNKNOWN,
            safe_summary="Evidence repository is configured but latest package was not inspected.",
        )

    def _domain_capability(self, domain_agent: str) -> Any | None:
        if self._capability_registry is None or self._capability_token is None:
            return None
        snapshot = self._capability_registry.snapshot(capability_token=self._capability_token)
        return next(
            (
                capability
                for capability in snapshot.domains
                if capability.domain_agent == domain_agent
            ),
            None,
        )


def _missing_for_goal(
    message: str,
    sources: tuple[SourceReadiness, ...],
) -> tuple[str, ...]:
    normalized = message.lower()
    source_by_name = {source.source_name: source for source in sources}
    missing: list[str] = []
    if "量化" in message or "quant" in normalized:
        quant = source_by_name.get("quant_result")
        if quant is not None and quant.status is not ReadinessStatus.READY:
            missing.append("quant_result")
    if "候选" in message or "dashboard" in normalized:
        dashboard = source_by_name.get("dashboard_candidates")
        if dashboard is not None and dashboard.status is not ReadinessStatus.READY:
            missing.append("dashboard_candidates")
    return tuple(missing)


def _recommended_actions(sources: tuple[SourceReadiness, ...]) -> tuple[str, ...]:
    actions: list[str] = []
    for source in sources:
        if source.status is ReadinessStatus.EMPTY:
            actions.append(f"{source.source_name}: run or publish upstream data first.")
        elif source.status in {
            ReadinessStatus.ERROR,
            ReadinessStatus.UNAVAILABLE,
            ReadinessStatus.NOT_CONFIGURED,
        }:
            actions.append(f"{source.source_name}: {source.safe_summary}")
    return tuple(actions)
