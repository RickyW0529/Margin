"""Tests for user-confirmed incremental turn state."""

from __future__ import annotations

from margin.agents.context.turn_context import resolve_turn_context


def test_financial_followup_inherits_metric_but_current_security_and_limit_win() -> None:
    first = resolve_turn_context("我想看一下中国平安的 ROE")
    previous_messages = (
        {
            "role": "user",
            "payload": {"resolved_turn_context": first.model_dump(mode="json")},
        },
        {
            "role": "assistant",
            "payload": {
                "resolved_turn_context": {
                    **first.model_dump(mode="json"),
                    "security_query": "assistant-text-must-not-win",
                }
            },
        },
    )

    resolved = resolve_turn_context(
        "深交所000001.SZ 最近4期的",
        previous_messages=previous_messages,
    )

    assert resolved.security_query == "000001.SZ"
    assert resolved.indicator_id == "roe_ttm"
    assert resolved.max_points_per_indicator == 4
    assert resolved.inherited_fields == ("indicator_id", "chart_type")
    assert resolved.financial_metric_worker_inputs() == {
        "user_query": "深交所000001.SZ 最近4期的 ROE",
        "security_query": "000001.SZ",
        "indicator_id": "roe_ttm",
        "chart_type": "line",
        "max_points_per_indicator": 4,
    }


def test_noise_does_not_inherit_prior_financial_state() -> None:
    first = resolve_turn_context("中国平安 ROE")

    resolved = resolve_turn_context(
        "hhhh",
        previous_messages=(
            {
                "role": "user",
                "payload": {"resolved_turn_context": first.model_dump(mode="json")},
            },
        ),
    )

    assert resolved.intent == "unknown"
    assert resolved.security_query is None
    assert resolved.indicator_id is None
    assert resolved.financial_metric_worker_inputs() is None
