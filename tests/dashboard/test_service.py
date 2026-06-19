"""Tests for module 08 dashboard services."""

from __future__ import annotations

import json
from datetime import UTC, datetime

from margin.dashboard.models import FeedbackType, ItemStatus, RunStatus
from margin.dashboard.repository import MemoryDashboardRepository
from margin.dashboard.service import (
    DashboardQueryService,
    DashboardResearchService,
    EvidenceViewService,
    ExportService,
    FeedbackService,
    JobService,
    ReportRenderer,
    ValuationViewService,
)
from margin.research.models import ResearchSignal, SignalType, WorkflowState
from margin.research.repository import MemoryResearchRepository
from margin.research.snapshot import ResearchSnapshotBuilder
from margin.research.workflow import WorkflowResult


class FakeResearchService:
    def __init__(self, research_repository: MemoryResearchRepository) -> None:
        self._repository = research_repository

    def run(self, symbol, decision_at=None, portfolio_id=None):
        signal = ResearchSignal(
            symbol=symbol,
            signal_type=SignalType.RESEARCH_CANDIDATE,
            confidence=0.84,
            statement="经营现金流改善，估值仍有安全边际",
            evidence_refs=("ev_cashflow",),
            claim_ids=("cl_cashflow",),
            risk_score=0.28,
            counter_arguments=("行业需求恢复不及预期",),
        )
        snapshot = (
            ResearchSnapshotBuilder()
            .for_run("run_fake_06")
            .with_state(WorkflowState.PUBLISHED)
            .with_decision_at(decision_at or datetime(2026, 6, 19, tzinfo=UTC))
            .with_symbols([symbol])
            .with_strategy_version("sv_demo")
            .with_prompt_version("prompt_v1")
            .with_evidence_ids(["ev_cashflow"])
            .with_claim_ids(["cl_cashflow"])
            .with_signals([signal])
            .with_prior_outputs(
                {
                    "valuation_tool": {"value": 12.0},
                    "risk_review": {"risk_score": 0.28, "risk_factors": ["需求波动"]},
                    "reflect_counter_argument": {
                        "counter_arguments": ["行业需求恢复不及预期"],
                        "unknowns": [],
                    },
                }
            )
            .build()
        )
        self._repository.add_snapshot(snapshot)
        return WorkflowResult(
            run_id=snapshot.run_id,
            state=WorkflowState.PUBLISHED,
            signals=[signal],
            snapshot=snapshot.model_dump(mode="json"),
            snapshot_persisted=True,
        )


def _services():
    dashboard_repository = MemoryDashboardRepository()
    research_repository = MemoryResearchRepository()
    research_service = FakeResearchService(research_repository)
    run_service = DashboardResearchService(
        research_service=research_service,
        repository=dashboard_repository,
    )
    query_service = DashboardQueryService(
        repository=dashboard_repository,
        research_repository=research_repository,
    )
    return dashboard_repository, research_repository, run_service, query_service


def test_dashboard_research_service_run_batch_creates_run_and_items():
    repo, _, service, _ = _services()

    run = service.run_batch(
        decision_at=datetime(2026, 6, 19, 9, 30, tzinfo=UTC),
        strategy_id="st_demo",
        version_id="sv_demo",
        symbols=["000001.SZ"],
    )

    items = repo.list_items(run.run_id)
    assert run.status == RunStatus.PUBLISHED
    assert run.item_count == 1
    assert items[0].symbol == "000001.SZ"
    assert items[0].status == ItemStatus.PUBLISHED
    assert items[0].snapshot_id is not None


def test_query_service_derives_candidate_cards_and_home_summary():
    _, _, run_service, query_service = _services()
    run = run_service.run_batch(
        decision_at=datetime(2026, 6, 19, tzinfo=UTC),
        strategy_id="st_demo",
        version_id="sv_demo",
        symbols=["000001.SZ"],
    )

    cards = query_service.get_candidate_cards(run.run_id)
    summary = query_service.get_home_summary()

    assert cards[0].symbol == "000001.SZ"
    assert cards[0].value_trap_score == 0.28
    assert cards[0].counter_arguments == ["行业需求恢复不及预期"]
    assert "不构成买卖指令" in cards[0].disclaimer
    assert summary.today_candidates[0].item_id == cards[0].item_id
    assert summary.run_stats["item_count"] == 1


def test_evidence_and_valuation_views_use_snapshot_context():
    repo, research_repo, run_service, _ = _services()
    run = run_service.run_batch(
        decision_at=datetime(2026, 6, 19, tzinfo=UTC),
        strategy_id="st_demo",
        version_id="sv_demo",
        symbols=["000001.SZ"],
    )
    item = repo.list_items(run.run_id)[0]

    evidence = EvidenceViewService(repo, research_repo).get_evidence_view(item.item_id)
    valuation = ValuationViewService(repo, research_repo).get_valuation_view(item.item_id)

    assert evidence.locators_available is True
    assert evidence.source_distribution == {"unknown": 1}
    assert evidence.claims[0].claim_id == "cl_cashflow"
    assert valuation.base_valuation_range == (10.8, 13.2)
    assert valuation.value_trap_score == 0.28


def test_feedback_and_job_services_are_append_only():
    repo, _, run_service, _ = _services()
    run = run_service.run_batch(
        decision_at=datetime(2026, 6, 19, tzinfo=UTC),
        strategy_id="st_demo",
        version_id="sv_demo",
        symbols=["000001.SZ"],
    )
    item = repo.list_items(run.run_id)[0]
    feedback_service = FeedbackService(repo)

    feedback = feedback_service.record_feedback(
        item.item_id,
        FeedbackType.WATCH,
        "继续观察",
    )
    job = JobService().record_completed_job(run.run_id)

    assert repo.list_feedback(item.item_id) == [feedback]
    assert job.run_id == run.run_id
    assert json.loads(job.payload_json)["run_id"] == run.run_id


def test_report_renderer_and_export_service_include_auditable_sections():
    repo, research_repo, run_service, _ = _services()
    run = run_service.run_batch(
        decision_at=datetime(2026, 6, 19, tzinfo=UTC),
        strategy_id="st_demo",
        version_id="sv_demo",
        symbols=["000001.SZ"],
    )
    item = repo.list_items(run.run_id)[0]
    renderer = ReportRenderer(repo, research_repo)

    report = renderer.render_report(item.item_id)
    export = ExportService(renderer).export_report(item.item_id, "json")
    exported = json.loads(export.content)

    assert report.item_id == item.item_id
    assert report.sections["evidence"]["source_distribution"] == {"unknown": 1}
    assert report.sections["valuation"]["base_valuation_range"] == [10.8, 13.2]
    assert report.sections["audit"]["snapshot_id"] == item.snapshot_id
    assert "不构成买卖指令" in report.content
    assert export.mime_type == "application/json"
    assert exported["item_id"] == item.item_id
    assert exported["sections"]["summary"]["symbol"] == "000001.SZ"
