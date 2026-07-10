"""Canonical document, warehouse-fact, and quant-result evidence details."""

from __future__ import annotations

import json
from collections.abc import Callable
from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from typing import Any, Protocol

from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from margin.data.db_models import StandardizedIndicatorFactRow
from margin.data.facts import StandardizedIndicatorFact
from margin.evidence.models import Evidence
from margin.news.models import DocumentEvent, SourceLevel
from margin.valuation_discovery.db_models import (
    QuantFactorValueRow,
    QuantInputSnapshotFactRow,
    QuantInputSnapshotRow,
    QuantScreenResultRow,
    QuantScreenRunRow,
)
from margin.valuation_discovery.models import (
    DataStatus,
    QuantResult,
    QuantRun,
    ResearchGuardrail,
    ScreeningStatus,
)


class EvidenceSourceKind(StrEnum):
    """Canonical evidence backing kinds supported by the detail API."""

    DOCUMENT = "document"
    WAREHOUSE_FACT = "warehouse_fact"
    QUANT_RESULT = "quant_result"


class EvidenceHighlight(BaseModel):
    """One verified character range to highlight in canonical Markdown."""

    start: int
    end: int
    quote: str
    label: str | None = None

    model_config = {"frozen": True}


class EvidenceDetail(BaseModel):
    """Frontend read model for a complete evidence source and its cited ranges."""

    evidence_id: str
    source_kind: EvidenceSourceKind
    title: str
    source_level: str
    source_url: str | None = None
    document_id: str | None = None
    markdown: str
    highlights: tuple[EvidenceHighlight, ...] = Field(default_factory=tuple)
    locator: dict[str, Any] = Field(default_factory=dict)
    snapshot_id: str | None = None
    pit_timestamp: datetime | None = None
    source_name: str | None = None

    model_config = {"frozen": True}


class QuantFactorEvidenceValue(BaseModel):
    """One persisted factor value used to explain a quant result."""

    factor_value_id: str
    factor_group: str
    factor_name: str
    raw_value: float | None = None
    score: float | None = None
    direction: str
    missing: bool = False
    detail: dict[str, Any] = Field(default_factory=dict)

    model_config = {"frozen": True}


class QuantInputLineage(BaseModel):
    """Frozen input snapshot metadata behind one quant result."""

    snapshot_id: str
    scope_version_id: str
    universe_snapshot_id: str
    decision_at: datetime
    known_at: datetime
    required_indicators: tuple[str, ...] = Field(default_factory=tuple)
    optional_indicators: tuple[str, ...] = Field(default_factory=tuple)
    quant_feature_set_version_id: str | None = None
    user_indicator_view_version_id: str | None = None
    feature_snapshot_id: str | None = None
    market_window_start: datetime | None = None
    market_window_end: datetime | None = None
    fact_count: int = 0
    data_status: str
    quality_flags: tuple[str, ...] = Field(default_factory=tuple)
    freshness_flags: tuple[str, ...] = Field(default_factory=tuple)
    pit_validation_errors: tuple[str, ...] = Field(default_factory=tuple)
    corporate_action_adjustment_version: str | None = None
    industry_snapshot_id: str | None = None
    input_hash: str

    model_config = {"frozen": True}


class QuantResultEvidenceRecord(BaseModel):
    """Complete immutable quant output and its input lineage."""

    result: QuantResult
    quant_run: QuantRun | None = None
    input_snapshot: QuantInputLineage | None = None
    fact_ids: tuple[str, ...] = Field(default_factory=tuple)
    factor_values: tuple[QuantFactorEvidenceValue, ...] = Field(default_factory=tuple)

    model_config = {"frozen": True}


class EvidenceReader(Protocol):
    """Evidence-record lookup boundary."""

    def get_evidence(self, evidence_id: str) -> Evidence | None:
        """Return one immutable evidence record."""


class DocumentReader(Protocol):
    """Canonical document lookup boundary."""

    def get_document_event(self, event_id: str) -> DocumentEvent | None:
        """Return a document by event ID."""

    def get_document_event_by_document_id(self, document_id: str) -> DocumentEvent | None:
        """Return a document by canonical document ID."""


class WarehouseFactReader(Protocol):
    """Warehouse fact lookup boundary."""

    def get_fact(self, fact_id: str) -> StandardizedIndicatorFact | None:
        """Return one standardized immutable warehouse fact."""


class QuantResultReader(Protocol):
    """Quant-result lookup boundary with full input lineage."""

    def get_quant_result(self, result_id: str) -> QuantResultEvidenceRecord | None:
        """Return one immutable quant result and the inputs that produced it."""


class EvidenceDetailService:
    """Resolve evidence IDs to complete canonical source content."""

    def __init__(
        self,
        *,
        evidence_reader: EvidenceReader,
        document_reader: DocumentReader,
        warehouse_fact_reader: WarehouseFactReader,
        quant_result_reader: QuantResultReader | None = None,
    ) -> None:
        self._evidence = evidence_reader
        self._documents = document_reader
        self._facts = warehouse_fact_reader
        self._quant_results = quant_result_reader

    def get_detail(self, evidence_id: str) -> EvidenceDetail | None:
        """Resolve an evidence, document, warehouse-fact, or quant-result ID."""
        evidence = self._evidence.get_evidence(evidence_id)
        if evidence is not None:
            document = self._documents.get_document_event_by_document_id(evidence.document_id)
            return _document_evidence_detail(evidence, document)

        document = self._documents.get_document_event(evidence_id)
        if document is None:
            document = self._documents.get_document_event_by_document_id(evidence_id)
        if document is not None:
            return _document_event_detail(evidence_id, document)

        fact = self._facts.get_fact(evidence_id)
        if fact is not None:
            return _warehouse_fact_detail(evidence_id, fact)

        if self._quant_results is not None:
            quant_result = self._quant_results.get_quant_result(evidence_id)
            if quant_result is not None:
                return _quant_result_detail(quant_result)
        return None


class SQLAlchemyWarehouseFactDetailRepository:
    """Read standardized facts by their canonical fact ID."""

    def __init__(self, session_factory: Callable[[], Session]) -> None:
        self._session_factory = session_factory

    def get_fact(self, fact_id: str) -> StandardizedIndicatorFact | None:
        """Return one standardized fact without a point-in-time reinterpretation."""
        with self._session_factory() as session:
            row = session.get(StandardizedIndicatorFactRow, fact_id)
            return _fact_from_row(row) if row is not None else None


class SQLAlchemyQuantResultDetailRepository:
    """Read a quant result together with its persisted PIT input lineage."""

    def __init__(self, session_factory: Callable[[], Session]) -> None:
        self._session_factory = session_factory

    def get_quant_result(self, result_id: str) -> QuantResultEvidenceRecord | None:
        """Return one quant result, run, input snapshot, factors, and fact IDs."""
        with self._session_factory() as session:
            result_row = session.get(QuantScreenResultRow, result_id)
            if result_row is None:
                return None
            run_row = session.get(QuantScreenRunRow, result_row.quant_run_id)
            input_row = (
                session.get(QuantInputSnapshotRow, run_row.input_snapshot_id)
                if run_row is not None
                else None
            )
            input_snapshot_id = run_row.input_snapshot_id if run_row is not None else None
            fact_rows = (
                session.scalars(
                    select(QuantInputSnapshotFactRow)
                    .where(
                        QuantInputSnapshotFactRow.snapshot_id == input_snapshot_id,
                        QuantInputSnapshotFactRow.security_id == result_row.security_id,
                    )
                    .order_by(
                        QuantInputSnapshotFactRow.indicator_code,
                        QuantInputSnapshotFactRow.fact_id,
                    )
                ).all()
                if input_snapshot_id is not None
                else []
            )
            factor_rows = session.scalars(
                select(QuantFactorValueRow)
                .where(QuantFactorValueRow.result_id == result_id)
                .order_by(QuantFactorValueRow.factor_group, QuantFactorValueRow.factor_name)
            ).all()
        return QuantResultEvidenceRecord(
            result=_quant_result_from_row(result_row),
            quant_run=_quant_run_from_row(run_row) if run_row is not None else None,
            input_snapshot=(
                _quant_input_lineage_from_row(input_row) if input_row is not None else None
            ),
            fact_ids=tuple(dict.fromkeys(row.fact_id for row in fact_rows)),
            factor_values=tuple(_quant_factor_from_row(row) for row in factor_rows),
        )


def _document_evidence_detail(
    evidence: Evidence,
    document: DocumentEvent | None,
) -> EvidenceDetail:
    markdown = (
        document.content
        if document is not None and document.content is not None
        else evidence.content
    )
    highlights = _evidence_highlights(markdown, evidence)
    locator = {
        "chunk_id": evidence.chunk_id,
        "source_type": evidence.source_type,
        "content_hash": evidence.content_hash,
        **_non_null_locator_fields(evidence),
    }
    return EvidenceDetail(
        evidence_id=evidence.evidence_id,
        source_kind=EvidenceSourceKind.DOCUMENT,
        title=(document.title if document is not None else evidence.source_name)
        or evidence.document_id,
        source_level=_source_level_label(evidence.source_level),
        source_url=document.source_url if document is not None else evidence.source_url,
        document_id=evidence.document_id,
        markdown=markdown,
        highlights=highlights,
        locator=locator,
        snapshot_id=document.snapshot_id if document is not None else evidence.snapshot_id,
        pit_timestamp=document.available_at if document is not None else evidence.available_at,
        source_name=document.source_name if document is not None else evidence.source_name,
    )


def _document_event_detail(evidence_id: str, document: DocumentEvent) -> EvidenceDetail:
    return EvidenceDetail(
        evidence_id=evidence_id,
        source_kind=EvidenceSourceKind.DOCUMENT,
        title=document.title,
        source_level=_source_level_label(document.source_level),
        source_url=document.source_url,
        document_id=document.document_id,
        markdown=document.content or "",
        locator={
            "event_id": document.event_id,
            "document_id": document.document_id,
            "content_hash": document.content_hash,
            "processing_status": document.processing_status.value,
        },
        snapshot_id=document.snapshot_id,
        pit_timestamp=document.available_at,
        source_name=document.source_name,
    )


def _warehouse_fact_detail(
    evidence_id: str,
    fact: StandardizedIndicatorFact,
) -> EvidenceDetail:
    markdown = _fact_markdown(fact)
    value = _escape_table_cell(_fact_value(fact))
    highlight = _highlight_for_text(markdown, value, label=fact.indicator_id)
    source_url = fact.lineage.get("source_url")
    return EvidenceDetail(
        evidence_id=evidence_id,
        source_kind=EvidenceSourceKind.WAREHOUSE_FACT,
        title=f"{fact.security_id} · {fact.indicator_id}",
        source_level="L3",
        source_url=str(source_url) if source_url else None,
        markdown=markdown,
        highlights=(highlight,) if highlight is not None else (),
        locator={
            "fact_id": fact.fact_id,
            "provider_fact_id": fact.provider_fact_id,
            "endpoint_code": fact.endpoint_code,
            "security_id": fact.security_id,
            "indicator_id": fact.indicator_id,
            "event_at": fact.event_at.isoformat(),
            "available_at": fact.available_at.isoformat(),
            "raw_snapshot_id": fact.raw_snapshot_id,
        },
        snapshot_id=fact.raw_snapshot_id,
        pit_timestamp=fact.available_at,
        source_name=fact.provider_code,
    )


def _quant_result_detail(record: QuantResultEvidenceRecord) -> EvidenceDetail:
    result = record.result
    quant_run = record.quant_run
    input_snapshot = record.input_snapshot
    score = _format_number(result.final_score)
    summary = f"最终得分：{score}；筛选状态：{result.screening_status.value}"
    markdown = _quant_result_markdown(record, summary=summary)
    highlight = _highlight_for_text(markdown, summary, label="量化结论")
    input_snapshot_id = (
        input_snapshot.snapshot_id
        if input_snapshot is not None
        else quant_run.input_snapshot_id
        if quant_run is not None
        else None
    )
    decision_at = quant_run.decision_at if quant_run is not None else result.created_at
    locator: dict[str, Any] = {
        "quant_result_id": result.result_id,
        "quant_run_id": result.quant_run_id,
        "input_snapshot_id": input_snapshot_id,
        "fact_ids": list(record.fact_ids),
        "security_id": result.security_id,
        "result_created_at": result.created_at.isoformat(),
        "factor_value_ids": [item.factor_value_id for item in record.factor_values],
        "lineage": {
            "quant_run_id": result.quant_run_id,
            "input_snapshot_id": input_snapshot_id,
            "fact_ids": list(record.fact_ids),
        },
    }
    if quant_run is not None:
        locator.update(
            {
                "scope_version_id": quant_run.scope_version_id,
                "strategy_version_id": quant_run.strategy_version_id,
                "decision_at": quant_run.decision_at.isoformat(),
                "run_status": quant_run.status,
            }
        )
    display_name = result.factor_details.get("name")
    title_subject = (
        f"{result.security_id} · {display_name}"
        if isinstance(display_name, str) and display_name.strip()
        else result.security_id
    )
    return EvidenceDetail(
        evidence_id=result.result_id,
        source_kind=EvidenceSourceKind.QUANT_RESULT,
        title=f"{title_subject} · 量化筛选结果",
        source_level="L3",
        markdown=markdown,
        highlights=(highlight,) if highlight is not None else (),
        locator=locator,
        snapshot_id=input_snapshot_id or result.result_id,
        pit_timestamp=decision_at,
        source_name="quant_worker",
    )


def _quant_result_markdown(
    record: QuantResultEvidenceRecord,
    *,
    summary: str,
) -> str:
    result = record.result
    quant_run = record.quant_run
    input_snapshot = record.input_snapshot
    display_name = result.factor_details.get("name")
    subject = result.security_id
    if isinstance(display_name, str) and display_name.strip():
        subject = f"{subject} · {display_name.strip()}"

    status_rows = (
        ("筛选状态", result.screening_status.value),
        ("数据状态", result.data_status.value),
        ("研究护栏", result.research_guardrail.value),
        ("需要人工复核", "是" if result.review_required else "否"),
        ("综合排名", _display_value(result.rank_overall)),
        ("行业排名", _display_value(result.rank_in_industry)),
        ("结论摘要", result.reason_summary or "—"),
    )
    score_rows = (
        ("最终得分", result.final_score),
        ("质量", result.quality_score),
        ("估值", result.value_score),
        ("成长", result.growth_score),
        ("动量", result.momentum_score),
        ("风险", result.risk_score),
    )
    factor_table = _quant_factor_table(record.factor_values)
    lineage_rows = (
        ("量化结果 ID", result.result_id),
        ("量化运行 ID", result.quant_run_id),
        ("运行状态", quant_run.status if quant_run is not None else "—"),
        (
            "策略版本",
            quant_run.strategy_version_id if quant_run is not None else "—",
        ),
        ("范围版本", quant_run.scope_version_id if quant_run is not None else "—"),
        (
            "输入快照 ID",
            input_snapshot.snapshot_id if input_snapshot is not None else "—",
        ),
        (
            "决策时间",
            quant_run.decision_at.isoformat() if quant_run is not None else "—",
        ),
        (
            "输入已知时间",
            input_snapshot.known_at.isoformat() if input_snapshot is not None else "—",
        ),
        (
            "输入哈希",
            input_snapshot.input_hash if input_snapshot is not None else "—",
        ),
        ("结果生成时间", result.created_at.isoformat()),
    )
    fact_lines = _markdown_list(record.fact_ids)
    risk_lines = _markdown_list(result.risk_flags)
    review_lines = _markdown_list(result.review_reasons)
    factor_details = _indented_json(result.factor_details)
    input_details = _quant_input_details(input_snapshot)
    return (
        f"# {_escape_markdown_inline(subject)} · 量化筛选结果\n\n"
        f"> {summary}\n\n"
        f"## 状态与结论\n\n{_field_table(status_rows)}\n\n"
        f"## 分数组成\n\n{_score_table(score_rows)}\n\n"
        f"## 持久化因子值\n\n{factor_table}\n\n"
        f"## 完整因子详情\n\n{factor_details}\n\n"
        f"## 风险标记\n\n{risk_lines}\n\n"
        f"## 复核原因\n\n{review_lines}\n\n"
        f"## 运行与输入血缘\n\n{_field_table(lineage_rows)}\n\n"
        f"### 输入快照\n\n{input_details}\n\n"
        f"### 事实 ID\n\n{fact_lines}"
    )


def _field_table(rows: tuple[tuple[str, Any], ...]) -> str:
    return "\n".join(
        [
            "| 字段 | 内容 |",
            "| --- | --- |",
            *(
                f"| {_escape_table_cell(name)} | {_escape_table_cell(_display_value(value))} |"
                for name, value in rows
            ),
        ]
    )


def _score_table(rows: tuple[tuple[str, float | None], ...]) -> str:
    return "\n".join(
        [
            "| 分数组 | 得分 |",
            "| --- | ---: |",
            *(f"| {name} | {_format_number(value)} |" for name, value in rows),
        ]
    )


def _quant_factor_table(values: tuple[QuantFactorEvidenceValue, ...]) -> str:
    if not values:
        return "未持久化独立因子行；完整模型输出见下方因子详情。"
    rows = [
        "| 因子组 | 因子 | 原始值 | 得分 | 方向 | 缺失 | 明细 |",
        "| --- | --- | ---: | ---: | --- | --- | --- |",
    ]
    rows.extend(
        "| "
        + " | ".join(
            (
                _escape_table_cell(value.factor_group),
                _escape_table_cell(value.factor_name),
                _format_number(value.raw_value),
                _format_number(value.score),
                _escape_table_cell(value.direction),
                "是" if value.missing else "否",
                _escape_table_cell(
                    json.dumps(value.detail, ensure_ascii=False, sort_keys=True, default=str)
                ),
            )
        )
        + " |"
        for value in values
    )
    return "\n".join(rows)


def _quant_input_details(input_snapshot: QuantInputLineage | None) -> str:
    if input_snapshot is None:
        return "输入快照记录不可用。"
    rows = (
        ("快照 ID", input_snapshot.snapshot_id),
        ("范围版本", input_snapshot.scope_version_id),
        ("股票池快照", input_snapshot.universe_snapshot_id),
        ("决策时间", input_snapshot.decision_at.isoformat()),
        ("已知时间", input_snapshot.known_at.isoformat()),
        ("特征快照", input_snapshot.feature_snapshot_id or "—"),
        ("量化特征集版本", input_snapshot.quant_feature_set_version_id or "—"),
        ("用户指标视图版本", input_snapshot.user_indicator_view_version_id or "—"),
        (
            "市场窗口开始",
            input_snapshot.market_window_start.isoformat()
            if input_snapshot.market_window_start is not None
            else "—",
        ),
        (
            "市场窗口结束",
            input_snapshot.market_window_end.isoformat()
            if input_snapshot.market_window_end is not None
            else "—",
        ),
        ("事实数量", input_snapshot.fact_count),
        ("数据状态", input_snapshot.data_status),
        ("必需指标", ", ".join(input_snapshot.required_indicators) or "—"),
        ("可选指标", ", ".join(input_snapshot.optional_indicators) or "—"),
        ("质量标记", ", ".join(input_snapshot.quality_flags) or "—"),
        ("新鲜度标记", ", ".join(input_snapshot.freshness_flags) or "—"),
        ("PIT 校验错误", ", ".join(input_snapshot.pit_validation_errors) or "—"),
        (
            "复权规则版本",
            input_snapshot.corporate_action_adjustment_version or "—",
        ),
        ("行业快照", input_snapshot.industry_snapshot_id or "—"),
    )
    return _field_table(rows)


def _markdown_list(values: tuple[str, ...]) -> str:
    if not values:
        return "- 无"
    return "\n".join(f"- {_escape_markdown_inline(value)}" for value in values)


def _indented_json(value: Any) -> str:
    rendered = json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True, default=str)
    return "\n".join(f"    {line}" for line in rendered.splitlines())


def _display_value(value: Any) -> str:
    if value is None:
        return "—"
    if isinstance(value, float):
        return _format_number(value)
    return str(value)


def _format_number(value: float | None) -> str:
    if value is None:
        return "—"
    return f"{value:.10g}"


def _escape_markdown_inline(value: str) -> str:
    text = value.replace("\r\n", "\n").replace("\r", "\n").replace("\n", " / ")
    text = text.replace("\\", "\\\\")
    for marker in ("`", "*", "[", "]", "<", ">", "|"):
        text = text.replace(marker, f"\\{marker}")
    return text


def _evidence_highlights(markdown: str, evidence: Evidence) -> tuple[EvidenceHighlight, ...]:
    span = evidence.quote_span
    if span is not None:
        start, end = span
        if 0 <= start < end <= len(markdown):
            quote = markdown[start:end]
            if _same_text(quote, evidence.content):
                return (
                    EvidenceHighlight(
                        start=start,
                        end=end,
                        quote=quote,
                        label=evidence.section or "引用片段",
                    ),
                )
    highlight = _highlight_for_text(
        markdown,
        evidence.content,
        label=evidence.section or "引用片段",
    )
    return (highlight,) if highlight is not None else ()


def _highlight_for_text(
    markdown: str,
    text: str,
    *,
    label: str,
) -> EvidenceHighlight | None:
    if not text:
        return None
    start = markdown.find(text)
    if start < 0:
        return None
    end = start + len(text)
    return EvidenceHighlight(start=start, end=end, quote=markdown[start:end], label=label)


def _same_text(left: str, right: str) -> bool:
    return " ".join(left.split()) == " ".join(right.split())


def _non_null_locator_fields(evidence: Evidence) -> dict[str, Any]:
    values = {
        "page": evidence.page,
        "bbox": evidence.bbox,
        "section": evidence.section,
        "paragraph_index": evidence.paragraph_index,
        "dom_path": evidence.dom_path,
        "table_id": evidence.table_id,
        "row_id": evidence.row_id,
        "column_id": evidence.column_id,
        "quote_span": evidence.quote_span,
    }
    return {key: value for key, value in values.items() if value is not None}


def _source_level_label(source_level: SourceLevel | int) -> str:
    return f"L{int(source_level)}"


def _fact_markdown(fact: StandardizedIndicatorFact) -> str:
    value = _fact_value(fact)
    rows = (
        ("证券", fact.security_id),
        ("指标", fact.indicator_id),
        ("值", value),
        ("单位", fact.unit or ""),
        ("业务时间", fact.event_at.isoformat()),
        ("可用时间", fact.available_at.isoformat()),
        ("数据源", fact.provider_code),
        ("质量分", str(fact.quality_score)),
    )
    table = "\n".join(
        [
            "| 字段 | 内容 |",
            "| --- | --- |",
            *(f"| {name} | {_escape_table_cell(item)} |" for name, item in rows),
        ]
    )
    lineage = _indented_json(fact.lineage)
    return (
        f"# {fact.security_id} · {fact.indicator_id}\n\n"
        f"{table}\n\n## Lineage\n\n{lineage}"
    )


def _fact_value(fact: StandardizedIndicatorFact) -> str:
    if fact.numeric_value is not None:
        return str(fact.numeric_value)
    if fact.text_value is not None:
        return fact.text_value
    if fact.json_value is not None:
        return json.dumps(fact.json_value, ensure_ascii=False, sort_keys=True, default=str)
    return "null"


def _escape_table_cell(value: str) -> str:
    text = value.replace("\r\n", "\n").replace("\r", "\n")
    return (
        text.replace("\\", "\\\\")
        .replace("|", "\\|")
        .replace("`", "\\`")
        .replace("<", "\\<")
        .replace(">", "\\>")
        .replace("\n", " / ")
    )


def _fact_from_row(row: StandardizedIndicatorFactRow) -> StandardizedIndicatorFact:
    return StandardizedIndicatorFact(
        fact_id=row.fact_id,
        provider_code=row.provider,
        provider_fact_id=row.provider_fact_id,
        endpoint_code=row.endpoint_code,
        security_id=row.security_id,
        indicator_id=row.indicator_id,
        indicator_version=row.indicator_version,
        event_at=row.event_at,
        available_at=row.available_at,
        fetched_at=row.fetched_at,
        published_at=row.published_at,
        revised_at=row.revised_at,
        numeric_value=Decimal(row.numeric_value) if row.numeric_value is not None else None,
        text_value=row.text_value,
        json_value=row.json_value,
        unit=row.unit,
        quality_score=Decimal(row.quality_score),
        mapping_version=row.mapping_version,
        raw_snapshot_id=row.raw_snapshot_id,
        lineage=dict(row.lineage or {}),
    )


def _quant_result_from_row(row: QuantScreenResultRow) -> QuantResult:
    return QuantResult(
        result_id=row.result_id,
        quant_run_id=row.quant_run_id,
        security_id=row.security_id,
        final_score=row.final_score,
        quality_score=row.quality_score,
        value_score=row.value_score,
        growth_score=row.growth_score,
        momentum_score=row.momentum_score,
        risk_score=row.risk_score,
        rank_overall=row.rank_overall,
        rank_in_industry=row.rank_in_industry,
        screening_status=ScreeningStatus(row.screening_status),
        data_status=DataStatus(row.data_status),
        risk_flags=tuple(row.risk_flags or ()),
        review_required=row.review_required,
        review_reasons=tuple(row.review_reasons or ()),
        research_guardrail=ResearchGuardrail(row.research_guardrail),
        reason_summary=row.reason_summary,
        factor_details=dict(row.factor_details or {}),
        created_at=row.created_at,
    )


def _quant_run_from_row(row: QuantScreenRunRow) -> QuantRun:
    return QuantRun(
        quant_run_id=row.quant_run_id,
        input_snapshot_id=row.input_snapshot_id,
        scope_version_id=row.scope_version_id,
        strategy_version_id=row.strategy_version_id,
        decision_at=row.decision_at,
        config_hash=row.config_hash,
        status=row.status,
        created_at=row.created_at,
    )


def _quant_input_lineage_from_row(row: QuantInputSnapshotRow) -> QuantInputLineage:
    return QuantInputLineage(
        snapshot_id=row.snapshot_id,
        scope_version_id=row.scope_version_id,
        universe_snapshot_id=row.universe_snapshot_id,
        decision_at=row.decision_at,
        known_at=row.known_at,
        required_indicators=tuple(row.required_indicators or ()),
        optional_indicators=tuple(row.optional_indicators or ()),
        quant_feature_set_version_id=row.quant_feature_set_version_id,
        user_indicator_view_version_id=row.user_indicator_view_version_id,
        feature_snapshot_id=row.feature_snapshot_id,
        market_window_start=row.market_window_start,
        market_window_end=row.market_window_end,
        fact_count=row.fact_count,
        data_status=row.data_status,
        quality_flags=tuple(row.quality_flags or ()),
        freshness_flags=tuple(row.freshness_flags or ()),
        pit_validation_errors=tuple(row.pit_validation_errors or ()),
        corporate_action_adjustment_version=row.corporate_action_adjustment_version,
        industry_snapshot_id=row.industry_snapshot_id,
        input_hash=row.input_hash,
    )


def _quant_factor_from_row(row: QuantFactorValueRow) -> QuantFactorEvidenceValue:
    return QuantFactorEvidenceValue(
        factor_value_id=row.factor_value_id,
        factor_group=row.factor_group,
        factor_name=row.factor_name,
        raw_value=row.raw_value,
        score=row.score,
        direction=row.direction,
        missing=row.missing,
        detail=dict(row.detail_json or {}),
    )


__all__ = [
    "EvidenceDetail",
    "EvidenceDetailService",
    "EvidenceHighlight",
    "EvidenceSourceKind",
    "QuantFactorEvidenceValue",
    "QuantInputLineage",
    "QuantResultEvidenceRecord",
    "SQLAlchemyQuantResultDetailRepository",
    "SQLAlchemyWarehouseFactDetailRepository",
]
