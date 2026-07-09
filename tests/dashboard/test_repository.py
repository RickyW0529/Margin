"""Tests for module 08 dashboard repositories.

Verifies that both the in-memory and SQLAlchemy dashboard repositories round-trip
runs, items, and feedback records.
"""

from __future__ import annotations

from datetime import UTC, datetime

from margin.agent_runtime.context_store import MemoryAgentContextStore
from margin.agents.workers.dashboard_publisher_worker import DashboardPublisherWorker
from margin.dashboard.db_models import (
    DashboardFeedbackRow,
    DashboardItemRow,
    DashboardRunRow,
)
from margin.dashboard.models import (
    DashboardFilters,
    DashboardSort,
    FeedbackRecord,
    FeedbackType,
    ResearchItem,
    ResearchRun,
)
from margin.dashboard.repository import (
    MemoryDashboardRepository,
    SQLAlchemyDashboardRepository,
)
from margin.storage.base import Base
from margin.storage.database import (
    DatabaseSettings,
    create_database_engine,
    create_session_factory,
)


def _run(run_id: str = "dr_repo") -> ResearchRun:
    """Build a deterministic research run fixture.

    Args:
        run_id: str: .

    Returns:
        ResearchRun: .
    """
    return ResearchRun(
        run_id=run_id,
        decision_at=datetime(2026, 6, 19, tzinfo=UTC),
        strategy_id="st_repo",
        version_id="sv_repo",
        universe=["000001.SZ"],
        item_count=1,
        published_count=1,
    )


def _item(run_id: str = "dr_repo") -> ResearchItem:
    """Build a deterministic research item fixture.

    Args:
        run_id: str: .

    Returns:
        ResearchItem: .
    """
    return ResearchItem(
        item_id="di_repo",
        run_id=run_id,
        symbol="000001.SZ",
        signal_type="research_candidate",
        confidence=0.82,
        statement="经营现金流改善",
        workflow_run_id="run_06",
        snapshot_id="snap_06",
        evidence_ids=["ev_1"],
        claim_ids=["cl_1"],
        target_weight=0.32,
        adjusted_weight=0.24,
        agent_adjustment={
            "action": "reduce_weight",
            "reason": "evidence risk",
        },
        counter_arguments=["估值修复低于预期"],
    )


def test_memory_repository_round_trips_run_items_and_feedback():
    """Test that the memory repository round-trips runs, items, and feedback.

    Returns:
        Any: .
    """
    repo = MemoryDashboardRepository()
    run = _run()
    item = _item(run.run_id)
    feedback = FeedbackRecord(
        item_id=item.item_id,
        feedback_type=FeedbackType.WATCH,
        comment="继续观察",
    )

    repo.add_run(run)
    repo.add_items([item])
    repo.add_feedback(feedback)

    assert repo.get_run(run.run_id) == run
    assert repo.list_runs(strategy_id="st_repo") == [run]
    assert repo.get_item(item.item_id) == item
    assert repo.list_items(run.run_id) == [item]
    assert repo.list_feedback(item.item_id) == [feedback]


def test_sqlalchemy_repository_round_trips_run_items_and_feedback(database_url):
    """Test that the SQLAlchemy repository round-trips runs, items, and feedback.

    Args:
        database_url: Any: .

    Returns:
        Any: .
    """
    engine = create_database_engine(DatabaseSettings(url=database_url))
    Base.metadata.create_all(engine)
    session_factory = create_session_factory(engine)
    with session_factory.begin() as session:
        for row in (DashboardFeedbackRow, DashboardItemRow, DashboardRunRow):
            session.query(row).delete()

    repo = SQLAlchemyDashboardRepository(session_factory)
    run = _run("dr_pg")
    item = _item(run.run_id).model_copy(update={"item_id": "di_pg"})
    feedback = FeedbackRecord(
        item_id=item.item_id,
        feedback_type=FeedbackType.REJECT,
        comment="证据不足",
    )

    try:
        repo.add_run(run)
        repo.add_items([item])
        repo.add_feedback(feedback)

        fresh = SQLAlchemyDashboardRepository(session_factory)

        assert fresh.get_run(run.run_id) == run
        assert fresh.list_items(run.run_id) == [item]
        assert fresh.list_feedback(item.item_id) == [feedback]
    finally:
        Base.metadata.drop_all(engine)
        engine.dispose()


def test_sqlalchemy_candidate_list_prefers_complete_run_for_same_decision_time(database_url):
    """Candidate queries choose the newer complete projection when PIT times tie.

    Args:
        database_url: Any: .

    Returns:
        Any: .
    """
    engine = create_database_engine(DatabaseSettings(url=database_url))
    Base.metadata.create_all(engine)
    session_factory = create_session_factory(engine)
    with session_factory.begin() as session:
        for row in (DashboardFeedbackRow, DashboardItemRow, DashboardRunRow):
            session.query(row).delete()

    repo = SQLAlchemyDashboardRepository(session_factory)
    old_run = _run("dr_old").model_copy(
        update={
            "version_id": "scope-current",
            "item_count": 1,
            "created_at": datetime(2026, 6, 22, tzinfo=UTC),
        }
    )
    new_run = _run("dr_new").model_copy(
        update={
            "version_id": "scope-current",
            "universe": ["002416.SZ", "600740.SH"],
            "item_count": 2,
            "published_count": 2,
            "created_at": datetime(2026, 6, 22, tzinfo=UTC),
        }
    )
    old_item = _item(old_run.run_id).model_copy(update={"item_id": "di_old", "symbol": "000001.SZ"})
    new_items = [
        _item(new_run.run_id).model_copy(update={"item_id": "di_new_1", "symbol": "002416.SZ"}),
        _item(new_run.run_id).model_copy(update={"item_id": "di_new_2", "symbol": "600740.SH"}),
    ]

    try:
        repo.add_run(old_run)
        repo.add_items([old_item])
        repo.add_run(new_run)
        repo.add_items(new_items)

        response = repo.list_research_candidates_v2(
            scope_version_id="scope-current",
            universe_code="ALL_A",
            filters=DashboardFilters(),
            sort=DashboardSort(field="final_score", direction="desc"),
            cursor=None,
            limit=20,
        )

        assert {item.security_id for item in response.items} == {
            "002416.SZ",
            "600740.SH",
        }
    finally:
        Base.metadata.drop_all(engine)
        engine.dispose()


def test_sqlalchemy_candidate_list_prefers_stock_analyst_adjusted_projection(
    database_url,
) -> None:
    """Adjusted StockAnalyst projections are the dashboard-visible latest run.

    Args:
        database_url: Any: .

    Returns:
        None: .
    """
    engine = create_database_engine(DatabaseSettings(url=database_url))
    Base.metadata.create_all(engine)
    session_factory = create_session_factory(engine)
    with session_factory.begin() as session:
        for row in (DashboardFeedbackRow, DashboardItemRow, DashboardRunRow):
            session.query(row).delete()

    repo = SQLAlchemyDashboardRepository(session_factory)
    source_run = _run("dr_quant").model_copy(
        update={
            "version_id": "scope-current",
            "strategy_id": "quant:ml_lifecycle",
            "universe": ["000001.SZ", "000002.SZ", "000003.SZ"],
            "item_count": 3,
            "published_count": 3,
            "created_at": datetime(2026, 6, 22, tzinfo=UTC),
        }
    )
    source_items = [
        _item(source_run.run_id).model_copy(
            update={
                "item_id": "di_quant_1",
                "symbol": "000001.SZ",
                "target_weight": 0.5,
                "adjusted_weight": 0.5,
            }
        ),
        _item(source_run.run_id).model_copy(
            update={
                "item_id": "di_quant_2",
                "symbol": "000002.SZ",
                "target_weight": 0.5,
                "adjusted_weight": 0.5,
            }
        ),
        _item(source_run.run_id).model_copy(
            update={
                "item_id": "di_quant_3",
                "symbol": "000003.SZ",
                "target_weight": 0.2,
                "adjusted_weight": 0.2,
                "rejection_reasons": ["short_term_overheat"],
            }
        ),
    ]
    context_store = MemoryAgentContextStore()
    analyst = DashboardPublisherWorker(
        write_context_artifact=context_store.add_artifact,
        dashboard_repository=repo,
    )

    try:
        repo.add_run(source_run)
        repo.add_items(source_items)

        result = analyst.adjust_quant_candidates(
            run_id="ar_sql_projection",
            candidates=(
                {
                    "item_id": "di_quant_1",
                    "security_id": "000001.SZ",
                    "screening_status": "pass",
                    "target_weight": 0.5,
                },
                {
                    "item_id": "di_quant_2",
                    "security_id": "000002.SZ",
                    "screening_status": "pass",
                    "target_weight": 0.5,
                },
                {
                    "item_id": "di_quant_3",
                    "security_id": "000003.SZ",
                    "screening_status": "pass",
                    "target_weight": 0.2,
                    "risk_flags": ("short_term_overheat",),
                },
            ),
            max_stock_exposure=0.8,
        )

        response = repo.list_research_candidates_v2(
            scope_version_id="scope-current",
            universe_code="ALL_A",
            filters=DashboardFilters(),
            sort=DashboardSort(field="symbol", direction="asc"),
            cursor=None,
            limit=20,
        )

        assert result.dashboard_run_id == "dr_agent_ar_sql_projection"
        assert result.removed_security_ids == ("000003.SZ",)
        assert [item.security_id for item in response.items] == [
            "000001.SZ",
            "000002.SZ",
        ]
        assert [item.adjusted_weight for item in response.items] == [0.4, 0.4]
        assert {item.agent_adjustment["source"] for item in response.items} == {
            "DashboardPublisherWorker"
        }
        artifact = context_store.get_artifact("ctx_ar_sql_projection_portfolio_adjustment")
        assert artifact is not None
        assert artifact.payload_json["removed_security_ids"] == ["000003.SZ"]
    finally:
        Base.metadata.drop_all(engine)
        engine.dispose()
