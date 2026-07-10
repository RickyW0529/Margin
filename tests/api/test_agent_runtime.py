"""API tests for MainAgent runtime and scheduled stock analysis."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

from fastapi.testclient import TestClient

from margin.agent_runtime.chat_repository import (
    AgentChatRepository,
    MemoryAgentChatRepository,
)
from margin.agent_runtime.context_store import (
    MemoryAgentContextStore,
    make_context_artifact,
)
from margin.agent_runtime.schedules import MemoryAgentScheduleRepository
from margin.agents.runtime.service import (
    AgentRuntimeService,
    UserQnaCommand,
)
from margin.api.main import create_app
from margin.core.hashing import stable_json_hash
from margin.dashboard.models import ResearchItem, ResearchRun
from margin.dashboard.repository import MemoryDashboardRepository
from margin.dashboard.service import DashboardServiceBundle
from margin.platform_runtime.repository import IdempotencyKeyRecord, MemoryIdempotencyStore
from margin.research.llm import DeterministicLLMProvider, LLMResult
from margin.settings import MarginSettings

DECISION_AT = datetime(2026, 6, 22, tzinfo=UTC)


def test_user_qna_agent_run_returns_main_agent_trace() -> None:
    """Test that user Q&A goes through the MainAgent runtime.

    Returns:
        None: .
    """
    llm_provider = _AnswerLLMProvider("LLM 基于当前推荐数据回答：000001.SZ。")
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
    assert body["agent_trace"]["steps"][0]["expert_agent_name"].endswith("ExpertAgent")
    assert body["agent_trace"]["activities"][0] == {
        "activity_id": f"{body['run_id']}:planning",
        "stage": "planning",
        "actor": "MainAgent",
        "action": "route_request",
        "status": "succeeded",
        "summary": "已根据当前问题和结构化上下文生成执行计划。",
        "tool_name": None,
        "evidence_refs": [],
    }
    assert body["agent_trace"]["activities"][1]["stage"] == "execution"
    assert {artifact["artifact_type"] for artifact in body["artifacts"]} >= {
        "analysis_table",
        "qna_answer",
        "final_user_answer",
    }
    assert llm_provider.calls == ["main_plan", "expert_plan", "answer"]


def test_user_qna_greeting_runs_general_llm_agent() -> None:
    """Test that a greeting is planned by MainAgent and answered by the LLM agent.

    Returns:
        None: .
    """
    llm_provider = _AnswerLLMProvider("你好，我是 Margin。")
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
            "step_id": "dt_general",
            "expert_agent_name": "GeneralQnaExpertAgent",
            "skill_id": "answer_general_qna",
            "status": "succeeded",
        }
    ]
    assert any(artifact["artifact_type"] == "qna_answer" for artifact in body["artifacts"])
    assert llm_provider.calls == ["main_plan", "expert_plan", "answer"]


def test_user_qna_persists_chat_session_and_uses_context_for_followup() -> None:
    """Test that follow-up questions restore DB-backed chat context.

    Returns:
        None: .
    """
    llm_provider = _AnswerLLMProvider("LLM 基于当前推荐数据回答：000001.SZ。")
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
        "今日推荐股票是什么？" in prompt and "LLM 基于当前推荐数据回答：000001.SZ。" in prompt
        for prompt in llm_provider.prompts
    )


def test_user_qna_persists_and_passes_resolved_incremental_state(monkeypatch) -> None:
    """Only typed state on prior user messages may fill an elliptical follow-up."""
    commands: list[UserQnaCommand] = []

    def record_command(
        _runtime: AgentRuntimeService,
        command: UserQnaCommand,
    ) -> SimpleNamespace:
        commands.append(command)
        return _fake_user_qna_result()

    monkeypatch.setattr(AgentRuntimeService, "run_user_qna", record_command)
    chat_repository = MemoryAgentChatRepository()
    client = _client_with_agent_runtime(chat_repository=chat_repository)
    first = client.post(
        "/api/v1/agent-runs/user-qna",
        headers=_idempotency_headers("resolved-context-1"),
        json={"scope_version_id": "scope-1", "message": "中国平安 ROE"},
    )
    second = client.post(
        "/api/v1/agent-runs/user-qna",
        headers=_idempotency_headers("resolved-context-2"),
        json={
            "scope_version_id": "scope-1",
            "session_id": first.json()["session_id"],
            "message": "深交所000001.SZ 最近4期的",
        },
    )

    assert second.status_code == 200
    resolved = commands[-1].resolved_turn_context
    assert resolved is not None
    assert resolved.security_query == "000001.SZ"
    assert resolved.indicator_id == "roe_ttm"
    assert resolved.max_points_per_indicator == 4
    user_messages = [
        message for message in chat_repository.list_messages(first.json()["session_id"])
        if message.role == "user"
    ]
    assert user_messages[-1].payload["resolved_turn_context"] == resolved.model_dump(
        mode="json"
    )


def test_user_qna_persists_context_pack_artifact() -> None:
    """Test that L1 planning persists a structured ContextPack (not dual-written)."""
    from margin.agents.context.repository import MemoryContextRepository

    context_store = MemoryAgentContextStore()
    context_repository = MemoryContextRepository()
    client = _client_with_agent_runtime(
        context_store=context_store,
        context_repository=context_repository,
    )

    response = client.post(
        "/api/v1/agent-runs/user-qna",
        headers=_idempotency_headers("qna-context-pack"),
        json={"scope_version_id": "scope-1", "message": "你好"},
    )

    assert response.status_code == 200
    run_id = response.json()["run_id"]
    pack_id = f"ctxpack_{run_id}_mainagent"
    # Source of truth is ContextRepository — no dual-write into runtime artifacts.
    assert context_store.get_artifact(pack_id) is None
    pack = context_repository.get_context_pack(pack_id)
    assert pack is not None
    assert pack.token_budget == 4000
    assert pack.target_agent == "MainAgent"
    # API expansion reconstructs the pack as an artifact view (payload is redacted).
    detail = client.get(f"/api/v1/agent-artifacts/{pack_id}")
    assert detail.status_code == 200
    body = detail.json()
    assert body["artifact_type"] == "context_pack"
    assert body["artifact_id"] == pack_id
    assert body["producer_agent"] == "MainAgent"


def test_user_qna_rejects_unknown_chat_session() -> None:
    """Test that clients cannot append to a missing chat session.

    Returns:
        None: .
    """
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


def test_agent_artifact_detail_returns_persisted_payload() -> None:
    """Test that chat artifact refs can be expanded through a scoped read API.

    Returns:
        None: .
    """
    context_store = MemoryAgentContextStore()
    artifact = make_context_artifact(
        artifact_id="ctx_test_table",
        run_id="ar_qna_1",
        artifact_type="analysis_table",
        producer_agent="DataQuestionWorker",
        payload_json={
            "columns": ["symbol", "score"],
            "rows": [
                {"symbol": "000001.SZ", "score": 86},
                {"symbol": "600000.SH", "score": 82},
            ],
            "raw_text": "不应直接返回的原始大文本",
            "nested": {"provider_token": "secret-provider-token"},
        },
        source_refs=("GET /api/v1/research",),
        evidence_refs=("ev_1",),
    )
    context_store.add_artifact(artifact)
    client = _client_with_agent_runtime(context_store=context_store)

    response = client.get("/api/v1/agent-artifacts/ctx_test_table")

    assert response.status_code == 200
    body = response.json()
    assert body["artifact_id"] == "ctx_test_table"
    assert body["artifact_type"] == "analysis_table"
    assert body["producer_agent"] == "DataQuestionWorker"
    assert body["payload_json"]["rows"][0]["symbol"] == "000001.SZ"
    assert body["payload_json"]["raw_text"] == "[redacted]"
    assert body["payload_json"]["nested"]["provider_token"] == "[redacted]"
    assert body["payload_hash"] == artifact.payload_hash
    assert body["source_refs"] == ["GET /api/v1/research"]
    assert body["evidence_refs"] == ["ev_1"]


def test_agent_artifact_detail_returns_404_for_missing_artifact() -> None:
    """Test that missing artifact IDs are explicit 404s.

    Returns:
        None: .
    """
    client = _client_with_agent_runtime()

    response = client.get("/api/v1/agent-artifacts/ctx_missing")

    assert response.status_code == 404
    assert response.json()["detail"]["code"] == "agent_artifact_not_found"


def test_stock_analysis_schedule_can_be_saved_and_read() -> None:
    """Test that the automatic stock-analysis schedule is persisted by the API.

    Returns:
        None: .
    """
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
    """Test that mutating agent runtime endpoints require an idempotency key.

    Returns:
        None: .
    """
    client = _client_with_agent_runtime()

    qna_response = client.post(
        "/api/v1/agent-runs/user-qna",
        json={"scope_version_id": "scope-1", "message": "你好"},
    )
    workspace_response = client.post(
        "/api/v1/agent-runs/workspace",
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
    assert workspace_response.status_code == 400
    assert schedule_response.status_code == 400
    assert qna_response.json()["detail"] == "Idempotency-Key header is required"
    assert workspace_response.json()["detail"] == "Idempotency-Key header is required"
    assert schedule_response.json()["detail"] == "Idempotency-Key header is required"


def test_workspace_agent_uses_explicit_tool_grant_and_independent_idempotency_scope(
    monkeypatch,
) -> None:
    """Normal Q&A stays read-only while the admin route opts into workspace tools."""
    commands: list[UserQnaCommand] = []

    def record_command(
        runtime: AgentRuntimeService,
        command: UserQnaCommand,
    ) -> SimpleNamespace:
        del runtime
        commands.append(command)
        return _fake_user_qna_result()

    monkeypatch.setattr(AgentRuntimeService, "run_user_qna", record_command)
    idempotency_store = MemoryIdempotencyStore()
    client = _client_with_agent_runtime(idempotency_store=idempotency_store)
    headers = _idempotency_headers("shared-qna-key")
    body = {"scope_version_id": "scope-1", "message": "你好"}

    user_response = client.post(
        "/api/v1/agent-runs/user-qna",
        headers=headers,
        json=body,
    )
    workspace_response = client.post(
        "/api/v1/agent-runs/workspace",
        headers=headers,
        json=body,
    )

    assert user_response.status_code == 200
    assert workspace_response.status_code == 200
    assert [command.allow_workspace_tools for command in commands] == [False, True]
    assert idempotency_store.get_idempotency_key("agent.user_qna:shared-qna-key") is not None
    workspace_record = idempotency_store.get_idempotency_key(
        "agent.workspace_qna:shared-qna-key"
    )
    assert workspace_record is not None
    assert workspace_record.scope == "agent.workspace_qna"


def test_workspace_agent_requires_admin_bearer_token_in_production(monkeypatch) -> None:
    """Workspace-capable requests are protected by the production admin guard."""
    monkeypatch.setattr(
        AgentRuntimeService,
        "run_user_qna",
        lambda _runtime, _command: _fake_user_qna_result(),
    )
    client = _client_with_agent_runtime()
    monkeypatch.setattr(
        "margin.api.dependencies.get_settings",
        lambda: MarginSettings(
            _env_file=None,
            environment="production",
            database_url="postgresql+psycopg://margin_app:strong@db:5432/margin",
            secret_master_key="!" * 32,
            admin_api_token="admin-secret",
        ),
    )
    body = {"scope_version_id": "scope-1", "message": "你好"}

    unauthorized = client.post(
        "/api/v1/agent-runs/workspace",
        headers=_idempotency_headers("workspace-auth"),
        json=body,
    )
    authorized = client.post(
        "/api/v1/agent-runs/workspace",
        headers={
            **_idempotency_headers("workspace-auth"),
            "Authorization": "Bearer admin-secret",
        },
        json=body,
    )

    assert unauthorized.status_code == 401
    assert unauthorized.json()["detail"] == "admin bearer token is required"
    assert authorized.status_code == 200


def test_user_qna_guardrail_blocks_guaranteed_return_claims() -> None:
    """Test that financial guarantee requests are blocked before expert routing.

    Returns:
        None: .
    """
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


def _fake_user_qna_result() -> SimpleNamespace:
    """Return the API-facing subset of a successful runtime result."""
    return SimpleNamespace(
        answer="test answer",
        guardrail=SimpleNamespace(
            allowed=True,
            decision="allow",
            summary="request allowed",
            triggered_policies=(),
        ),
        trace_steps=(),
        artifacts=(),
        references=(),
    )


def _client_with_agent_runtime(
    llm_provider: DeterministicLLMProvider | None = None,
    chat_repository: AgentChatRepository | None = None,
    context_store: MemoryAgentContextStore | None = None,
    context_repository: object | None = None,
    idempotency_store: MemoryIdempotencyStore | None = None,
) -> TestClient:
    """Build a test client with in-memory agent runtime dependencies."""
    from margin.agents.context.repository import MemoryContextRepository

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
    context_store = context_store or MemoryAgentContextStore()
    context_repository = context_repository or MemoryContextRepository()
    idempotency_store = idempotency_store or MemoryIdempotencyStore()
    fallback_llm_provider = llm_provider or _AnswerLLMProvider("LLM 默认测试回答：000001.SZ。")

    def llm_provider_factory() -> DeterministicLLMProvider:
        """Return the deterministic test LLM provider."""
        return fallback_llm_provider

    return TestClient(
        create_app(
            dashboard_services=bundle,
            agent_runtime_service=AgentRuntimeService(
                context_store=context_store,
                context_repository=context_repository,
                dashboard_services=bundle,
                llm_provider_factory=llm_provider_factory,
            ),
            agent_context_store=context_store,
            agent_context_repository=context_repository,
            agent_schedule_repository=MemoryAgentScheduleRepository(),
            agent_chat_repository=chat_repository or MemoryAgentChatRepository(),
            llm_provider_factory=llm_provider_factory,
            idempotency_store=idempotency_store,
        )
    )


def _idempotency_headers(key: str) -> dict[str, str]:
    """Return headers required by mutating API endpoints.

    Args:
        key: str: .

    Returns:
        dict[str, str]: .
    """
    return {"Idempotency-Key": key}


class _AnswerLLMProvider(DeterministicLLMProvider):
    """Test LLM that returns Main plan, Expert plan, and a free-form answer."""

    def __init__(self, answer: str) -> None:
        """Initialize with one deterministic answer."""
        super().__init__(response={})
        self._answer = answer
        self.calls: list[str] = []
        self.prompts: list[str] = []
        self._structured_calls = 0

    def complete(
        self,
        prompt: str,
        *,
        response_schema: dict[str, object] | None = None,
        temperature: float = 0.0,
    ) -> LLMResult:
        """Process complete.

        Args:
            prompt: str: .
            response_schema: dict[str, object] | None: .
            temperature: float: .

        Returns:
            LLMResult: .
        """
        del temperature
        self.prompts.append(prompt)
        if response_schema is not None:
            self._structured_calls += 1
            if self._structured_calls % 2 == 1:
                self.calls.append("main_plan")
                return LLMResult(
                    output={
                        "steps": [
                            {
                                "step_id": "general",
                                "agent": "GeneralQnaExpertAgent",
                                "task": "Delegate the user request to the general Q&A expert.",
                                "required_output_types": ["analysis_table", "qna_answer"],
                            }
                        ],
                        "final_answer_requirements": ["use_approved_capsules_only"],
                    },
                    model="test",
                    success=True,
                    latency_ms=0.0,
                    raw_response="main_plan",
                )
            self.calls.append("expert_plan")
            return LLMResult(
                output={
                    "steps": [
                        {
                            "step_id": "answer",
                            "worker_agent": "GeneralQnaWorker",
                            "skill_id": "answer_general_qna",
                            "task": "Answer from approved context only.",
                            "required_output_types": ["analysis_table", "qna_answer"],
                        }
                    ],
                    "audit_requirements": ["verify_artifacts_before_returning"],
                },
                model="test",
                success=True,
                latency_ms=0.0,
                raw_response="expert_plan",
            )
        self.calls.append("answer")
        return LLMResult(
            output={"content": self._answer},
            model="test",
            success=True,
            latency_ms=0.0,
            raw_response=self._answer,
        )


def test_user_qna_replays_same_idempotency_key_without_second_llm_call() -> None:
    """Identical Idempotency-Key + body must replay without re-running the LLM."""
    llm_provider = _AnswerLLMProvider("LLM 幂等回答：000001.SZ。")
    client = _client_with_agent_runtime(llm_provider=llm_provider)
    headers = _idempotency_headers("qna-idempotent-once")
    body = {
        "scope_version_id": "scope-1",
        "message": "今日推荐？",
        "session_id": None,
        "universe": "ALL_A",
        "language": "zh",
    }

    first = client.post("/api/v1/agent-runs/user-qna", headers=headers, json=body)
    second = client.post("/api/v1/agent-runs/user-qna", headers=headers, json=body)

    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json()["run_id"] == second.json()["run_id"]
    assert first.json()["answer"] == second.json()["answer"]
    # One planning path only; replay must not call the LLM again.
    assert llm_provider.calls == ["main_plan", "expert_plan", "answer"]


def test_user_qna_pending_idempotency_key_does_not_execute_runtime() -> None:
    """In-flight duplicate requests must not append chat or run the LLM path."""
    body = {
        "scope_version_id": "scope-1",
        "message": "今日推荐？",
        "session_id": None,
        "universe": "ALL_A",
        "language": "zh",
    }
    store = MemoryIdempotencyStore()
    now = datetime(2026, 7, 9, tzinfo=UTC)
    store.begin_idempotency_key(
        IdempotencyKeyRecord(
            idempotency_key="agent.user_qna:qna-pending",
            scope="agent.user_qna",
            request_hash=stable_json_hash(body),
            response_hash=None,
            response_ref=None,
            status="pending",
            created_at=now,
            expires_at=now + timedelta(hours=24),
        )
    )
    llm_provider = _AnswerLLMProvider("should not run")
    client = _client_with_agent_runtime(
        llm_provider=llm_provider,
        idempotency_store=store,
    )

    response = client.post(
        "/api/v1/agent-runs/user-qna",
        headers=_idempotency_headers("qna-pending"),
        json=body,
    )

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "idempotency_key_in_progress"
    assert llm_provider.calls == []


def test_user_qna_idempotency_key_conflict_on_different_body() -> None:
    """Reusing Idempotency-Key with a different body returns 409."""
    client = _client_with_agent_runtime()
    headers = _idempotency_headers("qna-idempotent-conflict")

    first = client.post(
        "/api/v1/agent-runs/user-qna",
        headers=headers,
        json={"scope_version_id": "scope-1", "message": "第一问"},
    )
    second = client.post(
        "/api/v1/agent-runs/user-qna",
        headers=headers,
        json={"scope_version_id": "scope-1", "message": "第二问"},
    )

    assert first.status_code == 200
    assert second.status_code == 409
    assert second.json()["detail"]["code"] == "idempotency_key_conflict"
