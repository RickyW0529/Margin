"""Research scope binding for valuation discovery."""

from __future__ import annotations

from typing import Any

from pydantic import Field

from margin.valuation_discovery.models import FrozenModel, UniverseSnapshot


class QuantFeatureSet(FrozenModel):
    """Quant feature requirements frozen by a strategy/scope version."""

    version_id: str
    required_indicators: tuple[str, ...]
    optional_indicators: tuple[str, ...] = ()
    history_days: int | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class UserIndicatorView(FrozenModel):
    """User-facing indicator visibility settings.

    This view affects dashboard/AI presentation but must not remove indicators
    required by quant feature computation.
    """

    version_id: str
    visible_indicator_ids: tuple[str, ...]
    hidden_indicator_ids: tuple[str, ...] = ()
    metadata: dict[str, Any] = Field(default_factory=dict)


class ScopeBinding(FrozenModel):
    """Frozen scope inputs required to build a QuantInputSnapshot."""

    scope_version_id: str
    universe_snapshot: UniverseSnapshot
    quant_feature_set: QuantFeatureSet
    user_indicator_view: UserIndicatorView
    corporate_action_adjustment_version: str
    industry_snapshot_id: str
    metadata: dict[str, Any] = Field(default_factory=dict)
