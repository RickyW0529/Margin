"""Tests for v1 Agent cards and executor registry visibility."""

from __future__ import annotations

import pytest

from margin.agent_runtime.cards import default_agent_card_registry
from margin.agents.cards.registry import v0_agent_cards_to_worker_cards
from margin.agents.runtime.executor_registry import (
    ExecutorRegistry,
    default_qna_executor_registry,
)


def test_planner_only_sees_worker_cards_with_registered_executors() -> None:
    worker_cards = v0_agent_cards_to_worker_cards(
        default_agent_card_registry().list_cards()
    )
    registry = default_qna_executor_registry()

    visible = registry.planner_visible_worker_cards(worker_cards)
    visible_names = {card.name for card in visible}

    assert visible_names == {"DataAnalystAgent", "GeneralQnaAgent"}
    assert "CodeSandboxAgent" not in visible_names


def test_code_sandbox_becomes_visible_only_after_executor_registration() -> None:
    worker_cards = v0_agent_cards_to_worker_cards(
        default_agent_card_registry().list_cards()
    )
    registry = default_qna_executor_registry()
    registry.register(
        agent_name="CodeSandboxAgent",
        skill_id="run_sandboxed_analysis_code",
        executor=object(),
    )

    visible = registry.planner_visible_worker_cards(worker_cards)

    assert {card.name for card in visible} >= {
        "DataAnalystAgent",
        "GeneralQnaAgent",
        "CodeSandboxAgent",
    }


def test_validate_visible_cards_rejects_unregistered_skill() -> None:
    worker_cards = v0_agent_cards_to_worker_cards(
        default_agent_card_registry().list_cards()
    )
    registry = ExecutorRegistry()

    with pytest.raises(ValueError, match="missing executor"):
        registry.validate_cards(worker_cards, require_all_visible=True)
