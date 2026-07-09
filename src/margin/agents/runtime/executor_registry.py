"""Executor registry used to keep planner-visible cards executable."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any, Literal

from margin.agent_runtime.models import AgentCard
from margin.agents.cards.worker_cards import WorkerAgentCard


@dataclass(frozen=True)
class ExecutorKey:
    """One executable agent/skill key.."""

    agent_name: str
    skill_id: str


@dataclass(frozen=True)
class ExecutorSpec:
    """Executable WorkerAgent skill metadata."""

    agent_name: str
    skill_id: str
    executor: object
    runtime: Literal["deterministic", "langgraph", "python"] = "python"
    required_tools: tuple[str, ...] = ()
    output_artifact_types: tuple[str, ...] = ()
    domain: str | None = None
    enabled: bool = True


class ExecutorRegistry:
    """Registry mapping WorkerAgent skills to executable implementations.."""

    def __init__(self) -> None:
        """Process __init__.

        Returns:
            None: .
        """
        self._specs: dict[ExecutorKey, ExecutorSpec] = {}

    def register(self, *, agent_name: str, skill_id: str, executor: object) -> None:
        """Register one executable agent skill.

        Args:
            agent_name: str: .
            skill_id: str: .
            executor: object: .

        Returns:
            None: .
        """
        self.register_spec(
            ExecutorSpec(agent_name=agent_name, skill_id=skill_id, executor=executor)
        )

    def register_spec(self, spec: ExecutorSpec) -> None:
        """Register one executable agent skill with runtime metadata."""
        self._specs[ExecutorKey(spec.agent_name, spec.skill_id)] = spec

    def has(self, agent_name: str, skill_id: str) -> bool:
        """Return whether an executor exists.

        Args:
            agent_name: str: .
            skill_id: str: .

        Returns:
            bool: .
        """
        spec = self._specs.get(ExecutorKey(agent_name, skill_id))
        return spec is not None and spec.enabled

    def get(self, agent_name: str, skill_id: str) -> object:
        """Return an executor or raise a clear error.

        Args:
            agent_name: str: .
            skill_id: str: .

        Returns:
            object: .
        """
        key = ExecutorKey(agent_name, skill_id)
        try:
            spec = self._specs[key]
        except KeyError as exc:
            raise KeyError(f"missing executor for {agent_name}.{skill_id}") from exc
        if not spec.enabled:
            raise KeyError(f"disabled executor for {agent_name}.{skill_id}")
        return spec.executor

    def get_spec(self, agent_name: str, skill_id: str) -> ExecutorSpec | None:
        """Return executor metadata if registered."""
        spec = self._specs.get(ExecutorKey(agent_name, skill_id))
        if spec is None or not spec.enabled:
            return None
        return spec

    def list_specs(self, *, domain: str | None = None) -> tuple[ExecutorSpec, ...]:
        """Return registered executor metadata."""
        specs = tuple(spec for spec in self._specs.values() if spec.enabled)
        if domain is None:
            return specs
        return tuple(spec for spec in specs if spec.domain == domain)

    def explain_missing(self, card: WorkerAgentCard, skill: object) -> str:
        """Return a stable missing-executor explanation for one worker skill."""
        skill_id = getattr(skill, "skill_id", "")
        key = ExecutorKey(card.name, skill_id)
        spec = self._specs.get(key)
        if spec is not None and not spec.enabled:
            return f"executor disabled for {card.name}.{skill_id}"
        return f"missing executor for {card.name}.{skill_id}"

    def planner_visible_worker_cards(
        self,
        cards: Iterable[WorkerAgentCard],
    ) -> tuple[WorkerAgentCard, ...]:
        """Return cards with only executable, non-planned skills.

        Args:
            cards: Iterable[WorkerAgentCard]: .

        Returns:
            tuple[WorkerAgentCard, ...]: .
        """
        visible: list[WorkerAgentCard] = []
        for card in cards:
            skills = tuple(
                skill
                for skill in card.skills
                if not skill.planned_only and self.has(card.name, skill.skill_id)
            )
            if skills:
                visible.append(card.model_copy(update={"skills": skills}))
        return tuple(visible)

    def planner_visible_agent_cards(
        self,
        cards: Iterable[AgentCard],
    ) -> tuple[AgentCard, ...]:
        """Return legacy AgentCards with only executable Q&A skills.

        Args:
            cards: Iterable[AgentCard]: .

        Returns:
            tuple[AgentCard, ...]: .
        """
        visible: list[AgentCard] = []
        for card in cards:
            skills = tuple(
                skill
                for skill in card.skills
                if skill.qa_allowed and self.has(card.name, skill.skill_id)
            )
            if skills:
                visible.append(card.model_copy(update={"skills": skills}))
        return tuple(visible)

    def validate_cards(
        self,
        cards: Iterable[WorkerAgentCard],
        *,
        require_all_visible: bool = False,
    ) -> None:
        """Validate that visible worker skills have executors.

        Args:
            cards: Iterable[WorkerAgentCard]: .
            require_all_visible: bool: .

        Returns:
            None: .
        """
        missing: list[str] = []
        for card in cards:
            for skill in card.skills:
                if skill.planned_only:
                    continue
                if require_all_visible or self.has(card.name, skill.skill_id):
                    if not self.has(card.name, skill.skill_id):
                        missing.append(f"{card.name}.{skill.skill_id}")
        if missing:
            raise ValueError("missing executor: " + ", ".join(sorted(missing)))


def default_qna_executor_registry() -> ExecutorRegistry:
    """Return the executable Q&A worker registry for current v0 adapters.

    Returns:
        ExecutorRegistry: .
    """
    registry = ExecutorRegistry()
    registry.register(
        agent_name="GeneralQnaAgent",
        skill_id="answer_general_qna",
        executor=_RegisteredOnlyExecutor(),
    )
    registry.register(
        agent_name="DataAnalystAgent",
        skill_id="answer_with_analysis_artifacts",
        executor=_RegisteredOnlyExecutor(),
    )
    return registry


class _RegisteredOnlyExecutor:
    """Marker executor used when the legacy route owns actual execution.."""

    def __call__(self, *args: Any, **kwargs: Any) -> None:
        """Process __call__.

        Args:
            *args: Any: .
            **kwargs: Any: .

        Returns:
            None: .
        """
        raise NotImplementedError("legacy adapter executes this skill directly")
