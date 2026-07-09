"""Capability registry for planner-visible Agent runtime abilities."""

from __future__ import annotations

from collections.abc import Mapping
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from margin.agents.cards.domain_cards import DomainAgentCard
from margin.agents.cards.worker_cards import WorkerAgentCard, WorkerSkill
from margin.agents.runtime.executor_registry import ExecutorRegistry, ExecutorSpec
from margin.agents.security.capability import CapabilityToken
from margin.agents.tools.authz import capability_allows_tool
from margin.agents.tools.catalog import ToolCatalog
from margin.agents.tools.specs import ToolSpec


class CapabilityStatus(StrEnum):
    """Executable status for planner-visible capabilities."""

    EXECUTABLE = "executable"
    PLANNED_ONLY = "planned_only"
    MISSING_EXECUTOR = "missing_executor"
    MISSING_TOOL = "missing_tool"
    TOKEN_DENIED = "token_denied"
    DEPENDENCY_UNAVAILABLE = "dependency_unavailable"
    DISABLED = "disabled"


class ToolCapabilityView(BaseModel):
    """Planner-safe view of one tool capability."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    tool_name: str
    status: CapabilityStatus
    input_schema: dict[str, Any] = Field(default_factory=dict)
    output_schema: dict[str, Any] = Field(default_factory=dict)
    reason: str = ""


class WorkerCapabilityView(BaseModel):
    """Planner-safe view of one WorkerAgent skill capability."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    worker_agent: str
    domain: str
    skill_id: str
    status: CapabilityStatus
    output_artifact_types: tuple[str, ...]
    tool_allowlist: tuple[str, ...]
    runtime: str
    reason: str = ""


class DomainCapabilityView(BaseModel):
    """Planner-safe view of one Domain ExpertAgent capability."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    domain_agent: str
    domain: str
    status: CapabilityStatus
    executable_worker_skills: tuple[WorkerCapabilityView, ...]
    required_output_types: tuple[str, ...]
    missing_output_types: tuple[str, ...] = ()
    reason: str = ""


class CapabilitySnapshot(BaseModel):
    """Current runtime capability snapshot."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    domains: tuple[DomainCapabilityView, ...]
    workers: tuple[WorkerCapabilityView, ...]
    tools: tuple[ToolCapabilityView, ...]


class CapabilityContractReport(BaseModel):
    """Startup contract validation result."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    valid: bool
    errors: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()


class CapabilityRegistry:
    """Single source of truth for executable Agent runtime capabilities."""

    def __init__(
        self,
        *,
        domain_cards: tuple[DomainAgentCard, ...],
        worker_cards: tuple[WorkerAgentCard, ...],
        executor_registry: ExecutorRegistry,
        tool_catalog: ToolCatalog,
        feature_flags: Mapping[str, bool] | None = None,
    ) -> None:
        self._domain_cards = domain_cards
        self._worker_cards = worker_cards
        self._executor_registry = executor_registry
        self._tool_catalog = tool_catalog
        self._feature_flags = dict(feature_flags or {})

    def visible_domain_cards(
        self,
        *,
        capability_token: CapabilityToken,
        require_executable_worker: bool = True,
    ) -> tuple[DomainAgentCard, ...]:
        """Return DomainAgent cards that are currently executable."""
        visible: list[DomainAgentCard] = []
        for card in self._domain_cards:
            view = self._domain_view(card, capability_token)
            if view.status is CapabilityStatus.DISABLED:
                continue
            if require_executable_worker and view.status is not CapabilityStatus.EXECUTABLE:
                continue
            visible.append(card)
        return tuple(visible)

    def visible_worker_cards(
        self,
        *,
        domain: str,
        capability_token: CapabilityToken,
        required_output_types: tuple[str, ...] = (),
    ) -> tuple[WorkerAgentCard, ...]:
        """Return WorkerAgent cards with only executable skills for a domain."""
        visible: list[WorkerAgentCard] = []
        for card in self._worker_cards:
            if card.domain != domain or not self._enabled(card.name, card.domain):
                continue
            skills = tuple(
                skill
                for skill in card.skills
                if self._worker_skill_status(
                    card,
                    skill,
                    capability_token,
                    required_output_types=required_output_types,
                )[0]
                is CapabilityStatus.EXECUTABLE
            )
            if skills:
                visible.append(card.model_copy(update={"skills": skills}))
        return tuple(visible)

    def snapshot(self, *, capability_token: CapabilityToken) -> CapabilitySnapshot:
        """Return a full capability snapshot with hidden capability reasons."""
        workers: list[WorkerCapabilityView] = []
        for card in self._worker_cards:
            for skill in card.skills:
                workers.append(self._worker_view(card, skill, capability_token))
        return CapabilitySnapshot(
            domains=tuple(
                self._domain_view(card, capability_token) for card in self._domain_cards
            ),
            workers=tuple(workers),
            tools=tuple(
                self._tool_view(spec.tool_name, capability_token)
                for spec in self._tool_catalog.list_specs()
            ),
        )

    def validate_startup_contracts(self) -> CapabilityContractReport:
        """Validate static card/executor/tool contracts."""
        errors: list[str] = []
        warnings: list[str] = []
        workers_by_name = {card.name: card for card in self._worker_cards}
        for card in self._worker_cards:
            if not self._enabled(card.name, card.domain):
                continue
            for skill in card.skills:
                if skill.planned_only:
                    continue
                if not skill.output_artifact_types:
                    errors.append(f"{card.name}.{skill.skill_id} has no output_artifact_types")
                if not self._executor_registry.has(card.name, skill.skill_id):
                    errors.append(
                        self._executor_registry.explain_missing(card, skill)
                    )
                missing_tools = [
                    tool_name
                    for tool_name in skill.tool_allowlist
                    if not self._tool_catalog.has(tool_name)
                ]
                for tool_name in missing_tools:
                    errors.append(f"{card.name}.{skill.skill_id} missing tool {tool_name}")
        for domain_card in self._domain_cards:
            if not self._enabled(domain_card.name, domain_card.domain):
                continue
            candidate_cards = tuple(
                workers_by_name[name]
                for name in domain_card.worker_agent_names
                if name in workers_by_name
            )
            if not candidate_cards:
                warnings.append(f"{domain_card.name} has no registered worker cards")
                continue
            produced = {
                output
                for worker_card in candidate_cards
                for skill in worker_card.skills
                if not skill.planned_only
                for output in skill.output_artifact_types
            }
            missing_outputs = tuple(
                output for output in domain_card.required_output_types if output not in produced
            )
            if missing_outputs:
                errors.append(
                    f"{domain_card.name} missing producible outputs: "
                    + ", ".join(missing_outputs)
                )
        return CapabilityContractReport(
            valid=not errors,
            errors=tuple(dict.fromkeys(errors)),
            warnings=tuple(dict.fromkeys(warnings)),
        )

    def _domain_view(
        self,
        card: DomainAgentCard,
        capability_token: CapabilityToken,
    ) -> DomainCapabilityView:
        if not self._enabled(card.name, card.domain):
            return DomainCapabilityView(
                domain_agent=card.name,
                domain=card.domain,
                status=CapabilityStatus.DISABLED,
                executable_worker_skills=(),
                required_output_types=card.required_output_types,
                missing_output_types=card.required_output_types,
                reason="disabled by feature flag",
            )
        worker_names = set(card.worker_agent_names)
        worker_views = tuple(
            self._worker_view(worker_card, skill, capability_token)
            for worker_card in self._worker_cards
            if worker_card.name in worker_names and worker_card.domain == card.domain
            for skill in worker_card.skills
        )
        executable_workers = tuple(
            view for view in worker_views if view.status is CapabilityStatus.EXECUTABLE
        )
        produced_outputs = {
            output
            for view in executable_workers
            for output in view.output_artifact_types
        }
        missing_outputs = tuple(
            output for output in card.required_output_types if output not in produced_outputs
        )
        if not executable_workers:
            return DomainCapabilityView(
                domain_agent=card.name,
                domain=card.domain,
                status=_domain_hidden_status(worker_views),
                executable_worker_skills=(),
                required_output_types=card.required_output_types,
                missing_output_types=missing_outputs or card.required_output_types,
                reason=_domain_hidden_reason(card, worker_views),
            )
        if missing_outputs:
            return DomainCapabilityView(
                domain_agent=card.name,
                domain=card.domain,
                status=CapabilityStatus.DEPENDENCY_UNAVAILABLE,
                executable_worker_skills=executable_workers,
                required_output_types=card.required_output_types,
                missing_output_types=missing_outputs,
                reason="required outputs are not covered by executable workers",
            )
        return DomainCapabilityView(
            domain_agent=card.name,
            domain=card.domain,
            status=CapabilityStatus.EXECUTABLE,
            executable_worker_skills=executable_workers,
            required_output_types=card.required_output_types,
        )

    def _worker_view(
        self,
        card: WorkerAgentCard,
        skill: WorkerSkill,
        capability_token: CapabilityToken,
    ) -> WorkerCapabilityView:
        status, reason, spec = self._worker_skill_status(card, skill, capability_token)
        runtime = spec.runtime if spec is not None else card.supported_runtimes[0]
        return WorkerCapabilityView(
            worker_agent=card.name,
            domain=card.domain,
            skill_id=skill.skill_id,
            status=status,
            output_artifact_types=skill.output_artifact_types,
            tool_allowlist=skill.tool_allowlist,
            runtime=runtime,
            reason=reason,
        )

    def _worker_skill_status(
        self,
        card: WorkerAgentCard,
        skill: WorkerSkill,
        capability_token: CapabilityToken,
        *,
        required_output_types: tuple[str, ...] = (),
    ) -> tuple[CapabilityStatus, str, ExecutorSpec | None]:
        if not self._enabled(card.name, card.domain):
            return CapabilityStatus.DISABLED, "disabled by feature flag", None
        if skill.planned_only:
            return CapabilityStatus.PLANNED_ONLY, "skill is planned_only", None
        spec = self._executor_registry.get_spec(card.name, skill.skill_id)
        if spec is None:
            return (
                CapabilityStatus.MISSING_EXECUTOR,
                self._executor_registry.explain_missing(card, skill),
                None,
            )
        if spec.runtime not in card.supported_runtimes:
            return (
                CapabilityStatus.DEPENDENCY_UNAVAILABLE,
                f"executor runtime {spec.runtime} is not supported by {card.name}",
                spec,
            )
        if not skill.output_artifact_types:
            return (
                CapabilityStatus.DEPENDENCY_UNAVAILABLE,
                "skill declares no output_artifact_types",
                spec,
            )
        missing_outputs = tuple(
            output
            for output in required_output_types
            if output not in skill.output_artifact_types
        )
        if missing_outputs:
            return (
                CapabilityStatus.DEPENDENCY_UNAVAILABLE,
                "skill cannot produce required outputs: " + ", ".join(missing_outputs),
                spec,
            )
        missing_tools = tuple(
            tool_name
            for tool_name in skill.tool_allowlist
            if not self._tool_catalog.has(tool_name)
        )
        if missing_tools:
            return (
                CapabilityStatus.MISSING_TOOL,
                "missing tools: " + ", ".join(missing_tools),
                spec,
            )
        denied_tools = tuple(
            tool_name
            for tool_name in skill.tool_allowlist
            if self._tool_view(tool_name, capability_token).status
            is not CapabilityStatus.EXECUTABLE
        )
        if denied_tools:
            return (
                CapabilityStatus.TOKEN_DENIED,
                "capability token denies tools: " + ", ".join(denied_tools),
                spec,
            )
        return CapabilityStatus.EXECUTABLE, "", spec

    def _tool_view(
        self,
        tool_name: str,
        capability_token: CapabilityToken,
    ) -> ToolCapabilityView:
        specs = self._tool_catalog.specs_for_name(tool_name)
        if not specs:
            return ToolCapabilityView(
                tool_name=tool_name,
                status=CapabilityStatus.MISSING_TOOL,
                reason=self._tool_catalog.explain_missing(tool_name),
            )
        allowed_spec = next(
            (spec for spec in specs if capability_allows_tool(capability_token, spec)),
            None,
        )
        spec = allowed_spec or specs[0]
        status = (
            CapabilityStatus.EXECUTABLE
            if allowed_spec is not None
            else CapabilityStatus.TOKEN_DENIED
        )
        reason = "" if allowed_spec is not None else "capability token does not allow tool"
        return _tool_capability_view(spec, status=status, reason=reason)

    def _enabled(self, name: str, domain: str) -> bool:
        if self._feature_flags.get(name) is False:
            return False
        if self._feature_flags.get(domain) is False:
            return False
        return True


def _tool_capability_view(
    spec: ToolSpec,
    *,
    status: CapabilityStatus,
    reason: str = "",
) -> ToolCapabilityView:
    return ToolCapabilityView(
        tool_name=spec.tool_name,
        status=status,
        input_schema={"schema_ref": spec.input_schema_ref},
        output_schema={"schema_ref": spec.output_schema_ref},
        reason=reason,
    )


def _domain_hidden_status(
    worker_views: tuple[WorkerCapabilityView, ...],
) -> CapabilityStatus:
    if not worker_views:
        return CapabilityStatus.MISSING_EXECUTOR
    for status in (
        CapabilityStatus.MISSING_EXECUTOR,
        CapabilityStatus.MISSING_TOOL,
        CapabilityStatus.TOKEN_DENIED,
        CapabilityStatus.PLANNED_ONLY,
        CapabilityStatus.DISABLED,
    ):
        if any(view.status is status for view in worker_views):
            return status
    return CapabilityStatus.DEPENDENCY_UNAVAILABLE


def _domain_hidden_reason(
    card: DomainAgentCard,
    worker_views: tuple[WorkerCapabilityView, ...],
) -> str:
    if not worker_views:
        return f"no worker cards registered for {card.name}"
    reasons = tuple(view.reason for view in worker_views if view.reason)
    if not reasons:
        return "no executable worker skills"
    return "; ".join(dict.fromkeys(reasons))
