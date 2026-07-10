"""Data question worker for read-only PIT warehouse analysis."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from langgraph.graph import END, START, StateGraph
from pydantic import BaseModel, ConfigDict, Field

from margin.agent_runtime.context_store import ContextArtifact, make_context_artifact
from margin.agents.security.capability import CapabilityToken
from margin.agents.tools.specs import ToolCallRequest, ToolCallStatus
from margin.agents.tools.warehouse_tools import WarehouseReadTools, WarehouseToolResult
from margin.core.hashing import stable_json_hash


@dataclass(frozen=True)
class FinancialMetricAnalysis:
    """Structured data-analysis output for one financial metric question."""

    answer: str
    table_artifact: ContextArtifact
    chart_artifact: ContextArtifact
    image_artifact: ContextArtifact
    metric_artifact: ContextArtifact
    table_rows: list[dict[str, Any]]
    worker_activity_artifact: ContextArtifact
    audit_event_refs: tuple[str, ...] = ()
    skill_id: str = "answer_financial_metric"


class FinancialMetricWorkflowState(BaseModel):
    """State carried through DataQuestionWorker's fixed LangGraph tool flow."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    run_id: str
    message: str
    conversation_context: tuple[dict[str, str], ...] = ()
    chart_type: str = "line"
    decision_at: datetime
    analysis_text: str = ""
    user_query_text: str = ""
    security_query_text: str = ""
    requested_indicator_id: str = ""
    max_points_per_indicator: int = Field(default=12, ge=1, le=100)
    metric: dict[str, Any] | None = None
    profiles: list[Any] = Field(default_factory=list)
    indicator_catalog: list[Any] = Field(default_factory=list)
    history: list[Any] = Field(default_factory=list)
    metric_schema: dict[str, Any] = Field(default_factory=dict)
    tool_calls: tuple[str, ...] = ()
    audit_event_refs: tuple[str, ...] = ()


class DataQuestionWorker:
    """Answer user data questions through read-only PIT warehouse queries."""

    name = "DataQuestionWorker"
    skill_id = "answer_financial_metric"

    def __init__(self, warehouse_repository: Any) -> None:
        """Initialize with the warehouse read repository."""
        self._warehouse_repository = warehouse_repository

    def answer_financial_metric(
        self,
        *,
        run_id: str,
        message: str,
        worker_inputs: dict[str, Any] | None = None,
        chart_type: str = "line",
        conversation_context: tuple[dict[str, str], ...] = (),
        decision_at: datetime | None = None,
        tool_gateway: Any | None = None,
        capability_token: CapabilityToken | None = None,
        context_pack_id: str | None = None,
        context_pack_hash: str | None = None,
        worker_task_id: str | None = None,
        idempotency_key: str | None = None,
    ) -> FinancialMetricAnalysis | None:
        """Answer a supported financial metric question from PIT warehouse facts."""
        normalized_inputs = _normalize_worker_inputs(worker_inputs)
        if normalized_inputs is None:
            return None
        decision_time = decision_at or datetime.now(UTC)
        state = _run_financial_metric_workflow(
            repository=self._warehouse_repository,
            run_id=run_id,
            message=message,
            worker_inputs=normalized_inputs,
            conversation_context=conversation_context,
            chart_type=normalized_inputs["chart_type"] or _normalize_chart_type(chart_type),
            decision_at=decision_time,
            tool_gateway=tool_gateway,
            capability_token=capability_token,
            context_pack_id=context_pack_id,
            context_pack_hash=context_pack_hash,
            worker_task_id=worker_task_id,
            idempotency_key=idempotency_key,
        )
        metric = state.metric
        if metric is None:
            return None
        profiles = list(state.profiles)
        if not profiles:
            return _empty_financial_metric_analysis(
                run_id=run_id,
                metric=metric,
                message=state.security_query_text or state.user_query_text,
                workflow_tool_calls=state.tool_calls,
                audit_event_refs=state.audit_event_refs,
                max_points_per_indicator=state.max_points_per_indicator,
            )
        return _financial_metric_analysis_from_history(
            run_id=run_id,
            metric=metric,
            profiles=profiles,
            history=list(state.history),
            chart_type=state.chart_type,
            workflow_tool_calls=state.tool_calls,
            audit_event_refs=state.audit_event_refs,
            max_points_per_indicator=state.max_points_per_indicator,
        )


def _run_financial_metric_workflow(
    *,
    repository: Any,
    run_id: str,
    message: str,
    worker_inputs: dict[str, Any],
    conversation_context: tuple[dict[str, str], ...],
    chart_type: str,
    decision_at: datetime,
    tool_gateway: Any | None = None,
    capability_token: CapabilityToken | None = None,
    context_pack_id: str | None = None,
    context_pack_hash: str | None = None,
    worker_task_id: str | None = None,
    idempotency_key: str | None = None,
) -> FinancialMetricWorkflowState:
    """Run the fixed internal LangGraph workflow for financial metrics."""
    graph = StateGraph(FinancialMetricWorkflowState)
    tools = (
        _GatewayWarehouseReadTools(
            gateway=tool_gateway,
            capability_token=capability_token,
            run_id=run_id,
            worker_task_id=worker_task_id or f"wt_{run_id}_data_question",
            context_pack_id=context_pack_id,
            context_pack_hash=context_pack_hash,
            idempotency_key=idempotency_key or run_id,
        )
        if tool_gateway is not None and capability_token is not None
        else WarehouseReadTools(repository)
    )

    def recover_context(state: FinancialMetricWorkflowState) -> dict[str, Any]:
        user_query_text = worker_inputs["user_query"]
        security_query_text = worker_inputs["security_query"]
        analysis_text = _analysis_text_with_context(user_query_text, state.conversation_context)
        return {
            "analysis_text": analysis_text,
            "user_query_text": user_query_text,
            "security_query_text": security_query_text,
            "requested_indicator_id": worker_inputs.get("indicator_id", ""),
            "max_points_per_indicator": worker_inputs.get(
                "max_points_per_indicator",
                12,
            ),
        }

    def describe_schema(state: FinancialMetricWorkflowState) -> dict[str, Any]:
        schema = tools.describe_schema()
        return {
            "metric_schema": schema.output,
            "tool_calls": (*state.tool_calls, schema.tool_name),
            "audit_event_refs": _append_audit_ref(state.audit_event_refs, schema.audit_ref),
        }

    def resolve_security(state: FinancialMetricWorkflowState) -> dict[str, Any]:
        security_result = tools.resolve_security(
            query_text=state.security_query_text or state.user_query_text or state.analysis_text,
            decision_at=state.decision_at,
        )
        return {
            "profiles": security_result.output.get("raw_profiles")
            or security_result.output.get("profiles", []),
            "tool_calls": (*state.tool_calls, security_result.tool_name),
            "audit_event_refs": _append_audit_ref(
                state.audit_event_refs,
                security_result.audit_ref,
            ),
        }

    def discover_indicators(state: FinancialMetricWorkflowState) -> dict[str, Any]:
        security_ids = tuple(_profile_security_id(profile) for profile in state.profiles[:3])
        catalog_result = tools.discover_indicators(
            security_ids=security_ids,
            query_text=state.user_query_text,
            decision_at=state.decision_at,
        )
        return {
            "indicator_catalog": catalog_result.output.get("indicators", []),
            "tool_calls": (*state.tool_calls, catalog_result.tool_name),
            "audit_event_refs": _append_audit_ref(
                state.audit_event_refs,
                catalog_result.audit_ref,
            ),
        }

    def select_indicator(state: FinancialMetricWorkflowState) -> dict[str, Any]:
        metric = _select_metric_from_catalog(
            state.indicator_catalog,
            requested_indicator_id=state.requested_indicator_id,
            query_text=state.user_query_text,
        )
        return {
            "metric": metric,
            "metric_schema": {
                **state.metric_schema,
                "selected_indicator_id": metric.get("indicator_id") if metric else None,
                "discovered_indicator_count": len(state.indicator_catalog),
            },
        }

    def query_indicator_history(state: FinancialMetricWorkflowState) -> dict[str, Any]:
        audit_event_refs = state.audit_event_refs
        if state.metric is None or not state.profiles:
            history: list[Any] = []
        else:
            history_result = tools.query_indicator_history(
                security_ids=tuple(
                    _profile_security_id(profile) for profile in state.profiles[:3]
                ),
                indicator_ids=(state.metric["indicator_id"],),
                decision_at=state.decision_at,
                max_points_per_indicator=state.max_points_per_indicator,
            )
            history = history_result.output.get("history", [])
            audit_event_refs = _append_audit_ref(
                audit_event_refs,
                history_result.audit_ref,
            )
        return {
            "history": history,
            "tool_calls": (*state.tool_calls, "warehouse.query_indicator_history"),
            "audit_event_refs": audit_event_refs,
        }

    def prepare_chart(state: FinancialMetricWorkflowState) -> dict[str, Any]:
        return {"tool_calls": (*state.tool_calls, "python.render_chart")}

    graph.add_node("recover_context", recover_context)
    graph.add_node("describe_schema", describe_schema)
    graph.add_node("resolve_security", resolve_security)
    graph.add_node("discover_indicators", discover_indicators)
    graph.add_node("select_indicator", select_indicator)
    graph.add_node("query_indicator_history", query_indicator_history)
    graph.add_node("prepare_chart", prepare_chart)
    graph.add_edge(START, "recover_context")
    graph.add_edge("recover_context", "describe_schema")
    graph.add_edge("describe_schema", "resolve_security")
    graph.add_edge("resolve_security", "discover_indicators")
    graph.add_edge("discover_indicators", "select_indicator")
    graph.add_edge("select_indicator", "query_indicator_history")
    graph.add_edge("query_indicator_history", "prepare_chart")
    graph.add_edge("prepare_chart", END)
    compiled = graph.compile()
    output = compiled.invoke(
        FinancialMetricWorkflowState(
            run_id=run_id,
            message=message,
            conversation_context=conversation_context,
            chart_type=chart_type,
            decision_at=decision_at,
        )
    )
    if isinstance(output, FinancialMetricWorkflowState):
        return output
    return FinancialMetricWorkflowState.model_validate(output)


class _GatewayWarehouseReadTools:
    """Warehouse tool facade that delegates every call through ToolGateway."""

    def __init__(
        self,
        *,
        gateway: Any,
        capability_token: CapabilityToken,
        run_id: str,
        worker_task_id: str,
        context_pack_id: str | None,
        context_pack_hash: str | None,
        idempotency_key: str,
    ) -> None:
        self._gateway = gateway
        self._capability_token = capability_token
        self._run_id = run_id
        self._worker_task_id = worker_task_id
        self._context_pack_id = context_pack_id
        self._context_pack_hash = context_pack_hash
        self._idempotency_key = idempotency_key

    def describe_schema(self) -> WarehouseToolResult:
        return self._call("warehouse.describe_schema", {})

    def resolve_security(
        self,
        *,
        query_text: str,
        decision_at: datetime,
        limit: int = 5,
    ) -> WarehouseToolResult:
        return self._call(
            "warehouse.resolve_security",
            {
                "query_text": query_text,
                "decision_at": decision_at.isoformat(),
                "limit": limit,
            },
        )

    def discover_indicators(
        self,
        *,
        security_ids: tuple[str, ...],
        query_text: str,
        decision_at: datetime,
        limit: int = 200,
    ) -> WarehouseToolResult:
        return self._call(
            "warehouse.discover_indicators",
            {
                "security_ids": list(security_ids),
                "query_text": query_text,
                "decision_at": decision_at.isoformat(),
                "limit": limit,
            },
        )

    def query_indicator_history(
        self,
        *,
        security_ids: tuple[str, ...],
        indicator_ids: tuple[str, ...],
        decision_at: datetime,
        years: int = 4,
        max_points_per_indicator: int = 12,
    ) -> WarehouseToolResult:
        return self._call(
            "warehouse.query_indicator_history",
            {
                "security_ids": list(security_ids),
                "indicator_ids": list(indicator_ids),
                "decision_at": decision_at.isoformat(),
                "years": years,
                "max_points_per_indicator": max_points_per_indicator,
            },
        )

    def _call(self, tool_name: str, input_json: dict[str, Any]) -> WarehouseToolResult:
        payload_hash = stable_json_hash(input_json).replace(":", "_")
        tool_call_id = (
            f"tc_{self._worker_task_id}_{tool_name.replace('.', '_')}_{payload_hash}"
        )
        result = self._gateway.call(
            ToolCallRequest(
                tool_call_id=tool_call_id,
                run_id=self._run_id,
                task_id=self._worker_task_id,
                caller_agent=DataQuestionWorker.name,
                tool_name=tool_name,
                tool_version="v1",
                input_json=input_json,
                capability_token=self._capability_token,
                context_pack_id=self._context_pack_id,
                context_pack_hash=self._context_pack_hash,
                idempotency_key=f"{self._idempotency_key}:{tool_name}:{payload_hash}",
                deadline_ms=30_000,
            )
        )
        if result.status is not ToolCallStatus.SUCCEEDED or result.output_json is None:
            raise RuntimeError(result.error_code or f"{tool_name} failed")
        return WarehouseToolResult(
            tool_name=tool_name,
            output=result.output_json,
            audit_ref=result.audit_ref,
        )


def _append_audit_ref(
    refs: tuple[str, ...],
    audit_ref: str | None,
) -> tuple[str, ...]:
    if not audit_ref:
        return refs
    return tuple(dict.fromkeys((*refs, audit_ref)))


def _analysis_text_with_context(
    message: str,
    conversation_context: tuple[dict[str, str], ...],
) -> str:
    """Return sanitized current request plus previous user-only context.

    Assistant messages are intentionally excluded.  They frequently contain
    generated no-data answers, chart labels, and trace text; passing them to
    warehouse lookup makes the resolver search for a whole transcript.
    """
    current = _sanitize_worker_query_text(message, max_chars=300)
    recent_user_turns = [
        _sanitize_worker_query_text(item.get("content", ""), max_chars=160)
        for item in conversation_context[-4:]
        if item.get("role") == "user"
    ]
    recent_user_turns = [item for item in recent_user_turns if item]
    if not recent_user_turns:
        return current
    return "\n".join((current, "recent_user_turns:", *recent_user_turns))


def _normalize_worker_inputs(worker_inputs: dict[str, Any] | None) -> dict[str, Any] | None:
    """Validate ExpertAgent-filled worker placeholders.

    The LLM planner may provide ``worker_inputs``, but these values cross a
    trust boundary.  They must never contain role-marked chat transcripts or
    prior assistant output.  This function accepts only compact scalar fields.
    """
    if not worker_inputs:
        return None
    user_query = _sanitize_worker_query_text(worker_inputs.get("user_query"), max_chars=300)
    security_query = _sanitize_worker_security_text(worker_inputs.get("security_query"))
    indicator_id = _sanitize_indicator_id(worker_inputs.get("indicator_id"))
    chart_type = _normalize_chart_type(str(worker_inputs.get("chart_type") or "line"))
    max_points_per_indicator = _normalize_max_points(
        worker_inputs.get("max_points_per_indicator")
    )
    if not user_query or not security_query:
        return None
    if indicator_id == "roe_ttm" and _WORKER_METRIC_TERM_RE.search(user_query) is None:
        return None
    return {
        "user_query": user_query,
        "security_query": security_query,
        "indicator_id": indicator_id,
        "chart_type": chart_type,
        "max_points_per_indicator": max_points_per_indicator,
    }


_WORKER_CURRENT_USER_MARKER_RE = re.compile(r"(?i)\bcurrent_user\s*:\s*")
_WORKER_ROLE_MARKER_RE = re.compile(r"(?im)^\s*(?:system|user|assistant|current_user)\s*:")
_WORKER_INLINE_ROLE_MARKER_RE = re.compile(r"(?i)\b(?:system|user|assistant|current_user)\s*:")
_WORKER_METRIC_TERM_RE = re.compile(
    r"(?i)(?<![A-Za-z])roe(?:\s*ttm)?(?![A-Za-z])|return\s+on\s+equity|净资产收益率|净资产回报率|净资产回报"
)
_WORKER_SECURITY_TOKEN_RE = re.compile(
    r"(?:\d{6}(?:\.(?:SH|SZ|BJ))?|[\u4e00-\u9fffA-Za-z][\u4e00-\u9fffA-Za-z0-9·（）().-]{1,40})",
    flags=re.IGNORECASE,
)
_WORKER_SECURITY_PREFIXES = (
    "请帮我看一下",
    "请帮我查一下",
    "帮我看一下",
    "帮我查一下",
    "我想看一下",
    "我想看看",
    "我想查询",
    "我想查",
    "我想看",
    "请问",
    "麻烦",
    "帮我",
    "给我看一下",
    "给我查一下",
    "给我看看",
    "给我",
    "想看一下",
    "想看看",
    "想查询",
    "想查",
    "想看",
    "查看一下",
    "查一下",
    "看一下",
    "查询",
    "查看",
    "查查",
    "看看",
    "看",
    "查",
)
_WORKER_SECURITY_STOPWORDS = {
    "user",
    "assistant",
    "current_user",
    "system",
    "roe",
    "ttm",
    "return",
    "equity",
    "净资产收益率",
    "净资产回报率",
    "历史记录",
    "趋势",
    "指标",
    "标的",
    "股票",
}


def _sanitize_worker_query_text(value: object, *, max_chars: int) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    parts = _WORKER_CURRENT_USER_MARKER_RE.split(text)
    if len(parts) > 1:
        text = parts[-1]
    lines: list[str] = []
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if re.match(r"(?i)^(?:assistant|system)\s*:", line):
            continue
        line = re.sub(r"(?i)^(?:user|current_user)\s*:\s*", "", line).strip()
        if line:
            lines.append(line)
    compact = re.sub(r"\s+", " ", " ".join(lines)).strip()
    return compact[:max_chars].strip()


def _sanitize_worker_security_text(value: object) -> str:
    text = _sanitize_worker_query_text(value, max_chars=160)
    if not text or _WORKER_ROLE_MARKER_RE.search(text):
        return ""
    if _WORKER_METRIC_TERM_RE.search(text):
        text = _security_from_metric_question(text)
    else:
        text = _clean_worker_security_candidate(text)
    tokens = [
        token.strip(" 的关于一下这个这只该只股票标的公司")
        for token in _WORKER_SECURITY_TOKEN_RE.findall(text)
    ]
    tokens = [
        token
        for token in tokens
        if token and token.casefold() not in _WORKER_SECURITY_STOPWORDS
    ]
    if not tokens:
        return ""
    candidate = tokens[-1]
    if _WORKER_INLINE_ROLE_MARKER_RE.search(candidate) or len(candidate) > 64:
        return ""
    return candidate


def _security_from_metric_question(value: str) -> str:
    match = _WORKER_METRIC_TERM_RE.search(value)
    if match is None:
        return ""
    before_metric = _clean_worker_security_candidate(value[: match.start()])
    if before_metric:
        return before_metric
    return _clean_worker_security_candidate(value[match.end() :])


def _clean_worker_security_candidate(value: str) -> str:
    text = _WORKER_INLINE_ROLE_MARKER_RE.sub(" ", str(value or ""))
    text = re.sub(r"[：:，,。；;？?！!、/\\|]+", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    text = text.strip(" 的关于一下这个这只该只股票标的公司")
    changed = True
    while changed:
        changed = False
        for prefix in _WORKER_SECURITY_PREFIXES:
            if text.startswith(prefix):
                text = text[len(prefix) :].strip()
                changed = True
    text = text.strip(" 的关于一下这个这只该只股票标的公司")
    text = _WORKER_METRIC_TERM_RE.sub(" ", text)
    return re.sub(r"\s+", " ", text).strip()[:80]


def _sanitize_indicator_id(value: object) -> str:
    indicator_id = str(value or "").strip().casefold()
    if indicator_id == "roe_ttm":
        return "roe_ttm"
    return ""


def _normalize_chart_type(chart_type: str) -> str:
    """Return the supported visualization type for the data worker."""
    if chart_type == "bar":
        return "bar"
    return "line"


def _normalize_max_points(value: object) -> int:
    """Return a bounded history-point count for warehouse reads."""
    try:
        count = int(value) if value is not None else 12
    except (TypeError, ValueError):
        return 12
    return count if 1 <= count <= 100 else 12


def _metric_from_indicator_id(indicator_id: str) -> dict[str, str] | None:
    """Return the supported financial metric selected by ExpertAgent."""
    if indicator_id == "roe_ttm":
        return {"indicator_id": "roe_ttm", "label": "ROE TTM", "unit": "%"}
    return None


def _select_metric_from_catalog(
    indicator_catalog: list[Any],
    *,
    requested_indicator_id: str,
    query_text: str,
) -> dict[str, Any] | None:
    """Select a metric from discovered warehouse metadata, not from prompts."""
    catalog = [_normalize_indicator_catalog_item(item) for item in indicator_catalog]
    requested = requested_indicator_id.strip()
    if requested:
        for item in catalog:
            if item["indicator_id"] == requested:
                return item
    query = query_text.casefold()
    scored: list[tuple[int, dict[str, Any]]] = []
    for item in catalog:
        score = 0
        values = (
            item["indicator_id"],
            item["label"],
            *item["aliases"],
            *item["source_fields"],
        )
        for value in values:
            normalized = str(value).casefold()
            if normalized and normalized in query:
                score += max(2, len(normalized))
            elif normalized and any(part and part in query for part in normalized.split("_")):
                score += 1
        if score:
            scored.append((score, item))
    if scored:
        return sorted(scored, key=lambda pair: pair[0], reverse=True)[0][1]
    if len(catalog) == 1:
        return catalog[0]
    return None


def _normalize_indicator_catalog_item(item: Any) -> dict[str, Any]:
    """Normalize discovered indicator metadata for Worker use."""
    data = dict(item) if isinstance(item, dict) else {
        "indicator_id": getattr(item, "indicator_id", ""),
        "label": getattr(item, "label", ""),
        "unit": getattr(item, "unit", ""),
        "value_scale": getattr(item, "value_scale", None),
        "aliases": getattr(item, "aliases", ()),
        "coverage": getattr(item, "coverage", {}),
        "source_fields": getattr(item, "source_fields", ()),
    }
    indicator_id = str(data.get("indicator_id") or "").strip()
    aliases = tuple(str(value) for value in data.get("aliases") or () if str(value).strip())
    source_fields = tuple(
        str(value) for value in data.get("source_fields") or () if str(value).strip()
    )
    return {
        "indicator_id": indicator_id,
        "label": str(data.get("label") or indicator_id.replace("_", " ")).strip(),
        "unit": str(data.get("unit") or "").strip(),
        "value_scale": data.get("value_scale"),
        "aliases": aliases,
        "coverage": data.get("coverage") or {},
        "source_fields": source_fields,
    }


def _profile_security_id(profile: Any) -> str:
    if isinstance(profile, dict):
        return str(profile.get("security_id") or "")
    return str(getattr(profile, "security_id", "") or "")


def _profile_name(profile: Any) -> str:
    if isinstance(profile, dict):
        return str(profile.get("name") or profile.get("security_id") or "")
    return str(getattr(profile, "name", "") or getattr(profile, "security_id", "") or "")


def _history_security_id(value: Any) -> str:
    if isinstance(value, dict):
        return str(value.get("security_id") or "")
    return str(getattr(value, "security_id", "") or "")


def _history_provider(value: Any) -> str:
    if isinstance(value, dict):
        return str(value.get("provider") or "")
    return str(getattr(value, "provider", "") or "")


def _history_fact_id(value: Any) -> str:
    if isinstance(value, dict):
        return str(value.get("fact_id") or "")
    return str(getattr(value, "fact_id", "") or "")


def _history_raw_snapshot_id(value: Any) -> str:
    if isinstance(value, dict):
        return str(value.get("raw_snapshot_id") or "")
    return str(getattr(value, "raw_snapshot_id", "") or "")


def _history_numeric_value(value: Any) -> Any:
    if isinstance(value, dict):
        return value.get("numeric_value")
    return getattr(value, "numeric_value", None)


def _history_datetime(value: Any, field_name: str) -> datetime:
    raw = value.get(field_name) if isinstance(value, dict) else getattr(value, field_name)
    if isinstance(raw, datetime):
        return raw if raw.tzinfo is not None else raw.replace(tzinfo=UTC)
    return datetime.fromisoformat(str(raw).replace("Z", "+00:00"))


def _extract_security_codes(message: str) -> list[str]:
    """Extract A-share style security IDs from user text."""
    codes: list[str] = []
    for match in re.finditer(r"\b(\d{6})(?:\.(SH|SZ|BJ))?\b", message, flags=re.IGNORECASE):
        raw_code = match.group(1)
        suffix = match.group(2)
        if suffix:
            codes.append(f"{raw_code}.{suffix.upper()}")
            continue
        if raw_code.startswith(("6", "9")):
            codes.append(f"{raw_code}.SH")
        elif raw_code.startswith(("0", "2", "3")):
            codes.append(f"{raw_code}.SZ")
        else:
            codes.append(raw_code)
    return codes


def _financial_metric_analysis_from_history(
    *,
    run_id: str,
    metric: dict[str, str],
    profiles: list[Any],
    history: list[Any],
    chart_type: str,
    workflow_tool_calls: tuple[str, ...],
    audit_event_refs: tuple[str, ...] = (),
    max_points_per_indicator: int = 12,
) -> FinancialMetricAnalysis:
    """Build table/chart/metric artifacts and a user-facing answer from history."""
    profile_by_security_id = {_profile_security_id(profile): profile for profile in profiles}
    rows = [
        {
            "date": _history_datetime(value, "event_at").date().isoformat(),
            "security_id": _history_security_id(value),
            "name": _profile_name(profile_by_security_id.get(_history_security_id(value)))
            or _history_security_id(value),
            "indicator_id": metric["indicator_id"],
            "metric": metric["label"],
            "value": _metric_display_value(metric, _history_numeric_value(value)),
            "unit": metric["unit"],
            "available_at": _history_datetime(value, "available_at").isoformat(),
            "source": _history_provider(value),
            "fact_id": _history_fact_id(value),
            "raw_snapshot_id": _history_raw_snapshot_id(value),
            "locator": (
                "warehouse://standardized_indicator_facts/"
                f"{_history_fact_id(value) or _history_datetime(value, 'event_at').date()}"
                f"?security_id={_history_security_id(value)}"
                f"&indicator_id={metric['indicator_id']}"
                f"&event_at={_history_datetime(value, 'event_at').isoformat()}"
                f"&available_at={_history_datetime(value, 'available_at').isoformat()}"
                f"&raw_snapshot_id={_history_raw_snapshot_id(value)}"
            ),
        }
        for value in sorted(
            history,
            key=lambda item: (_history_security_id(item), _history_datetime(item, "event_at")),
        )
    ]
    if not rows:
        return _empty_financial_metric_analysis(
            run_id=run_id,
            metric=metric,
            message=_profile_name(profiles[0]) if profiles else "",
            chart_type=chart_type,
            workflow_tool_calls=workflow_tool_calls,
            audit_event_refs=audit_event_refs,
            max_points_per_indicator=max_points_per_indicator,
        )
    latest = rows[-1]
    previous = rows[-2] if len(rows) > 1 else None
    evidence_refs = tuple(
        dict.fromkeys(str(row["fact_id"]) for row in rows if row.get("fact_id"))
    )
    delta = (
        round(float(latest["value"]) - float(previous["value"]), 2)
        if previous is not None
        else None
    )
    answer = _financial_metric_answer(
        latest=latest,
        previous=previous,
        delta=delta,
    )
    table_artifact = make_context_artifact(
        artifact_id=f"ctx_{run_id}_financial_metric_table",
        run_id=run_id,
        artifact_type="analysis_table",
        producer_agent=DataQuestionWorker.name,
        payload_json={
            "columns": [
                "date",
                "security_id",
                "name",
                "indicator_id",
                "metric",
                "value",
                "unit",
                "available_at",
                "source",
                "fact_id",
                "raw_snapshot_id",
                "locator",
            ],
            "rows": rows,
        },
        source_refs=("warehouse:indicator_history_pit",),
        evidence_refs=evidence_refs,
    )
    chart_artifact = make_context_artifact(
        artifact_id=f"ctx_{run_id}_financial_metric_chart",
        run_id=run_id,
        artifact_type="chart_spec",
        producer_agent=DataQuestionWorker.name,
        payload_json={
            "chart_type": chart_type,
            "title": f"{latest['name']} {metric['label']} 趋势",
            "x_field": "date",
            "y_field": "value",
            "unit": metric["unit"],
            "series": [
                {
                    "metric": metric["indicator_id"],
                    "label": metric["label"],
                    "points": [{"x": row["date"], "y": row["value"]} for row in rows],
                }
            ],
        },
        source_refs=("warehouse:indicator_history_pit",),
        evidence_refs=evidence_refs,
    )
    svg = _render_financial_metric_svg(
        title=f"{latest['name']} {metric['label']} 趋势",
        points=[{"x": row["date"], "y": row["value"]} for row in rows],
        unit=metric["unit"],
        chart_type=chart_type,
    )
    image_artifact = make_context_artifact(
        artifact_id=f"ctx_{run_id}_financial_metric_image",
        run_id=run_id,
        artifact_type="visualization_image",
        producer_agent=DataQuestionWorker.name,
        payload_json={
            "image_format": "svg",
            "chart_type": chart_type,
            "title": f"{latest['name']} {metric['label']} 趋势",
            "svg": svg,
        },
        source_refs=("warehouse:indicator_history_pit",),
        evidence_refs=evidence_refs,
    )
    metric_artifact = make_context_artifact(
        artifact_id=f"ctx_{run_id}_financial_metric_latest",
        run_id=run_id,
        artifact_type="computed_metric",
        producer_agent=DataQuestionWorker.name,
        payload_json={
            "security_id": latest["security_id"],
            "name": latest["name"],
            "indicator_id": metric["indicator_id"],
            "label": metric["label"],
            "latest_date": latest["date"],
            "latest_value": latest["value"],
            "previous_value": previous["value"] if previous else None,
            "delta": delta,
            "unit": metric["unit"],
            "available_at": latest["available_at"],
        },
        source_refs=("warehouse:indicator_history_pit",),
        evidence_refs=evidence_refs,
    )
    worker_activity_artifact = _worker_activity_artifact(
        run_id=run_id,
        analysis_text=f"{latest['name']} {latest['metric']}",
        chart_type=chart_type,
        indicator_id=metric["indicator_id"],
        rows=rows,
        security_ids=tuple(_profile_security_id(profile) for profile in profiles[:3]),
        tool_calls=workflow_tool_calls,
        max_points_per_indicator=max_points_per_indicator,
        evidence_refs=evidence_refs,
    )
    return FinancialMetricAnalysis(
        answer=answer,
        table_artifact=table_artifact,
        chart_artifact=chart_artifact,
        image_artifact=image_artifact,
        metric_artifact=metric_artifact,
        table_rows=rows,
        worker_activity_artifact=worker_activity_artifact,
        audit_event_refs=audit_event_refs,
    )


def _empty_financial_metric_analysis(
    *,
    run_id: str,
    metric: dict[str, str],
    message: str,
    chart_type: str = "line",
    workflow_tool_calls: tuple[str, ...] = (),
    audit_event_refs: tuple[str, ...] = (),
    max_points_per_indicator: int = 12,
) -> FinancialMetricAnalysis:
    """Return a traceable empty analysis when the warehouse has no matching facts."""
    display_message = (
        _sanitize_worker_security_text(message)
        or _sanitize_worker_query_text(message, max_chars=80)
        or "该标的"
    )
    answer = (
        f"没有在当前 PIT 数据仓库中找到 {display_message} 的 {metric['label']} "
        "历史记录。这个回答只说明数据缺口，不构成投资建议。"
    )
    table_artifact = make_context_artifact(
        artifact_id=f"ctx_{run_id}_financial_metric_table",
        run_id=run_id,
        artifact_type="analysis_table",
        producer_agent=DataQuestionWorker.name,
        payload_json={"columns": ["date", "security_id", "metric", "value"], "rows": []},
        source_refs=("warehouse:indicator_history_pit",),
    )
    chart_artifact = make_context_artifact(
        artifact_id=f"ctx_{run_id}_financial_metric_chart",
        run_id=run_id,
        artifact_type="chart_spec",
        producer_agent=DataQuestionWorker.name,
        payload_json={
            "chart_type": chart_type,
            "title": f"{metric['label']} 趋势",
            "x_field": "date",
            "y_field": "value",
            "unit": metric["unit"],
            "series": [{"metric": metric["indicator_id"], "label": metric["label"], "points": []}],
        },
        source_refs=("warehouse:indicator_history_pit",),
    )
    image_artifact = make_context_artifact(
        artifact_id=f"ctx_{run_id}_financial_metric_image",
        run_id=run_id,
        artifact_type="visualization_image",
        producer_agent=DataQuestionWorker.name,
        payload_json={
            "image_format": "svg",
            "chart_type": chart_type,
            "title": f"{metric['label']} 趋势",
            "svg": _render_financial_metric_svg(
                title=f"{metric['label']} 趋势",
                points=[],
                unit=metric["unit"],
                chart_type=chart_type,
            ),
        },
        source_refs=("warehouse:indicator_history_pit",),
    )
    metric_artifact = make_context_artifact(
        artifact_id=f"ctx_{run_id}_financial_metric_latest",
        run_id=run_id,
        artifact_type="computed_metric",
        producer_agent=DataQuestionWorker.name,
        payload_json={
            "indicator_id": metric["indicator_id"],
            "label": metric["label"],
            "latest_value": None,
            "unit": metric["unit"],
        },
        source_refs=("warehouse:indicator_history_pit",),
    )
    worker_activity_artifact = _worker_activity_artifact(
        run_id=run_id,
        analysis_text=display_message,
        chart_type=chart_type,
        indicator_id=metric["indicator_id"],
        rows=[],
        security_ids=(),
        tool_calls=workflow_tool_calls,
        max_points_per_indicator=max_points_per_indicator,
    )
    return FinancialMetricAnalysis(
        answer=answer,
        table_artifact=table_artifact,
        chart_artifact=chart_artifact,
        image_artifact=image_artifact,
        metric_artifact=metric_artifact,
        table_rows=[],
        worker_activity_artifact=worker_activity_artifact,
        audit_event_refs=audit_event_refs,
    )


def _worker_activity_artifact(
    *,
    run_id: str,
    analysis_text: str,
    chart_type: str,
    indicator_id: str,
    rows: list[dict[str, Any]],
    security_ids: tuple[str, ...],
    tool_calls: tuple[str, ...],
    max_points_per_indicator: int = 12,
    evidence_refs: tuple[str, ...] = (),
) -> ContextArtifact:
    """Return a frontend-safe activity log for the DataQuestionWorker."""
    python_code = "\n".join(
        (
            "# DataQuestionWorker generated this deterministic analysis plan.",
            "decision_at = datetime.now(UTC)",
            f"security_ids = {security_ids!r}",
            f"indicator_ids = ({indicator_id!r},)",
            "history = warehouse.indicator_history(",
            "    IndicatorHistoryQuery(",
            "        security_ids=security_ids,",
            "        indicator_ids=indicator_ids,",
            "        start_date=decision_at.date() - timedelta(days=1460),",
            "        end_date=decision_at.date(),",
            "        decision_at=decision_at,",
            f"        max_points_per_indicator={max_points_per_indicator},",
            "    )",
            ")",
            "rows = normalize_metric_history(history)",
            f"svg = render_financial_metric_svg(rows, chart_type={chart_type!r})",
        )
    )
    return make_context_artifact(
        artifact_id=f"ctx_{run_id}_data_question_worker_activity",
        run_id=run_id,
        artifact_type="worker_activity",
        producer_agent=DataQuestionWorker.name,
        payload_json={
            "expert_agent": "DataExpertAgent",
            "worker_agent": DataQuestionWorker.name,
            "skill_id": DataQuestionWorker.skill_id,
            "workflow_runtime": "langgraph",
            "summary": "读取 PIT 财务指标并生成可视化产物。",
            "tool_calls": list(tool_calls),
            "max_points_per_indicator": max_points_per_indicator,
            "actions": [
                {
                    "name": "恢复上下文",
                    "detail": f"读取当前问题并识别为 {indicator_id} 指标分析任务。",
                },
                {
                    "name": "解析证券",
                    "detail": f"解析到证券范围：{', '.join(security_ids) or '未匹配'}",
                },
                {
                    "name": "查询 PIT 指标",
                    "detail": (
                        f"读取 {indicator_id}，并要求 available_at <= decision_at。"
                    ),
                },
                {
                    "name": "标准化指标",
                    "detail": f"将历史指标转换为前端展示行，共 {len(rows)} 条。",
                },
                {
                    "name": "生成图像",
                    "detail": f"生成 {chart_type} SVG 图像产物。",
                },
            ],
            "python_code": python_code,
        },
        source_refs=("warehouse:indicator_history_pit", "agent:DataQuestionWorker"),
        evidence_refs=evidence_refs,
    )


def _render_financial_metric_svg(
    *,
    title: str,
    points: list[dict[str, Any]],
    unit: str,
    chart_type: str,
) -> str:
    """Render a self-contained SVG image for a financial metric visualization."""
    width = 760
    height = 320
    plot_left = 56
    plot_top = 64
    plot_width = 640
    plot_height = 180
    title_escaped = _svg_escape(title)
    if not points:
        return (
            f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
            f'viewBox="0 0 {width} {height}" role="img" aria-label="{title_escaped}">'
            '<rect width="100%" height="100%" rx="18" fill="#f8fafc"/>'
            f'<text x="32" y="42" font-size="22" font-weight="700" fill="#111827">'
            f"{title_escaped}</text>"
            '<text x="32" y="160" font-size="16" fill="#64748b">暂无可绘制数据</text>'
            "</svg>"
        )
    values = [float(point["y"]) for point in points]
    min_value = min(values)
    max_value = max(values)
    if min_value == max_value:
        min_value -= 1
        max_value += 1
    padding = (max_value - min_value) * 0.12
    domain_min = min_value - padding
    domain_max = max_value + padding

    def y_coord(value: float) -> float:
        ratio = (value - domain_min) / (domain_max - domain_min)
        return plot_top + plot_height - ratio * plot_height

    background = (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
        f'viewBox="0 0 {width} {height}" role="img" aria-label="{title_escaped}">'
        '<rect width="100%" height="100%" rx="18" fill="#f8fafc"/>'
        f'<text x="32" y="42" font-size="22" font-weight="700" fill="#111827">'
        f"{title_escaped}</text>"
        f'<text x="{plot_left}" y="{plot_top + plot_height + 36}" '
        'font-size="13" fill="#64748b">'
        f'{_svg_escape(str(points[0]["x"]))} - {_svg_escape(str(points[-1]["x"]))}'
        "</text>"
        f'<line x1="{plot_left}" y1="{plot_top + plot_height}" '
        f'x2="{plot_left + plot_width}" y2="{plot_top + plot_height}" '
        'stroke="#cbd5e1" stroke-width="1"/>'
    )
    latest_label = (
        f'<text x="{plot_left + plot_width}" y="42" text-anchor="end" '
        'font-size="22" font-weight="700" fill="#111827">'
        f'{values[-1]:.2f}{_svg_escape(unit)}</text>'
    )
    if chart_type == "bar":
        gap = 10
        bar_width = max(10, (plot_width - gap * (len(points) - 1)) / len(points))
        bars = []
        for index, point in enumerate(points):
            value = float(point["y"])
            x = plot_left + index * (bar_width + gap)
            y = y_coord(value)
            bar_height = plot_top + plot_height - y
            bars.append(
                f'<rect x="{x:.2f}" y="{y:.2f}" width="{bar_width:.2f}" '
                f'height="{bar_height:.2f}" rx="6" fill="#2563eb"/>'
            )
        return background + latest_label + "".join(bars) + "</svg>"

    if len(points) == 1:
        coordinates = [(plot_left + plot_width / 2, y_coord(values[0]))]
    else:
        coordinates = [
            (
                plot_left + (plot_width * index / (len(points) - 1)),
                y_coord(float(point["y"])),
            )
            for index, point in enumerate(points)
        ]
    line_points = " ".join(f"{x:.2f},{y:.2f}" for x, y in coordinates)
    circles = "".join(
        f'<circle cx="{x:.2f}" cy="{y:.2f}" r="4" fill="#ffffff" '
        'stroke="#2563eb" stroke-width="3"/>'
        for x, y in coordinates
    )
    return (
        background
        + latest_label
        + f'<polyline points="{line_points}" fill="none" stroke="#2563eb" '
        'stroke-width="4" stroke-linecap="round" stroke-linejoin="round"/>'
        + circles
        + "</svg>"
    )


def _svg_escape(value: str) -> str:
    """Escape text embedded in generated SVG."""
    return (
        value.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def _metric_display_value(metric: dict[str, Any], value: Any) -> float:
    """Convert stored numeric metric values to user-facing units."""
    numeric = float(value)
    value_scale = metric.get("value_scale")
    if value_scale is not None:
        numeric *= float(value_scale)
    elif metric.get("unit") == "%" and abs(numeric) <= 1.5:
        numeric *= 100
    return round(numeric, 2)


def _financial_metric_answer(
    *,
    latest: dict[str, Any],
    previous: dict[str, Any] | None,
    delta: float | None,
) -> str:
    """Return a concise, data-grounded financial metric answer."""
    base = (
        f"{latest['name']}（{latest['security_id']}）最近一期 {latest['metric']} "
        f"为 {latest['value']:.2f}{latest['unit']}，报告期 {latest['date']}，"
        f"该数据在 {latest['available_at']} 后可用。"
    )
    if previous is None or delta is None:
        return base + " 当前仓库没有足够的上一期数据计算趋势。"
    direction = "上升" if delta > 0 else "下降" if delta < 0 else "持平"
    delta_unit = "个百分点" if latest["unit"] == "%" else latest["unit"]
    return (
        base
        + f" 相比上一期 {previous['date']} 的 {previous['value']:.2f}{previous['unit']}，"
        + f"{direction} {abs(delta):.2f}{delta_unit}。"
        + " 以上为数据事实整理，不构成投资建议。"
    )
