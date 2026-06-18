"""审计日志 — 记录每次 Provider 调用的参数摘要与结果状态（架构 §22 审计日志不可修改）。

对应 plan 0101.3：每次调用记录参数摘要与结果状态。
对应架构 §4.2.1：Provider 必须记录 fetched_at、available_at、原始响应哈希。
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from margin.core.provider import CallResult


class AuditRecord(BaseModel):
    """一条不可变的审计记录。"""

    provider_name: str
    provider_version: str
    method: str
    params_summary: dict[str, Any]
    success: bool
    error: str | None = None
    fetched_at: datetime
    available_at: datetime | None = None
    response_hash: str | None = None
    cost: float = 0.0
    latency_ms: float | None = None
    attempt_count: int = 1
    from_fallback: bool = False
    trace_id: str = Field(default_factory=lambda: "")

    model_config = {"frozen": True}


def compute_hash(data: Any) -> str:
    """计算数据的 SHA256 哈希，用于原始响应哈希校验。"""
    if data is None:
        return "sha256:none"
    serialized = json.dumps(data, sort_keys=True, default=str, ensure_ascii=False)
    return "sha256:" + hashlib.sha256(serialized.encode("utf-8")).hexdigest()


class AuditLogger:
    """审计日志写入器。

    MVP 阶段使用追加写 JSONL 文件，保证只追加不修改。
    后续 1002 会迁移到 PostgreSQL 不可变审计表。
    """

    def __init__(self, log_path: Path | None = None) -> None:
        self._log_path = log_path or Path.home() / ".margin" / "audit" / "provider_calls.jsonl"
        self._log_path.parent.mkdir(parents=True, exist_ok=True)

    def log_call(
        self,
        provider_name: str,
        provider_version: str,
        method: str,
        params: dict[str, Any],
        result: CallResult,
        trace_id: str = "",
    ) -> AuditRecord:
        """记录一次 Provider 调用，返回不可变的 AuditRecord。"""
        params_summary = _summarize_params(params)

        record = AuditRecord(
            provider_name=provider_name,
            provider_version=provider_version,
            method=method,
            params_summary=params_summary,
            success=result.success,
            error=result.error,
            fetched_at=result.fetched_at,
            available_at=result.available_at,
            response_hash=result.response_hash,
            cost=result.cost,
            latency_ms=result.latency_ms,
            attempt_count=result.attempt_count,
            from_fallback=result.from_fallback,
            trace_id=trace_id,
        )

        self._append(record)
        return record

    def _append(self, record: AuditRecord) -> None:
        line = record.model_dump_json() + "\n"
        with open(self._log_path, "a", encoding="utf-8") as f:
            f.write(line)

    def read_all(self) -> list[AuditRecord]:
        """读取全部审计记录（用于测试与审计查询）。"""
        if not self._log_path.is_file():
            return []
        records: list[AuditRecord] = []
        for line in self._log_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line:
                records.append(AuditRecord.model_validate_json(line))
        return records


def _summarize_params(params: dict[str, Any]) -> dict[str, Any]:
    """对参数做摘要：截断长值，隐藏敏感字段。"""
    sensitive_keys = {"token", "api_key", "password", "secret"}
    summary: dict[str, Any] = {}
    for key, value in params.items():
        if key.lower() in sensitive_keys:
            summary[key] = "***REDACTED***"
        elif isinstance(value, (list, tuple)) and len(value) > 10:
            summary[key] = f"{type(value).__name__}[len={len(value)}]"
        elif isinstance(value, str) and len(value) > 200:
            summary[key] = value[:200] + "..."
        else:
            summary[key] = value
    return summary
