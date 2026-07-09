"""Executor registry used to keep planner-visible cards executable."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

from margin.agent_runtime.models import AgentCard
from margin.agents.cards.worker_cards import WorkerAgentCard


@dataclass(frozen=True)
class ExecutorKey:
    """One executable agent/skill key.."""

    agent_name: str
    skill_id: str


class ExecutorRegistry:
    """Registry mapping WorkerAgent skills to executable implementations.."""

    def __init__(self) -> None:
        """Process __init__.

        Returns:
            None: .
        """
        self._executors: dict[ExecutorKey, object] = {}

    def register(self, *, agent_name: str, skill_id: str, executor: object) -> None:
        """Register one executable agent skill.

        Args:
            agent_name: str: .
            skill_id: str: .
            executor: object: .

        Returns:
            None: .
        """
        self._executors[ExecutorKey(agent_name, skill_id)] = executor

    def has(self, agent_name: str, skill_id: str) -> bool:
        """Return whether an executor exists.

        Args:
            agent_name: str: .
            skill_id: str: .

        Returns:
            bool: .
        """
        return ExecutorKey(agent_name, skill_id) in self._executors

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
            return self._executors[key]
        except KeyError as exc:
            raise KeyError(f"missing executor for {agent_name}.{skill_id}") from exc

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
