"""API tests for MainAgent runtime and scheduled stock analysis."""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace

from fastapi.testclient import TestClient

from margin.agent_runtime.cards import default_agent_card_registry
from margin.agent_runtime.chat_repository import (
    AgentChatRepository,
    MemoryAgentChatRepository,
)
from margin.agent_runtime.context_store import MemoryAgentContextStore
from margin.agent_runtime.main_agent import MainAgentRuntime
from margin.agent_runtime.schedules import MemoryAgentScheduleRepository
from margin.agent_runtime.step_definitions import load_scheduled_stock_analysis_flow
from margin.api.main import create_app
from margin.dashboard.models import ResearchItem, ResearchRun
from margin.dashboard.repository import MemoryDashboardRepository
from margin.dashboard.service import DashboardServiceBundle
from margin.research.llm import DeterministicLLMProvider, LLMResult

DECISION_AT = datetime(2026, 6, 22, tzinfo=UTC)


def test_user_qna_agent_run_returns_main_agent_trace() -> None:
    """Test that user Q&A goes through the MainAgent runtime."""
    llm_provider = _PlannerAndAnswerLLMProvider(
        plan_response={
            "plan_id": "plan_ar_qna_recommendation",
            "fixed_flow": False,
            "steps": [
                {
                    "expert_agent_name": "DataAnalystAgent",
                    "skill_id": "answer_with_analysis_artifacts",
                }
            ],
        },
        answer="LLM 基于当前推荐数据回答：000001.SZ。",
    )
    client = _client_with_agent_runtime(llm_provider=llm_provider)

    response = client.post(
        "/api/v1/agent-runs/user-qna",
        headers=_idempotency_headers("qna-recommendation"),
        json={"scope_version_id": "scope-1", "message": "今日推荐股票是什么？"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["session_id"].startswith("acs_")
    assert body["user_message_id"].startswith("acm_")
    assert body["assistant_message_id"].startswith("acm_")
    assert body["run_id"].startswith("ar_qna_")
    assert "000001.SZ" in body["answer"]
    assert body["answer"] == "LLM 基于当前推荐数据回答：000001.SZ。"
    assert body["guardrail"]["allowed"] is True
    assert body["agent_trace"]["steps"][0]["expert_agent_name"] == "DataAnalystAgent"
    assert body["artifacts"][0]["artifact_type"] == "analysis_table"
    assert body["artifacts"][1]["artifact_type"] == "explanation"
    assert llm_provider.calls == ["planner", "answer"]


def test_user_qna_greeting_runs_general_llm_agent() -> None:
    """Test that a greeting is planned by MainAgent and answered by the LLM agent."""
    llm_provider = _PlannerAndAnswerLLMProvider(
        plan_response={
            "plan_id": "plan_ar_qna_greeting",
            "fixed_flow": False,
            "steps": [
                {
                    "expert_agent_name": "GeneralQnaAgent",
                    "skill_id": "answer_general_qna",
                }
            ],
        },
        answer="你好，我是 Margin。",
    )
    client = _client_with_agent_runtime(llm_provider=llm_provider)

    response = client.post(
        "/api/v1/agent-runs/user-qna",
        headers=_idempotency_headers("qna-greeting"),
        json={"scope_version_id": "scope-1", "message": "你好"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["answer"] == "你好，我是 Margin。"
    assert body["agent_trace"]["steps"] == [
        {
            "step_id": "qna_1_generalqna",
            "expert_agent_name": "GeneralQnaAgent",
            "skill_id": "answer_general_qna",
            "status": "succeeded",
        }
    ]
    assert body["artifacts"][0]["artifact_type"] == "explanation"
    assert body["artifacts"][0]["producer_agent"] == "GeneralQnaAgent"
    assert llm_provider.calls == ["planner", "answer"]


def test_user_qna_persists_chat_session_and_uses_context_for_followup() -> None:
    """Test that follow-up questions restore DB-backed chat context."""
    llm_provider = _PlannerAndAnswerLLMProvider(
        plan_response={
            "plan_id": "plan_ar_qna_context",
            "fixed_flow": False,
            "steps": [
                {
                    "expert_agent_name": "DataAnalystAgent",
                    "skill_id": "answer_with_analysis_artifacts",
                }
            ],
        },
        answer="LLM 基于当前推荐数据回答：000001.SZ。",
    )
    chat_repository = MemoryAgentChatRepository()
    client = _client_with_agent_runtime(
        llm_provider=llm_provider,
        chat_repository=chat_repository,
    )

    first_response = client.post(
        "/api/v1/agent-runs/user-qna",
        headers=_idempotency_headers("qna-context-1"),
        json={"scope_version_id": "scope-1", "message": "今日推荐股票是什么？"},
    )
    assert first_response.status_code == 200
    session_id = first_response.json()["session_id"]

    second_response = client.post(
        "/api/v1/agent-runs/user-qna",
        headers=_idempotency_headers("qna-context-2"),
        json={
            "scope_version_id": "scope-1",
            "session_id": session_id,
            "message": "那为什么？",
        },
    )

    assert second_response.status_code == 200
    assert second_response.json()["session_id"] == session_id
    detail_response = client.get(f"/api/v1/agent-chat/sessions/{session_id}")
    assert detail_response.status_code == 200
    detail = detail_response.json()
    assert detail["session"]["title"] == "今日推荐股票是什么？"
    assert [message["role"] for message in detail["messages"]] == [
        "user",
        "assistant",
        "user",
        "assistant",
    ]
    assert [message["content"] for message in detail["messages"]][:3] == [
        "今日推荐股票是什么？",
        "LLM 基于当前推荐数据回答：000001.SZ。",
        "那为什么？",
    ]
    sessions_response = client.get("/api/v1/agent-chat/sessions")
    assert sessions_response.status_code == 200
    assert sessions_response.json()["items"][0]["session_id"] == session_id
    assert any(
        "今日推荐股票是什么？" in prompt
        and "LLM 基于当前推荐数据回答：000001.SZ。" in prompt
        for prompt in llm_provider.prompts
    )


def test_user_qna_rejects_unknown_chat_session() -> None:
    """Test that clients cannot append to a missing chat session."""
    client = _client_with_agent_runtime()

    response = client.post(
        "/api/v1/agent-runs/user-qna",
        headers=_idempotency_headers("qna-missing-session"),
        json={
            "scope_version_id": "scope-1",
            "session_id": "acs_missing",
            "message": "继续上次问题",
        },
    )

    assert response.status_code == 404
    assert response.json()["detail"]["code"] == "chat_session_not_found"


def test_stock_analysis_schedule_can_be_saved_and_read() -> None:
    """Test that the automatic stock-analysis schedule is persisted by the API."""
    client = _client_with_agent_runtime()

    put_response = client.put(
        "/api/v1/agent-schedules/stock-analysis",
        headers=_idempotency_headers("schedule-save"),
        json={
            "enabled": True,
            "hour": 8,
            "minute": 30,
            "timezone": "Asia/Shanghai",
            "scope_version_id": "scope-current",
            "universe": "ALL_A",
        },
    )
    get_response = client.get("/api/v1/agent-schedules/stock-analysis")

    assert put_response.status_code == 200
    assert get_response.status_code == 200
    body = get_response.json()
    assert body["enabled"] is True
    assert body["hour"] == 8
    assert body["minute"] == 30
    assert body["scope_version_id"] == "scope-current"
    assert body["next_run_at"] is not None


def test_agent_runtime_mutations_require_idempotency_key() -> None:
    """Test that mutating agent runtime endpoints require an idempotency key."""
    client = _client_with_agent_runtime()

    qna_response = client.post(
        "/api/v1/agent-runs/user-qna",
        json={"scope_version_id": "scope-1", "message": "你好"},
    )
    schedule_response = client.put(
        "/api/v1/agent-schedules/stock-analysis",
        json={
            "enabled": True,
            "hour": 8,
            "minute": 30,
            "timezone": "Asia/Shanghai",
            "scope_version_id": "scope-current",
            "universe": "ALL_A",
        },
    )

    assert qna_response.status_code == 400
    assert schedule_response.status_code == 400
    assert qna_response.json()["detail"] == "Idempotency-Key header is required"
    assert schedule_response.json()["detail"] == "Idempotency-Key header is required"


def test_user_qna_guardrail_blocks_guaranteed_return_claims() -> None:
    """Test that financial guarantee requests are blocked before expert routing."""
    client = _client_with_agent_runtime()

    response = client.post(
        "/api/v1/agent-runs/user-qna",
        headers=_idempotency_headers("qna-guardrail"),
        json={"scope_version_id": "scope-1", "message": "能保证这只股票收益吗？"},
    )

    assert response.status_code == 403
    body = response.json()["detail"]
    assert body["code"] == "agent_guardrail_blocked"
    assert body["triggered_policies"] == ["financial_guarantee"]


def _client_with_agent_runtime(
    llm_provider: DeterministicLLMProvider | None = None,
    chat_repository: AgentChatRepository | None = None,
) -> TestClient:
    """Build a test client with in-memory agent runtime dependencies."""
    dashboard_repository = MemoryDashboardRepository()
    bundle = DashboardServiceBundle.in_memory(
        dashboard_repository=dashboard_repository,
    )
    run = ResearchRun(
        run_id="run-1",
        decision_at=DECISION_AT,
        strategy_id="strategy-1",
        version_id="scope-1",
        universe=["000001.SZ"],
        status="partial",
        item_count=1,
        published_count=1,
    )
    item = ResearchItem(
        item_id="item-1",
        run_id=run.run_id,
        symbol="000001.SZ",
        signal_type="research_candidate",
        confidence=0.82,
        statement="经营现金流改善",
        workflow_run_id="wf-1",
        snapshot_id="assess-old",
        status="published",
    )
    dashboard_repository.add_run(run)
    dashboard_repository.add_items([item])
    fallback_llm_provider = llm_provider or _PlannerAndAnswerLLMProvider(
        plan_response={
            "plan_id": "plan_ar_qna_default",
            "fixed_flow": False,
            "steps": [
                {
                    "expert_agent_name": "DataAnalystAgent",
                    "skill_id": "answer_with_analysis_artifacts",
                }
            ],
        },
        answer="LLM 默认测试回答：000001.SZ。",
    )

    def llm_provider_factory() -> DeterministicLLMProvider:
        return fallback_llm_provider

    return TestClient(
        create_app(
            dashboard_services=bundle,
            main_agent_runtime=MainAgentRuntime(
                context_store=MemoryAgentContextStore(),
                card_registry=default_agent_card_registry(),
                scheduled_flow=load_scheduled_stock_analysis_flow(),
                llm_provider_factory=llm_provider_factory,
            ),
            agent_schedule_repository=MemoryAgentScheduleRepository(),
            agent_chat_repository=chat_repository or MemoryAgentChatRepository(),
            strategy_service=_FakeStrategyService(),
            llm_provider_factory=llm_provider_factory,
        )
    )


def _idempotency_headers(key: str) -> dict[str, str]:
    """Return headers required by mutating API endpoints."""
    return {"Idempotency-Key": key}


class _FakeStrategyService:
    """Fake strategy service exposing one active research scope."""

    def ensure_current_research_scope(self, owner_id: str) -> SimpleNamespace:
        """Return the active scope."""
        return SimpleNamespace(
            owner_id=owner_id,
            version_id="scope-1",
            lifecycle="active",
        )


class _PlannerAndAnswerLLMProvider(DeterministicLLMProvider):
    """Test LLM that returns a structured plan first and free-form answer later."""

    def __init__(self, *, plan_response: dict[str, object], answer: str) -> None:
        super().__init__(response={})
        self._plan_response = plan_response
        self._answer = answer
        self.calls: list[str] = []
        self.prompts: list[str] = []

    def complete(
        self,
        prompt: str,
        *,
        response_schema: dict[str, object] | None = None,
        temperature: float = 0.0,
    ) -> LLMResult:
        del temperature
        self.prompts.append(prompt)
        if response_schema:
            self.calls.append("planner")
            return LLMResult(
                output=self._plan_response,
                model="test",
                success=True,
                latency_ms=0.0,
            )
        self.calls.append("answer")
        return LLMResult(
            output={"content": self._answer},
            model="test",
            success=True,
            latency_ms=0.0,
            raw_response=self._answer,
        )
