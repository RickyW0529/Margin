"""Provider 类型定义、描述符与基类协议。

对应 spec 01 §3 接口契约、架构 §4.2 连接器接口、§8.1 Provider 接入层、§20.1 插件协议。
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime
from enum import StrEnum
from typing import Any, Protocol, runtime_checkable

from pydantic import BaseModel, Field


class ProviderType(StrEnum):
    """Provider 能力类型（架构 §8.1）。"""

    MARKET_DATA = "market_data"
    WEB_SEARCH = "web_search"
    LLM = "llm"
    EMBEDDING = "embedding"
    RERANK = "rerank"
    VECTOR_STORE = "vector_store"
    NOTIFICATION = "notification"


class ProviderStatus(StrEnum):
    """Provider 健康状态。"""

    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNHEALTHY = "unhealthy"
    UNKNOWN = "unknown"


class HealthCheckResult(BaseModel):
    """健康检查结果。"""

    provider_name: str
    status: ProviderStatus
    checked_at: datetime
    latency_ms: float | None = None
    message: str | None = None
    details: dict[str, Any] = Field(default_factory=dict)


class CallResult(BaseModel):
    """Provider 调用结果（含审计与成本元数据）。"""

    provider_name: str
    provider_version: str
    success: bool
    data: Any = None
    error: str | None = None
    fetched_at: datetime = Field(default_factory=lambda: datetime.now())
    available_at: datetime | None = None
    response_hash: str | None = None
    cost: float = 0.0
    latency_ms: float | None = None
    attempt_count: int = 1
    from_fallback: bool = False


class ProviderDescriptor(BaseModel):
    """Provider 元数据描述符（对应架构 §20.1 插件协议 + §8.1 Provider 要求）。

    描述 Provider 的身份、能力、Secret 引用与配置，不含敏感凭据。
    """

    name: str
    version: str
    provider_type: ProviderType
    capabilities: list[str] = Field(default_factory=list)
    secret_refs: list[str] = Field(default_factory=list)
    config: dict[str, Any] = Field(default_factory=dict)

    model_config = {"frozen": True}


class BaseProvider(ABC):
    """所有 Provider 的抽象基类。

    子类必须实现 descriptor 和 healthcheck。
    具体业务方法（如 get_bars）由各类型的 Protocol 定义（见下方）。
    """

    @property
    @abstractmethod
    def descriptor(self) -> ProviderDescriptor:
        """返回此 Provider 的元数据描述符。"""

    @abstractmethod
    def healthcheck(self) -> HealthCheckResult:
        """执行健康检查，返回状态。"""


# ---------------------------------------------------------------------------
# 业务 Protocol — 结构化子类型（架构 §4.2）
# ---------------------------------------------------------------------------


@runtime_checkable
class MarketDataProvider(Protocol):
    """A 股市场数据 Provider 协议（架构 §4.2）。"""

    def get_securities(self, as_of: datetime) -> list[dict[str, Any]]:
        ...

    def get_bars(
        self,
        symbols: list[str],
        start: datetime,
        end: datetime,
        frequency: str = "1d",
    ) -> list[dict[str, Any]]:
        ...

    def get_adjustment_factors(
        self,
        symbols: list[str],
        start: datetime,
        end: datetime,
    ) -> list[dict[str, Any]]:
        ...

    def get_financials(
        self,
        symbols: list[str],
        start: datetime,
        end: datetime,
    ) -> list[dict[str, Any]]:
        ...

    def get_index_members(self, index_code: str, as_of: datetime) -> list[dict[str, Any]]:
        ...


@runtime_checkable
class WebSearchProvider(Protocol):
    """WebSearch Provider 协议（架构 §6.2.1）。"""

    def search(self, query: str, max_results: int = 10) -> list[dict[str, Any]]:
        ...
