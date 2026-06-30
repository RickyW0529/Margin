"""Scoped read tools for fourth-layer Analysis Mart snapshots."""

from __future__ import annotations

from dataclasses import asdict
from datetime import datetime
from typing import Any

from pydantic import BaseModel

from margin.research.tools.definitions import (
    ToolCapability,
    ToolDefinition,
    ToolDefinitionRegistry,
)
from margin.valuation_discovery.analysis_mart import AnalysisMartRepository


class AnalysisSnapshotQuery(BaseModel):
    """Lookup the latest Analysis Mart snapshot for one security and scope."""

    security_id: str
    scope_version_id: str
    decision_at: datetime


class AnalysisRowsQuery(BaseModel):
    """Read child rows from one Analysis Mart snapshot."""

    security_id: str
    decision_at: datetime
    analysis_snapshot_id: str


class QuantFeatureSnapshotQuery(BaseModel):
    """Lookup the latest fourth-layer quant feature snapshot for one scope."""

    scope_version_id: str
    decision_at: datetime


class QuantFeatureRowsQuery(BaseModel):
    """Read current-security feature rows from one quant feature snapshot."""

    security_id: str
    decision_at: datetime
    feature_snapshot_id: str


def register_analysis_mart_tools(
    registry: ToolDefinitionRegistry,
    *,
    repository: AnalysisMartRepository,
) -> None:
    """Register read-only Analysis Mart tools in a tool registry.

    Args:
        registry: Tool definition registry to populate.
        repository: Analysis Mart repository used by tool handlers.
    """
    registry.register(
        ToolDefinition(
            name="analysis_snapshot_get",
            capability=ToolCapability.QUANT_READ,
            version="analysis-snapshot-get-v0.3.0",
            description="Read the latest fourth-layer analysis snapshot for this security.",
            input_model=AnalysisSnapshotQuery,
            handler=lambda payload: _get_snapshot(repository, payload),
            estimated_result_bytes=16_384,
        )
    )
    registry.register(
        ToolDefinition(
            name="analysis_metrics_list",
            capability=ToolCapability.QUANT_READ,
            version="analysis-metrics-list-v0.3.0",
            description="List structured metrics for one Analysis Mart snapshot.",
            input_model=AnalysisRowsQuery,
            handler=lambda payload: _list_metrics(repository, payload),
            estimated_result_bytes=32_768,
        )
    )
    registry.register(
        ToolDefinition(
            name="quant_feature_snapshot_get",
            capability=ToolCapability.QUANT_READ,
            version="quant-feature-snapshot-get-v0.3.0",
            description=(
                "Read metadata for the latest fourth-layer quant feature snapshot."
            ),
            input_model=QuantFeatureSnapshotQuery,
            handler=lambda payload: _get_feature_snapshot(repository, payload),
            estimated_result_bytes=16_384,
        )
    )
    registry.register(
        ToolDefinition(
            name="quant_feature_rows_list",
            capability=ToolCapability.QUANT_READ,
            version="quant-feature-rows-list-v0.3.0",
            description=(
                "List fourth-layer quant features for the scoped security only."
            ),
            input_model=QuantFeatureRowsQuery,
            handler=lambda payload: _list_feature_rows(repository, payload),
            estimated_result_bytes=32_768,
        )
    )
    registry.register(
        ToolDefinition(
            name="analysis_findings_list",
            capability=ToolCapability.QUANT_READ,
            version="analysis-findings-list-v0.3.0",
            description="List structured findings for one Analysis Mart snapshot.",
            input_model=AnalysisRowsQuery,
            handler=lambda payload: _list_findings(repository, payload),
            estimated_result_bytes=32_768,
        )
    )


def _get_snapshot(
    repository: AnalysisMartRepository,
    payload: dict[str, Any],
) -> dict[str, Any]:
    """Return the latest analysis snapshot for one security and scope."""
    snapshot = repository.latest_snapshot(
        security_id=str(payload["security_id"]),
        scope_version_id=str(payload["scope_version_id"]),
        as_of=payload["decision_at"],
    )
    return {"snapshot": _serialize(snapshot) if snapshot is not None else None}


def _list_metrics(
    repository: AnalysisMartRepository,
    payload: dict[str, Any],
) -> dict[str, Any]:
    """List structured metrics for one authorized analysis snapshot."""
    snapshot = _authorized_snapshot(repository, payload)
    if snapshot is None:
        return {"metrics": []}
    return {
        "analysis_snapshot_id": snapshot.analysis_snapshot_id,
        "metrics": [
            _serialize(metric)
            for metric in repository.list_metrics(snapshot.analysis_snapshot_id)
        ],
    }


def _list_findings(
    repository: AnalysisMartRepository,
    payload: dict[str, Any],
) -> dict[str, Any]:
    """List structured findings for one authorized analysis snapshot."""
    snapshot = _authorized_snapshot(repository, payload)
    if snapshot is None:
        return {"findings": []}
    return {
        "analysis_snapshot_id": snapshot.analysis_snapshot_id,
        "findings": [
            _serialize(finding)
            for finding in repository.list_findings(snapshot.analysis_snapshot_id)
        ],
    }


def _get_feature_snapshot(
    repository: AnalysisMartRepository,
    payload: dict[str, Any],
) -> dict[str, Any]:
    """Return the latest quant feature snapshot metadata for one scope."""
    snapshot = repository.latest_feature_snapshot(
        scope_version_id=str(payload["scope_version_id"]),
        as_of=payload["decision_at"],
    )
    return {
        "feature_snapshot": _serialize(snapshot) if snapshot is not None else None
    }


def _list_feature_rows(
    repository: AnalysisMartRepository,
    payload: dict[str, Any],
) -> dict[str, Any]:
    """List quant feature rows for the scoped security within one snapshot."""
    snapshot = repository.get_feature_snapshot(str(payload["feature_snapshot_id"]))
    if snapshot is None or snapshot.decision_at > payload["decision_at"]:
        return {"feature_rows": []}
    security_id = str(payload["security_id"])
    return {
        "feature_snapshot_id": snapshot.feature_snapshot_id,
        "feature_rows": [
            _serialize(row)
            for row in repository.list_feature_rows(snapshot.feature_snapshot_id)
            if row.security_id == security_id
        ],
    }


def _authorized_snapshot(
    repository: AnalysisMartRepository,
    payload: dict[str, Any],
):
    """Return the snapshot only if it matches the scoped security and decision time."""
    snapshot = repository.get_snapshot(str(payload["analysis_snapshot_id"]))
    if snapshot is None:
        return None
    if snapshot.security_id != payload["security_id"]:
        return None
    if snapshot.decision_at > payload["decision_at"]:
        return None
    return snapshot


def _serialize(value) -> dict[str, Any]:
    """Convert a dataclass value to a JSON-safe dict with tuple-to-list coercion."""
    data = asdict(value)
    for key, item in list(data.items()):
        if isinstance(item, tuple):
            data[key] = list(item)
    return data
