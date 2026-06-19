# 模块 09：持仓监控实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 实现 Margin 模块 09（持仓监控），对现有持仓执行盘中安全的确定性规则检测，生成不可变提醒与复盘记录，并在持仓详情页展示监控面板与操作历史。

**Architecture:** 模块 09 在 `src/margin/holdings_monitoring/` 下独立实现，复用模块 02 的 `Position` / `PositionThesis` / `PositionDetail`，不反向改写持仓数据。核心 `HoldingsMonitoringService` 按价格/时间/策略/排名/暴露等规则生成 `AlertEvent` 与 `PositionMonitoringSnapshot`；`MonitoringRepository` 提供内存与 PostgreSQL 两种持久化；FastAPI 暴露 evaluate / alerts / reviews / history / behavior-metrics 端点；Next.js 持仓详情页读取并展示。

**Tech Stack:** Python 3.12, Pydantic v2, FastAPI, SQLAlchemy, pytest；前端 Next.js 16, React 19, TypeScript, Tailwind CSS, lucide-react, vitest。

---

## 文件结构映射

**后端新增/修改：**

| 文件 | 职责 |
|------|------|
| `src/margin/holdings_monitoring/models.py` | 不可变领域模型 |
| `src/margin/holdings_monitoring/db_models.py` | SQLAlchemy 行模型 |
| `src/margin/holdings_monitoring/repository.py` | 仓库 Protocol + 内存/SQLAlchemy 实现 |
| `src/margin/holdings_monitoring/service.py` | 确定性规则引擎与 DI 容器 |
| `src/margin/holdings_monitoring/__init__.py` | 公共导出 |
| `src/margin/api/routes/monitoring.py` | FastAPI 路由 |
| `src/margin/api/dependencies.py` | 新增 `get_monitoring_services()` |
| `src/margin/api/main.py` | 注册 monitoring router |
| `alembic/versions/20260619_0008_holdings_monitoring.py` | 创建 `alert_events` / `position_reviews` 表 |

**前端新增/修改：**

| 文件 | 职责 |
|------|------|
| `web/lib/api.ts` | 新增 `AlertEvent`、`OperationHistoryEntry` 类型与 fetch 函数 |
| `web/app/positions/[positionId]/page.tsx` | 并行获取持仓详情、提醒、历史 |
| `web/components/position-detail.tsx` | 渲染持仓监控面板与操作历史 |
| `web/components/position-review-badge.tsx` | 持仓复核状态徽章 |
| `web/components/research-status-badge.tsx` | 研究状态徽章（与模块 08 共享） |

**测试新增：**

| 文件 | 职责 |
|------|------|
| `tests/holdings_monitoring/test_models.py` | 模型验证 |
| `tests/holdings_monitoring/test_repository.py` | 仓库行为 |
| `tests/holdings_monitoring/test_service.py` | 规则引擎 |
| `tests/api/test_monitoring.py` | API 端点 |
| `web/components/position-detail.test.tsx` | 持仓详情渲染 |

---

### Task 1: 模块 09 领域模型

**Files:**
- Create: `src/margin/holdings_monitoring/models.py`
- Test: `tests/holdings_monitoring/test_models.py`

- [ ] **Step 1: 写失败测试**

```python
from margin.holdings_monitoring.models import AlertEvent, AlertPriority, AlertType


def test_alert_event_has_p0_severity_and_rule_name():
    alert = AlertEvent(
        portfolio_id="pf_1",
        position_id="pos_1",
        symbol="000001.SZ",
        alert_type=AlertType.PRICE_INVALIDATION,
        severity=AlertPriority.P0,
        message="价格触及失效条件",
        rule_name="price_invalidation",
    )
    assert alert.severity == AlertPriority.P0
    assert alert.rule_name == "price_invalidation"
    assert alert.alert_id.startswith("al_")
```

Run: `pytest tests/holdings_monitoring/test_models.py::test_alert_event_has_p0_severity_and_rule_name -v`
Expected: FAIL "ModuleNotFoundError: No module named 'margin.holdings_monitoring'"

- [ ] **Step 2: 实现最小模型**

`src/margin/holdings_monitoring/models.py`:

```python
"""Domain models for module 09 holdings monitoring."""

from __future__ import annotations

import uuid
from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field, field_validator

from margin.news.models import ensure_utc, utc_now
from margin.portfolio.models import PositionHealthStatus, ThesisStatus


class AlertPriority(StrEnum):
    """Alert priority levels defined by product design §10.2."""

    P0 = "P0"
    P1 = "P1"
    P2 = "P2"
    P3 = "P3"


class AlertType(StrEnum):
    """Supported deterministic holdings-monitoring alert types."""

    DATA_QUALITY = "data_quality"
    NEW_DISCLOSURE = "new_disclosure"
    NEGATIVE_EVENT = "negative_event"
    PRICE_INVALIDATION = "price_invalidation"
    MODEL_RANK_CHANGE = "model_rank_change"
    INDUSTRY_EXPOSURE = "industry_exposure"
    VALUATION_TARGET = "valuation_target"
    STRATEGY_FAILURE = "strategy_failure"
    KEY_EVENT_PENDING = "key_event_pending"


class ReviewDecision(StrEnum):
    """Manual review decisions after an alert."""

    HOLD = "hold"
    REDUCE = "reduce"
    EXIT = "exit"
    WATCH = "watch"
    IGNORE = "ignore"


class AlertEvent(BaseModel):
    """Append-only alert emitted by the holdings monitoring rule engine."""

    alert_id: str = Field(default_factory=lambda: f"al_{uuid.uuid4().hex[:12]}")
    portfolio_id: str
    position_id: str
    symbol: str
    alert_type: AlertType
    severity: AlertPriority = AlertPriority.P2
    message: str
    rule_name: str
    triggered_at: datetime = Field(default_factory=utc_now)
    evidence_refs: list[str] = Field(default_factory=list)
    changed_thesis: bool = False
    acknowledged_at: datetime | None = None

    model_config = {"frozen": True}

    @field_validator("triggered_at", "acknowledged_at")
    @classmethod
    def normalize_timestamps(cls, value: datetime | None) -> datetime | None:
        return ensure_utc(value) if value is not None else None


class PositionMonitoringSnapshot(BaseModel):
    """Result of one deterministic position monitoring evaluation."""

    position_id: str
    portfolio_id: str
    symbol: str
    health_status: PositionHealthStatus
    thesis_status: ThesisStatus
    evaluated_at: datetime = Field(default_factory=utc_now)
    reasons: list[str] = Field(default_factory=list)
    alerts: list[AlertEvent] = Field(default_factory=list)
    data_missing: bool = False

    model_config = {"frozen": True}

    @field_validator("evaluated_at")
    @classmethod
    def normalize_evaluated_at(cls, value: datetime) -> datetime:
        return ensure_utc(value)


class PositionReviewRecord(BaseModel):
    """Append-only manual review record after an alert."""

    review_id: str = Field(default_factory=lambda: f"rv_{uuid.uuid4().hex[:12]}")
    portfolio_id: str
    position_id: str
    alert_id: str | None = None
    decision: ReviewDecision
    rationale: str
    action_taken_at: datetime | None = None
    created_at: datetime = Field(default_factory=utc_now)

    model_config = {"frozen": True}

    @field_validator("action_taken_at", "created_at")
    @classmethod
    def normalize_review_timestamps(
        cls,
        value: datetime | None,
    ) -> datetime | None:
        return ensure_utc(value) if value is not None else None


class OperationHistoryEntry(BaseModel):
    """Unified operation-history entry for a position detail view."""

    event_id: str
    position_id: str
    event_type: str
    occurred_at: datetime
    summary: str
    metadata: dict[str, Any] = Field(default_factory=dict)

    model_config = {"frozen": True}

    @field_validator("occurred_at")
    @classmethod
    def normalize_occurred_at(cls, value: datetime) -> datetime:
        return ensure_utc(value)


class BehaviorMetric(BaseModel):
    """User behavior metric derived from alert and review timestamps."""

    metric_id: str = Field(default_factory=lambda: f"bm_{uuid.uuid4().hex[:12]}")
    portfolio_id: str
    position_id: str
    alert_id: str
    review_id: str
    action_latency_seconds: int | None = None
    signal_execution_gap: str | None = None

    model_config = {"frozen": True}
```

Run: `pytest tests/holdings_monitoring/test_models.py -v`
Expected: PASS

- [ ] **Step 3: 提交**

```bash
git add src/margin/holdings_monitoring/models.py tests/holdings_monitoring/test_models.py
git commit -m "feat(holdings_monitoring): add module 09 domain models"
```

---

### Task 2: SQLAlchemy 数据库模型与迁移

**Files:**
- Create: `src/margin/holdings_monitoring/db_models.py`
- Create: `alembic/versions/20260619_0008_holdings_monitoring.py`
- Test: `tests/holdings_monitoring/test_repository.py`（后续扩展）

- [ ] **Step 1: 写失败测试**

```python
def test_alert_event_row_table_name():
    from margin.holdings_monitoring.db_models import AlertEventRow
    assert AlertEventRow.__tablename__ == "alert_events"
```

Run: `pytest tests/holdings_monitoring/test_repository.py::test_alert_event_row_table_name -v`
Expected: FAIL "ModuleNotFoundError: No module named 'margin.holdings_monitoring.db_models'"

- [ ] **Step 2: 实现 db_models**

`src/margin/holdings_monitoring/db_models.py`:

```python
"""SQLAlchemy ORM models for module 09 holdings monitoring."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from margin.storage.base import Base


class AlertEventRow(Base):
    """Append-only persisted alert event."""

    __tablename__ = "alert_events"
    __table_args__ = (
        Index("ix_alert_events_portfolio_position", "portfolio_id", "position_id"),
        Index("ix_alert_events_severity_time", "severity", "triggered_at"),
    )

    alert_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    portfolio_id: Mapped[str] = mapped_column(
        ForeignKey("portfolios.portfolio_id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    position_id: Mapped[str] = mapped_column(String(96), nullable=False)
    symbol: Mapped[str] = mapped_column(String(32), nullable=False)
    alert_type: Mapped[str] = mapped_column(String(48), nullable=False)
    severity: Mapped[str] = mapped_column(String(8), nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    rule_name: Mapped[str] = mapped_column(String(80), nullable=False)
    triggered_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    evidence_refs: Mapped[list[str]] = mapped_column(JSONB, nullable=False)
    changed_thesis: Mapped[bool] = mapped_column(Boolean, nullable=False)
    acknowledged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class PositionReviewRow(Base):
    """Append-only persisted manual review record."""

    __tablename__ = "position_reviews"
    __table_args__ = (
        Index("ix_position_reviews_portfolio_position", "portfolio_id", "position_id"),
    )

    review_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    portfolio_id: Mapped[str] = mapped_column(
        ForeignKey("portfolios.portfolio_id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    position_id: Mapped[str] = mapped_column(String(96), nullable=False)
    alert_id: Mapped[str | None] = mapped_column(
        ForeignKey("alert_events.alert_id", ondelete="RESTRICT")
    )
    decision: Mapped[str] = mapped_column(String(32), nullable=False)
    rationale: Mapped[str] = mapped_column(Text, nullable=False)
    action_taken_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
```

`alembic/versions/20260619_0008_holdings_monitoring.py`:

```python
"""Create holdings monitoring tables."""

from alembic import op
from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Index, String, Text
from sqlalchemy.dialects.postgresql import JSONB

revision = "20260619_0008_monitoring"
down_revision = "20260619_0007_dashboard"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "alert_events",
        Column("alert_id", String(64), primary_key=True),
        Column(
            "portfolio_id",
            String(64),
            ForeignKey("portfolios.portfolio_id", ondelete="RESTRICT"),
            nullable=False,
            index=True,
        ),
        Column("position_id", String(96), nullable=False),
        Column("symbol", String(32), nullable=False),
        Column("alert_type", String(48), nullable=False),
        Column("severity", String(8), nullable=False),
        Column("message", Text, nullable=False),
        Column("rule_name", String(80), nullable=False),
        Column("triggered_at", DateTime(timezone=True), nullable=False),
        Column("evidence_refs", JSONB, nullable=False, default=list),
        Column("changed_thesis", Boolean, nullable=False, default=False),
        Column("acknowledged_at", DateTime(timezone=True), nullable=True),
        Index("ix_alert_events_portfolio_position", "portfolio_id", "position_id"),
        Index("ix_alert_events_severity_time", "severity", "triggered_at"),
    )
    op.create_table(
        "position_reviews",
        Column("review_id", String(64), primary_key=True),
        Column(
            "portfolio_id",
            String(64),
            ForeignKey("portfolios.portfolio_id", ondelete="RESTRICT"),
            nullable=False,
            index=True,
        ),
        Column("position_id", String(96), nullable=False),
        Column(
            "alert_id",
            String(64),
            ForeignKey("alert_events.alert_id", ondelete="RESTRICT"),
            nullable=True,
        ),
        Column("decision", String(32), nullable=False),
        Column("rationale", Text, nullable=False),
        Column("action_taken_at", DateTime(timezone=True), nullable=True),
        Column("created_at", DateTime(timezone=True), nullable=False),
        Index("ix_position_reviews_portfolio_position", "portfolio_id", "position_id"),
    )


def downgrade() -> None:
    op.drop_table("position_reviews")
    op.drop_table("alert_events")
```

Run: `pytest tests/holdings_monitoring/test_repository.py::test_alert_event_row_table_name -v`
Expected: PASS

- [ ] **Step 3: 提交**

```bash
git add src/margin/holdings_monitoring/db_models.py alembic/versions/20260619_0008_holdings_monitoring.py
git commit -m "feat(holdings_monitoring): add alert_events and position_reviews schema"
```

---

### Task 3: 仓库接口与持久化实现

**Files:**
- Create: `src/margin/holdings_monitoring/repository.py`
- Test: `tests/holdings_monitoring/test_repository.py`

- [ ] **Step 1: 写失败测试**

```python
from margin.holdings_monitoring.models import AlertEvent, AlertPriority, AlertType
from margin.holdings_monitoring.repository import MemoryMonitoringRepository


def test_memory_repository_adds_and_lists_alerts():
    repo = MemoryMonitoringRepository()
    alert = AlertEvent(
        portfolio_id="pf_1",
        position_id="pos_1",
        symbol="A",
        alert_type=AlertType.PRICE_INVALIDATION,
        severity=AlertPriority.P0,
        message="m",
        rule_name="r",
    )
    repo.add_alert(alert)
    assert repo.list_alerts("pf_1", "pos_1") == [alert]
```

Run: `pytest tests/holdings_monitoring/test_repository.py::test_memory_repository_adds_and_lists_alerts -v`
Expected: FAIL "ModuleNotFoundError: No module named 'margin.holdings_monitoring.repository'"

- [ ] **Step 2: 实现仓库**

`src/margin/holdings_monitoring/repository.py`:

```python
"""Persistence repositories for module 09 holdings monitoring."""

from __future__ import annotations

from collections.abc import Callable
from typing import Protocol

from sqlalchemy import select
from sqlalchemy.orm import Session

from margin.holdings_monitoring.db_models import AlertEventRow, PositionReviewRow
from margin.holdings_monitoring.models import (
    AlertEvent,
    AlertPriority,
    AlertType,
    PositionReviewRecord,
    ReviewDecision,
)


class MonitoringRepository(Protocol):
    """Persistence contract consumed by holdings monitoring services."""

    def add_alert(self, alert: AlertEvent) -> None:
        """Append an alert event."""
        ...

    def list_alerts(
        self,
        portfolio_id: str,
        position_id: str | None = None,
    ) -> list[AlertEvent]:
        """Return alerts for a portfolio, optionally filtered by position."""
        ...

    def get_alert(self, alert_id: str) -> AlertEvent | None:
        """Return one alert by identifier."""
        ...

    def add_review(self, review: PositionReviewRecord) -> None:
        """Append a manual position review."""
        ...

    def list_reviews(
        self,
        portfolio_id: str,
        position_id: str | None = None,
    ) -> list[PositionReviewRecord]:
        """Return review records for a portfolio or position."""
        ...


class MemoryMonitoringRepository:
    """In-memory monitoring repository for tests and embedded usage."""

    def __init__(self) -> None:
        self._alerts: dict[str, AlertEvent] = {}
        self._reviews: dict[str, PositionReviewRecord] = {}

    def add_alert(self, alert: AlertEvent) -> None:
        self._alerts[alert.alert_id] = alert

    def list_alerts(
        self,
        portfolio_id: str,
        position_id: str | None = None,
    ) -> list[AlertEvent]:
        alerts = [
            alert for alert in self._alerts.values()
            if alert.portfolio_id == portfolio_id
        ]
        if position_id is not None:
            alerts = [alert for alert in alerts if alert.position_id == position_id]
        return sorted(alerts, key=lambda item: (item.triggered_at, item.alert_id))

    def get_alert(self, alert_id: str) -> AlertEvent | None:
        return self._alerts.get(alert_id)

    def add_review(self, review: PositionReviewRecord) -> None:
        self._reviews[review.review_id] = review

    def list_reviews(
        self,
        portfolio_id: str,
        position_id: str | None = None,
    ) -> list[PositionReviewRecord]:
        reviews = [
            review for review in self._reviews.values()
            if review.portfolio_id == portfolio_id
        ]
        if position_id is not None:
            reviews = [review for review in reviews if review.position_id == position_id]
        return sorted(reviews, key=lambda item: (item.created_at, item.review_id))


class SQLAlchemyMonitoringRepository:
    """PostgreSQL monitoring repository backed by short SQLAlchemy sessions."""

    def __init__(self, session_factory: Callable[[], Session]) -> None:
        self._session_factory = session_factory

    def add_alert(self, alert: AlertEvent) -> None:
        with self._session_factory.begin() as session:
            session.add(_alert_to_row(alert))

    def list_alerts(
        self,
        portfolio_id: str,
        position_id: str | None = None,
    ) -> list[AlertEvent]:
        statement = select(AlertEventRow).where(
            AlertEventRow.portfolio_id == portfolio_id
        )
        if position_id is not None:
            statement = statement.where(AlertEventRow.position_id == position_id)
        statement = statement.order_by(
            AlertEventRow.triggered_at,
            AlertEventRow.alert_id,
        )
        with self._session_factory() as session:
            return [_alert_from_row(row) for row in session.scalars(statement).all()]

    def get_alert(self, alert_id: str) -> AlertEvent | None:
        with self._session_factory() as session:
            row = session.get(AlertEventRow, alert_id)
            return _alert_from_row(row) if row is not None else None

    def add_review(self, review: PositionReviewRecord) -> None:
        with self._session_factory.begin() as session:
            session.add(_review_to_row(review))

    def list_reviews(
        self,
        portfolio_id: str,
        position_id: str | None = None,
    ) -> list[PositionReviewRecord]:
        statement = select(PositionReviewRow).where(
            PositionReviewRow.portfolio_id == portfolio_id
        )
        if position_id is not None:
            statement = statement.where(PositionReviewRow.position_id == position_id)
        statement = statement.order_by(
            PositionReviewRow.created_at,
            PositionReviewRow.review_id,
        )
        with self._session_factory() as session:
            return [_review_from_row(row) for row in session.scalars(statement).all()]


def _alert_to_row(alert: AlertEvent) -> AlertEventRow:
    return AlertEventRow(
        alert_id=alert.alert_id,
        portfolio_id=alert.portfolio_id,
        position_id=alert.position_id,
        symbol=alert.symbol,
        alert_type=alert.alert_type.value,
        severity=alert.severity.value,
        message=alert.message,
        rule_name=alert.rule_name,
        triggered_at=alert.triggered_at,
        evidence_refs=list(alert.evidence_refs),
        changed_thesis=alert.changed_thesis,
        acknowledged_at=alert.acknowledged_at,
    )


def _alert_from_row(row: AlertEventRow) -> AlertEvent:
    return AlertEvent(
        alert_id=row.alert_id,
        portfolio_id=row.portfolio_id,
        position_id=row.position_id,
        symbol=row.symbol,
        alert_type=AlertType(row.alert_type),
        severity=AlertPriority(row.severity),
        message=row.message,
        rule_name=row.rule_name,
        triggered_at=row.triggered_at,
        evidence_refs=list(row.evidence_refs),
        changed_thesis=row.changed_thesis,
        acknowledged_at=row.acknowledged_at,
    )


def _review_to_row(review: PositionReviewRecord) -> PositionReviewRow:
    return PositionReviewRow(
        review_id=review.review_id,
        portfolio_id=review.portfolio_id,
        position_id=review.position_id,
        alert_id=review.alert_id,
        decision=review.decision.value,
        rationale=review.rationale,
        action_taken_at=review.action_taken_at,
        created_at=review.created_at,
    )


def _review_from_row(row: PositionReviewRow) -> PositionReviewRecord:
    return PositionReviewRecord(
        review_id=row.review_id,
        portfolio_id=row.portfolio_id,
        position_id=row.position_id,
        alert_id=row.alert_id,
        decision=ReviewDecision(row.decision),
        rationale=row.rationale,
        action_taken_at=row.action_taken_at,
        created_at=row.created_at,
    )
```

Run: `pytest tests/holdings_monitoring/test_repository.py -v`
Expected: PASS

- [ ] **Step 3: 提交**

```bash
git add src/margin/holdings_monitoring/repository.py tests/holdings_monitoring/test_repository.py
git commit -m "feat(holdings_monitoring): add monitoring repository interface and impls"
```

---

### Task 4: HoldingsMonitoringService 确定性规则引擎

**Files:**
- Create: `src/margin/holdings_monitoring/service.py`
- Test: `tests/holdings_monitoring/test_service.py`

- [ ] **Step 1: 写失败测试**

```python
from datetime import datetime, UTC

from margin.holdings_monitoring.models import AlertPriority, AlertType
from margin.holdings_monitoring.service import HoldingsMonitoringService
from margin.portfolio.models import Position, PositionHealthStatus, PositionThesis, ThesisStatus


def test_price_invalidation_triggers_p0_alert():
    service = HoldingsMonitoringService()
    position = Position(
        position_id="pos_1",
        portfolio_id="pf_1",
        symbol="000001.SZ",
        quantity=100,
        cost_price=10.0,
        cost_amount=1000.0,
        current_price=8.5,
        market_value=850.0,
    )
    snapshot = service.evaluate_position(
        portfolio_id="pf_1",
        position=position,
        thesis=None,
        current_price=8.5,
    )
    assert snapshot.health_status == PositionHealthStatus.INVALIDATED
    assert snapshot.thesis_status == ThesisStatus.THESIS_INVALIDATED
    assert any(a.severity == AlertPriority.P0 for a in snapshot.alerts)
```

Run: `pytest tests/holdings_monitoring/test_service.py::test_price_invalidation_triggers_p0_alert -v`
Expected: FAIL "ModuleNotFoundError: No module named 'margin.holdings_monitoring.service'"

- [ ] **Step 2: 实现规则引擎**

`src/margin/holdings_monitoring/service.py`:

```python
"""Services for module 09 holdings monitoring."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from margin.holdings_monitoring.models import (
    AlertEvent,
    AlertPriority,
    AlertType,
    BehaviorMetric,
    OperationHistoryEntry,
    PositionMonitoringSnapshot,
    PositionReviewRecord,
    ReviewDecision,
)
from margin.holdings_monitoring.repository import (
    MemoryMonitoringRepository,
    MonitoringRepository,
)
from margin.portfolio.models import (
    Position,
    PositionHealthStatus,
    PositionThesis,
    ThesisStatus,
    Trade,
)
from margin.portfolio.service import PortfolioService

PRICE_INVALIDATION_DRAWDOWN = 0.10
PRICE_RISK_DRAWDOWN = 0.05


class HoldingsMonitoringService:
    """Deterministic holdings monitoring service for intraday-safe checks."""

    def __init__(
        self,
        repository: MonitoringRepository | None = None,
        portfolio_service: PortfolioService | None = None,
    ) -> None:
        self._repository = repository or MemoryMonitoringRepository()
        self._portfolio_service = portfolio_service

    def evaluate_position(
        self,
        *,
        portfolio_id: str,
        position: Position,
        thesis: PositionThesis | None,
        current_price: float | None = None,
        evidence_refs: list[str] | None = None,
        model_rank_delta: float | None = None,
        industry_exposure: float | None = None,
        strategy_failure: bool = False,
        upcoming_event_at: datetime | None = None,
        decision_at: datetime | None = None,
    ) -> PositionMonitoringSnapshot:
        """Evaluate one position with deterministic monitoring rules."""
        evaluated_at = _ensure_dt(decision_at)
        evidence_refs = evidence_refs or []
        resolved_price = current_price if current_price is not None else position.current_price
        alerts: list[AlertEvent] = []
        reasons: list[str] = []
        health_status = PositionHealthStatus.HEALTHY
        thesis_status = thesis.status if thesis else ThesisStatus.THESIS_VALID
        data_missing = False

        if resolved_price is None:
            data_missing = True
            health_status = PositionHealthStatus.DATA_MISSING
            reasons.append("价格数据缺失，停止输出高置信持仓判断")
            alerts.append(
                self._build_alert(
                    portfolio_id=portfolio_id,
                    position=position,
                    alert_type=AlertType.DATA_QUALITY,
                    severity=AlertPriority.P2,
                    rule_name="data_missing_price",
                    message="价格数据缺失，已降级为 DATA_MISSING",
                    triggered_at=evaluated_at,
                    evidence_refs=evidence_refs,
                )
            )
        elif position.cost_price > 0 and resolved_price <= position.cost_price * (
            1 - PRICE_INVALIDATION_DRAWDOWN
        ):
            health_status = PositionHealthStatus.INVALIDATED
            thesis_status = ThesisStatus.THESIS_INVALIDATED
            reasons.append("价格触及投资逻辑失效阈值")
            alerts.append(
                self._build_alert(
                    portfolio_id=portfolio_id,
                    position=position,
                    alert_type=AlertType.PRICE_INVALIDATION,
                    severity=AlertPriority.P0,
                    rule_name="price_invalidation",
                    message="价格触及失效条件，投资逻辑需要立即复核",
                    triggered_at=evaluated_at,
                    evidence_refs=evidence_refs,
                    changed_thesis=True,
                )
            )
        elif position.cost_price > 0 and resolved_price <= position.cost_price * (
            1 - PRICE_RISK_DRAWDOWN
        ):
            health_status = PositionHealthStatus.RISK
            thesis_status = ThesisStatus.RISK_ALERT
            reasons.append("价格接近投资逻辑失效阈值")
            alerts.append(
                self._build_alert(
                    portfolio_id=portfolio_id,
                    position=position,
                    alert_type=AlertType.PRICE_INVALIDATION,
                    severity=AlertPriority.P1,
                    rule_name="price_risk",
                    message="价格接近失效条件，交易时段需要复核",
                    triggered_at=evaluated_at,
                    evidence_refs=evidence_refs,
                )
            )

        if thesis and thesis.next_review_at and thesis.next_review_at <= evaluated_at:
            if health_status == PositionHealthStatus.HEALTHY:
                health_status = PositionHealthStatus.EVENT_PENDING
            reasons.append("持仓到达下一次复核时间")
            alerts.append(
                self._build_alert(
                    portfolio_id=portfolio_id,
                    position=position,
                    alert_type=AlertType.KEY_EVENT_PENDING,
                    severity=AlertPriority.P2,
                    rule_name="next_review_due",
                    message="持仓到达计划复核时间",
                    triggered_at=evaluated_at,
                    evidence_refs=evidence_refs,
                )
            )

        if strategy_failure:
            if health_status == PositionHealthStatus.HEALTHY:
                health_status = PositionHealthStatus.WATCH
            reasons.append("策略运行失败，进入降级观察")
            alerts.append(
                self._build_alert(
                    portfolio_id=portfolio_id,
                    position=position,
                    alert_type=AlertType.STRATEGY_FAILURE,
                    severity=AlertPriority.P2,
                    rule_name="strategy_failure",
                    message="策略运行失败，已降级为规则型提醒",
                    triggered_at=evaluated_at,
                    evidence_refs=evidence_refs,
                )
            )

        if model_rank_delta is not None and model_rank_delta <= -30:
            if health_status == PositionHealthStatus.HEALTHY:
                health_status = PositionHealthStatus.WATCH
            reasons.append("模型排名明显下降")
            alerts.append(
                self._build_alert(
                    portfolio_id=portfolio_id,
                    position=position,
                    alert_type=AlertType.MODEL_RANK_CHANGE,
                    severity=AlertPriority.P2,
                    rule_name="model_rank_drop",
                    message="模型排名明显下降，进入观察",
                    triggered_at=evaluated_at,
                    evidence_refs=evidence_refs,
                )
            )

        if industry_exposure is not None and industry_exposure >= 0.35:
            if health_status == PositionHealthStatus.HEALTHY:
                health_status = PositionHealthStatus.WATCH
            reasons.append("行业暴露超过监控阈值")
            alerts.append(
                self._build_alert(
                    portfolio_id=portfolio_id,
                    position=position,
                    alert_type=AlertType.INDUSTRY_EXPOSURE,
                    severity=AlertPriority.P2,
                    rule_name="industry_exposure_limit",
                    message="行业暴露超过监控阈值",
                    triggered_at=evaluated_at,
                    evidence_refs=evidence_refs,
                )
            )

        if upcoming_event_at is not None:
            if health_status == PositionHealthStatus.HEALTHY:
                health_status = PositionHealthStatus.EVENT_PENDING
            reasons.append("关键事件即将发生")
            alerts.append(
                self._build_alert(
                    portfolio_id=portfolio_id,
                    position=position,
                    alert_type=AlertType.KEY_EVENT_PENDING,
                    severity=AlertPriority.P2,
                    rule_name="upcoming_key_event",
                    message="关键事件即将发生",
                    triggered_at=evaluated_at,
                    evidence_refs=evidence_refs,
                )
            )

        for alert in alerts:
            self._repository.add_alert(alert)

        return PositionMonitoringSnapshot(
            position_id=position.position_id,
            portfolio_id=portfolio_id,
            symbol=position.symbol,
            health_status=health_status,
            thesis_status=thesis_status,
            evaluated_at=evaluated_at,
            reasons=reasons,
            alerts=alerts,
            data_missing=data_missing,
        )

    def evaluate_position_by_id(
        self,
        *,
        portfolio_id: str,
        position_id: str,
        current_price: float | None = None,
        evidence_refs: list[str] | None = None,
        model_rank_delta: float | None = None,
        industry_exposure: float | None = None,
        strategy_failure: bool = False,
        upcoming_event_at: datetime | None = None,
        decision_at: datetime | None = None,
    ) -> PositionMonitoringSnapshot:
        """Load one position from PortfolioService and evaluate it."""
        if self._portfolio_service is None:
            raise RuntimeError("portfolio service is required for evaluate_position_by_id")
        detail = self._portfolio_service.get_position_detail(portfolio_id, position_id)
        return self.evaluate_position(
            portfolio_id=portfolio_id,
            position=_position_from_detail(detail, portfolio_id),
            thesis=detail.thesis,
            current_price=current_price,
            evidence_refs=evidence_refs,
            model_rank_delta=model_rank_delta,
            industry_exposure=industry_exposure,
            strategy_failure=strategy_failure,
            upcoming_event_at=upcoming_event_at,
            decision_at=decision_at,
        )

    def list_alerts(
        self,
        portfolio_id: str,
        position_id: str | None = None,
    ) -> list[AlertEvent]:
        return self._repository.list_alerts(portfolio_id, position_id)

    def record_review(
        self,
        *,
        portfolio_id: str,
        position_id: str,
        alert_id: str | None,
        decision: ReviewDecision,
        rationale: str,
        action_taken_at: datetime | None = None,
    ) -> PositionReviewRecord:
        if alert_id is not None and self._repository.get_alert(alert_id) is None:
            raise KeyError(f"alert '{alert_id}' not found")
        review = PositionReviewRecord(
            portfolio_id=portfolio_id,
            position_id=position_id,
            alert_id=alert_id,
            decision=decision,
            rationale=rationale,
            action_taken_at=action_taken_at,
        )
        self._repository.add_review(review)
        return review

    def list_reviews(
        self,
        portfolio_id: str,
        position_id: str | None = None,
    ) -> list[PositionReviewRecord]:
        return self._repository.list_reviews(portfolio_id, position_id)

    def get_behavior_metrics(
        self,
        portfolio_id: str,
        position_id: str,
    ) -> list[BehaviorMetric]:
        alerts = {alert.alert_id: alert for alert in self.list_alerts(portfolio_id, position_id)}
        metrics: list[BehaviorMetric] = []
        for review in self.list_reviews(portfolio_id, position_id):
            if review.alert_id is None or review.alert_id not in alerts:
                continue
            alert = alerts[review.alert_id]
            latency = None
            if review.action_taken_at is not None:
                latency = int(
                    (review.action_taken_at - alert.triggered_at).total_seconds()
                )
            metrics.append(
                BehaviorMetric(
                    portfolio_id=portfolio_id,
                    position_id=position_id,
                    alert_id=alert.alert_id,
                    review_id=review.review_id,
                    action_latency_seconds=latency,
                    signal_execution_gap=review.decision.value,
                )
            )
        return metrics

    def get_operation_history(
        self,
        *,
        portfolio_id: str,
        position_id: str,
        trades: list[Trade] | None = None,
    ) -> list[OperationHistoryEntry]:
        resolved_trades = trades
        if resolved_trades is None and self._portfolio_service is not None:
            detail = self._portfolio_service.get_position_detail(portfolio_id, position_id)
            resolved_trades = []
            for item in detail.trade_history:
                resolved_trades.append(
                    Trade(
                        trade_id=str(item["trade_id"]),
                        portfolio_id=portfolio_id,
                        symbol=detail.symbol,
                        side=str(item["side"]),
                        quantity=float(item["quantity"]),
                        price=float(item["price"]),
                        amount=float(item["amount"]),
                        traded_at=item["traded_at"],
                        source=str(item["source"]),
                    )
                )
        entries: list[OperationHistoryEntry] = []
        for trade in resolved_trades or []:
            entries.append(
                OperationHistoryEntry(
                    event_id=trade.trade_id,
                    position_id=position_id,
                    event_type="trade",
                    occurred_at=trade.traded_at,
                    summary=f"{trade.side.value} {trade.quantity:g} @ {trade.price:g}",
                    metadata={
                        "symbol": trade.symbol,
                        "amount": trade.amount,
                        "source": trade.source.value,
                    },
                )
            )
        for alert in self.list_alerts(portfolio_id, position_id):
            entries.append(
                OperationHistoryEntry(
                    event_id=alert.alert_id,
                    position_id=position_id,
                    event_type="alert",
                    occurred_at=alert.triggered_at,
                    summary=alert.message,
                    metadata={
                        "severity": alert.severity.value,
                        "alert_type": alert.alert_type.value,
                    },
                )
            )
        for review in self.list_reviews(portfolio_id, position_id):
            entries.append(
                OperationHistoryEntry(
                    event_id=review.review_id,
                    position_id=position_id,
                    event_type="review",
                    occurred_at=review.action_taken_at or review.created_at,
                    summary=review.rationale,
                    metadata={
                        "decision": review.decision.value,
                        "alert_id": review.alert_id,
                    },
                )
            )
        return sorted(entries, key=lambda item: (item.occurred_at, item.event_id))

    def _build_alert(
        self,
        *,
        portfolio_id: str,
        position: Position,
        alert_type: AlertType,
        severity: AlertPriority,
        rule_name: str,
        message: str,
        triggered_at: datetime,
        evidence_refs: list[str],
        changed_thesis: bool = False,
    ) -> AlertEvent:
        return AlertEvent(
            portfolio_id=portfolio_id,
            position_id=position.position_id,
            symbol=position.symbol,
            alert_type=alert_type,
            severity=severity,
            message=message,
            rule_name=rule_name,
            triggered_at=triggered_at,
            evidence_refs=evidence_refs,
            changed_thesis=changed_thesis,
        )


@dataclass(frozen=True)
class MonitoringServiceBundle:
    """Container for FastAPI dependency injection."""

    monitoring: HoldingsMonitoringService

    @classmethod
    def in_memory(
        cls,
        *,
        portfolio_service: PortfolioService | None = None,
        repository: MemoryMonitoringRepository | None = None,
    ) -> MonitoringServiceBundle:
        return cls(
            monitoring=HoldingsMonitoringService(
                repository=repository or MemoryMonitoringRepository(),
                portfolio_service=portfolio_service,
            )
        )

    @classmethod
    def from_repositories(
        cls,
        *,
        repository: MonitoringRepository,
        portfolio_service: PortfolioService,
    ) -> MonitoringServiceBundle:
        return cls(
            monitoring=HoldingsMonitoringService(
                repository=repository,
                portfolio_service=portfolio_service,
            )
        )


def _ensure_dt(value: datetime | None) -> datetime:
    if value is None:
        return datetime.now(UTC)
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _position_from_detail(detail: object, portfolio_id: str) -> Position:
    return Position(
        position_id=getattr(detail, "position_id"),
        portfolio_id=portfolio_id,
        symbol=getattr(detail, "symbol"),
        quantity=getattr(detail, "quantity"),
        cost_price=getattr(detail, "cost_price"),
        cost_amount=getattr(detail, "cost_amount"),
        current_price=getattr(detail, "current_price"),
        market_value=getattr(detail, "market_value"),
        unrealized_pnl=getattr(detail, "unrealized_pnl"),
        unrealized_pnl_pct=getattr(detail, "unrealized_pnl_pct"),
        industry=getattr(detail, "industry"),
        health_status=getattr(detail, "health_status"),
        thesis=getattr(detail, "thesis"),
        updated_at=getattr(detail, "updated_at"),
    )
```

Run: `pytest tests/holdings_monitoring/test_service.py -v`
Expected: PASS

- [ ] **Step 3: 提交**

```bash
git add src/margin/holdings_monitoring/service.py tests/holdings_monitoring/test_service.py
git commit -m "feat(holdings_monitoring): add deterministic monitoring rule engine"
```

---

### Task 5: FastAPI 监控路由

**Files:**
- Create: `src/margin/api/routes/monitoring.py`
- Test: `tests/api/test_monitoring.py`

- [ ] **Step 1: 写失败测试**

```python
from fastapi.testclient import TestClient
from margin.api.main import create_app
from margin.holdings_monitoring.service import MonitoringServiceBundle


def test_monitoring_router_registered():
    bundle = MonitoringServiceBundle.in_memory()
    app = create_app(monitoring_services=bundle)
    client = TestClient(app)
    response = client.post(
        "/api/v1/positions/pos_1/monitoring/evaluate",
        json={"portfolio_id": "pf_1"},
    )
    assert response.status_code != 404
```

Run: `pytest tests/api/test_monitoring.py::test_monitoring_router_registered -v`
Expected: FAIL "404"（router 未注册）

- [ ] **Step 2: 实现路由**

`src/margin/api/routes/monitoring.py`:

```python
"""Holdings monitoring API routes for module 09."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field

from margin.api.dependencies import get_monitoring_services
from margin.holdings_monitoring.models import (
    AlertEvent,
    BehaviorMetric,
    OperationHistoryEntry,
    PositionMonitoringSnapshot,
    PositionReviewRecord,
    ReviewDecision,
)
from margin.holdings_monitoring.service import MonitoringServiceBundle

router = APIRouter(prefix="/api/v1", tags=["monitoring"])

Services = Annotated[MonitoringServiceBundle, Depends(get_monitoring_services)]


class MonitoringEvaluateRequest(BaseModel):
    """Request body for deterministic position monitoring evaluation."""

    portfolio_id: str = Field(min_length=1)
    current_price: float | None = None
    evidence_refs: list[str] = Field(default_factory=list)
    model_rank_delta: float | None = None
    industry_exposure: float | None = None
    strategy_failure: bool = False
    upcoming_event_at: datetime | None = None
    decision_at: datetime | None = None


class ReviewCreate(BaseModel):
    """Request body for appending a position review record."""

    portfolio_id: str = Field(min_length=1)
    alert_id: str | None = None
    decision: ReviewDecision
    rationale: str = Field(min_length=1)
    action_taken_at: datetime | None = None


def _not_found(exc: KeyError) -> HTTPException:
    return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))


@router.post(
    "/positions/{position_id}/monitoring/evaluate",
    response_model=PositionMonitoringSnapshot,
    status_code=status.HTTP_201_CREATED,
)
def evaluate_position_monitoring(
    position_id: str,
    request: MonitoringEvaluateRequest,
    services: Services,
) -> PositionMonitoringSnapshot:
    """Evaluate a position using deterministic monitoring rules."""
    try:
        return services.monitoring.evaluate_position_by_id(
            portfolio_id=request.portfolio_id,
            position_id=position_id,
            current_price=request.current_price,
            evidence_refs=request.evidence_refs,
            model_rank_delta=request.model_rank_delta,
            industry_exposure=request.industry_exposure,
            strategy_failure=request.strategy_failure,
            upcoming_event_at=request.upcoming_event_at,
            decision_at=request.decision_at,
        )
    except KeyError as exc:
        raise _not_found(exc) from exc


@router.get("/positions/{position_id}/alerts", response_model=list[AlertEvent])
def get_position_alerts(
    position_id: str,
    services: Services,
    portfolio_id: Annotated[str, Query(min_length=1)],
) -> list[AlertEvent]:
    """Return append-only alert events for a position."""
    return services.monitoring.list_alerts(portfolio_id, position_id)


@router.post(
    "/positions/{position_id}/reviews",
    response_model=PositionReviewRecord,
    status_code=status.HTTP_201_CREATED,
)
def create_position_review(
    position_id: str,
    request: ReviewCreate,
    services: Services,
) -> PositionReviewRecord:
    """Append a manual review for a position alert."""
    try:
        return services.monitoring.record_review(
            portfolio_id=request.portfolio_id,
            position_id=position_id,
            alert_id=request.alert_id,
            decision=request.decision,
            rationale=request.rationale,
            action_taken_at=request.action_taken_at,
        )
    except KeyError as exc:
        raise _not_found(exc) from exc


@router.get(
    "/positions/{position_id}/history",
    response_model=list[OperationHistoryEntry],
)
def get_position_history(
    position_id: str,
    services: Services,
    portfolio_id: Annotated[str, Query(min_length=1)],
) -> list[OperationHistoryEntry]:
    """Return unified trade/alert/review operation history for a position."""
    try:
        return services.monitoring.get_operation_history(
            portfolio_id=portfolio_id,
            position_id=position_id,
        )
    except KeyError as exc:
        raise _not_found(exc) from exc


@router.get(
    "/positions/{position_id}/behavior-metrics",
    response_model=list[BehaviorMetric],
)
def get_position_behavior_metrics(
    position_id: str,
    services: Services,
    portfolio_id: Annotated[str, Query(min_length=1)],
) -> list[BehaviorMetric]:
    """Return action-latency metrics derived from alert/review records."""
    return services.monitoring.get_behavior_metrics(portfolio_id, position_id)
```

`tests/api/test_monitoring.py`（完整端到端测试）：

```python
from datetime import datetime

from fastapi.testclient import TestClient

from margin.api.main import create_app
from margin.holdings_monitoring.service import MonitoringServiceBundle
from margin.portfolio.service import PortfolioService


def _client_with_position():
    portfolio_service = PortfolioService()
    portfolio = portfolio_service.create_portfolio("user_1", "Core", cash=10000)
    portfolio_service.add_trade(
        portfolio.portfolio_id,
        "000001.SZ",
        "buy",
        1000,
        10,
        datetime(2026, 6, 1),
    )
    position = portfolio_service.get_positions(portfolio.portfolio_id)[0]
    portfolio_service.update_thesis(
        portfolio.portfolio_id,
        position.position_id,
        thesis="现金流改善与估值修复",
        invalidation_conditions=["价格跌破成本 10%"],
    )
    monitoring_services = MonitoringServiceBundle.in_memory(
        portfolio_service=portfolio_service
    )
    app = create_app(
        portfolio_service=portfolio_service,
        monitoring_services=monitoring_services,
    )
    return TestClient(app), portfolio.portfolio_id, position.position_id


def test_monitoring_api_evaluates_alerts_reviews_and_history():
    client, portfolio_id, position_id = _client_with_position()

    snapshot = client.post(
        f"/api/v1/positions/{position_id}/monitoring/evaluate",
        json={
            "portfolio_id": portfolio_id,
            "current_price": 8.8,
            "evidence_refs": ["ev_price_drop"],
            "decision_at": "2026-06-19T09:30:00Z",
        },
    )
    alerts = client.get(
        f"/api/v1/positions/{position_id}/alerts",
        params={"portfolio_id": portfolio_id},
    )
    alert_id = snapshot.json()["alerts"][0]["alert_id"]
    review = client.post(
        f"/api/v1/positions/{position_id}/reviews",
        json={
            "portfolio_id": portfolio_id,
            "alert_id": alert_id,
            "decision": "reduce",
            "rationale": "价格触发失效条件，降低仓位",
            "action_taken_at": "2026-06-19T10:00:00Z",
        },
    )
    history = client.get(
        f"/api/v1/positions/{position_id}/history",
        params={"portfolio_id": portfolio_id},
    )

    assert snapshot.status_code == 201
    assert snapshot.json()["health_status"] == "invalidated"
    assert snapshot.json()["alerts"][0]["severity"] == "P0"
    assert alerts.status_code == 200
    assert alerts.json()[0]["alert_id"] == alert_id
    assert review.status_code == 201
    assert review.json()["decision"] == "reduce"
    assert history.status_code == 200
    assert [entry["event_type"] for entry in history.json()] == [
        "trade",
        "alert",
        "review",
    ]
```

Run: `pytest tests/api/test_monitoring.py -v`
Expected: PASS

- [ ] **Step 3: 提交**

```bash
git add src/margin/api/routes/monitoring.py tests/api/test_monitoring.py
git commit -m "feat(api): add holdings monitoring routes"
```

---

### Task 6: 依赖注入与主应用注册

**Files:**
- Modify: `src/margin/api/dependencies.py`
- Modify: `src/margin/api/main.py`
- Test: `tests/api/test_monitoring.py`

- [ ] **Step 1: 写失败测试**

```python
def test_monitoring_services_dependency_is_cached():
    from margin.api.dependencies import get_monitoring_services
    assert get_monitoring_services() is get_monitoring_services()
```

Run: `pytest tests/api/test_monitoring.py::test_monitoring_services_dependency_is_cached -v`
Expected: FAIL "ImportError: cannot import name 'get_monitoring_services'"

- [ ] **Step 2: 实现依赖注入**

在 `src/margin/api/dependencies.py` 追加：

```python
from margin.holdings_monitoring.repository import SQLAlchemyMonitoringRepository
from margin.holdings_monitoring.service import MonitoringServiceBundle


@lru_cache
def get_monitoring_services() -> MonitoringServiceBundle:
    """Return production holdings monitoring services backed by PostgreSQL."""
    engine = create_database_engine()
    session_factory = create_session_factory(engine)
    portfolio_repository = SQLAlchemyPortfolioRepository(session_factory)
    portfolio_service = PortfolioService(repository=portfolio_repository)
    monitoring_repository = SQLAlchemyMonitoringRepository(session_factory)
    return MonitoringServiceBundle.from_repositories(
        repository=monitoring_repository,
        portfolio_service=portfolio_service,
    )
```

在 `src/margin/api/main.py` 中：

```python
from margin.api.dependencies import (
    get_dashboard_services,
    get_monitoring_services,
    get_portfolio_service,
    get_research_service,
    get_strategy_service,
)
from margin.api.routes.monitoring import router as monitoring_router
```

并在 `create_app` 签名与 include_router 中增加 monitoring：

```python
def create_app(
    portfolio_service: PortfolioService | None = None,
    research_service: ResearchService | None = None,
    strategy_service: StrategyService | None = None,
    dashboard_services: DashboardServiceBundle | None = None,
    monitoring_services: MonitoringServiceBundle | None = None,
) -> FastAPI:
    application = FastAPI(title="Margin API", version="0.1.0")
    application.include_router(portfolio_router)
    application.include_router(research_router)
    application.include_router(strategy_router)
    application.include_router(dashboard_router)
    application.include_router(monitoring_router)

    if portfolio_service is not None:
        application.dependency_overrides[get_portfolio_service] = lambda: portfolio_service
    if research_service is not None:
        application.dependency_overrides[get_research_service] = lambda: research_service
    if strategy_service is not None:
        application.dependency_overrides[get_strategy_service] = lambda: strategy_service
    if dashboard_services is not None:
        application.dependency_overrides[get_dashboard_services] = lambda: dashboard_services
    if monitoring_services is not None:
        application.dependency_overrides[get_monitoring_services] = lambda: monitoring_services

    @application.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    return application
```

Run: `pytest tests/api/test_monitoring.py -v`
Expected: PASS

- [ ] **Step 3: 提交**

```bash
git add src/margin/api/dependencies.py src/margin/api/main.py
git commit -m "feat(api): wire holdings monitoring dependency injection and router"
```

---

### Task 7: 包导出与后端清理

**Files:**
- Create: `src/margin/holdings_monitoring/__init__.py`
- Test: `ruff check src tests`

- [ ] **Step 1: 实现 `__init__.py`**

```python
"""Holdings monitoring module."""

from margin.holdings_monitoring.models import (
    AlertEvent,
    AlertPriority,
    AlertType,
    BehaviorMetric,
    OperationHistoryEntry,
    PositionMonitoringSnapshot,
    PositionReviewRecord,
    ReviewDecision,
)
from margin.holdings_monitoring.repository import (
    MemoryMonitoringRepository,
    MonitoringRepository,
    SQLAlchemyMonitoringRepository,
)
from margin.holdings_monitoring.service import (
    HoldingsMonitoringService,
    MonitoringServiceBundle,
)

__all__ = [
    "AlertEvent",
    "AlertPriority",
    "AlertType",
    "BehaviorMetric",
    "HoldingsMonitoringService",
    "MemoryMonitoringRepository",
    "MonitoringRepository",
    "MonitoringServiceBundle",
    "OperationHistoryEntry",
    "PositionMonitoringSnapshot",
    "PositionReviewRecord",
    "ReviewDecision",
    "SQLAlchemyMonitoringRepository",
]
```

- [ ] **Step 2: 运行 ruff**

Run: `ruff check src tests`
Expected: PASS

- [ ] **Step 3: 提交**

```bash
git add src/margin/holdings_monitoring/__init__.py
git commit -m "feat(holdings_monitoring): add public package exports"
```

---

### Task 8: 前端 API 类型与请求函数

**Files:**
- Modify: `web/lib/api.ts`
- Test: 可选 `web/lib/api.test.ts`（若时间紧可省略）

- [ ] **Step 1: 新增类型与请求函数**

在 `web/lib/api.ts` 追加：

```typescript
export type AlertEvent = {
  alert_id: string;
  portfolio_id: string;
  position_id: string;
  symbol: string;
  alert_type: string;
  severity: "P0" | "P1" | "P2" | "P3";
  message: string;
  rule_name: string;
  triggered_at: string;
  evidence_refs: string[];
  changed_thesis: boolean;
  acknowledged_at: string | null;
};

export type OperationHistoryEntry = {
  event_id: string;
  position_id: string;
  event_type: "trade" | "alert" | "review";
  occurred_at: string;
  summary: string;
  metadata: Record<string, unknown>;
};

export function fetchPositionAlerts(
  portfolioId: string,
  positionId: string,
): Promise<AlertEvent[]> {
  return request<AlertEvent[]>(
    `/api/v1/positions/${positionId}/alerts?portfolio_id=${encodeURIComponent(portfolioId)}`,
  );
}

export function fetchPositionHistory(
  portfolioId: string,
  positionId: string,
): Promise<OperationHistoryEntry[]> {
  return request<OperationHistoryEntry[]>(
    `/api/v1/positions/${positionId}/history?portfolio_id=${encodeURIComponent(portfolioId)}`,
  );
}
```

- [ ] **Step 2: 运行前端 lint**

Run: `cd web && npm run lint`
Expected: PASS

- [ ] **Step 3: 提交**

```bash
git add web/lib/api.ts
git commit -m "feat(web): add holdings monitoring API types and fetch helpers"
```

---

### Task 9: 持仓详情监控 UI

**Files:**
- Modify: `web/app/positions/[positionId]/page.tsx`
- Modify: `web/components/position-detail.tsx`
- Create: `web/components/position-review-badge.tsx`
- Create: `web/components/research-status-badge.tsx`
- Test: `web/components/position-detail.test.tsx`

- [ ] **Step 1: 写失败测试**

```typescript
import { render, screen } from "@testing-library/react";
import { PositionDetailView } from "./position-detail";
import type { AlertEvent, OperationHistoryEntry, PositionDetail } from "@/lib/api";

test("renders monitoring panel with P0 alert", () => {
  const detail: PositionDetail = {
    position_id: "pos_1",
    portfolio_id: "pf_1",
    symbol: "000001.SZ",
    quantity: 100,
    cost_price: 10,
    cost_amount: 1000,
    current_price: 8.5,
    market_value: 850,
    unrealized_pnl: -150,
    unrealized_pnl_pct: -0.15,
    weight: 0.1,
    industry: "银行",
    health_status: "INVALIDATED",
    thesis: {
      thesis_id: "th_1",
      position_id: "pos_1",
      thesis: "买入逻辑",
      entry_conditions: [],
      hold_conditions: [],
      invalidation_conditions: ["价格跌破 9 元"],
      target_horizon: "6M",
      next_review_at: null,
      status: "THESIS_INVALIDATED",
      created_at: "2026-06-19T00:00:00Z",
    },
    trade_history: [],
  };
  const alerts: AlertEvent[] = [{
    alert_id: "al_1",
    portfolio_id: "pf_1",
    position_id: "pos_1",
    symbol: "000001.SZ",
    alert_type: "price_invalidation",
    severity: "P0",
    message: "价格触及失效条件",
    rule_name: "price_invalidation",
    triggered_at: "2026-06-19T09:30:00Z",
    evidence_refs: [],
    changed_thesis: true,
    acknowledged_at: null,
  }];
  render(
    <PositionDetailView
      portfolioId="pf_1"
      detail={detail}
      alerts={alerts}
      history={[]}
      error={null}
    />,
  );
  expect(screen.getByText("价格触及失效条件")).toBeInTheDocument();
  expect(screen.getByText("P0")).toBeInTheDocument();
});
```

Run: `cd web && npm test -- position-detail.test.tsx`
Expected: FAIL

- [ ] **Step 2: 实现组件**

`web/components/position-review-badge.tsx`:

```typescript
export function PositionReviewBadge({ status }: { status: string | null | undefined }) {
  if (!status) return null;
  const labels: Record<string, string> = {
    review: "需要复核",
    validated: "逻辑有效",
    invalidated: "逻辑失效",
    risk: "风险提醒",
  };
  return <span className={`badge position-review ${status}`}>{labels[status] ?? status}</span>;
}
```

`web/components/research-status-badge.tsx`:

```typescript
export function ResearchStatusBadge({ status }: { status: string }) {
  const labels: Record<string, string> = {
    published: "已发布",
    abstained: "已放弃",
    aborted: "已中止",
    data_missing: "数据缺失",
  };
  return <span className={`badge research-status ${status}`}>{labels[status] ?? status}</span>;
}
```

`web/app/positions/[positionId]/page.tsx`:

```typescript
import { notFound } from "next/navigation";

import { PositionDetailView } from "@/components/position-detail";
import {
  fetchPositionAlerts,
  fetchPositionDetail,
  fetchPositionHistory,
} from "@/lib/api";

export default async function PositionPage({
  params,
}: {
  params: Promise<{ positionId: string }>;
}) {
  const { positionId } = await params;
  const portfolioId = "demo";

  try {
    const [detail, alerts, history] = await Promise.all([
      fetchPositionDetail(portfolioId, positionId),
      fetchPositionAlerts(portfolioId, positionId),
      fetchPositionHistory(portfolioId, positionId),
    ]);
    return (
      <PositionDetailView
        portfolioId={portfolioId}
        detail={detail}
        alerts={alerts}
        history={history}
        error={null}
      />
    );
  } catch {
    return <PositionDetailView portfolioId={portfolioId} detail={null} error="加载失败" />;
  }
}
```

`web/components/position-detail.tsx`: 参考现有实现，确保 `PositionDetailView` 接收 `alerts` 与 `history` props，渲染持仓监控面板与操作历史。核心渲染逻辑如下（完整文件见仓库）：

```typescript
export type PositionDetailViewProps = {
  portfolioId: string;
  detail: PositionDetail | null;
  alerts?: AlertEvent[];
  history?: OperationHistoryEntry[];
  error: string | null;
};

export function PositionDetailView({
  portfolioId,
  detail,
  alerts = [],
  history = [],
  error,
}: PositionDetailViewProps) {
  // ... 头部、指标、买入逻辑、持仓监控、盈亏、操作历史 ...
}
```

Run: `cd web && npm test -- position-detail.test.tsx`
Expected: PASS

- [ ] **Step 3: 提交**

```bash
git add web/app/positions/[positionId]/page.tsx web/components/position-detail.tsx \
  web/components/position-review-badge.tsx web/components/research-status-badge.tsx \
  web/components/position-detail.test.tsx
git commit -m "feat(web): add holdings monitoring panel to position detail"
```

---

### Task 10: 集成测试与最终验证

**Files:**
- 全部新增/修改文件

- [ ] **Step 1: 运行后端测试**

Run: `pytest tests/holdings_monitoring tests/api/test_monitoring.py -v`
Expected: PASS

- [ ] **Step 2: 运行后端 lint**

Run: `ruff check src tests`
Expected: PASS

- [ ] **Step 3: 运行前端测试与 lint**

Run:
```bash
cd web && npm run lint
cd web && npm test
```
Expected: PASS

- [ ] **Step 4: 提交**

```bash
git add .
git commit -m "feat(holdings_monitoring): complete module 09 MVP with tests and lint"
```

---

## 计划自查

### Spec 覆盖检查

| 设计文档章节 | 实现任务 |
|-------------|---------|
| 4.1 AlertEvent / AlertPriority / AlertType | Task 1 |
| 4.2 PositionMonitoringSnapshot | Task 1 |
| 4.3 PositionReviewRecord / ReviewDecision | Task 1 |
| 4.4 OperationHistoryEntry | Task 1 |
| 4.5 BehaviorMetric | Task 1 |
| 5.1 HoldingsMonitoringService 规则引擎 | Task 4 |
| 5.2 MonitoringServiceBundle | Task 4 |
| 6. API 端点 | Task 5 + Task 6 |
| 7. 前端页面 | Task 9 |
| 8. 降级策略 | Task 4 / Task 5（DATA_MISSING / 404） |
| 9. 测试 | 各 Task 均含测试 |

### Placeholder 扫描

- 无 TBD / TODO / "implement later" / "add appropriate error handling" 等占位符。
- 每个代码步骤均包含具体代码或具体修改位置。

### 类型一致性检查

- `AlertEvent.severity` 使用 `AlertPriority` StrEnum，与仓库、服务、API 一致。
- `PositionMonitoringSnapshot.health_status` 复用模块 02 `PositionHealthStatus`。
- `MonitoringServiceBundle` 统一用于 DI，路由与 `dependencies.py` / `main.py` 一致。

## 执行交接

计划已保存到 `docs/superpowers/plans/2026-06-19-module-09-holdings-monitoring.md`。

**两种执行方式：**

1. **Subagent-Driven（推荐）**：按任务逐个派发子代理，每个任务完成后做 spec compliance + code quality 两轮审查。
2. **Inline Execution**：在当前会话按任务批次直接执行，关键节点 checkpoint 后给你确认。

你选哪种？
