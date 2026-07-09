"""Dashboard publishing worker for v1 Agent flows."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from margin.agent_runtime.context_store import ContextArtifact, make_context_artifact
from margin.agents.protocol.models import AgentExecutionStatus
from margin.dashboard.models import ResearchItem, ResearchRun
from margin.dashboard.repository import DashboardRepository


@dataclass(frozen=True)
class DashboardPublisherAdjustmentResult:
    """Result produced by DashboardPublisherWorker candidate adjustment."""

    status: AgentExecutionStatus
    artifacts: tuple[ContextArtifact, ...]
    adjustments: tuple[dict[str, Any], ...]
    removed_security_ids: tuple[str, ...]
    dashboard_run_id: str | None = None


class DashboardPublisherWorker:
    """Publish post-quant Agent adjustments into ContextStore and Dashboard."""

    name = "DashboardPublisherWorker"
    skill_id = "publish_adjusted_dashboard_projection"

    def __init__(
        self,
        *,
        write_context_artifact: Callable[[ContextArtifact], None],
        dashboard_repository: DashboardRepository | None = None,
    ) -> None:
        """Initialize the dashboard publisher worker."""
        self._write_context_artifact = write_context_artifact
        self._dashboard_repository = dashboard_repository

    def adjust_quant_candidates(
        self,
        *,
        run_id: str,
        candidates: tuple[dict[str, Any], ...],
        max_stock_exposure: float = 0.80,
    ) -> DashboardPublisherAdjustmentResult:
        """Build and persist portfolio-adjustment artifacts for quant candidates."""
        raw_adjustments = tuple(_candidate_adjustment(candidate) for candidate in candidates)
        adjustments = _scale_adjustments_to_exposure(
            raw_adjustments,
            max_stock_exposure=max_stock_exposure,
        )
        removed = tuple(
            str(item["security_id"]) for item in adjustments if item.get("action") == "delete"
        )
        dashboard_run_id = self._publish_dashboard_adjustment_projection(
            run_id=run_id,
            adjustments=adjustments,
        )
        artifact = make_context_artifact(
            artifact_id=f"ctx_{run_id}_portfolio_adjustment",
            run_id=run_id,
            artifact_type="portfolio_adjustment",
            producer_agent=self.name,
            payload_json={
                "max_stock_exposure": max_stock_exposure,
                "min_cash": round(1.0 - max_stock_exposure, 10),
                "removed_security_ids": list(removed),
                "adjustments": list(adjustments),
                "dashboard_projection_update": "portfolio_adjustment_ready",
                "dashboard_run_id": dashboard_run_id,
            },
            source_refs=("analysis_mart_snapshot", "quant_result"),
        )
        projection_event = make_context_artifact(
            artifact_id=f"ctx_{run_id}_dashboard_projection_event",
            run_id=run_id,
            artifact_type="dashboard_projection_event",
            producer_agent=self.name,
            payload_json={
                "dashboard_run_id": dashboard_run_id,
                "visible_item_count": sum(
                    1 for item in adjustments if item.get("action") != "delete"
                ),
                "removed_security_ids": list(removed),
                "adjustment_artifact_id": artifact.artifact_id,
                "projection_status": (
                    "published" if dashboard_run_id is not None else "not_configured"
                ),
            },
            source_refs=(artifact.artifact_id,),
        )
        self._write_context_artifact(artifact)
        self._write_context_artifact(projection_event)
        return DashboardPublisherAdjustmentResult(
            status=AgentExecutionStatus.SUCCEEDED,
            artifacts=(artifact, projection_event),
            adjustments=adjustments,
            removed_security_ids=removed,
            dashboard_run_id=dashboard_run_id,
        )

    def _publish_dashboard_adjustment_projection(
        self,
        *,
        run_id: str,
        adjustments: tuple[dict[str, Any], ...],
    ) -> str | None:
        """Write an adjusted dashboard projection when a repository is configured."""
        if self._dashboard_repository is None or not adjustments:
            return None
        source_items = _source_dashboard_items(
            self._dashboard_repository,
            adjustments,
        )
        if not source_items:
            return None
        source_run = self._dashboard_repository.get_run(source_items[0].run_id)
        if source_run is None:
            return None

        dashboard_run_id = f"dr_agent_{run_id}"
        adjustment_by_security_id = {
            str(adjustment.get("security_id")): adjustment for adjustment in adjustments
        }
        adjusted_items: list[ResearchItem] = []
        for item in source_items:
            adjustment = adjustment_by_security_id.get(item.symbol)
            if adjustment is None or adjustment.get("action") == "delete":
                continue
            adjusted_items.append(
                item.model_copy(
                    update={
                        "item_id": f"{dashboard_run_id}_{item.symbol}",
                        "run_id": dashboard_run_id,
                        "adjusted_weight": _optional_float(adjustment.get("adjusted_weight")),
                        "agent_adjustment": {
                            "source": self.name,
                            "run_id": run_id,
                            "action": str(adjustment.get("action") or "keep"),
                            "target_weight": _optional_float(adjustment.get("target_weight")),
                            "adjusted_weight": _optional_float(adjustment.get("adjusted_weight")),
                            "reasons": list(adjustment.get("reasons", ())),
                            "risk_flags": list(adjustment.get("risk_flags", ())),
                        },
                    }
                )
            )
        adjusted_run = _dashboard_adjusted_run(
            source_run=source_run,
            dashboard_run_id=dashboard_run_id,
            run_id=run_id,
            items=tuple(adjusted_items),
        )
        self._dashboard_repository.add_run(adjusted_run)
        self._dashboard_repository.add_items(adjusted_items)
        return dashboard_run_id


def _candidate_adjustment(candidate: dict[str, Any]) -> dict[str, Any]:
    """Return one deterministic post-quant adjustment row."""
    security_id = str(candidate.get("security_id") or candidate.get("symbol") or "")
    item_id = str(candidate.get("item_id") or "")
    target_weight = _optional_float(candidate.get("target_weight")) or 0.0
    risk_flags = tuple(str(flag) for flag in candidate.get("risk_flags", ()) or ())
    review_required = bool(candidate.get("review_required", False))
    screening_status = str(candidate.get("screening_status") or "")
    delete_reasons: list[str] = []
    if screening_status not in {"pass", "near_threshold", "watchlist"}:
        delete_reasons.append("screening_status_not_researchable")
    if review_required:
        delete_reasons.append("review_required")
    if "short_term_overheat" in risk_flags:
        delete_reasons.append("short_term_overheat")
    if delete_reasons:
        return {
            "item_id": item_id,
            "security_id": security_id,
            "action": "delete",
            "target_weight": target_weight,
            "adjusted_weight": 0.0,
            "reasons": delete_reasons,
            "risk_flags": list(risk_flags),
        }
    return {
        "item_id": item_id,
        "security_id": security_id,
        "action": "keep",
        "target_weight": target_weight,
        "adjusted_weight": target_weight,
        "reasons": [],
        "risk_flags": list(risk_flags),
    }


def _scale_adjustments_to_exposure(
    adjustments: tuple[dict[str, Any], ...],
    *,
    max_stock_exposure: float,
) -> tuple[dict[str, Any], ...]:
    """Scale kept/reduced weights so projected exposure respects the cap."""
    total = sum(
        _optional_float(item.get("adjusted_weight")) or 0.0
        for item in adjustments
        if item.get("action") != "delete"
    )
    if total <= max_stock_exposure or total <= 0.0:
        return adjustments
    scale = max_stock_exposure / total
    scaled: list[dict[str, Any]] = []
    for item in adjustments:
        if item.get("action") == "delete":
            scaled.append(dict(item))
            continue
        adjusted = round((_optional_float(item.get("adjusted_weight")) or 0.0) * scale, 10)
        reasons = list(item.get("reasons", ()))
        reasons.append("exposure_cap_scaling")
        scaled.append(
            {
                **item,
                "action": "reduce_weight",
                "adjusted_weight": adjusted,
                "reasons": reasons,
            }
        )
    return tuple(scaled)


def _optional_float(value: Any) -> float | None:
    """Return a float when conversion is possible."""
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _source_dashboard_items(
    repository: DashboardRepository,
    adjustments: tuple[dict[str, Any], ...],
) -> tuple[ResearchItem, ...]:
    """Load source dashboard items referenced by adjustment rows."""
    item_ids = tuple(
        str(adjustment.get("item_id") or "")
        for adjustment in adjustments
        if adjustment.get("item_id")
    )
    if item_ids:
        items = tuple(
            item for item_id in item_ids if (item := repository.get_item(item_id)) is not None
        )
        if items:
            return items
    source_run_id = next(
        (str(adjustment.get("run_id")) for adjustment in adjustments if adjustment.get("run_id")),
        "",
    )
    if source_run_id:
        items = repository.list_items(source_run_id)
        security_ids = {
            str(adjustment.get("security_id"))
            for adjustment in adjustments
            if adjustment.get("security_id")
        }
        return tuple(item for item in items if item.symbol in security_ids)
    return ()


def _dashboard_adjusted_run(
    *,
    source_run: ResearchRun,
    dashboard_run_id: str,
    run_id: str,
    items: tuple[ResearchItem, ...],
) -> ResearchRun:
    """Build the latest dashboard run representing worker overlay."""
    published_count = sum(1 for item in items if item.status.value == "published")
    return source_run.model_copy(
        update={
            "run_id": dashboard_run_id,
            "strategy_id": f"{source_run.strategy_id}:agent_adjusted",
            "universe": [item.symbol for item in items],
            "summary": f"DashboardPublisherWorker adjusted projection for {run_id}",
            "item_count": len(items),
            "published_count": published_count,
            "abstained_count": len(items) - published_count,
            "aborted_count": 0,
            "created_at": datetime.now(UTC),
        }
    )
