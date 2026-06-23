"""Industry-specific valuation model registry."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

MODEL_VERSION = "valuation-v0.2.0"


@dataclass(frozen=True)
class ValuationModelResult:
    """Deterministic valuation model output."""

    security_id: str
    industry_family: str
    model_name: str
    model_version: str
    available: bool
    value_range: tuple[float, float] = (0.0, 0.0)
    key_assumptions: dict[str, float] | None = None
    sensitivity: dict[str, float] | None = None
    data_requirements: tuple[str, ...] = ()
    unavailable_reasons: tuple[str, ...] = ()


@dataclass(frozen=True)
class IndustryValuationModel:
    """Valuation model metadata and callable implementation."""

    model_name: str
    required_inputs: tuple[str, ...]
    evaluator: Callable[[str, str, dict[str, Any]], ValuationModelResult]

    def value(
        self,
        *,
        security_id: str,
        industry_family: str,
        inputs: dict[str, Any],
    ) -> ValuationModelResult:
        """Evaluate this model or return unavailable reasons."""
        missing = tuple(
            field
            for field in self.required_inputs
            if inputs.get(field) is None
        )
        if missing:
            return ValuationModelResult(
                security_id=security_id,
                industry_family=industry_family,
                model_name=self.model_name,
                model_version=MODEL_VERSION,
                available=False,
                data_requirements=self.required_inputs,
                unavailable_reasons=missing,
            )
        return self.evaluator(security_id, industry_family, inputs)


class IndustryValuationRegistry:
    """Registry mapping industry families to appropriate valuation models."""

    def __init__(self, models: dict[str, IndustryValuationModel]) -> None:
        """init  ."""
        self._models = models

    @classmethod
    def default(cls) -> IndustryValuationRegistry:
        """Return the v0.2 default industry valuation registry."""
        bank = IndustryValuationModel(
            model_name="bank_pb_roe",
            required_inputs=(
                "book_value_per_share",
                "roe_ttm",
                "pb_floor",
                "pb_ceiling",
            ),
            evaluator=_bank_pb_roe,
        )
        insurance = IndustryValuationModel(
            model_name="insurance_ev_yield",
            required_inputs=("embedded_value_per_share", "investment_yield"),
            evaluator=_insurance_ev_yield,
        )
        cyclic = IndustryValuationModel(
            model_name="mid_cycle_earnings",
            required_inputs=("mid_cycle_eps", "pe_floor", "pe_ceiling"),
            evaluator=_mid_cycle_earnings,
        )
        normalized = IndustryValuationModel(
            model_name="normalized_earnings",
            required_inputs=("normalized_eps", "pe_floor", "pe_ceiling"),
            evaluator=_normalized_earnings,
        )
        growth = IndustryValuationModel(
            model_name="growth_fcf_path",
            required_inputs=("fcf_per_share_forward", "fcf_multiple_floor", "fcf_multiple_ceiling"),
            evaluator=_growth_fcf_path,
        )
        utilities = IndustryValuationModel(
            model_name="dividend_regulated_return",
            required_inputs=(
                "dividend_per_share",
                "dividend_yield_floor",
                "dividend_yield_ceiling",
            ),
            evaluator=_dividend_regulated_return,
        )
        return cls(
            {
                "bank": bank,
                "banks": bank,
                "insurance": insurance,
                "cyclic_resources": cyclic,
                "resources": cyclic,
                "materials": cyclic,
                "consumer": normalized,
                "manufacturing": normalized,
                "technology": growth,
                "growth": growth,
                "utilities": utilities,
                "high_dividend": utilities,
            }
        )

    def model_for(self, industry_family: str) -> IndustryValuationModel:
        """Return the model configured for an industry family."""
        normalized = industry_family.strip().lower()
        if normalized not in self._models:
            return self._models["consumer"]
        return self._models[normalized]

    def value(
        self,
        *,
        security_id: str,
        industry_family: str,
        inputs: dict[str, Any],
    ) -> ValuationModelResult:
        """Evaluate the configured model for a security."""
        model = self.model_for(industry_family)
        return model.value(
            security_id=security_id,
            industry_family=industry_family,
            inputs=inputs,
        )


def _bank_pb_roe(
    security_id: str,
    industry_family: str,
    inputs: dict[str, Any],
) -> ValuationModelResult:
    """bank pb roe."""
    book_value = _float(inputs["book_value_per_share"])
    roe = _float(inputs["roe_ttm"])
    pb_floor = _float(inputs["pb_floor"])
    pb_ceiling = _float(inputs["pb_ceiling"])
    return ValuationModelResult(
        security_id=security_id,
        industry_family=industry_family,
        model_name="bank_pb_roe",
        model_version=MODEL_VERSION,
        available=True,
        value_range=(book_value * pb_floor, book_value * pb_ceiling),
        key_assumptions={
            "book_value_per_share": book_value,
            "roe_ttm": roe,
            "pb_floor": pb_floor,
            "pb_ceiling": pb_ceiling,
        },
        sensitivity={"roe_ttm": roe, "pb_spread": pb_ceiling - pb_floor},
        data_requirements=("book_value_per_share", "roe_ttm", "pb_floor", "pb_ceiling"),
    )


def _insurance_ev_yield(
    security_id: str,
    industry_family: str,
    inputs: dict[str, Any],
) -> ValuationModelResult:
    """insurance ev yield."""
    embedded_value = _float(inputs["embedded_value_per_share"])
    investment_yield = _float(inputs["investment_yield"])
    multiple_floor = _float(inputs.get("ev_multiple_floor", 0.75))
    multiple_ceiling = _float(inputs.get("ev_multiple_ceiling", 1.15))
    return _available_result(
        security_id,
        industry_family,
        "insurance_ev_yield",
        (embedded_value * multiple_floor, embedded_value * multiple_ceiling),
        {"embedded_value_per_share": embedded_value, "investment_yield": investment_yield},
        {
            "investment_yield": investment_yield,
            "ev_multiple_spread": multiple_ceiling - multiple_floor,
        },
        ("embedded_value_per_share", "investment_yield"),
    )


def _mid_cycle_earnings(
    security_id: str,
    industry_family: str,
    inputs: dict[str, Any],
) -> ValuationModelResult:
    """mid cycle earnings."""
    eps = _float(inputs["mid_cycle_eps"])
    pe_floor = _float(inputs["pe_floor"])
    pe_ceiling = _float(inputs["pe_ceiling"])
    commodity_sensitivity = _float(inputs.get("commodity_sensitivity", 0.5))
    return _available_result(
        security_id,
        industry_family,
        "mid_cycle_earnings",
        (eps * pe_floor, eps * pe_ceiling),
        {"mid_cycle_eps": eps, "pe_floor": pe_floor, "pe_ceiling": pe_ceiling},
        {"commodity_sensitivity": commodity_sensitivity, "pe_spread": pe_ceiling - pe_floor},
        ("mid_cycle_eps", "pe_floor", "pe_ceiling"),
    )


def _normalized_earnings(
    security_id: str,
    industry_family: str,
    inputs: dict[str, Any],
) -> ValuationModelResult:
    """normalized earnings."""
    eps = _float(inputs["normalized_eps"])
    pe_floor = _float(inputs["pe_floor"])
    pe_ceiling = _float(inputs["pe_ceiling"])
    margin_stability = _float(inputs.get("margin_stability", 0.5))
    return _available_result(
        security_id,
        industry_family,
        "normalized_earnings",
        (eps * pe_floor, eps * pe_ceiling),
        {"normalized_eps": eps, "pe_floor": pe_floor, "pe_ceiling": pe_ceiling},
        {"margin_stability": margin_stability, "pe_spread": pe_ceiling - pe_floor},
        ("normalized_eps", "pe_floor", "pe_ceiling"),
    )


def _growth_fcf_path(
    security_id: str,
    industry_family: str,
    inputs: dict[str, Any],
) -> ValuationModelResult:
    """growth fcf path."""
    fcf = _float(inputs["fcf_per_share_forward"])
    multiple_floor = _float(inputs["fcf_multiple_floor"])
    multiple_ceiling = _float(inputs["fcf_multiple_ceiling"])
    dilution_rate = _float(inputs.get("dilution_rate", 0.0))
    dilution_adjustment = max(0.0, 1.0 - dilution_rate)
    return _available_result(
        security_id,
        industry_family,
        "growth_fcf_path",
        (fcf * multiple_floor * dilution_adjustment, fcf * multiple_ceiling * dilution_adjustment),
        {
            "fcf_per_share_forward": fcf,
            "fcf_multiple_floor": multiple_floor,
            "fcf_multiple_ceiling": multiple_ceiling,
        },
        {"dilution_rate": dilution_rate, "multiple_spread": multiple_ceiling - multiple_floor},
        ("fcf_per_share_forward", "fcf_multiple_floor", "fcf_multiple_ceiling"),
    )


def _dividend_regulated_return(
    security_id: str,
    industry_family: str,
    inputs: dict[str, Any],
) -> ValuationModelResult:
    """dividend regulated return."""
    dividend = _float(inputs["dividend_per_share"])
    yield_floor = _float(inputs["dividend_yield_floor"])
    yield_ceiling = _float(inputs["dividend_yield_ceiling"])
    regulated_return = _float(inputs.get("regulated_asset_return", 0.0))
    low = dividend / yield_ceiling
    high = dividend / yield_floor
    return _available_result(
        security_id,
        industry_family,
        "dividend_regulated_return",
        (low, high),
        {
            "dividend_per_share": dividend,
            "dividend_yield_floor": yield_floor,
            "dividend_yield_ceiling": yield_ceiling,
        },
        {"regulated_asset_return": regulated_return, "yield_spread": yield_ceiling - yield_floor},
        ("dividend_per_share", "dividend_yield_floor", "dividend_yield_ceiling"),
    )


def _available_result(
    security_id: str,
    industry_family: str,
    model_name: str,
    value_range: tuple[float, float],
    key_assumptions: dict[str, float],
    sensitivity: dict[str, float],
    data_requirements: tuple[str, ...],
) -> ValuationModelResult:
    """available result."""
    low, high = sorted(value_range)
    return ValuationModelResult(
        security_id=security_id,
        industry_family=industry_family,
        model_name=model_name,
        model_version=MODEL_VERSION,
        available=True,
        value_range=(low, high),
        key_assumptions=key_assumptions,
        sensitivity=sensitivity,
        data_requirements=data_requirements,
    )


def _float(value: Any) -> float:
    """float."""
    return float(value)
