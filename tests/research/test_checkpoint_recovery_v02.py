"""v0.2 checkpoint recovery tests for the AI delta review graph.

This module verifies that the PostgreSQL-backed LangGraph checkpointer
correctly round-trips checkpoints, validates identity hashes, and that the
graph can resume from an interrupted checkpoint without replaying already
completed LLM analysis branches.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest
from langgraph.checkpoint.base import empty_checkpoint
from pydantic import BaseModel
from sqlalchemy import delete

import margin.news.db_models  # noqa: F401 - register FK target tables in Base metadata
from margin.research.checkpoint import PostgresGraphCheckpointer
from margin.research.db_models import (
    AIGraphCheckpointRow,
    AIGraphRunRow,
    ResearchDeltaOutboxRow,
    ResearchDeltaReviewRow,
)
from margin.research.graph.builder import (
    GraphDependencies,
    build_ai_delta_review_graph,
)
from margin.research.graph.nodes.analysis import AnalysisRequest
from margin.research.graph.state import (
    ReviewMode,
    ReviewOutcome,
    create_initial_state,
)
from margin.research.tools.definitions import (
    ToolCapability,
    ToolDefinition,
    ToolDefinitionRegistry,
)
from margin.research.tools.executor import MemoryToolCallAuditRepository
from margin.research.tools.factory import ScopedToolFactory, ScopedToolSession
from margin.research.tools.policy import ToolPolicyEngine
from margin.storage.base import Base
from margin.storage.database import (
    DatabaseSettings,
    create_database_engine,
    create_session_factory,
)

DECISION_AT = datetime(2026, 6, 23, tzinfo=UTC)


class RetrievalInput(BaseModel):
    """Input model for the evidence retrieval tool used in recovery tests.

    Attributes:
        security_id: The security identifier to retrieve evidence for.
        decision_at: The point-in-time decision timestamp.
        questions: Tuple of research questions to answer.
        evidence_gaps: Tuple of known evidence gaps to fill.
        supplemental: Whether this is a supplemental retrieval request.
    """

    security_id: str
    decision_at: datetime
    questions: tuple[str, ...]
    evidence_gaps: tuple[str, ...] = ()
    supplemental: bool = False


def test_postgres_checkpointer_round_trips_checkpoint_and_rejects_identity_mismatch(
    database_url: str,
) -> None:
    """Verify the Postgres checkpointer round-trips checkpoints and validates identity.

    Seeds a graph run, writes a checkpoint with pending writes, loads it back,
    and asserts that channel values, metadata, and pending writes are preserved.
    Also verifies that a mismatched ``identity_hash`` raises a ``ValueError``.

    Args:
        database_url: Fixture providing the PostgreSQL integration-test URL.
    """
    session_factory = _session_factory(database_url)
    graph_run_id = "graph-checkpoint-roundtrip"
    _cleanup_graph_rows(session_factory, graph_run_id)
    state = _state(graph_run_id=graph_run_id)
    _seed_graph_run(session_factory, state)
    checkpointer = PostgresGraphCheckpointer(session_factory)
    checkpoint = empty_checkpoint()
    checkpoint["id"] = "cp-1"
    checkpoint["channel_values"] = {
        "security_id": state.security_id,
        "llm_call_count": 1,
    }
    checkpoint["channel_versions"] = {
        "security_id": 1,
        "llm_call_count": 1,
    }
    config = _config(state)

    saved_config = checkpointer.put(
        config,
        checkpoint,
        {"source": "unit-test"},
        {"security_id": 1, "llm_call_count": 1},
    )
    checkpointer.put_writes(
        saved_config,
        [("llm_call_ids", ("llm-1",))],
        task_id="task-valuation",
        task_path="valuation_analysis",
    )

    loaded = checkpointer.get_tuple(saved_config)
    assert loaded is not None
    assert loaded.checkpoint["id"] == "cp-1"
    assert loaded.checkpoint["channel_values"]["llm_call_count"] == 1
    assert loaded.metadata["source"] == "unit-test"
    assert loaded.pending_writes == [
        ("task-valuation", "llm_call_ids", ["llm-1"])
    ]

    with pytest.raises(ValueError, match="identity_hash mismatch"):
        checkpointer.get_tuple(
            {
                "configurable": {
                    **saved_config["configurable"],
                    "identity_hash": "sha256:wrong",
                }
            }
        )

    _cleanup_graph_rows(session_factory, graph_run_id)


def test_graph_resumes_from_checkpoint_without_repeating_completed_llm_branches(
    database_url: str,
) -> None:
    """Verify the graph resumes after an interrupted decision without replaying work.

    Runs the graph with an interrupt after the analysis join, then resumes it
    and asserts that the four analysis branches are not re-executed while the
    decision node runs exactly once, producing the expected outcome.

    Args:
        database_url: Fixture providing the PostgreSQL integration-test URL.
    """
    session_factory = _session_factory(database_url)
    graph_run_id = "graph-checkpoint-resume"
    _cleanup_graph_rows(session_factory, graph_run_id)
    state = _state(graph_run_id=graph_run_id).with_updates(
        review_mode=ReviewMode.FULL_REVIEW,
        change_set={"material_news": True},
    )
    _seed_graph_run(session_factory, state)
    fixture = _RecoverableGraphFixture()
    checkpointer = PostgresGraphCheckpointer(session_factory)
    interrupted_graph = build_ai_delta_review_graph(
        fixture.dependencies(
            checkpointer=checkpointer,
            interrupt_after=("analysis_join",),
        )
    )
    resumed_graph = build_ai_delta_review_graph(
        fixture.dependencies(checkpointer=checkpointer)
    )

    interrupted_graph.invoke(state, config=_config(state))

    assert fixture.analysis_call_count == 4
    result = resumed_graph.invoke(None, config=_config(state))

    assert result["current_review_outcome"] == ReviewOutcome.UPDATE_ASSESSMENT
    assert fixture.analysis_call_count == 4
    assert fixture.decision_call_count == 1
    assert result["llm_call_count"] == 5

    _cleanup_graph_rows(session_factory, graph_run_id)


class _RecoverableGraphFixture:
    """Graph fixture whose decision node crashes once after analysis branches.

    This fixture provides deterministic analysis and decision handlers along
    with a scoped tool factory, enabling checkpoint recovery tests to verify
    that completed LLM branches are not replayed after an interruption.

    Attributes:
        audit: In-memory tool call audit repository recording tool invocations.
        analysis_call_count: Number of times analysis handlers have been called.
    """

    def __init__(self) -> None:
        """Initialize the fixture with empty audit and call counters."""
        self.audit = MemoryToolCallAuditRepository()
        self.analysis_call_count = 0
        self._decision_calls = 0

    @property
    def decision_call_count(self) -> int:
        """int: Number of times the decision handler has been called."""
        return self._decision_calls

    def dependencies(
        self,
        *,
        checkpointer: Any,
        interrupt_after: tuple[str, ...] | None = None,
    ) -> GraphDependencies:
        """Build graph dependencies with scoped tools and deterministic handlers.

        Args:
            checkpointer: The LangGraph checkpointer to attach to the graph.
            interrupt_after: Optional tuple of node names after which to
                interrupt execution.

        Returns:
            A ``GraphDependencies`` instance wired with the fixture's handlers.
        """
        registry = ToolDefinitionRegistry()
        registry.register(
            ToolDefinition(
                name="evidence_retrieve",
                capability=ToolCapability.EVIDENCE_RETRIEVE,
                version="evidence-retrieve-v0.2.0",
                description="Retrieve frozen evidence.",
                input_model=RetrievalInput,
                handler=lambda payload: {
                    "package_id": "pkg-recovery",
                    "summary": {
                        "security_id": payload["security_id"],
                        "evidence_ids": ["ev-1"],
                        "quality_status": "usable",
                    },
                },
            )
        )
        factory = ScopedToolFactory(
            tool_registry=registry,
            policy=ToolPolicyEngine(),
            audit_repository=self.audit,
        )
        return GraphDependencies(
            tool_factory=factory,
            analysis_handlers={
                node_name: self._analysis_handler(node_name)
                for node_name in (
                    "fundamental_analysis",
                    "valuation_analysis",
                    "risk_review",
                    "counter_argument",
                    "targeted_reanalysis",
                )
            },
            decision_handler=self._decision,
            checkpointer=checkpointer,
            interrupt_after=interrupt_after,
        )

    def _analysis_handler(
        self,
        node_name: str,
    ):
        """Create a deterministic analysis handler for the given node name."""
        def handler(
            request: AnalysisRequest,
            session: ScopedToolSession,
) -> dict[str, Any]:
            self.analysis_call_count += 1
            return {
                "node_name": node_name,
                "security_id": request.security_id,
                "completed": True,
                "llm_call_ids": [f"llm-{node_name}"],
            }

        return handler

    def _decision(self, state) -> dict[str, Any]:
        """Return a deterministic decision result and increment the call counter."""
        self._decision_calls += 1
        return {
            "outcome": ReviewOutcome.UPDATE_ASSESSMENT.value,
            "confidence": 0.78,
            "evidence_ids": list(state.node_outputs["evidence_packages"].keys()),
            "changed_assumptions": [{"name": "margin", "status": "updated"}],
            "llm_call_ids": ["llm-decision"],
        }


def _session_factory(database_url: str):
    """Create a session factory with all tables initialized on the test database."""
    engine = create_database_engine(DatabaseSettings(url=database_url))
    Base.metadata.create_all(engine)
    return create_session_factory(engine)


def _state(*, graph_run_id: str):
    """Build an initial graph state for the given run ID."""
    return create_initial_state(
        graph_run_id=graph_run_id,
        context_snapshot_id=f"ctx-{graph_run_id}",
        context_input_hash=f"sha256:ctx-{graph_run_id}",
        scope_version_id="scope-1",
        security_id="000001.SZ",
        decision_at=DECISION_AT,
    )


def _config(state) -> dict[str, dict[str, str]]:
    """Build a LangGraph config dict from the given state's identity fields."""
    return {
        "configurable": {
            "thread_id": state.graph_run_id,
            "checkpoint_ns": "",
            "identity_hash": state.identity_hash,
        }
    }


def _seed_graph_run(session_factory, state) -> None:
    """Insert an initial ``AIGraphRunRow`` row for the given state."""
    now = datetime.now(UTC)
    with session_factory.begin() as session:
        session.add(
            AIGraphRunRow(
                graph_run_id=state.graph_run_id,
                graph_version=state.graph_version,
                context_snapshot_id=state.context_snapshot_id,
                context_input_hash=state.context_input_hash,
                identity_hash=state.identity_hash,
                state_hash="sha256:initial",
                scope_version_id=state.scope_version_id,
                security_id=state.security_id,
                decision_at=state.decision_at,
                status="running",
                review_mode=state.review_mode.value if state.review_mode else None,
                created_at=now,
                updated_at=now,
                started_at=now,
            )
        )


def _cleanup_graph_rows(session_factory, graph_run_id: str) -> None:
    """Delete all graph-related rows for the given run ID."""
    with session_factory.begin() as session:
        for row in (
            ResearchDeltaOutboxRow,
            ResearchDeltaReviewRow,
            AIGraphCheckpointRow,
            AIGraphRunRow,
        ):
            session.execute(delete(row).where(row.graph_run_id == graph_run_id))
