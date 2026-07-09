"""Deterministic confidence calibration for valuation discovery."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ConfidenceResult:
    """Calibrated confidence output.."""

    confidence: float
    band: str
    drivers: dict[str, float]
    penalties: dict[str, float]
    calibration_version: str


class ConfidenceCalibrator:
    """Deterministic confidence scorer.."""

    def __init__(self, *, version: str = "confidence-v0.2.0") -> None:
        """Initialize the calibrator with a calibration version label.

        Args:
            version: str: .

        Returns:
            None: .
        """
        self._version = version

    def score(
        self,
        *,
        quant_discount: float,
        quality_stability: float,
        data_completeness: float,
        evidence_consistency: float,
        risk_counter_score: float,
        valuation_sensitivity: float,
    ) -> ConfidenceResult:
        """Return deterministic confidence, band, drivers, and penalties.

        Args:
            quant_discount: float: .
            quality_stability: float: .
            data_completeness: float: .
            evidence_consistency: float: .
            risk_counter_score: float: .
            valuation_sensitivity: float: .

        Returns:
            ConfidenceResult: .
        """
        drivers = {
            "quant_discount": _clamp(quant_discount),
            "quality_stability": _clamp(quality_stability),
            "data_completeness": _clamp(data_completeness),
            "evidence_consistency": _clamp(evidence_consistency),
            "risk_counter_score": _clamp(risk_counter_score),
            "valuation_sensitivity_inverse": 1.0 - _clamp(valuation_sensitivity),
        }
        base = (
            0.25 * drivers["quant_discount"]
            + 0.20 * drivers["quality_stability"]
            + 0.20 * drivers["data_completeness"]
            + 0.15 * drivers["evidence_consistency"]
            + 0.10 * drivers["risk_counter_score"]
            + 0.10 * drivers["valuation_sensitivity_inverse"]
        )
        penalties = _penalties(
            data_completeness=drivers["data_completeness"],
            evidence_consistency=drivers["evidence_consistency"],
            risk_counter_score=drivers["risk_counter_score"],
            valuation_sensitivity=1.0 - drivers["valuation_sensitivity_inverse"],
        )
        confidence = _clamp(base - sum(penalties.values()))
        return ConfidenceResult(
            confidence=confidence,
            band=_band(confidence),
            drivers=drivers,
            penalties=penalties,
            calibration_version=self._version,
        )


def _penalties(
    *,
    data_completeness: float,
    evidence_consistency: float,
    risk_counter_score: float,
    valuation_sensitivity: float,
) -> dict[str, float]:
    """Compute deterministic penalty deductions from weak driver values.

    Args:
        data_completeness: float: .
        evidence_consistency: float: .
        risk_counter_score: float: .
        valuation_sensitivity: float: .

    Returns:
        dict[str, float]: .
    """
    penalties: dict[str, float] = {}
    if evidence_consistency < 0.60:
        penalties["evidence_conflict_penalty"] = (0.60 - evidence_consistency) * 0.20
    if risk_counter_score < 0.50:
        penalties["risk_counter_penalty"] = (0.50 - risk_counter_score) * 0.15
    if data_completeness < 0.70:
        penalties["data_gap_penalty"] = (0.70 - data_completeness) * 0.20
    if valuation_sensitivity > 0.70:
        penalties["valuation_sensitivity_penalty"] = (valuation_sensitivity - 0.70) * 0.10
    return penalties


def _band(confidence: float) -> str:
    """Map a 0-1 confidence value to a high/medium/low band.

    Args:
        confidence: float: .

    Returns:
        str: .
    """
    if confidence >= 0.75:
        return "high"
    if confidence >= 0.45:
        return "medium"
    return "low"


def _clamp(value: float) -> float:
    """Clamp a value to the 0-1 range.

    Args:
        value: float: .

    Returns:
        float: .
    """
    return min(1.0, max(0.0, float(value)))
