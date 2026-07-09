"""Industry valuation and confidence calibration tests.

This module validates that the industry valuation registry selects the correct
model per industry family, reports unavailable reasons for missing inputs,
and that the confidence calibrator produces deterministic, conflict-penalized
scores without accepting LLM overrides.
"""

from __future__ import annotations

import pytest

from margin.valuation_discovery.confidence import ConfidenceCalibrator
from margin.valuation_discovery.valuation import IndustryValuationRegistry


def test_registry_uses_bank_model_for_bank_industry() -> None:
    """Verify the registry uses the bank PB-ROE model for the bank industry family.

    Returns:
        None: .
    """
    registry = IndustryValuationRegistry.default()

    result = registry.value(
        security_id="000001.SZ",
        industry_family="bank",
        inputs={
            "book_value_per_share": 20.0,
            "roe_ttm": 0.12,
            "pb_floor": 0.7,
            "pb_ceiling": 1.1,
        },
    )

    assert result.available is True
    assert result.model_name == "bank_pb_roe"
    assert result.value_range[0] < result.value_range[1]
    assert "roe_ttm" in result.key_assumptions
    assert result.model_version == "valuation-v0.2.0"


def test_non_matching_model_returns_unavailable_reason() -> None:
    """Verify a non-matching model returns unavailable with a descriptive reason.

    Returns:
        None: .
    """
    registry = IndustryValuationRegistry.default()

    result = registry.value(security_id="000001.SZ", industry_family="bank", inputs={})

    assert result.available is False
    assert "book_value_per_share" in result.unavailable_reasons


def test_registry_has_distinct_models_for_core_industry_families() -> None:
    """Verify the registry has distinct valuation models for core industry families.

    Returns:
        None: .
    """
    registry = IndustryValuationRegistry.default()

    assert registry.model_for("insurance").model_name == "insurance_ev_yield"
    assert registry.model_for("cyclic_resources").model_name == "mid_cycle_earnings"
    assert registry.model_for("consumer").model_name == "normalized_earnings"
    assert registry.model_for("technology").model_name == "growth_fcf_path"
    assert registry.model_for("utilities").model_name == "dividend_regulated_return"


def test_confidence_is_deterministic_and_penalized_by_conflicts() -> None:
    """Verify confidence scoring is deterministic and penalized by evidence conflicts.
    Returns:.

    Returns:
        None: .
    """
    calibrator = ConfidenceCalibrator(version="confidence-v0.2.0")

    result = calibrator.score(
        quant_discount=0.35,
        quality_stability=0.8,
        data_completeness=0.9,
        evidence_consistency=0.4,
        risk_counter_score=0.3,
        valuation_sensitivity=0.6,
    )
    repeated = calibrator.score(
        quant_discount=0.35,
        quality_stability=0.8,
        data_completeness=0.9,
        evidence_consistency=0.4,
        risk_counter_score=0.3,
        valuation_sensitivity=0.6,
    )

    assert result == repeated
    assert 0.0 <= result.confidence <= 1.0
    assert result.calibration_version == "confidence-v0.2.0"
    assert "evidence_conflict_penalty" in result.penalties
    assert result.band in {"low", "medium", "high"}


def test_confidence_does_not_accept_llm_override() -> None:
    """Verify the confidence calibrator does not accept an LLM confidence override.

    Returns:
        None: .
    """
    calibrator = ConfidenceCalibrator(version="confidence-v0.2.0")

    with pytest.raises(TypeError):
        calibrator.score(
            quant_discount=0.35,
            quality_stability=0.8,
            data_completeness=0.9,
            evidence_consistency=0.8,
            risk_counter_score=0.8,
            valuation_sensitivity=0.4,
            llm_confidence=0.99,
        )
