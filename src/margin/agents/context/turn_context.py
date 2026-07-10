"""Deterministic, user-confirmed state for one conversational turn."""

from __future__ import annotations

import re
from collections.abc import Sequence
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

InheritedTurnField = Literal[
    "security_query",
    "indicator_id",
    "chart_type",
    "max_points_per_indicator",
]


class ResolvedTurnContext(BaseModel):
    """Canonical query slots resolved from user-authored state only.

    The current user turn is authoritative. Missing slots may be inherited only
    from a ``ResolvedTurnContext`` persisted on an earlier *user* message. Raw
    assistant or planner text is never an input to this model.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: Literal["resolved-turn-v1"] = "resolved-turn-v1"
    current_user_text: str
    intent: Literal["financial_metric", "unknown"] = "unknown"
    security_query: str | None = None
    indicator_id: str | None = None
    chart_type: Literal["line", "bar"] | None = None
    max_points_per_indicator: int | None = Field(default=None, ge=1, le=100)
    inherited_fields: tuple[InheritedTurnField, ...] = ()

    @property
    def executable_financial_metric(self) -> bool:
        """Return whether the resolved state is complete enough for the data worker."""
        return bool(
            self.intent == "financial_metric"
            and self.security_query
            and self.indicator_id
        )

    def financial_metric_worker_inputs(self) -> dict[str, Any] | None:
        """Return canonical worker inputs without planner/assistant-derived keys."""
        if not self.executable_financial_metric:
            return None
        query_text = self.current_user_text
        if self.indicator_id == "roe_ttm" and _ROE_RE.search(query_text) is None:
            query_text = f"{query_text} ROE".strip()
        return {
            "user_query": query_text,
            "security_query": self.security_query,
            "indicator_id": self.indicator_id,
            "chart_type": self.chart_type or "line",
            "max_points_per_indicator": self.max_points_per_indicator or 12,
        }


_CURRENT_USER_MARKER_RE = re.compile(r"(?i)\bcurrent_user\s*:\s*")
_ROE_RE = re.compile(
    r"(?i)(?<![A-Za-z])roe(?:\s*ttm)?(?![A-Za-z])|return\s+on\s+equity|"
    r"净资产收益率|净资产回报率|净资产回报"
)
_SECURITY_CODE_RE = re.compile(
    r"(?<!\d)(\d{6})(?:\.(SH|SZ|BJ))?(?![A-Za-z0-9])",
    re.IGNORECASE,
)
_POINT_LIMIT_RE = re.compile(
    r"(?:最近|近)\s*(\d{1,3})\s*(?:期|个?季度|季|年)",
    re.IGNORECASE,
)
_FOLLOW_UP_RE = re.compile(
    r"最近|近\s*\d|历史|趋势|这几期|前几期|同期|季度|财报|柱状图|折线图|"
    r"(?:这|那|该)(?:个|只|家)?",
    re.IGNORECASE,
)
_SECURITY_TOKEN_RE = re.compile(
    r"[\u4e00-\u9fffA-Za-z][\u4e00-\u9fffA-Za-z0-9·（）().-]{1,40}",
    re.IGNORECASE,
)
_SECURITY_PREFIXES = (
    "请帮我看一下",
    "请帮我查一下",
    "帮我看一下",
    "帮我查一下",
    "我想看一下",
    "我想看看",
    "我想查询",
    "我想查",
    "我想看",
    "给我看一下",
    "给我查一下",
    "看一下",
    "查一下",
    "查询",
    "查看",
    "看看",
)
_SECURITY_STOPWORDS = {
    "roe",
    "ttm",
    "return",
    "equity",
    "净资产收益率",
    "净资产回报率",
    "最近",
    "历史",
    "趋势",
    "指标",
    "股票",
}


def resolve_turn_context(
    current_user_message: object,
    *,
    previous_messages: Sequence[object] = (),
) -> ResolvedTurnContext:
    """Resolve current slots, then inherit only from persisted user state."""
    current_text = _current_user_text(current_user_message)
    current_indicator = "roe_ttm" if _ROE_RE.search(current_text) else None
    current_security = _security_query(current_text, has_metric=current_indicator is not None)
    current_chart = _chart_type(current_text)
    current_limit = _point_limit(current_text)
    prior = _latest_user_resolved_context(previous_messages)

    has_financial_signal = bool(current_indicator or current_security or current_limit)
    is_follow_up = bool(
        prior
        and prior.executable_financial_metric
        and (
            current_indicator
            or current_chart
            or current_limit
            or (current_security and _FOLLOW_UP_RE.search(current_text))
        )
    )
    if not has_financial_signal and not is_follow_up:
        return ResolvedTurnContext(current_user_text=current_text)

    inherited: list[InheritedTurnField] = []
    security_query = current_security
    indicator_id = current_indicator
    chart_type = current_chart
    max_points = current_limit
    if is_follow_up and prior is not None:
        if not security_query and prior.security_query:
            security_query = prior.security_query
            inherited.append("security_query")
        if not indicator_id and prior.indicator_id:
            indicator_id = prior.indicator_id
            inherited.append("indicator_id")
        if not chart_type and prior.chart_type:
            chart_type = prior.chart_type
            inherited.append("chart_type")
        if max_points is None and prior.max_points_per_indicator is not None:
            max_points = prior.max_points_per_indicator
            inherited.append("max_points_per_indicator")

    intent: Literal["financial_metric", "unknown"] = (
        "financial_metric" if indicator_id or is_follow_up else "unknown"
    )
    if intent == "financial_metric":
        chart_type = chart_type or "line"
        max_points = max_points or 12
    return ResolvedTurnContext(
        current_user_text=current_text,
        intent=intent,
        security_query=security_query,
        indicator_id=indicator_id,
        chart_type=chart_type,
        max_points_per_indicator=max_points,
        inherited_fields=tuple(inherited),
    )


def _latest_user_resolved_context(
    messages: Sequence[object],
) -> ResolvedTurnContext | None:
    """Read only typed state persisted on prior user messages."""
    for message in reversed(messages):
        role = _message_value(message, "role")
        if role != "user":
            continue
        payload = _message_value(message, "payload")
        if not isinstance(payload, dict):
            continue
        raw_context = payload.get("resolved_turn_context")
        if not isinstance(raw_context, dict):
            continue
        try:
            context = ResolvedTurnContext.model_validate(raw_context)
        except ValueError:
            continue
        if context.executable_financial_metric:
            return context
    return None


def _message_value(message: object, field: str) -> Any:
    if isinstance(message, dict):
        return message.get(field)
    return getattr(message, field, None)


def _current_user_text(value: object, *, max_chars: int = 2000) -> str:
    text = str(value or "").strip()
    parts = _CURRENT_USER_MARKER_RE.split(text)
    if len(parts) > 1:
        text = parts[-1]
    lines: list[str] = []
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or re.match(r"(?i)^(?:assistant|system)\s*:", line):
            continue
        line = re.sub(r"(?i)^(?:user|current_user)\s*:\s*", "", line).strip()
        if line:
            lines.append(line)
    return re.sub(r"\s+", " ", " ".join(lines)).strip()[:max_chars]


def _security_query(text: str, *, has_metric: bool) -> str | None:
    code_match = _SECURITY_CODE_RE.search(text)
    if code_match is not None:
        code = code_match.group(1)
        suffix = code_match.group(2)
        if suffix:
            return f"{code}.{suffix.upper()}"
        if code.startswith(("6", "9")):
            return f"{code}.SH"
        if code.startswith(("0", "2", "3")):
            return f"{code}.SZ"
        return code
    if not has_metric:
        return None
    metric_match = _ROE_RE.search(text)
    if metric_match is None:
        return None
    before = _clean_security_candidate(text[: metric_match.start()])
    after = _clean_security_candidate(text[metric_match.end() :])
    tokens = _SECURITY_TOKEN_RE.findall(before or after)
    cleaned = [
        token.strip(" 的关于一下这个这只该只股票标的公司")
        for token in tokens
        if token.strip(" 的关于一下这个这只该只股票标的公司").casefold()
        not in _SECURITY_STOPWORDS
    ]
    return cleaned[-1] if cleaned else None


def _clean_security_candidate(value: str) -> str:
    text = re.sub(r"[：:，,。；;？?！!、/\\|]+", " ", str(value or ""))
    text = re.sub(r"\s+", " ", text).strip(" 的关于一下这个这只该只股票标的公司")
    changed = True
    while changed:
        changed = False
        for prefix in _SECURITY_PREFIXES:
            if text.startswith(prefix):
                text = text[len(prefix) :].strip()
                changed = True
    text = re.sub(r"(?:最近|近几期|近几年|历史|趋势)$", "", text).strip()
    return text[:80]


def _point_limit(text: str) -> int | None:
    match = _POINT_LIMIT_RE.search(text)
    if match is None:
        return None
    value = int(match.group(1))
    return value if 1 <= value <= 100 else None


def _chart_type(text: str) -> Literal["line", "bar"] | None:
    if "柱" in text or re.search(r"(?i)\bbar\b", text):
        return "bar"
    if "折线" in text or re.search(r"(?i)\bline\b", text):
        return "line"
    return None
