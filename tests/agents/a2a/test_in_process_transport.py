"""Unit tests for the official A2A in-process transport."""

from __future__ import annotations

from typing import Any

import pytest
from a2a.types import (
    AgentCapabilities,
    AgentCard,
    AgentInterface,
    AgentSkill,
    TaskNotFoundError,
    TaskState,
    VersionNotSupportedError,
)

from margin.agents.a2a import (
    AgentCall,
    AgentExecutionError,
    AgentResult,
    DuplicateTaskError,
    InProcessA2ATransport,
    SyncA2AClient,
    UnknownAgentError,
    make_data_artifact,
    make_data_part,
    read_data_part,
)


def _card(name: str, *, protocol_version: str = "1.0") -> AgentCard:
    return AgentCard(
        name=name,
        description=f"{name} test agent",
        supported_interfaces=[
            AgentInterface(
                url=f"inprocess://{name}",
                protocol_binding="INPROCESS",
                protocol_version=protocol_version,
            )
        ],
        version="1.0.0",
        capabilities=AgentCapabilities(),
        default_input_modes=["application/json"],
        default_output_modes=["application/json"],
        skills=[
            AgentSkill(
                id="execute",
                name="Execute",
                description="Execute one delegated plan step",
                tags=["test"],
            )
        ],
    )


def _artifact(name: str, payload: Any):
    return make_data_artifact(name=name, payload=payload)


def test_main_to_expert_to_worker_round_trip() -> None:
    transport = InProcessA2ATransport()
    calls: list[tuple[str, str, dict[str, Any]]] = []

    def worker_handler(call: AgentCall) -> AgentResult:
        payload = call.payloads[0]
        calls.append((call.source_agent, call.target_agent, payload))
        return AgentResult(
            artifacts=(
                _artifact(
                    "worker-result",
                    {
                        "worker": "ResearchWorker",
                        "completed_step": payload["plan_step"],
                        "facts": ["fact-a", "fact-b"],
                    },
                ),
            ),
            metadata={"executed_by": "ResearchWorker"},
        )

    expert_client = SyncA2AClient(transport, source_agent="ResearchExpert")

    def expert_handler(call: AgentCall) -> AgentResult:
        payload = call.payloads[0]
        calls.append((call.source_agent, call.target_agent, payload))
        worker_task = expert_client.send_data(
            "ResearchWorker",
            {
                "plan_step": "collect-evidence",
                "user_goal": payload["user_goal"],
            },
            task_id="expert-worker-task",
            context_id=call.message.context_id,
        )
        worker_output = read_data_part(worker_task.artifacts[0].parts[0])
        return AgentResult(
            artifacts=(
                _artifact(
                    "expert-review",
                    {
                        "reviewed_task": worker_task.id,
                        "accepted": worker_output["facts"] == ["fact-a", "fact-b"],
                    },
                ),
            ),
            metadata={"reviewed_worker_task": worker_task.id},
        )

    transport.register(_card("ResearchExpert"), expert_handler)
    transport.register(_card("ResearchWorker"), worker_handler)

    main_client = SyncA2AClient(transport, source_agent="MainAgent")
    expert_task = main_client.send_data(
        "ResearchExpert",
        {"user_goal": "analyze current evidence", "constraints": {"max_steps": 2}},
        task_id="main-expert-task",
        context_id="run-context",
    )

    assert expert_task.status.state == TaskState.TASK_STATE_COMPLETED
    assert expert_task.context_id == "run-context"
    assert len(expert_task.artifacts) == 1
    assert read_data_part(expert_task.artifacts[0].parts[0]) == {
        "reviewed_task": "expert-worker-task",
        "accepted": True,
    }
    assert expert_task.metadata["reviewed_worker_task"] == "expert-worker-task"

    worker_task = transport.get_task("expert-worker-task")
    assert worker_task.status.state == TaskState.TASK_STATE_COMPLETED
    assert worker_task.context_id == expert_task.context_id
    assert read_data_part(worker_task.artifacts[0].parts[0])["completed_step"] == (
        "collect-evidence"
    )
    assert calls == [
        (
            "MainAgent",
            "ResearchExpert",
            {"user_goal": "analyze current evidence", "constraints": {"max_steps": 2}},
        ),
        (
            "ResearchExpert",
            "ResearchWorker",
            {
                "plan_step": "collect-evidence",
                "user_goal": "analyze current evidence",
            },
        ),
    ]

    assert [
        status.state for status in transport.get_task_status_history("main-expert-task")
    ] == [
        TaskState.TASK_STATE_SUBMITTED,
        TaskState.TASK_STATE_WORKING,
        TaskState.TASK_STATE_COMPLETED,
    ]
    assert [
        status.state for status in transport.get_task_status_history("expert-worker-task")
    ] == [
        TaskState.TASK_STATE_SUBMITTED,
        TaskState.TASK_STATE_WORKING,
        TaskState.TASK_STATE_COMPLETED,
    ]


def test_discovery_returns_isolated_official_cards() -> None:
    transport = InProcessA2ATransport()
    transport.register(_card("WorkerB"), lambda call: AgentResult())
    transport.register(_card("WorkerA"), lambda call: AgentResult())
    client = SyncA2AClient(transport, source_agent="MainAgent")

    assert [card.name for card in client.list_agents()] == ["WorkerA", "WorkerB"]
    discovered = client.discover_agent("WorkerA")
    discovered.name = "mutated"
    assert client.discover_agent("WorkerA").name == "WorkerA"


def test_data_part_round_trips_nested_json() -> None:
    payload = {
        "plan": [{"step": "inspect", "required": True}],
        "counts": {"integer": 2, "decimal": 2.5},
        "notes": None,
    }
    part = make_data_part(payload)

    assert part.HasField("data")
    assert part.media_type == "application/json"
    assert read_data_part(part) == payload


def test_unknown_agent_duplicate_task_and_version_errors() -> None:
    transport = InProcessA2ATransport()
    call_count = 0

    def handler(call: AgentCall) -> AgentResult:
        nonlocal call_count
        call_count += 1
        return AgentResult(artifacts=(_artifact("result", {"ok": True}),))

    transport.register(_card("Worker"), handler)
    client = SyncA2AClient(transport, source_agent="Expert")

    with pytest.raises(UnknownAgentError):
        client.send_data("MissingWorker", {"step": "work"}, task_id="unknown-task")
    with pytest.raises(TaskNotFoundError):
        transport.get_task("unknown-task")

    completed = client.send_data("Worker", {"step": "work"}, task_id="same-task")
    assert completed.status.state == TaskState.TASK_STATE_COMPLETED
    with pytest.raises(DuplicateTaskError):
        client.send_data("Worker", {"step": "work-again"}, task_id="same-task")
    assert call_count == 1

    incompatible_client = SyncA2AClient(
        transport,
        source_agent="Expert",
        protocol_version="0.3",
    )
    with pytest.raises(VersionNotSupportedError):
        incompatible_client.send_data("Worker", {"step": "work"}, task_id="old-version")
    with pytest.raises(TaskNotFoundError):
        transport.get_task("old-version")


def test_handler_failure_is_recorded_as_failed_task() -> None:
    transport = InProcessA2ATransport()

    def failing_handler(call: AgentCall) -> AgentResult:
        raise RuntimeError("tool execution failed")

    transport.register(_card("FailingWorker"), failing_handler)
    client = SyncA2AClient(transport, source_agent="Expert")

    with pytest.raises(AgentExecutionError) as exc_info:
        client.send_data("FailingWorker", {"step": "run-tool"}, task_id="failed-task")

    assert isinstance(exc_info.value.cause, RuntimeError)
    assert exc_info.value.task.status.state == TaskState.TASK_STATE_FAILED
    assert transport.get_task("failed-task").status.state == TaskState.TASK_STATE_FAILED
    assert [
        status.state for status in transport.get_task_status_history("failed-task")
    ] == [
        TaskState.TASK_STATE_SUBMITTED,
        TaskState.TASK_STATE_WORKING,
        TaskState.TASK_STATE_FAILED,
    ]
