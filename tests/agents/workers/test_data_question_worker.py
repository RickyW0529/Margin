"""Tests for the read-only DataQuestionWorker."""

from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal

from margin.agents.workers.data_question_worker import DataQuestionWorker
from margin.data.warehouse_repository import (
    IndicatorHistoryQuery,
    IndicatorHistoryValue,
    SecurityProfileSearchQuery,
    SecurityProfileValue,
)


class _Warehouse:
    """Deterministic fake warehouse for data-question worker tests."""

    def __init__(self) -> None:
        self.search_queries: list[SecurityProfileSearchQuery] = []
        self.indicator_queries: list[IndicatorHistoryQuery] = []
        self.indicator_discovery_calls: list[dict[str, object]] = []

    def search_security_profiles(
        self,
        query: SecurityProfileSearchQuery,
    ) -> list[SecurityProfileValue]:
        """Return one China Ping An security for name search."""
        self.search_queries.append(query)
        return [
            SecurityProfileValue(
                security_id="601318.SH",
                symbol="601318",
                name="中国平安",
                exchange="SSE",
                listed_at=date(2007, 3, 1),
                delisted_at=None,
                is_st=False,
            )
        ]

    def indicator_history(
        self,
        query: IndicatorHistoryQuery,
    ) -> list[IndicatorHistoryValue]:
        """Return two PIT-safe ROE observations."""
        self.indicator_queries.append(query)
        return [
            IndicatorHistoryValue(
                fact_id="roe-2023",
                provider="tushare",
                security_id="601318.SH",
                indicator_id="roe_ttm",
                event_at=datetime(2023, 12, 31, tzinfo=UTC),
                available_at=datetime(2024, 4, 30, 9, 30, tzinfo=UTC),
                fetched_at=datetime(2024, 4, 30, 10, 0, tzinfo=UTC),
                numeric_value=Decimal("0.101"),
                quality_score=Decimal("1.0"),
            ),
            IndicatorHistoryValue(
                fact_id="roe-2024",
                provider="tushare",
                security_id="601318.SH",
                indicator_id="roe_ttm",
                event_at=datetime(2024, 12, 31, tzinfo=UTC),
                available_at=datetime(2025, 4, 30, 9, 30, tzinfo=UTC),
                fetched_at=datetime(2025, 4, 30, 10, 0, tzinfo=UTC),
                numeric_value=Decimal("0.123"),
                quality_score=Decimal("1.0"),
            ),
        ]

    def discover_indicators(
        self,
        *,
        security_ids: tuple[str, ...],
        query_text: str,
        decision_at: datetime,
        limit: int,
    ) -> list[dict[str, object]]:
        """Return indicator metadata discovered from the warehouse catalog."""
        self.indicator_discovery_calls.append(
            {
                "security_ids": security_ids,
                "query_text": query_text,
                "decision_at": decision_at,
                "limit": limit,
            }
        )
        return [
            {
                "indicator_id": "roe_ttm",
                "label": "ROE TTM",
                "unit": "%",
                "value_scale": 100,
                "aliases": ["roe", "ROE", "净资产收益率"],
                "coverage": {"point_count": 2},
                "source_fields": ["fina_indicator.roe"],
            }
        ]


def test_data_question_worker_answers_financial_metric_with_chart_artifact() -> None:
    """DataQuestionWorker should answer ROE via warehouse facts, not an LLM."""
    warehouse = _Warehouse()
    result = DataQuestionWorker(warehouse).answer_financial_metric(
        run_id="ar_test",
        message="中国平安最近 ROE 是多少？",
        worker_inputs=_roe_worker_inputs("中国平安最近 ROE 是多少？"),
        decision_at=datetime(2026, 7, 9, tzinfo=UTC),
    )

    assert result is not None
    assert "中国平安" in result.answer
    assert "ROE TTM" in result.answer
    assert "12.30%" in result.answer
    assert result.table_artifact.producer_agent == "DataQuestionWorker"
    assert result.metric_artifact.artifact_type == "computed_metric"
    assert result.chart_artifact.artifact_type == "chart_spec"
    assert result.image_artifact.artifact_type == "visualization_image"
    assert result.worker_activity_artifact.artifact_type == "worker_activity"
    assert result.worker_activity_artifact.payload_json["worker_agent"] == "DataQuestionWorker"
    assert result.worker_activity_artifact.payload_json["workflow_runtime"] == "langgraph"
    assert result.worker_activity_artifact.payload_json["tool_calls"] == [
        "warehouse.describe_schema",
        "warehouse.resolve_security",
        "warehouse.discover_indicators",
        "warehouse.query_indicator_history",
        "python.render_chart",
    ]
    assert result.worker_activity_artifact.payload_json["actions"][0]["name"] == "恢复上下文"
    assert "indicator_history" in result.worker_activity_artifact.payload_json["python_code"]
    assert "<svg" in result.image_artifact.payload_json["svg"]
    assert result.chart_artifact.payload_json["series"][0]["points"][-1] == {
        "x": "2024-12-31",
        "y": 12.3,
    }
    assert result.table_artifact.payload_json["rows"][-1]["fact_id"] == "roe-2024"
    assert result.table_artifact.payload_json["rows"][-1]["indicator_id"] == "roe_ttm"
    assert result.table_artifact.payload_json["rows"][-1]["locator"].startswith(
        "warehouse://standardized_indicator_facts/roe-2024"
    )
    assert warehouse.search_queries[0].query_text == "中国平安"
    assert warehouse.indicator_discovery_calls[0]["query_text"] == "中国平安最近 ROE 是多少？"
    assert warehouse.indicator_queries[0].indicator_ids == ("roe_ttm",)


def test_data_question_worker_can_render_bar_visualization() -> None:
    """Follow-up chart requests should produce a generated bar image artifact."""
    warehouse = _Warehouse()
    result = DataQuestionWorker(warehouse).answer_financial_metric(
        run_id="ar_test_bar",
        message="中国平安最近 ROE 是多少？",
        worker_inputs=_roe_worker_inputs("中国平安最近 ROE 是多少？", chart_type="bar"),
        decision_at=datetime(2026, 7, 9, tzinfo=UTC),
    )

    assert result is not None
    assert result.chart_artifact.payload_json["chart_type"] == "bar"
    assert result.image_artifact.payload_json["image_format"] == "svg"
    assert "rect" in result.image_artifact.payload_json["svg"]
    assert "polyline" not in result.image_artifact.payload_json["svg"]


def test_data_question_worker_honors_requested_history_point_limit() -> None:
    warehouse = _Warehouse()
    result = DataQuestionWorker(warehouse).answer_financial_metric(
        run_id="ar_test_four_periods",
        message="深交所000001.SZ 最近4期的",
        worker_inputs={
            "user_query": "深交所000001.SZ 最近4期的 ROE",
            "security_query": "000001.SZ",
            "indicator_id": "roe_ttm",
            "chart_type": "line",
            "max_points_per_indicator": 4,
        },
        decision_at=datetime(2026, 7, 9, tzinfo=UTC),
    )

    assert result is not None
    assert warehouse.indicator_queries[0].max_points_per_indicator == 4
    assert result.worker_activity_artifact.payload_json["max_points_per_indicator"] == 4


def test_data_question_worker_answers_parent_net_profit_metric() -> None:
    """DataQuestionWorker should support warehouse parent-net-profit time series."""
    warehouse = _ProfitWarehouse()
    result = DataQuestionWorker(warehouse).answer_financial_metric(
        run_id="ar_test_profit",
        message="中国平安近几年的净利润",
        worker_inputs={
            "user_query": "中国平安近几年的净利润",
            "security_query": "中国平安",
            "indicator_id": "n_income_attr_p",
            "chart_type": "line",
        },
        decision_at=datetime(2026, 7, 9, tzinfo=UTC),
    )

    assert result is not None
    assert "归母净利润" in result.answer
    assert "亿元" in result.answer
    assert warehouse.indicator_discovery_calls[0]["query_text"] == "中国平安近几年的净利润"
    assert warehouse.indicator_queries[0].indicator_ids == ("n_income_attr_p",)
    assert result.metric_artifact.payload_json["indicator_id"] == "n_income_attr_p"
    assert result.table_artifact.payload_json["rows"][-1]["value"] == 1200.0


def test_data_question_worker_strips_runtime_prompt_from_security_lookup_and_answer() -> None:
    """Worker task prompts must not leak role labels or confuse security lookup."""
    warehouse = _Warehouse()
    result = DataQuestionWorker(warehouse).answer_financial_metric(
        run_id="ar_test_prompt_clean",
        message=(
            "expert_task: Use data tools.\n"
            "worker_task: answer ROE.\n"
            "recent_conversation:\n"
            "user: 你好\n"
            "assistant: 你好，我是 Margin。\n"
            "current_user: 看一下中国平安的roe"
        ),
        worker_inputs=_roe_worker_inputs("看一下中国平安的roe"),
        conversation_context=(
            {"role": "user", "content": "你好"},
            {"role": "assistant", "content": "你好，我是 Margin。"},
        ),
        decision_at=datetime(2026, 7, 9, tzinfo=UTC),
    )

    assert result is not None
    assert warehouse.search_queries[0].query_text == "中国平安"
    assert "中国平安" in result.answer
    assert "user:" not in result.answer
    assert "assistant:" not in result.answer
    assert "current_user:" not in result.answer


def test_data_question_worker_empty_answer_hides_runtime_prompt() -> None:
    """No-data responses should mention only the clean target, not internal task text."""
    warehouse = _EmptyWarehouse()
    result = DataQuestionWorker(warehouse).answer_financial_metric(
        run_id="ar_test_empty_prompt_clean",
        message=(
            "expert_task: Use data tools.\n"
            "worker_task: answer ROE.\n"
            "recent_conversation:\n"
            "assistant: 上一次回答\n"
            "current_user: 看一下中国平安的roe"
        ),
        worker_inputs=_roe_worker_inputs("看一下中国平安的roe"),
        decision_at=datetime(2026, 7, 9, tzinfo=UTC),
    )

    assert result is not None
    assert "中国平安" in result.answer
    assert "user:" not in result.answer
    assert "assistant:" not in result.answer
    assert "current_user:" not in result.answer
    assert "expert_task" not in result.answer


class _EmptyWarehouse(_Warehouse):
    """Warehouse that resolves no security profiles."""

    def search_security_profiles(
        self,
        query: SecurityProfileSearchQuery,
    ) -> list[SecurityProfileValue]:
        """Capture the query and return no matches."""
        self.search_queries.append(query)
        return []


class _ProfitWarehouse(_Warehouse):
    """Warehouse that returns parent-net-profit observations."""

    def discover_indicators(
        self,
        *,
        security_ids: tuple[str, ...],
        query_text: str,
        decision_at: datetime,
        limit: int,
    ) -> list[dict[str, object]]:
        """Return a warehouse-discovered profit indicator catalog item."""
        self.indicator_discovery_calls.append(
            {
                "security_ids": security_ids,
                "query_text": query_text,
                "decision_at": decision_at,
                "limit": limit,
            }
        )
        return [
            {
                "indicator_id": "n_income_attr_p",
                "label": "归母净利润",
                "unit": "亿元",
                "value_scale": 0.00000001,
                "aliases": ["净利润", "归母净利润", "parent net profit"],
                "coverage": {"point_count": 2},
                "source_fields": ["income.n_income_attr_p"],
            }
        ]

    def indicator_history(
        self,
        query: IndicatorHistoryQuery,
    ) -> list[IndicatorHistoryValue]:
        """Return PIT-safe parent net profit history."""
        self.indicator_queries.append(query)
        return [
            IndicatorHistoryValue(
                fact_id="profit-2023",
                provider="tushare",
                security_id="601318.SH",
                indicator_id="n_income_attr_p",
                event_at=datetime(2023, 12, 31, tzinfo=UTC),
                available_at=datetime(2024, 4, 30, 9, 30, tzinfo=UTC),
                fetched_at=datetime(2024, 4, 30, 10, 0, tzinfo=UTC),
                numeric_value=Decimal("100000000000"),
                quality_score=Decimal("1.0"),
            ),
            IndicatorHistoryValue(
                fact_id="profit-2024",
                provider="tushare",
                security_id="601318.SH",
                indicator_id="n_income_attr_p",
                event_at=datetime(2024, 12, 31, tzinfo=UTC),
                available_at=datetime(2025, 4, 30, 9, 30, tzinfo=UTC),
                fetched_at=datetime(2025, 4, 30, 10, 0, tzinfo=UTC),
                numeric_value=Decimal("120000000000"),
                quality_score=Decimal("1.0"),
            ),
        ]


def _roe_worker_inputs(user_query: str, *, chart_type: str = "line") -> dict[str, str]:
    """Return ExpertAgent-filled placeholders for a China Ping An ROE task."""
    return {
        "user_query": user_query,
        "security_query": "中国平安",
        "indicator_id": "roe_ttm",
        "chart_type": chart_type,
    }
