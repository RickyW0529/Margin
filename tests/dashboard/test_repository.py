"""Tests for module 08 dashboard repositories."""

from __future__ import annotations

from datetime import UTC, datetime

from margin.dashboard.db_models import (
    DashboardFeedbackRow,
    DashboardItemRow,
    DashboardRunRow,
)
from margin.dashboard.models import FeedbackRecord, FeedbackType, ResearchItem, ResearchRun
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
        counter_arguments=["估值修复低于预期"],
    )


def test_memory_repository_round_trips_run_items_and_feedback():
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
