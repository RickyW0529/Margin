"""Detail-context enrichment for dashboard item pages."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy.orm import Session

from margin.dashboard.models import ResearchItem, ResearchRun
from margin.data.warehouse_repository import (
    AdjustedPriceQuery,
    IndicatorHistoryQuery,
    SQLAlchemyWarehouseRepository,
)
from margin.news.db_models import DocumentEventRow
from margin.research.db_models import ResearchDeltaReviewRow
from margin.sql.dashboard_queries import (
    dashboard_document_events,
    dashboard_effective_assessment,
    latest_dashboard_delta_review,
    latest_dashboard_research_context,
)
from margin.valuation_discovery.db_models import (
    ResearchContextSnapshotRow,
    ValuationAssessmentRow,
)

SessionFactory = Callable[[], Session]

TREND_PRICE_DAYS = 180
TREND_INDICATOR_DAYS = 1095
TREND_INDICATORS = ("pe_ttm", "pb", "roe_ttm", "n_income_attr_p")


def make_dashboard_detail_context_loader(
    *,
    session_factory: SessionFactory,
    warehouse_repository: SQLAlchemyWarehouseRepository | None = None,
) -> Callable[[ResearchItem, ResearchRun], dict[str, Any] | None]:
    """Return a loader that enriches one dashboard detail item.

    Args:
        session_factory: SessionFactory: .
        warehouse_repository: SQLAlchemyWarehouseRepository | None: .

    Returns:
        Callable[[ResearchItem, ResearchRun], dict[str, Any] | None]: .
    """

    def loader(item: ResearchItem, run: ResearchRun) -> dict[str, Any] | None:
        """Process loader.

        Args:
            item: ResearchItem: .
            run: ResearchRun: .

        Returns:
            dict[str, Any] | None: .
        """
        context = _load_latest_context(session_factory, item, run)
        if context is None:
            return None
        payload = dict(context["payload_json"] or {})
        review = _load_latest_review(session_factory, context["context_snapshot_id"])
        assessment = _load_effective_assessment(session_factory, item.symbol, run.version_id)
        documents = _load_news_documents(
            session_factory,
            tuple(str(value) for value in payload.get("news_document_ids") or ()),
        )
        trends = _load_trends(
            warehouse_repository,
            security_id=item.symbol,
            decision_at=context["decision_at"],
        )
        return build_dashboard_detail_context(
            security_id=item.symbol,
            context=context,
            payload=payload,
            review=review,
            assessment=assessment,
            documents=documents,
            trends=trends,
        )

    return loader


def build_dashboard_detail_context(
    *,
    security_id: str,
    context: dict[str, Any],
    payload: dict[str, Any],
    review: dict[str, Any] | None,
    assessment: dict[str, Any] | None,
    documents: Iterable[dict[str, Any]],
    trends: list[dict[str, Any]],
) -> dict[str, Any]:
    """Build the dashboard detail context dict consumed by ``DashboardQueryService``.

    Args:
        security_id: str: .
        context: dict[str, Any]: .
        payload: dict[str, Any]: .
        review: dict[str, Any] | None: .
        assessment: dict[str, Any] | None: .
        documents: Iterable[dict[str, Any]]: .
        trends: list[dict[str, Any]]: .

    Returns:
        dict[str, Any]: .
    """
    summary = _dict_value(payload.get("analysis_summary"))
    factor_details = _dict_value(payload.get("quant_factor_details"))
    display_name = _string_value(summary.get("name")) or _string_value(factor_details.get("name"))
    review_dict = _review_context(review, payload)
    assessment_dict = _assessment_context(assessment, payload)
    document_items = tuple(_document_context(document, security_id) for document in documents)
    valuation = _valuation_context(assessment)
    ai_outcome = _string_value(review_dict.get("outcome")) or ""
    deferred_reason = _string_value(review_dict.get("reason"))
    thesis_statement = _string_value(review_dict.get("conclusion"))
    if not thesis_statement and ai_outcome in {
        "abstain",
        "evidence_unavailable",
        "review_deferred",
    }:
        thesis_statement = deferred_reason
    thesis_statement = (
        thesis_statement
        or _string_value(summary.get("reason_summary"))
        or _string_value(payload.get("evidence_quality_status"))
    )
    return {
        "display_name": display_name,
        "current_review": review_dict,
        "effective_assessment": assessment_dict,
        "thesis": {
            "statement": thesis_statement,
            "ai_status": review_dict.get("outcome"),
            "news_target_complete": payload.get("news_target_complete"),
            "evidence_quality_status": payload.get("evidence_quality_status"),
        },
        "evidence": document_items,
        "factors": {
            "valuation": valuation,
            "trends": trends,
            "raw_metrics": _raw_metric_cards(factor_details),
        },
        "versions": {
            "context_snapshot_id": context.get("context_snapshot_id", ""),
            "news_context_bundle_id": payload.get("news_context_bundle_id") or "",
            "evidence_package_id": payload.get("evidence_package_id") or "",
            "analysis_snapshot_id": payload.get("analysis_snapshot_id") or "",
        },
    }


def _load_latest_context(
    session_factory: SessionFactory,
    item: ResearchItem,
    run: ResearchRun,
) -> dict[str, Any] | None:
    """Load the latest research context snapshot for the dashboard item.

    Args:
        session_factory: SessionFactory: .
        item: ResearchItem: .
        run: ResearchRun: .

    Returns:
        dict[str, Any] | None: .
    """
    with session_factory() as session:
        row = session.scalar(
            latest_dashboard_research_context(
                security_id=item.symbol,
                scope_version_id=run.version_id,
                quant_run_id=item.workflow_run_id,
            )
        )
    if row is None:
        return None
    return _research_context_row(row)


def _load_latest_review(
    session_factory: SessionFactory,
    context_snapshot_id: str,
) -> dict[str, Any] | None:
    """Load the latest AI review for one context snapshot.

    Args:
        session_factory: SessionFactory: .
        context_snapshot_id: str: .

    Returns:
        dict[str, Any] | None: .
    """
    with session_factory() as session:
        row = session.scalar(latest_dashboard_delta_review(context_snapshot_id))
    if row is None:
        return None
    return _delta_review_row(row)


def _load_effective_assessment(
    session_factory: SessionFactory,
    security_id: str,
    scope_version_id: str,
) -> dict[str, Any] | None:
    """Load the current effective assessment, if one exists.

    Args:
        session_factory: SessionFactory: .
        security_id: str: .
        scope_version_id: str: .

    Returns:
        dict[str, Any] | None: .
    """
    with session_factory() as session:
        row = session.scalar(
            dashboard_effective_assessment(
                security_id=security_id,
                scope_version_id=scope_version_id,
            )
        )
    if row is None:
        return None
    return _assessment_row(row)


def _load_news_documents(
    session_factory: SessionFactory,
    event_ids: tuple[str, ...],
) -> list[dict[str, Any]]:
    """Load document events referenced by a research context.

    Args:
        session_factory: SessionFactory: .
        event_ids: tuple[str, ...]: .

    Returns:
        list[dict[str, Any]]: .
    """
    if not event_ids:
        return []
    with session_factory() as session:
        rows = session.scalars(dashboard_document_events(event_ids)).all()
    return [_document_row(row) for row in rows]


def _research_context_row(row: ResearchContextSnapshotRow) -> dict[str, Any]:
    """Convert a research-context ORM row into the detail context shape.

    Args:
        row: ResearchContextSnapshotRow: .

    Returns:
        dict[str, Any]: .
    """
    return {
        "context_snapshot_id": row.context_snapshot_id,
        "security_id": row.security_id,
        "scope_version_id": row.scope_version_id,
        "decision_at": row.decision_at,
        "payload_json": row.payload_json,
        "created_at": row.created_at,
    }


def _delta_review_row(row: ResearchDeltaReviewRow) -> dict[str, Any]:
    """Convert a delta-review ORM row into the detail context shape.

    Args:
        row: ResearchDeltaReviewRow: .

    Returns:
        dict[str, Any]: .
    """
    return {
        "review_id": row.review_id,
        "graph_run_id": row.graph_run_id,
        "context_snapshot_id": row.context_snapshot_id,
        "outcome": row.outcome,
        "effective_assessment_id": row.effective_assessment_id,
        "assessment_freshness": row.assessment_freshness,
        "stale_reason": row.stale_reason,
        "confidence": row.confidence,
        "conclusion": row.conclusion,
        "evidence_ids": row.evidence_ids,
        "created_at": row.created_at,
    }


def _assessment_row(row: ValuationAssessmentRow) -> dict[str, Any]:
    """Convert an assessment ORM row into the detail context shape.

    Args:
        row: ValuationAssessmentRow: .

    Returns:
        dict[str, Any]: .
    """
    return {
        "assessment_id": row.assessment_id,
        "security_id": row.security_id,
        "scope_version_id": row.scope_version_id,
        "intrinsic_value": row.intrinsic_value,
        "margin_of_safety": row.margin_of_safety,
        "conclusion": row.conclusion,
        "evidence_refs": row.evidence_refs,
        "created_at": row.created_at,
    }


def _document_row(row: DocumentEventRow) -> dict[str, Any]:
    """Convert a document event row into the detail context shape.

    Args:
        row: DocumentEventRow: .

    Returns:
        dict[str, Any]: .
    """
    return {
        "event_id": row.event_id,
        "title": row.title,
        "source_name": row.source_name,
        "source_url": row.source_url,
        "source_level": row.source_level,
        "doc_type": row.doc_type,
        "symbols": row.symbols,
        "snapshot_id": row.snapshot_id,
        "published_at": row.published_at,
        "snippet": (row.content or "")[:320],
    }


def _load_trends(
    warehouse_repository: SQLAlchemyWarehouseRepository | None,
    *,
    security_id: str,
    decision_at: datetime,
) -> list[dict[str, Any]]:
    """Load PIT-safe market and indicator trends.

    Args:
        warehouse_repository: SQLAlchemyWarehouseRepository | None: .
        security_id: str: .
        decision_at: datetime: .

    Returns:
        list[dict[str, Any]]: .
    """
    if warehouse_repository is None:
        return []
    decision = _ensure_utc(decision_at)
    trends: list[dict[str, Any]] = []
    try:
        prices = warehouse_repository.adjusted_prices(
            AdjustedPriceQuery(
                security_ids=(security_id,),
                start_date=(decision - timedelta(days=TREND_PRICE_DAYS)).date(),
                end_date=decision.date(),
                decision_at=decision,
            )
        )
    except Exception:
        prices = []
    price_points = [
        {"date": item.trade_date.isoformat(), "value": float(item.adj_close)}
        for item in sorted(prices, key=lambda value: value.trade_date)
    ]
    if price_points:
        trends.append(
            {
                "metric": "adj_close",
                "label": "复权收盘价",
                "unit": "CNY",
                "points": _downsample_points(price_points, 80),
            }
        )
    try:
        history = warehouse_repository.indicator_history(
            IndicatorHistoryQuery(
                security_ids=(security_id,),
                indicator_ids=TREND_INDICATORS,
                start_date=(decision - timedelta(days=TREND_INDICATOR_DAYS)).date(),
                end_date=decision.date(),
                decision_at=decision,
                max_points_per_indicator=16,
            )
        )
    except Exception:
        history = []
    labels = {
        "pe_ttm": ("PE TTM", "x"),
        "pb": ("PB", "x"),
        "roe_ttm": ("ROE TTM", "%"),
        "n_income_attr_p": ("归母净利", "CNY"),
    }
    for indicator_id in TREND_INDICATORS:
        values = [item for item in history if item.indicator_id == indicator_id]
        if not values:
            continue
        label, unit = labels[indicator_id]
        trends.append(
            {
                "metric": indicator_id,
                "label": label,
                "unit": unit,
                "points": [
                    {
                        "date": item.event_at.date().isoformat(),
                        "value": float(item.numeric_value),
                    }
                    for item in sorted(values, key=lambda value: value.event_at)
                ],
            }
        )
    return trends


def _review_context(
    review: dict[str, Any] | None,
    payload: dict[str, Any],
) -> dict[str, Any]:
    """Build current-review context with explicit empty-evidence state.

    Args:
        review: dict[str, Any] | None: .
        payload: dict[str, Any]: .

    Returns:
        dict[str, Any]: .
    """
    if review is None:
        evidence_ids = payload.get("evidence_ids") or ()
        return {
            "outcome": "pending" if evidence_ids else "evidence_unavailable",
            "reason": (
                "AI 复核尚未完成。" if evidence_ids else "证据包为空，AI 复核不能形成可引用结论。"
            ),
            "conclusion": "",
            "confidence": None,
        }
    outcome = _string_value(review.get("outcome")) or "unknown"
    conclusion = _string_value(review.get("conclusion")) or ""
    reason = _review_reason(_string_value(review.get("stale_reason")))
    if not conclusion and outcome in {"review_deferred", "abstain"}:
        reason = reason or "证据包为空，AI 未形成可引用结论。"
    return {
        "outcome": outcome,
        "reason": reason,
        "run_id": review.get("graph_run_id"),
        "review_id": review.get("review_id"),
        "effective_assessment_id": review.get("effective_assessment_id"),
        "freshness": review.get("assessment_freshness"),
        "confidence": review.get("confidence"),
        "conclusion": conclusion,
        "evidence_ids": tuple(review.get("evidence_ids") or ()),
    }


def _review_reason(reason_code: str | None) -> str | None:
    """Return a user-facing reason for deferred AI reviews.

    Args:
        reason_code: str | None: .

    Returns:
        str | None: .
    """
    labels = {
        "empty_evidence_package": "证据包为空，AI 未形成可引用结论。",
        "news_target_incomplete": "News target 未完成，AI 复核延期。",
        "no_effective_assessment": "尚无当前有效估值结论。",
    }
    return labels.get(reason_code or "", reason_code)


def _assessment_context(
    assessment: dict[str, Any] | None,
    payload: dict[str, Any],
) -> dict[str, Any]:
    """Build effective-assessment context.

    Args:
        assessment: dict[str, Any] | None: .
        payload: dict[str, Any]: .

    Returns:
        dict[str, Any]: .
    """
    if assessment is None:
        return {
            "assessment_id": None,
            "freshness": "missing",
            "stale_reason": "empty_evidence_package"
            if not payload.get("evidence_ids")
            else "no_effective_assessment",
        }
    return {
        "assessment_id": assessment.get("assessment_id"),
        "freshness": "current",
        "stale_reason": None,
        "conclusion": assessment.get("conclusion"),
    }


def _valuation_context(assessment: dict[str, Any] | None) -> dict[str, Any]:
    """Build valuation card data without fabricating missing valuation.

    Args:
        assessment: dict[str, Any] | None: .

    Returns:
        dict[str, Any]: .
    """
    if assessment is None:
        return {
            "discount_rate": None,
            "intrinsic_value": None,
            "margin_of_safety": None,
            "status": "missing_assessment",
            "message": "AI 估值未形成：没有可引用证据支持 valuation assessment。",
        }
    margin = _optional_float(assessment.get("margin_of_safety"))
    return {
        "discount_rate": margin,
        "intrinsic_value": _optional_float(assessment.get("intrinsic_value")),
        "margin_of_safety": margin,
        "status": "available",
        "message": assessment.get("conclusion") or "",
    }


def _document_context(document: dict[str, Any], security_id: str) -> dict[str, Any]:
    """Map one document event into an evidence-like dashboard row.

    Args:
        document: dict[str, Any]: .
        security_id: str: .

    Returns:
        dict[str, Any]: .
    """
    snippet = _string_value(document.get("snippet")) or ""
    title = _string_value(document.get("title")) or document.get("event_id") or "新闻文档"
    symbols = tuple(document.get("symbols") or ())
    code = security_id.split(".")[0]
    linked = security_id in symbols or code in symbols or code in snippet or code in str(title)
    return {
        "evidence_id": document.get("event_id"),
        "title": title,
        "source_level": f"L{document.get('source_level')}",
        "locator": "news_document",
        "snapshot_id": document.get("snapshot_id"),
        "source_url": document.get("source_url"),
        "pit_timestamp": _iso_or_none(document.get("published_at")),
        "source_name": document.get("source_name"),
        "snippet": snippet,
        "linked_to_security": linked,
    }


def _raw_metric_cards(factor_details: dict[str, Any]) -> list[dict[str, Any]]:
    """Return compact raw metrics for the detail page.

    Args:
        factor_details: dict[str, Any]: .

    Returns:
        list[dict[str, Any]]: .
    """
    raw = _dict_value(_dict_value(factor_details.get("ai_quant_profile")).get("raw_factors"))
    labels = {
        "pe_ttm": ("PE TTM", "x"),
        "pb": ("PB", "x"),
        "dividend_yield": ("股息率", "%"),
        "return_20d": ("20日收益", "%"),
        "return_6m_ex_1m": ("6M-1M收益", "%"),
        "volatility_120d": ("120日波动", "%"),
        "max_drawdown_250d": ("250日回撤", "%"),
    }
    cards: list[dict[str, Any]] = []
    for key, (label, unit) in labels.items():
        value = _optional_float(raw.get(key))
        if value is None:
            continue
        display_value = value * 100 if unit == "%" else value
        cards.append(
            {
                "metric": key,
                "label": label,
                "value": display_value,
                "unit": unit,
            }
        )
    return cards


def _downsample_points(
    points: list[dict[str, Any]],
    max_points: int,
) -> list[dict[str, Any]]:
    """Downsample points while keeping first and last observations.

    Args:
        points: list[dict[str, Any]]: .
        max_points: int: .

    Returns:
        list[dict[str, Any]]: .
    """
    if len(points) <= max_points:
        return points
    step = max(1, len(points) // max_points)
    sampled = points[::step]
    if sampled[-1] != points[-1]:
        sampled.append(points[-1])
    return sampled


def _dict_value(value: Any) -> dict[str, Any]:
    """Return a dict or empty dict.

    Args:
        value: Any: .

    Returns:
        dict[str, Any]: .
    """
    return dict(value) if isinstance(value, dict) else {}


def _string_value(value: Any) -> str | None:
    """Return stripped non-empty strings.

    Args:
        value: Any: .

    Returns:
        str | None: .
    """
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def _optional_float(value: Any) -> float | None:
    """Convert Decimal/numeric values to float.

    Args:
        value: Any: .

    Returns:
        float | None: .
    """
    if value is None:
        return None
    if isinstance(value, Decimal):
        return float(value)
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _iso_or_none(value: Any) -> str | None:
    """Return ISO datetime text when available.

    Args:
        value: Any: .

    Returns:
        str | None: .
    """
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return None


def _ensure_utc(value: datetime) -> datetime:
    """Normalize a datetime to UTC.

    Args:
        value: datetime: .

    Returns:
        datetime: .
    """
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)
