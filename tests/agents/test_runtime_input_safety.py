from __future__ import annotations

from datetime import UTC, datetime

from margin.agent_runtime.chat_repository import new_chat_message, summarize_messages_for_prompt
from margin.agents.runtime.service import _worker_task_goal
from margin.agents.runtime.worker_executors import financial_metric_worker_inputs
from margin.agents.workers.data_question_worker import _normalize_worker_inputs


def test_financial_metric_inputs_use_current_turn_not_planner_transcript() -> None:
    transcript = (
        "user: 你好 "
        "assistant: 没有在当前 PIT 数据仓库中找到 user: 你好 的 ROE TTM 历史记录。 "
        "current_user: 我想看一下中国平安的roe"
    )

    inputs = financial_metric_worker_inputs(
        current_user_message=transcript,
        planner_worker_inputs={
            "user_query": transcript,
            "security_query": transcript,
            "indicator_id": "roe_ttm",
            "chart_type": "line",
        },
    )

    assert inputs == {
        "user_query": "我想看一下中国平安的roe",
        "security_query": "中国平安",
        "indicator_id": "roe_ttm",
        "chart_type": "line",
        "max_points_per_indicator": 12,
    }


def test_financial_metric_inputs_reject_noise_without_reusing_previous_roe() -> None:
    inputs = financial_metric_worker_inputs(
        current_user_message="hhhh",
        planner_worker_inputs={
            "user_query": "我想看一下中国平安的roe",
            "security_query": "中国平安",
            "indicator_id": "roe_ttm",
        },
    )

    assert inputs is None


def test_data_worker_normalizer_strips_role_marked_transcript() -> None:
    transcript = (
        "user: 你好 "
        "assistant: 没有在当前 PIT 数据仓库中找到 user: 你好 的 ROE TTM 历史记录。 "
        "current_user: 我想看一下中国平安的roe"
    )

    normalized = _normalize_worker_inputs(
        {
            "user_query": transcript,
            "security_query": transcript,
            "indicator_id": "roe_ttm",
            "chart_type": "line",
        }
    )

    assert normalized is not None
    assert normalized["user_query"] == "我想看一下中国平安的roe"
    assert normalized["security_query"] == "中国平安"
    assert normalized["indicator_id"] == "roe_ttm"


def test_data_worker_normalizer_rejects_noise_even_with_stale_indicator() -> None:
    normalized = _normalize_worker_inputs(
        {
            "user_query": "hhhh",
            "security_query": "user: 我想看一下中国平安的roe\ncurrent_user: hhhh",
            "indicator_id": "roe_ttm",
            "chart_type": "line",
        }
    )

    assert normalized is None


def test_chat_prompt_summary_never_replays_no_data_answer() -> None:
    message = new_chat_message(
        message_id="m1",
        session_id="s1",
        role="assistant",
        content=(
            "没有在当前 PIT 数据仓库中找到 user: 你好 assistant: 你好 "
            "current_user: hhhh 的 ROE TTM 历史记录。\n暂无可绘制数据"
        ),
        now=datetime(2026, 7, 9, tzinfo=UTC),
    )

    rows = summarize_messages_for_prompt([message])

    assert rows == [
        {
            "role": "assistant",
            "content": "上一次助手回答主要说明：本地数据源或 Dashboard 上下文缺少匹配数据。",
            "created_at": "2026-07-09T00:00:00+00:00",
        }
    ]


def test_chat_prompt_summary_uses_inline_current_user_only() -> None:
    message = new_chat_message(
        message_id="m1",
        session_id="s1",
        role="user",
        content=(
            "user: 你好 assistant: 没有在当前 PIT 数据仓库中找到 user: 你好 "
            "current_user: 我想看一下中国平安银行的roe"
        ),
        now=datetime(2026, 7, 9, tzinfo=UTC),
    )

    rows = summarize_messages_for_prompt([message])

    assert rows == [
        {
            "role": "user",
            "content": "我想看一下中国平安银行的roe",
            "created_at": "2026-07-09T00:00:00+00:00",
        }
    ]


def test_worker_task_goal_excludes_assistant_context() -> None:
    goal = _worker_task_goal(
        user_message="hhhh",
        conversation_context=(
            {"role": "user", "content": "我想看一下中国平安的roe"},
            {
                "role": "assistant",
                "content": "没有在当前 PIT 数据仓库中找到 current_user: hhhh 的 ROE TTM 历史记录。",
            },
        ),
        expert_task="answer current user request",
        worker_task="answer metric",
        worker_inputs={"security_query": "中国平安", "indicator_id": "roe_ttm"},
    )

    assert "assistant:" not in goal
    assert "没有在当前 PIT 数据仓库中找到" not in goal
    assert "current_user: hhhh" in goal
