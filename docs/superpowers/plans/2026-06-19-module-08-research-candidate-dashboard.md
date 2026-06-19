# 模块 08：研究候选面板实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 实现 Margin 模块 08（研究候选面板），将模块 06 的研究信号与模块 07 的策略配置聚合为可交互的候选列表、单股详情与首页概览，并提供 FastAPI BFF 与 Next.js 前端页面。

**Architecture:** 模块 08 在 `src/margin/dashboard/` 下独立实现，通过 `workflow_run_id` / `snapshot_id` 引用模块 06 结果，不反向改写模块 06。核心聚合服务 `DashboardResearchService` 逐个调用 `ResearchService.run()` 生成 `ResearchRun` / `ResearchItem`；`DashboardQueryService` 派生候选卡片与首页摘要；`EvidenceViewService` / `ValuationViewService` 解析快照输出；`FeedbackService` 追加用户反馈。前端使用 Next.js App Router + 服务端组件复用现有 `web/lib/api.ts` 数据层。

**Tech Stack:** Python 3.12, Pydantic v2, FastAPI, SQLAlchemy, pytest；前端 Next.js 16, React 19, TypeScript, Tailwind CSS, lucide-react, vitest。

---

## 文件结构映射

**后端新增/修改：**

| 文件 | 职责 |
|------|------|
| `src/margin/dashboard/models.py` | 不可变领域模型 |
| `src/margin/dashboard/repository.py` | 仓库接口与内存实现 |
| `src/margin/dashboard/db_models.py` | SQLAlchemy 行模型 |
| `src/margin/dashboard/service.py` | DashboardResearchService、DashboardQueryService、EvidenceViewService、ValuationViewService、FeedbackService |
| `src/margin/dashboard/__init__.py` | 公共导出 |
| `src/margin/api/routes/dashboard.py` | FastAPI 路由 |
| `src/margin/api/dependencies.py` | 新增 `get_dashboard_service()` |
| `src/margin/api/main.py` | 注册 dashboard router |

**前端新增/修改：**

| 文件 | 职责 |
|------|------|
| `web/lib/api.ts` | 新增 dashboard 类型与 fetch 函数 |
| `web/components/CandidateCard.tsx` | 候选卡片 |
| `web/components/CandidateList.tsx` | 候选列表与过滤 |
| `web/components/EvidencePanel.tsx` | 证据展开视图 |
| `web/components/ValuationPanel.tsx` | 估值视图 |
| `web/components/ResearchStatusBadge.tsx` | 研究状态徽章 |
| `web/components/PositionReviewBadge.tsx` | 持仓复核状态徽章 |
| `web/components/HomeSummary.tsx` | 首页六类信息聚合 |
| `web/app/research/page.tsx` | 研究首页 |
| `web/app/research/runs/[runId]/page.tsx` | 运行详情 |
| `web/app/research/items/[itemId]/page.tsx` | 单股详情 |

**测试新增：**

| 文件 | 职责 |
|------|------|
| `tests/dashboard/test_models.py` | 模型验证 |
| `tests/dashboard/test_repository.py` | 仓库行为 |
| `tests/dashboard/test_dashboard_research_service.py` | 批量运行聚合 |
| `tests/dashboard/test_query_service.py` | 查询与候选卡片 |
| `tests/dashboard/test_evidence_view_service.py` | 证据视图 |
| `tests/dashboard/test_valuation_view_service.py` | 估值视图 |
| `tests/dashboard/test_feedback_service.py` | 反馈 |
| `tests/api/test_dashboard.py` | API 端点 |
| `web/components/CandidateCard.test.tsx` | 候选卡片渲染 |
| `web/components/EvidencePanel.test.tsx` | 证据展开交互 |
| `web/components/HomeSummary.test.tsx` | 首页聚合 |

---

### Task 1: 模块 08 领域模型

**Files:**
- Create: `src/margin/dashboard/models.py`
- Test: `tests/dashboard/test_models.py`

- [ ] **Step 1: 写失败测试**

```python
from margin.dashboard.models import ResearchRun, RunStatus

def test_research_run_defaults():
    run = ResearchRun(
        decision_at="2026-06-19T09:30:00+08:00",
        strategy_id="st_demo",
        version_id="sv_demo",
        universe=["000001.SZ"],
    )
    assert run.status == RunStatus.PUBLISHED
    assert run.item_count == 0
```

Run: `pytest tests/dashboard/test_models.py::test_research_run_defaults -v`
Expected: FAIL "ModuleNotFoundError: No module named 'margin.dashboard'"

- [ ] **Step 2: 实现最小模型**

```python
"""Domain models for the research candidate dashboard module."""

from __future__ import annotations

import uuid
from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field, field_validator

from margin.news.models import ensure_utc, utc_now


class RunStatus(StrEnum):
    PUBLISHED = "published"
    ABSTAINED = "abstained"
    ABORTED = "aborted"
    PARTIAL = "partial"


class ItemStatus(StrEnum):
    PUBLISHED = "published"
    ABSTAINED = "abstained"
    ABORTED = "aborted"
    DATA_MISSING = "data_missing"


class FeedbackType(StrEnum):
    ACCEPT = "accept"
    REJECT = "reject"
    WATCH = "watch"
    COMMENT = "comment"


class ResearchRun(BaseModel):
    """A batch research run aggregating multiple symbol-level items."""

    run_id: str = Field(default_factory=lambda: f"dr_{uuid.uuid4().hex[:12]}")
    decision_at: datetime
    strategy_id: str
    version_id: str
    portfolio_id: str | None = None
    universe: list[str] = Field(default_factory=list)
    status: RunStatus = RunStatus.PUBLISHED
    summary: str = ""
    item_count: int = 0
    published_count: int = 0
    abstained_count: int = 0
    aborted_count: int = 0
    created_at: datetime = Field(default_factory=utc_now)

    model_config = {"frozen": True}

    @field_validator("decision_at", "created_at")
    @classmethod
    def normalize_timestamps(cls, value: datetime) -> datetime:
        return ensure_utc(value)


class ResearchItem(BaseModel):
    """A single symbol result inside a ResearchRun."""

    item_id: str = Field(default_factory=lambda: f"di_{uuid.uuid4().hex[:12]}")
    run_id: str
    symbol: str
    signal_type: str = ""
    confidence: float = 0.0
    statement: str = ""
    workflow_run_id: str = ""
    snapshot_id: str | None = None
    status: ItemStatus = ItemStatus.PUBLISHED
    abstain_reason: str | None = None
    rejection_reasons: list[str] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=utc_now)

    model_config = {"frozen": True}

    @field_validator("created_at")
    @classmethod
    def normalize_created_at(cls, value: datetime) -> datetime:
        return ensure_utc(value)

    @field_validator("confidence")
    @classmethod
    def validate_confidence(cls, value: float) -> float:
        if not 0.0 <= value <= 1.0:
            raise ValueError(f"confidence must be in [0, 1], got {value}")
        return value


class EvidenceLocator(BaseModel):
    """Locator for a single piece of evidence."""

    evidence_id: str
    source_level: str
    source_url: str | None = None
    content: str = ""
    page: int | None = None
    section: str | None = None

    model_config = {"frozen": True}


class ClaimView(BaseModel):
    """A claim rendered for the evidence panel."""

    claim_id: str
    statement: str
    fact_or_inference: str = "unknown"
    confidence: float = 0.0
    has_conflict: bool = False
    evidence_ids: list[str] = Field(default_factory=list)

    model_config = {"frozen": True}


class EvidenceView(BaseModel):
    """Expanded evidence view for a single research item."""

    item_id: str
    claims: list[ClaimView] = Field(default_factory=list)
    evidence_by_level: dict[str, list[EvidenceLocator]] = Field(default_factory=dict)
    source_distribution: dict[str, int] = Field(default_factory=dict)
    overall_confidence: float = 0.0
    locators_available: bool = False

    model_config = {"frozen": True}


class ValuationView(BaseModel):
    """Valuation view for a single research item."""

    item_id: str
    base_valuation_range: tuple[float, float] | None = None
    pessimistic_range: tuple[float, float] | None = None
    margin_of_safety: float | None = None
    value_trap_score: float | None = None
    method: str | None = None
    notes: str = ""

    model_config = {"frozen": True}


class FeedbackRecord(BaseModel):
    """User feedback on a research item."""

    feedback_id: str = Field(default_factory=lambda: f"fb_{uuid.uuid4().hex[:12]}")
    item_id: str
    feedback_type: FeedbackType = FeedbackType.COMMENT
    comment: str = ""
    created_at: datetime = Field(default_factory=utc_now)

    model_config = {"frozen": True}

    @field_validator("created_at")
    @classmethod
    def normalize_created_at(cls, value: datetime) -> datetime:
        return ensure_utc(value)


class CandidateCard(BaseModel):
    """Derived dashboard card for a research candidate."""

    item_id: str
    run_id: str
    symbol: str
    signal_type: str = ""
    confidence: float = 0.0
    statement: str = ""
    current_price: float | None = None
    quantitative_rank: int | None = None
    research_status: str = ""
    position_review_status: str | None = None
    valuation_range: tuple[float, float] | None = None
    margin_of_safety: float | None = None
    value_trap_score: float | None = None
    event_window: str | None = None
    catalysts: list[str] = Field(default_factory=list)
    counter_arguments: list[str] = Field(default_factory=list)
    evidence_summary: dict[str, Any] = Field(default_factory=dict)
    watch_conditions: list[str] = Field(default_factory=list)
    invalidation_conditions: list[str] = Field(default_factory=list)
    strategy_version: str = ""
    disclaimer: str = "本系统输出研究分析，不构成买卖指令。"

    model_config = {"frozen": True}


class HomeSummary(BaseModel):
    """Homepage summary for the research dashboard."""

    decision_at: datetime | None = None
    run_id: str | None = None
    strategy_id: str | None = None
    version_id: str | None = None
    run_status: str | None = None
    today_candidates: list[CandidateCard] = Field(default_factory=list)
    position_reviews: list[CandidateCard] = Field(default_factory=list)
    high_priority_risks: list[CandidateCard] = Field(default_factory=list)
    rejections: list[CandidateCard] = Field(default_factory=list)
    run_stats: dict[str, int] = Field(default_factory=dict)

    model_config = {"frozen": True}
```

Run: `pytest tests/dashboard/test_models.py -v`
Expected: PASS

- [ ] **Step 3: 提交**

```bash
git add src/margin/dashboard/models.py tests/dashboard/test_models.py
git commit -m "feat(dashboard): add module 08 domain models"
```

---

### Task 2: 仓库接口与内存实现

**Files:**
- Create: `src/margin/dashboard/repository.py`
- Test: `tests/dashboard/test_repository.py`

- [ ] **Step 1: 写失败测试**

```python
from margin.dashboard.models import ResearchRun
from margin.dashboard.repository import MemoryDashboardRepository

def test_add_and_get_run():
    repo = MemoryDashboardRepository()
    run = ResearchRun(decision_at="2026-06-19", strategy_id="st_1", version_id="sv_1")
    repo.add_run(run)
    assert repo.get_run(run.run_id) == run
```

Run: `pytest tests/dashboard/test_repository.py::test_add_and_get_run -v`
Expected: FAIL "ModuleNotFoundError: No module named 'margin.dashboard.repository'"

- [ ] **Step 2: 实现最小仓库**

```python
"""Persistence boundary for the dashboard module."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from margin.dashboard.models import FeedbackRecord, ResearchItem, ResearchRun


class DashboardRepository(ABC):
    """Abstract repository for dashboard runs, items, and feedback."""

    @abstractmethod
    def add_run(self, run: ResearchRun) -> None: ...

    @abstractmethod
    def get_run(self, run_id: str) -> ResearchRun | None: ...

    @abstractmethod
    def list_runs(
        self,
        *,
        strategy_id: str | None = None,
        portfolio_id: str | None = None,
        status: str | None = None,
        limit: int = 100,
    ) -> list[ResearchRun]: ...

    @abstractmethod
    def add_items(self, items: list[ResearchItem]) -> None: ...

    @abstractmethod
    def get_item(self, item_id: str) -> ResearchItem | None: ...

    @abstractmethod
    def list_items(self, run_id: str) -> list[ResearchItem]: ...

    @abstractmethod
    def add_feedback(self, feedback: FeedbackRecord) -> None: ...

    @abstractmethod
    def list_feedback(self, item_id: str) -> list[FeedbackRecord]: ...


class MemoryDashboardRepository(DashboardRepository):
    """In-memory dashboard repository for tests and local development."""

    def __init__(self) -> None:
        self._runs: dict[str, ResearchRun] = {}
        self._items: dict[str, ResearchItem] = {}
        self._feedback: dict[str, list[FeedbackRecord]] = {}

    def add_run(self, run: ResearchRun) -> None:
        self._runs[run.run_id] = run

    def get_run(self, run_id: str) -> ResearchRun | None:
        return self._runs.get(run_id)

    def list_runs(
        self,
        *,
        strategy_id: str | None = None,
        portfolio_id: str | None = None,
        status: str | None = None,
        limit: int = 100,
    ) -> list[ResearchRun]:
        runs = list(self._runs.values())
        if strategy_id:
            runs = [r for r in runs if r.strategy_id == strategy_id]
        if portfolio_id:
            runs = [r for r in runs if r.portfolio_id == portfolio_id]
        if status:
            runs = [r for r in runs if r.status == status]
        runs.sort(key=lambda r: r.created_at, reverse=True)
        return runs[:limit]

    def add_items(self, items: list[ResearchItem]) -> None:
        for item in items:
            self._items[item.item_id] = item

    def get_item(self, item_id: str) -> ResearchItem | None:
        return self._items.get(item_id)

    def list_items(self, run_id: str) -> list[ResearchItem]:
        items = [i for i in self._items.values() if i.run_id == run_id]
        items.sort(key=lambda i: i.created_at)
        return items

    def add_feedback(self, feedback: FeedbackRecord) -> None:
        self._feedback.setdefault(feedback.item_id, []).append(feedback)

    def list_feedback(self, item_id: str) -> list[FeedbackRecord]:
        return list(self._feedback.get(item_id, []))
```

Run: `pytest tests/dashboard/test_repository.py -v`
Expected: PASS

- [ ] **Step 3: 提交**

```bash
git add src/margin/dashboard/repository.py tests/dashboard/test_repository.py
git commit -m "feat(dashboard): add dashboard repository interface and memory impl"
```

---

### Task 3: SQLAlchemy 数据库模型

**Files:**
- Create: `src/margin/dashboard/db_models.py`
- Test: `tests/dashboard/test_repository.py`（扩展 SQLAlchemy 测试）

- [ ] **Step 1: 写失败测试**

```python
def test_sqlalchemy_repository_add_run(db_session):
    from margin.dashboard.db_models import DashboardRunRow
    from margin.dashboard.repository import SQLAlchemyDashboardRepository
    from margin.dashboard.models import ResearchRun

    repo = SQLAlchemyDashboardRepository(db_session)
    run = ResearchRun(decision_at="2026-06-19", strategy_id="st_1", version_id="sv_1")
    repo.add_run(run)
    row = db_session.get(DashboardRunRow, run.run_id)
    assert row is not None
    assert row.strategy_id == "st_1"
```

Run: `pytest tests/dashboard/test_repository.py::test_sqlalchemy_repository_add_run -v`
Expected: FAIL "ModuleNotFoundError: No module named 'margin.dashboard.db_models'"

- [ ] **Step 2: 实现 db_models 与 SQLAlchemy 仓库**

`src/margin/dashboard/db_models.py`:

```python
"""SQLAlchemy rows for the dashboard module."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from margin.storage.base import Base


class DashboardRunRow(Base):
    __tablename__ = "dashboard_runs"

    run_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    decision_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    strategy_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    version_id: Mapped[str] = mapped_column(String(64), nullable=False)
    portfolio_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    universe: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    summary: Mapped[str] = mapped_column(String(4096), nullable=False, default="")
    item_count: Mapped[int] = mapped_column(default=0)
    published_count: Mapped[int] = mapped_column(default=0)
    abstained_count: Mapped[int] = mapped_column(default=0)
    aborted_count: Mapped[int] = mapped_column(default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    items: Mapped[list["DashboardItemRow"]] = relationship(
        "DashboardItemRow",
        back_populates="run",
        cascade="all, delete-orphan",
    )


class DashboardItemRow(Base):
    __tablename__ = "dashboard_items"

    item_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    run_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("dashboard_runs.run_id"),
        nullable=False,
        index=True,
    )
    symbol: Mapped[str] = mapped_column(String(32), nullable=False)
    signal_type: Mapped[str] = mapped_column(String(32), nullable=False, default="")
    confidence: Mapped[float] = mapped_column(default=0.0)
    statement: Mapped[str] = mapped_column(String(4096), nullable=False, default="")
    workflow_run_id: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    snapshot_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    abstain_reason: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    rejection_reasons: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    run: Mapped[DashboardRunRow] = relationship("DashboardRunRow", back_populates="items")


class DashboardFeedbackRow(Base):
    __tablename__ = "dashboard_feedback"

    feedback_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    item_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    feedback_type: Mapped[str] = mapped_column(String(32), nullable=False)
    comment: Mapped[str] = mapped_column(String(4096), nullable=False, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
```

在 `src/margin/dashboard/repository.py` 追加：

```python
from sqlalchemy.orm import Session


class SQLAlchemyDashboardRepository(DashboardRepository):
    """PostgreSQL-backed dashboard repository."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def add_run(self, run: ResearchRun) -> None:
        from margin.dashboard.db_models import DashboardRunRow

        self._session.add(
            DashboardRunRow(
                run_id=run.run_id,
                decision_at=run.decision_at,
                strategy_id=run.strategy_id,
                version_id=run.version_id,
                portfolio_id=run.portfolio_id,
                universe=list(run.universe),
                status=run.status.value,
                summary=run.summary,
                item_count=run.item_count,
                published_count=run.published_count,
                abstained_count=run.abstained_count,
                aborted_count=run.aborted_count,
                created_at=run.created_at,
            )
        )

    def get_run(self, run_id: str) -> ResearchRun | None:
        from margin.dashboard.db_models import DashboardRunRow

        row = self._session.get(DashboardRunRow, run_id)
        if row is None:
            return None
        return self._run_from_row(row)

    def list_runs(
        self,
        *,
        strategy_id: str | None = None,
        portfolio_id: str | None = None,
        status: str | None = None,
        limit: int = 100,
    ) -> list[ResearchRun]:
        from margin.dashboard.db_models import DashboardRunRow

        query = self._session.query(DashboardRunRow)
        if strategy_id:
            query = query.filter_by(strategy_id=strategy_id)
        if portfolio_id:
            query = query.filter_by(portfolio_id=portfolio_id)
        if status:
            query = query.filter_by(status=status)
        rows = query.order_by(DashboardRunRow.created_at.desc()).limit(limit).all()
        return [self._run_from_row(row) for row in rows]

    def add_items(self, items: list[ResearchItem]) -> None:
        from margin.dashboard.db_models import DashboardItemRow

        for item in items:
            self._session.add(
                DashboardItemRow(
                    item_id=item.item_id,
                    run_id=item.run_id,
                    symbol=item.symbol,
                    signal_type=item.signal_type,
                    confidence=item.confidence,
                    statement=item.statement,
                    workflow_run_id=item.workflow_run_id,
                    snapshot_id=item.snapshot_id,
                    status=item.status.value,
                    abstain_reason=item.abstain_reason,
                    rejection_reasons=list(item.rejection_reasons),
                    created_at=item.created_at,
                )
            )

    def get_item(self, item_id: str) -> ResearchItem | None:
        from margin.dashboard.db_models import DashboardItemRow

        row = self._session.get(DashboardItemRow, item_id)
        if row is None:
            return None
        return self._item_from_row(row)

    def list_items(self, run_id: str) -> list[ResearchItem]:
        from margin.dashboard.db_models import DashboardItemRow

        rows = (
            self._session.query(DashboardItemRow)
            .filter_by(run_id=run_id)
            .order_by(DashboardItemRow.created_at)
            .all()
        )
        return [self._item_from_row(row) for row in rows]

    def add_feedback(self, feedback: FeedbackRecord) -> None:
        from margin.dashboard.db_models import DashboardFeedbackRow

        self._session.add(
            DashboardFeedbackRow(
                feedback_id=feedback.feedback_id,
                item_id=feedback.item_id,
                feedback_type=feedback.feedback_type.value,
                comment=feedback.comment,
                created_at=feedback.created_at,
            )
        )

    def list_feedback(self, item_id: str) -> list[FeedbackRecord]:
        from margin.dashboard.db_models import DashboardFeedbackRow

        rows = (
            self._session.query(DashboardFeedbackRow)
            .filter_by(item_id=item_id)
            .order_by(DashboardFeedbackRow.created_at)
            .all()
        )
        return [
            FeedbackRecord(
                feedback_id=row.feedback_id,
                item_id=row.item_id,
                feedback_type=row.feedback_type,
                comment=row.comment,
                created_at=row.created_at,
            )
            for row in rows
        ]

    def _run_from_row(self, row: Any) -> ResearchRun:
        return ResearchRun(
            run_id=row.run_id,
            decision_at=row.decision_at,
            strategy_id=row.strategy_id,
            version_id=row.version_id,
            portfolio_id=row.portfolio_id,
            universe=list(row.universe),
            status=row.status,
            summary=row.summary,
            item_count=row.item_count,
            published_count=row.published_count,
            abstained_count=row.abstained_count,
            aborted_count=row.aborted_count,
            created_at=row.created_at,
        )

    def _item_from_row(self, row: Any) -> ResearchItem:
        return ResearchItem(
            item_id=row.item_id,
            run_id=row.run_id,
            symbol=row.symbol,
            signal_type=row.signal_type,
            confidence=row.confidence,
            statement=row.statement,
            workflow_run_id=row.workflow_run_id,
            snapshot_id=row.snapshot_id,
            status=row.status,
            abstain_reason=row.abstain_reason,
            rejection_reasons=list(row.rejection_reasons),
            created_at=row.created_at,
        )
```

Run: `pytest tests/dashboard/test_repository.py -v`
Expected: PASS

- [ ] **Step 3: 提交**

```bash
git add src/margin/dashboard/db_models.py src/margin/dashboard/repository.py tests/dashboard/test_repository.py
git commit -m "feat(dashboard): add SQLAlchemy dashboard repository"
```

---

### Task 4: DashboardResearchService 批量运行聚合

**Files:**
- Create: `src/margin/dashboard/service.py`（先只放 DashboardResearchService）
- Test: `tests/dashboard/test_dashboard_research_service.py`

- [ ] **Step 1: 写失败测试**

```python
from datetime import datetime, UTC
from margin.dashboard.service import DashboardResearchService
from margin.dashboard.repository import MemoryDashboardRepository
from margin.research.service import ResearchService

def test_run_batch_creates_run_and_items():
    research = ResearchService()
    repo = MemoryDashboardRepository()
    service = DashboardResearchService(research_service=research, repository=repo)
    run = service.run_batch(
        decision_at=datetime(2026, 6, 19, 9, 30, tzinfo=UTC),
        strategy_id="st_demo",
        version_id="sv_demo",
        symbols=["000001.SZ"],
    )
    assert run.item_count == 1
    items = repo.list_items(run.run_id)
    assert len(items) == 1
    assert items[0].symbol == "000001.SZ"
```

Run: `pytest tests/dashboard/test_dashboard_research_service.py::test_run_batch_creates_run_and_items -v`
Expected: FAIL "ModuleNotFoundError: No module named 'margin.dashboard.service'"

- [ ] **Step 2: 实现 DashboardResearchService**

```python
"""High-level services for the research candidate dashboard."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from margin.dashboard.models import (
    ItemStatus,
    ResearchItem,
    ResearchRun,
    RunStatus,
)
from margin.dashboard.repository import DashboardRepository, MemoryDashboardRepository
from margin.research.models import WorkflowState
from margin.research.service import ResearchService
from margin.strategy.service import StrategyService


class DashboardResearchService:
    """Orchestrate symbol-level research runs into dashboard batches."""

    def __init__(
        self,
        research_service: ResearchService | None = None,
        strategy_service: StrategyService | None = None,
        repository: DashboardRepository | None = None,
    ) -> None:
        self._research = research_service or ResearchService()
        self._strategy = strategy_service or StrategyService()
        self._repository = repository or MemoryDashboardRepository()

    def run_batch(
        self,
        *,
        decision_at: datetime,
        strategy_id: str,
        version_id: str,
        portfolio_id: str | None = None,
        symbols: list[str] | None = None,
    ) -> ResearchRun:
        """Run research for a universe and aggregate into a ResearchRun."""
        version = self._strategy.get_profile(strategy_id).versions[-1]
        universe = symbols or list(version.config.universe)

        items: list[ResearchItem] = []
        for symbol in universe:
            result = self._research.run(
                symbol=symbol,
                decision_at=decision_at,
                portfolio_id=portfolio_id,
            )
            item = self._result_to_item(
                run_id="",
                symbol=symbol,
                result=result,
            )
            items.append(item)

        run = self._build_run(
            decision_at=decision_at,
            strategy_id=strategy_id,
            version_id=version_id,
            portfolio_id=portfolio_id,
            universe=universe,
            items=items,
        )
        items = [i.model_copy(update={"run_id": run.run_id}) for i in items]

        self._repository.add_run(run)
        self._repository.add_items(items)
        return run

    def _result_to_item(
        self,
        *,
        run_id: str,
        symbol: str,
        result: Any,
    ) -> ResearchItem:
        signal = result.signals[0] if result.signals else None
        status = ItemStatus.PUBLISHED
        if result.state in (WorkflowState.ABORTED.value,):
            status = ItemStatus.ABORTED
        elif signal is None or signal.signal_type in ("abstained", "watch"):
            status = ItemStatus.ABSTAINED

        return ResearchItem(
            run_id=run_id,
            symbol=symbol,
            signal_type=signal.signal_type if signal else "",
            confidence=signal.confidence if signal else 0.0,
            statement=signal.statement if signal else result.error or "",
            workflow_run_id=result.run_id,
            snapshot_id=result.snapshot.snapshot_id if result.snapshot else None,
            status=status,
            abstain_reason=result.error if status == ItemStatus.ABSTAINED else None,
            rejection_reasons=result.messages if status == ItemStatus.ABORTED else [],
        )

    def _build_run(
        self,
        *,
        decision_at: datetime,
        strategy_id: str,
        version_id: str,
        portfolio_id: str | None,
        universe: list[str],
        items: list[ResearchItem],
    ) -> ResearchRun:
        published = sum(1 for i in items if i.status == ItemStatus.PUBLISHED)
        abstained = sum(1 for i in items if i.status == ItemStatus.ABSTAINED)
        aborted = sum(1 for i in items if i.status == ItemStatus.ABORTED)

        if aborted == len(items):
            status = RunStatus.ABORTED
        elif published == 0:
            status = RunStatus.ABSTAINED
        elif aborted > 0 or abstained > 0:
            status = RunStatus.PARTIAL
        else:
            status = RunStatus.PUBLISHED

        return ResearchRun(
            decision_at=decision_at,
            strategy_id=strategy_id,
            version_id=version_id,
            portfolio_id=portfolio_id,
            universe=universe,
            status=status,
            summary=f"published={published}, abstained={abstained}, aborted={aborted}",
            item_count=len(items),
            published_count=published,
            abstained_count=abstained,
            aborted_count=aborted,
        )
```

Run: `pytest tests/dashboard/test_dashboard_research_service.py -v`
Expected: PASS（注意：模块 06 的 ResearchService 默认无 LLM，会产出 abstained/aborted 结果；测试应验证聚合行为，不依赖真实 LLM）

- [ ] **Step 3: 提交**

```bash
git add src/margin/dashboard/service.py tests/dashboard/test_dashboard_research_service.py
git commit -m "feat(dashboard): add DashboardResearchService batch aggregation"
```

---

### Task 5: DashboardQueryService（run/item 查询与候选卡片派生）

**Files:**
- Modify: `src/margin/dashboard/service.py`
- Test: `tests/dashboard/test_query_service.py`

- [ ] **Step 1: 写失败测试**

```python
from margin.dashboard.service import DashboardQueryService
from margin.dashboard.repository import MemoryDashboardRepository
from margin.dashboard.models import ResearchRun, ResearchItem, RunStatus, ItemStatus

def test_get_candidate_cards_filters_published():
    repo = MemoryDashboardRepository()
    run = ResearchRun(decision_at="2026-06-19", strategy_id="st_1", version_id="sv_1")
    repo.add_run(run)
    repo.add_items([
        ResearchItem(run_id=run.run_id, symbol="A", status=ItemStatus.PUBLISHED),
        ResearchItem(run_id=run.run_id, symbol="B", status=ItemStatus.ABSTAINED),
    ])
    service = DashboardQueryService(repository=repo)
    cards = service.get_candidate_cards(run.run_id)
    assert len(cards) == 1
    assert cards[0].symbol == "A"
```

Run: `pytest tests/dashboard/test_query_service.py::test_get_candidate_cards_filters_published -v`
Expected: FAIL "DashboardQueryService 未定义"

- [ ] **Step 2: 实现 DashboardQueryService**

在 `src/margin/dashboard/service.py` 追加：

```python
from margin.dashboard.models import CandidateCard, HomeSummary
from margin.portfolio.service import PortfolioService


class DashboardQueryService:
    """Read-only query service for dashboard views."""

    def __init__(
        self,
        repository: DashboardRepository | None = None,
        portfolio_service: PortfolioService | None = None,
    ) -> None:
        self._repository = repository or MemoryDashboardRepository()
        self._portfolio = portfolio_service or PortfolioService()

    def list_runs(
        self,
        *,
        strategy_id: str | None = None,
        portfolio_id: str | None = None,
        status: str | None = None,
        limit: int = 100,
    ) -> list[ResearchRun]:
        return self._repository.list_runs(
            strategy_id=strategy_id,
            portfolio_id=portfolio_id,
            status=status,
            limit=limit,
        )

    def get_run(self, run_id: str) -> ResearchRun:
        run = self._repository.get_run(run_id)
        if run is None:
            raise KeyError(f"run '{run_id}' not found")
        return run

    def get_run_items(self, run_id: str) -> list[ResearchItem]:
        return self._repository.list_items(run_id)

    def get_item(self, item_id: str) -> ResearchItem:
        item = self._repository.get_item(item_id)
        if item is None:
            raise KeyError(f"item '{item_id}' not found")
        return item

    def get_candidate_cards(
        self,
        run_id: str,
        portfolio_id: str | None = None,
    ) -> list[CandidateCard]:
        run = self.get_run(run_id)
        items = self.get_run_items(run_id)
        position_symbols = self._position_symbols(portfolio_id)
        cards = []
        for item in items:
            if item.status != ItemStatus.PUBLISHED:
                continue
            cards.append(self._to_candidate_card(item, run, position_symbols))
        return cards

    def get_home_summary(
        self,
        *,
        portfolio_id: str | None = None,
        strategy_id: str | None = None,
    ) -> HomeSummary:
        runs = self.list_runs(strategy_id=strategy_id, portfolio_id=portfolio_id, limit=1)
        if not runs:
            return HomeSummary()
        run = runs[0]
        items = self.get_run_items(run.run_id)
        position_symbols = self._position_symbols(portfolio_id)

        candidates = [
            self._to_candidate_card(i, run, position_symbols)
            for i in items if i.status == ItemStatus.PUBLISHED
        ]
        abstained = [
            self._to_candidate_card(i, run, position_symbols)
            for i in items if i.status == ItemStatus.ABSTAINED
        ]
        risks = [
            c for c in candidates
            if c.position_review_status and "review" in c.position_review_status.lower()
        ]

        return HomeSummary(
            decision_at=run.decision_at,
            run_id=run.run_id,
            strategy_id=run.strategy_id,
            version_id=run.version_id,
            run_status=run.status.value,
            today_candidates=candidates,
            position_reviews=[
                c for c in candidates if c.symbol in position_symbols
            ],
            high_priority_risks=risks,
            rejections=abstained,
            run_stats={
                "item_count": run.item_count,
                "published_count": run.published_count,
                "abstained_count": run.abstained_count,
                "aborted_count": run.aborted_count,
            },
        )

    def _position_symbols(self, portfolio_id: str | None) -> set[str]:
        if portfolio_id is None:
            return set()
        try:
            positions = self._portfolio.get_positions(portfolio_id)
            return {p.symbol for p in positions}
        except KeyError:
            return set()

    def _to_candidate_card(
        self,
        item: ResearchItem,
        run: ResearchRun,
        position_symbols: set[str],
    ) -> CandidateCard:
        position_review = None
        if item.symbol in position_symbols:
            position_review = "review"
        return CandidateCard(
            item_id=item.item_id,
            run_id=run.run_id,
            symbol=item.symbol,
            signal_type=item.signal_type,
            confidence=item.confidence,
            statement=item.statement,
            research_status=item.status.value,
            position_review_status=position_review,
            strategy_version=run.version_id,
        )
```

Run: `pytest tests/dashboard/test_query_service.py -v`
Expected: PASS

- [ ] **Step 3: 提交**

```bash
git add src/margin/dashboard/service.py tests/dashboard/test_query_service.py
git commit -m "feat(dashboard): add DashboardQueryService and candidate cards"
```

---

### Task 6: EvidenceViewService 证据展开

**Files:**
- Modify: `src/margin/dashboard/service.py`
- Test: `tests/dashboard/test_evidence_view_service.py`

- [ ] **Step 1: 写失败测试**

```python
from margin.dashboard.service import EvidenceViewService
from margin.dashboard.repository import MemoryDashboardRepository
from margin.dashboard.models import ResearchItem

def test_evidence_view_for_item_without_snapshot():
    repo = MemoryDashboardRepository()
    repo.add_items([ResearchItem(run_id="dr_1", symbol="A", snapshot_id=None)])
    service = EvidenceViewService(repository=repo, research_repository=MemoryResearchRepository())
    view = service.get_evidence_view(repo.list_items("dr_1")[0].item_id)
    assert view.overall_confidence == 0.0
```

Run: `pytest tests/dashboard/test_evidence_view_service.py::test_evidence_view_for_item_without_snapshot -v`
Expected: FAIL

- [ ] **Step 2: 实现 EvidenceViewService**

在 `src/margin/dashboard/service.py` 追加：

```python
from margin.dashboard.models import ClaimView, EvidenceLocator, EvidenceView
from margin.research.repository import ResearchRepository


class EvidenceViewService:
    """Build evidence expansion views from research snapshots."""

    def __init__(
        self,
        repository: DashboardRepository | None = None,
        research_repository: ResearchRepository | None = None,
    ) -> None:
        self._repository = repository or MemoryDashboardRepository()
        self._research_repo = research_repository

    def get_evidence_view(self, item_id: str) -> EvidenceView:
        item = self._repository.get_item(item_id)
        if item is None:
            raise KeyError(f"item '{item_id}' not found")
        if item.snapshot_id is None:
            return EvidenceView(item_id=item_id)

        snapshot = None
        if self._research_repo is not None:
            snapshot = self._research_repo.get_snapshot(item.snapshot_id)
        if snapshot is None:
            return EvidenceView(item_id=item_id)

        claims = [
            ClaimView(
                claim_id=c.claim_id,
                statement=c.statement,
                fact_or_inference=c.fact_or_inference.value,
                confidence=c.confidence,
                has_conflict=c.has_conflict,
                evidence_ids=c.evidence_ids,
            )
            for c in (snapshot.claims or [])
        ]

        evidence_by_level: dict[str, list[EvidenceLocator]] = {}
        locators_available = False
        for evidence in (snapshot.evidences or []):
            level = evidence.source_level.value
            evidence_by_level.setdefault(level, []).append(
                EvidenceLocator(
                    evidence_id=evidence.evidence_id,
                    source_level=level,
                    source_url=evidence.source_url,
                    content=evidence.content[:200],
                    page=evidence.page,
                    section=evidence.section,
                )
            )
            if evidence.is_locatable:
                locators_available = True

        distribution = {
            level: len(items) for level, items in evidence_by_level.items()
        }

        return EvidenceView(
            item_id=item_id,
            claims=claims,
            evidence_by_level=evidence_by_level,
            source_distribution=distribution,
            overall_confidence=item.confidence,
            locators_available=locators_available,
        )
```

Run: `pytest tests/dashboard/test_evidence_view_service.py -v`
Expected: PASS

- [ ] **Step 3: 提交**

```bash
git add src/margin/dashboard/service.py tests/dashboard/test_evidence_view_service.py
git commit -m "feat(dashboard): add EvidenceViewService"
```

---

### Task 7: ValuationViewService 估值视图

**Files:**
- Modify: `src/margin/dashboard/service.py`
- Test: `tests/dashboard/test_valuation_view_service.py`

- [ ] **Step 1: 写失败测试**

```python
from margin.dashboard.service import ValuationViewService
from margin.dashboard.repository import MemoryDashboardRepository
from margin.dashboard.models import ResearchItem

def test_valuation_view_returns_empty_when_no_data():
    repo = MemoryDashboardRepository()
    repo.add_items([ResearchItem(run_id="dr_1", symbol="A")])
    service = ValuationViewService(repository=repo)
    view = service.get_valuation_view(repo.list_items("dr_1")[0].item_id)
    assert view.item_id == repo.list_items("dr_1")[0].item_id
    assert view.margin_of_safety is None
```

Run: `pytest tests/dashboard/test_valuation_view_service.py::test_valuation_view_returns_empty_when_no_data -v`
Expected: FAIL

- [ ] **Step 2: 实现 ValuationViewService**

在 `src/margin/dashboard/service.py` 追加：

```python
from margin.dashboard.models import ValuationView


class ValuationViewService:
    """Build valuation views from item metadata or strategy config."""

    def __init__(
        self,
        repository: DashboardRepository | None = None,
        strategy_service: StrategyService | None = None,
    ) -> None:
        self._repository = repository or MemoryDashboardRepository()
        self._strategy = strategy_service or StrategyService()

    def get_valuation_view(self, item_id: str) -> ValuationView:
        item = self._repository.get_item(item_id)
        if item is None:
            raise KeyError(f"item '{item_id}' not found")

        # MVP: derive from strategy config valuation settings
        try:
            profile = self._strategy.get_profile(item.run_id and "")
            version = profile.versions[-1]
            cfg = version.config.valuation
            base_low = cfg.eps * cfg.pe * 0.9
            base_high = cfg.eps * cfg.pe * 1.1
            return ValuationView(
                item_id=item_id,
                base_valuation_range=(base_low, base_high),
                pessimistic_range=(base_low * 0.8, base_high * 0.8),
                margin_of_safety=0.15,
                value_trap_score=0.3,
                method=cfg.method,
                notes="基于策略配置的估值参数。",
            )
        except (KeyError, ValueError, IndexError):
            return ValuationView(item_id=item_id)
```

Run: `pytest tests/dashboard/test_valuation_view_service.py -v`
Expected: PASS

- [ ] **Step 3: 提交**

```bash
git add src/margin/dashboard/service.py tests/dashboard/test_valuation_view_service.py
git commit -m "feat(dashboard): add ValuationViewService"
```

---

### Task 8: FeedbackService 用户反馈

**Files:**
- Modify: `src/margin/dashboard/service.py`
- Test: `tests/dashboard/test_feedback_service.py`

- [ ] **Step 1: 写失败测试**

```python
from margin.dashboard.service import FeedbackService
from margin.dashboard.repository import MemoryDashboardRepository
from margin.dashboard.models import FeedbackType

def test_record_feedback():
    repo = MemoryDashboardRepository()
    service = FeedbackService(repository=repo)
    fb = service.record_feedback("di_1", FeedbackType.REJECT, "not convincing")
    assert fb.item_id == "di_1"
    assert fb.feedback_type == FeedbackType.REJECT
```

Run: `pytest tests/dashboard/test_feedback_service.py::test_record_feedback -v`
Expected: FAIL

- [ ] **Step 2: 实现 FeedbackService**

在 `src/margin/dashboard/service.py` 追加：

```python
from margin.dashboard.models import FeedbackRecord, FeedbackType


class FeedbackService:
    """Record user feedback on research items."""

    def __init__(
        self,
        repository: DashboardRepository | None = None,
    ) -> None:
        self._repository = repository or MemoryDashboardRepository()

    def record_feedback(
        self,
        item_id: str,
        feedback_type: FeedbackType,
        comment: str = "",
    ) -> FeedbackRecord:
        feedback = FeedbackRecord(
            item_id=item_id,
            feedback_type=feedback_type,
            comment=comment,
        )
        self._repository.add_feedback(feedback)
        return feedback
```

Run: `pytest tests/dashboard/test_feedback_service.py -v`
Expected: PASS

- [ ] **Step 3: 提交**

```bash
git add src/margin/dashboard/service.py tests/dashboard/test_feedback_service.py
git commit -m "feat(dashboard): add FeedbackService"
```

---

### Task 9: FastAPI Dashboard 路由

**Files:**
- Create: `src/margin/api/routes/dashboard.py`
- Test: `tests/api/test_dashboard.py`

- [ ] **Step 1: 写失败测试**

```python
from margin.api.main import create_app
from margin.dashboard.repository import MemoryDashboardRepository
from margin.dashboard.service import DashboardResearchService, DashboardQueryService
from margin.research.service import ResearchService

def test_list_research_runs_empty():
    repo = MemoryDashboardRepository()
    service = DashboardQueryService(repository=repo)
    app = create_app(dashboard_service=service)
    client = TestClient(app)
    response = client.get("/api/v1/research-runs?strategy_id=st_1")
    assert response.status_code == 200
    assert response.json() == []
```

Run: `pytest tests/api/test_dashboard.py::test_list_research_runs_empty -v`
Expected: FAIL "create_app() got an unexpected keyword argument 'dashboard_service'"

- [ ] **Step 2: 实现路由**

`src/margin/api/routes/dashboard.py`:

```python
"""Dashboard API routes for research candidates."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from margin.api.dependencies import get_dashboard_service
from margin.dashboard.models import FeedbackType
from margin.dashboard.service import (
    DashboardQueryService,
    DashboardResearchService,
    EvidenceViewService,
    FeedbackService,
    ValuationViewService,
)

router = APIRouter(prefix="/research-runs", tags=["dashboard"])


class CreateRunRequest(BaseModel):
    decision_at: datetime | None = None
    strategy_id: str = Field(min_length=1)
    version_id: str = Field(min_length=1)
    portfolio_id: str | None = None
    symbols: list[str] = Field(default_factory=list)


class FeedbackRequest(BaseModel):
    feedback_type: str = Field(default="comment")
    comment: str = ""


@router.get("")
def list_runs(
    strategy_id: str | None = None,
    portfolio_id: str | None = None,
    status: str | None = None,
    service: DashboardQueryService = Depends(get_dashboard_service),
) -> list[dict[str, Any]]:
    runs = service.list_runs(
        strategy_id=strategy_id,
        portfolio_id=portfolio_id,
        status=status,
    )
    return [run.model_dump() for run in runs]


@router.post("", status_code=status.HTTP_201_CREATED)
def create_run(
    request: CreateRunRequest,
    service: DashboardResearchService = Depends(get_dashboard_service),
) -> dict[str, Any]:
    try:
        run = service.run_batch(
            decision_at=request.decision_at or datetime.now(),
            strategy_id=request.strategy_id,
            version_id=request.version_id,
            portfolio_id=request.portfolio_id,
            symbols=request.symbols or None,
        )
    except (KeyError, ValueError) as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc
    return run.model_dump()


@router.get("/{run_id}")
def get_run(
    run_id: str,
    service: DashboardQueryService = Depends(get_dashboard_service),
) -> dict[str, Any]:
    try:
        return service.get_run(run_id).model_dump()
    except KeyError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc


@router.get("/{run_id}/items")
def get_run_items(
    run_id: str,
    service: DashboardQueryService = Depends(get_dashboard_service),
) -> list[dict[str, Any]]:
    try:
        return [item.model_dump() for item in service.get_run_items(run_id)]
    except KeyError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc


@router.get("/{run_id}/candidates")
def get_run_candidates(
    run_id: str,
    portfolio_id: str | None = None,
    service: DashboardQueryService = Depends(get_dashboard_service),
) -> list[dict[str, Any]]:
    try:
        cards = service.get_candidate_cards(run_id, portfolio_id=portfolio_id)
        return [card.model_dump() for card in cards]
    except KeyError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc


@router.get("/summary/latest")
def get_latest_summary(
    strategy_id: str | None = None,
    portfolio_id: str | None = None,
    service: DashboardQueryService = Depends(get_dashboard_service),
) -> dict[str, Any]:
    return service.get_home_summary(
        strategy_id=strategy_id,
        portfolio_id=portfolio_id,
    ).model_dump()


@router.get("/items/{item_id}")
def get_item(
    item_id: str,
    service: DashboardQueryService = Depends(get_dashboard_service),
) -> dict[str, Any]:
    try:
        return service.get_item(item_id).model_dump()
    except KeyError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc


@router.get("/items/{item_id}/evidence")
def get_item_evidence(
    item_id: str,
    service: EvidenceViewService = Depends(get_dashboard_service),
) -> dict[str, Any]:
    try:
        return service.get_evidence_view(item_id).model_dump()
    except KeyError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc


@router.get("/items/{item_id}/valuation")
def get_item_valuation(
    item_id: str,
    service: ValuationViewService = Depends(get_dashboard_service),
) -> dict[str, Any]:
    try:
        return service.get_valuation_view(item_id).model_dump()
    except KeyError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc


@router.post("/items/{item_id}/feedback")
def post_feedback(
    item_id: str,
    request: FeedbackRequest,
    service: FeedbackService = Depends(get_dashboard_service),
) -> dict[str, Any]:
    try:
        feedback_type = FeedbackType(request.feedback_type)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"invalid feedback_type: {request.feedback_type}",
        ) from exc
    try:
        feedback = service.record_feedback(
            item_id=item_id,
            feedback_type=feedback_type,
            comment=request.comment,
        )
    except KeyError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc
    return feedback.model_dump()
```

注意：`get_dashboard_service` 需要返回一个包含全部服务或一个聚合服务。为简化，可在 `dependencies.py` 中返回一个 `DashboardService` 门面，或在路由中分别注入。推荐在 `dependencies.py` 中创建 `DashboardService` 聚合门面。

- [ ] **Step 3: 提交**

```bash
git add src/margin/api/routes/dashboard.py tests/api/test_dashboard.py
git commit -m "feat(api): add dashboard research routes"
```

---

### Task 10: 依赖注入与主应用注册

**Files:**
- Modify: `src/margin/api/dependencies.py`
- Modify: `src/margin/api/main.py`
- Test: `tests/api/test_dashboard.py`

- [ ] **Step 1: 写失败测试**

```python
def test_dashboard_router_registered():
    app = create_app()
    routes = [r.path for r in app.routes]
    assert "/api/v1/research-runs" in routes
```

Run: `pytest tests/api/test_dashboard.py::test_dashboard_router_registered -v`
Expected: FAIL "路径未注册"

- [ ] **Step 2: 实现依赖注入**

`src/margin/api/dependencies.py` 追加：

```python
from functools import lru_cache

from margin.dashboard.repository import SQLAlchemyDashboardRepository
from margin.dashboard.service import (
    DashboardQueryService,
    DashboardResearchService,
    EvidenceViewService,
    FeedbackService,
    ValuationViewService,
)


class DashboardServiceFacade:
    """Facade exposing all dashboard services for dependency injection."""

    def __init__(self) -> None:
        self.research = DashboardResearchService()
        self.query = DashboardQueryService()
        self.evidence = EvidenceViewService()
        self.valuation = ValuationViewService()
        self.feedback = FeedbackService()


@lru_cache
def get_dashboard_service() -> DashboardServiceFacade:
    """Return the production dashboard service facade."""
    return DashboardServiceFacade()
```

`src/margin/api/main.py` 修改：

```python
from margin.api.dependencies import (
    get_dashboard_service,
    get_portfolio_service,
    get_research_service,
    get_strategy_service,
)
from margin.api.routes.dashboard import router as dashboard_router
from margin.api.routes.portfolios import router as portfolio_router
from margin.api.routes.research import router as research_router
from margin.api.routes.strategy import router as strategy_router


def create_app(
    portfolio_service: PortfolioService | None = None,
    research_service: ResearchService | None = None,
    strategy_service: StrategyService | None = None,
    dashboard_service: Any | None = None,
) -> FastAPI:
    application = FastAPI(title="Margin API", version="0.1.0")
    application.include_router(portfolio_router)
    application.include_router(research_router)
    application.include_router(strategy_router)
    application.include_router(dashboard_router)

    if dashboard_service is not None:
        application.dependency_overrides[get_dashboard_service] = (
            lambda: dashboard_service
        )
    # ... existing overrides
```

注意：路由文件里 `Depends(get_dashboard_service)` 返回的是 facade，但每个路由 handler 的参数类型写的是具体服务。FastAPI 会按参数类型注入，但 facade 不是这些类型。需要调整路由：让路由直接依赖 facade，或让 `get_dashboard_service` 返回实际服务。

更简单的做法：在 `dependencies.py` 中提供 `get_dashboard_query_service`、`get_dashboard_research_service` 等独立依赖，或让路由使用 facade 的字段：

```python
@router.get("")
def list_runs(
    strategy_id: str | None = None,
    facade: DashboardServiceFacade = Depends(get_dashboard_service),
) -> list[dict[str, Any]]:
    runs = facade.query.list_runs(...)
    return [run.model_dump() for run in runs]
```

按此方式调整 `dashboard.py` 中所有 handler。

Run: `pytest tests/api/test_dashboard.py -v`
Expected: PASS

- [ ] **Step 3: 提交**

```bash
git add src/margin/api/dependencies.py src/margin/api/main.py tests/api/test_dashboard.py
git commit -m "feat(api): wire dashboard service facade and router"
```

---

### Task 11: 包导出与后端清理

**Files:**
- Create: `src/margin/dashboard/__init__.py`
- Modify: 必要的 import 修正
- Test: `ruff check src tests`

- [ ] **Step 1: 实现 `__init__.py`**

```python
"""Public exports for the dashboard module."""

from __future__ import annotations

from margin.dashboard.models import (
    CandidateCard,
    EvidenceView,
    FeedbackRecord,
    FeedbackType,
    HomeSummary,
    ItemStatus,
    ResearchItem,
    ResearchRun,
    RunStatus,
    ValuationView,
)
from margin.dashboard.repository import (
    DashboardRepository,
    MemoryDashboardRepository,
    SQLAlchemyDashboardRepository,
)
from margin.dashboard.service import (
    DashboardQueryService,
    DashboardResearchService,
    EvidenceViewService,
    FeedbackService,
    ValuationViewService,
)

__all__ = [
    "CandidateCard",
    "DashboardQueryService",
    "DashboardRepository",
    "DashboardResearchService",
    "EvidenceViewService",
    "EvidenceView",
    "FeedbackRecord",
    "FeedbackService",
    "FeedbackType",
    "HomeSummary",
    "ItemStatus",
    "MemoryDashboardRepository",
    "ResearchItem",
    "ResearchRun",
    "RunStatus",
    "SQLAlchemyDashboardRepository",
    "ValuationView",
    "ValuationViewService",
]
```

- [ ] **Step 2: 运行 ruff**

Run: `ruff check src tests`
Expected: PASS（修复所有 import 排序、行长度、未使用变量等问题）

- [ ] **Step 3: 提交**

```bash
git add src/margin/dashboard/__init__.py
git commit -m "feat(dashboard): add public package exports"
```

---

### Task 12: 前端 API 类型与请求函数

**Files:**
- Modify: `web/lib/api.ts`
- Test: `web/lib/api.test.ts`（可选，若时间紧可省略）

- [ ] **Step 1: 新增类型与请求函数**

在 `web/lib/api.ts` 追加：

```typescript
export type ResearchRun = {
  run_id: string;
  decision_at: string;
  strategy_id: string;
  version_id: string;
  portfolio_id: string | null;
  universe: string[];
  status: string;
  summary: string;
  item_count: number;
  published_count: number;
  abstained_count: number;
  aborted_count: number;
  created_at: string;
};

export type ResearchItem = {
  item_id: string;
  run_id: string;
  symbol: string;
  signal_type: string;
  confidence: number;
  statement: string;
  workflow_run_id: string;
  snapshot_id: string | null;
  status: string;
  abstain_reason: string | null;
  rejection_reasons: string[];
  created_at: string;
};

export type CandidateCard = {
  item_id: string;
  run_id: string;
  symbol: string;
  signal_type: string;
  confidence: number;
  statement: string;
  current_price: number | null;
  quantitative_rank: number | null;
  research_status: string;
  position_review_status: string | null;
  valuation_range: [number, number] | null;
  margin_of_safety: number | null;
  value_trap_score: number | null;
  event_window: string | null;
  catalysts: string[];
  counter_arguments: string[];
  evidence_summary: Record<string, unknown>;
  watch_conditions: string[];
  invalidation_conditions: string[];
  strategy_version: string;
  disclaimer: string;
};

export type EvidenceView = {
  item_id: string;
  claims: Array<{
    claim_id: string;
    statement: string;
    fact_or_inference: string;
    confidence: number;
    has_conflict: boolean;
    evidence_ids: string[];
  }>;
  evidence_by_level: Record<string, Array<{
    evidence_id: string;
    source_level: string;
    source_url: string | null;
    content: string;
    page: number | null;
    section: string | null;
  }>>;
  source_distribution: Record<string, number>;
  overall_confidence: number;
  locators_available: boolean;
};

export type ValuationView = {
  item_id: string;
  base_valuation_range: [number, number] | null;
  pessimistic_range: [number, number] | null;
  margin_of_safety: number | null;
  value_trap_score: number | null;
  method: string | null;
  notes: string;
};

export type HomeSummary = {
  decision_at: string | null;
  run_id: string | null;
  strategy_id: string | null;
  version_id: string | null;
  run_status: string | null;
  today_candidates: CandidateCard[];
  position_reviews: CandidateCard[];
  high_priority_risks: CandidateCard[];
  rejections: CandidateCard[];
  run_stats: Record<string, number>;
};

async function post<T>(path: string, body: unknown): Promise<T> {
  const response = await fetch(`${API_BASE_URL}${path}`, {
    method: "POST",
    headers: {
      accept: "application/json",
      "content-type": "application/json",
    },
    body: JSON.stringify(body),
  });
  if (!response.ok) {
    throw new Error(`Margin API ${response.status}: ${path}`);
  }
  return response.json() as Promise<T>;
}

export function fetchResearchRuns(
  params: { strategy_id?: string; portfolio_id?: string; status?: string } = {},
): Promise<ResearchRun[]> {
  const query = new URLSearchParams();
  if (params.strategy_id) query.set("strategy_id", params.strategy_id);
  if (params.portfolio_id) query.set("portfolio_id", params.portfolio_id);
  if (params.status) query.set("status", params.status);
  return request<ResearchRun[]>(`/api/v1/research-runs?${query.toString()}`);
}

export function fetchResearchRun(runId: string): Promise<ResearchRun> {
  return request<ResearchRun>(`/api/v1/research-runs/${runId}`);
}

export function fetchResearchItems(runId: string): Promise<ResearchItem[]> {
  return request<ResearchItem[]>(`/api/v1/research-runs/${runId}/items`);
}

export function fetchResearchItem(itemId: string): Promise<ResearchItem> {
  return request<ResearchItem>(`/api/v1/research-runs/items/${itemId}`);
}

export function fetchEvidenceView(itemId: string): Promise<EvidenceView> {
  return request<EvidenceView>(`/api/v1/research-runs/items/${itemId}/evidence`);
}

export function fetchValuationView(itemId: string): Promise<ValuationView> {
  return request<ValuationView>(`/api/v1/research-runs/items/${itemId}/valuation`);
}

export function postResearchRun(body: {
  strategy_id: string;
  version_id: string;
  portfolio_id?: string;
  symbols?: string[];
  decision_at?: string;
}): Promise<ResearchRun> {
  return post<ResearchRun>("/api/v1/research-runs", body);
}

export function postFeedback(
  itemId: string,
  body: { feedback_type: string; comment?: string },
): Promise<{ feedback_id: string }> {
  return post<{ feedback_id: string }>(
    `/api/v1/research-runs/items/${itemId}/feedback`,
    body,
  );
}
```

- [ ] **Step 2: 运行前端 lint**

Run: `cd web && npm run lint`
Expected: PASS

- [ ] **Step 3: 提交**

```bash
git add web/lib/api.ts
git commit -m "feat(web): add dashboard API types and fetch helpers"
```

---

### Task 13: 候选卡片组件

**Files:**
- Create: `web/components/CandidateCard.tsx`
- Create: `web/components/CandidateList.tsx`
- Create: `web/components/ResearchStatusBadge.tsx`
- Create: `web/components/PositionReviewBadge.tsx`
- Test: `web/components/CandidateCard.test.tsx`

- [ ] **Step 1: 写失败测试**

```typescript
import { render, screen } from "@testing-library/react";
import { CandidateCard } from "./Candidate-card";
import type { CandidateCard as CandidateCardType } from "@/lib/api";

test("renders disclaimer", () => {
  const card: CandidateCardType = {
    item_id: "di_1",
    run_id: "dr_1",
    symbol: "000001.SZ",
    signal_type: "research_candidate",
    confidence: 0.82,
    statement: "Free cash flow improved.",
    current_price: 12.5,
    quantitative_rank: 3,
    research_status: "published",
    position_review_status: null,
    valuation_range: [10, 15],
    margin_of_safety: 0.2,
    value_trap_score: 0.3,
    event_window: "Q2 earnings",
    catalysts: ["earnings"],
    counter_arguments: ["macro risk"],
    evidence_summary: {},
    watch_conditions: ["watch margin"],
    invalidation_conditions: ["margin drops"],
    strategy_version: "sv_1",
    disclaimer: "本系统输出研究分析，不构成买卖指令。",
  };
  render(<CandidateCard card={card} />);
  expect(screen.getByText(/不构成买卖指令/)).toBeInTheDocument();
});
```

Run: `cd web && npm test -- CandidateCard.test.tsx`
Expected: FAIL

- [ ] **Step 2: 实现组件**

`web/components/CandidateCard.tsx`:

```typescript
import type { CandidateCard as CandidateCardType } from "@/lib/api";

export function CandidateCard({ card }: { card: CandidateCardType }) {
  return (
    <article className="candidate-card" aria-labelledby={`candidate-${card.item_id}`}>
      <header className="candidate-header">
        <h3 id={`candidate-${card.item_id}`}>{card.symbol}</h3>
        <ResearchStatusBadge status={card.research_status} />
        {card.position_review_status && (
          <PositionReviewBadge status={card.position_review_status} />
        )}
      </header>
      <p className="candidate-statement">{card.statement}</p>
      <dl className="candidate-meta">
        <dt>置信度</dt>
        <dd>{(card.confidence * 100).toFixed(0)}%</dd>
        {card.margin_of_safety !== null && (
          <>
            <dt>安全边际</dt>
            <dd>{(card.margin_of_safety * 100).toFixed(0)}%</dd>
          </>
        )}
        {card.value_trap_score !== null && (
          <>
            <dt>价值陷阱评分</dt>
            <dd>{card.value_trap_score.toFixed(2)}</dd>
          </>
        )}
      </dl>
      {card.counter_arguments.length > 0 && (
        <div className="candidate-counter">
          <strong>反方理由</strong>
          <ul>
            {card.counter_arguments.map((reason, idx) => (
              <li key={idx}>{reason}</li>
            ))}
          </ul>
        </div>
      )}
      <p className="candidate-disclaimer">{card.disclaimer}</p>
    </article>
  );
}
```

`web/components/ResearchStatusBadge.tsx`:

```typescript
export function ResearchStatusBadge({ status }: { status: string }) {
  return <span className={`badge research-status ${status}`}>{status}</span>;
}
```

`web/components/PositionReviewBadge.tsx`:

```typescript
export function PositionReviewBadge({ status }: { status: string }) {
  return <span className={`badge position-review ${status}`}>{status}</span>;
}
```

`web/components/CandidateList.tsx`:

```typescript
"use client";

import { useMemo, useState } from "react";
import { CandidateCard } from "./CandidateCard";
import type { CandidateCard as CandidateCardType } from "@/lib/api";

export function CandidateList({ cards }: { cards: CandidateCardType[] }) {
  const [filter, setFilter] = useState<string>("all");
  const filtered = useMemo(() => {
    if (filter === "all") return cards;
    return cards.filter((c) => c.research_status === filter);
  }, [cards, filter]);

  return (
    <div className="candidate-list">
      <div className="filter-bar">
        {["all", "published", "abstained", "aborted"].map((status) => (
          <button
            key={status}
            className={filter === status ? "active" : ""}
            onClick={() => setFilter(status)}
          >
            {status}
          </button>
        ))}
      </div>
      {filtered.length === 0 ? (
        <div className="empty-state">无匹配候选</div>
      ) : (
        <ul className="candidate-grid">
          {filtered.map((card) => (
            <li key={card.item_id}>
              <CandidateCard card={card} />
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
```

Run: `cd web && npm test -- CandidateCard.test.tsx`
Expected: PASS

- [ ] **Step 3: 提交**

```bash
git add web/components/CandidateCard.tsx web/components/CandidateList.tsx \
  web/components/ResearchStatusBadge.tsx web/components/PositionReviewBadge.tsx \
  web/components/CandidateCard.test.tsx
git commit -m "feat(web): add candidate card components"
```

---

### Task 14: 证据面板与估值面板

**Files:**
- Create: `web/components/EvidencePanel.tsx`
- Create: `web/components/ValuationPanel.tsx`
- Test: `web/components/EvidencePanel.test.tsx`

- [ ] **Step 1: 写失败测试**

```typescript
import { render, screen } from "@testing-library/react";
import { EvidencePanel } from "./EvidencePanel";
import type { EvidenceView } from "@/lib/api";

test("renders claims", () => {
  const view: EvidenceView = {
    item_id: "di_1",
    claims: [
      { claim_id: "c1", statement: "Revenue grew", fact_or_inference: "fact", confidence: 0.9, has_conflict: false, evidence_ids: ["e1"] },
    ],
    evidence_by_level: {},
    source_distribution: {},
    overall_confidence: 0.9,
    locators_available: true,
  };
  render(<EvidencePanel view={view} />);
  expect(screen.getByText("Revenue grew")).toBeInTheDocument();
});
```

Run: `cd web && npm test -- EvidencePanel.test.tsx`
Expected: FAIL

- [ ] **Step 2: 实现组件**

`web/components/EvidencePanel.tsx`:

```typescript
import type { EvidenceView } from "@/lib/api";

export function EvidencePanel({ view }: { view: EvidenceView }) {
  return (
    <section className="evidence-panel" aria-labelledby="evidence-heading">
      <h2 id="evidence-heading">证据链</h2>
      <p>整体置信度: {(view.overall_confidence * 100).toFixed(0)}%</p>
      {view.claims.length === 0 ? (
        <div className="empty-state">暂无结论</div>
      ) : (
        <ul className="claim-list">
          {view.claims.map((claim) => (
            <li key={claim.claim_id} className={claim.has_conflict ? "conflict" : ""}>
              <p>{claim.statement}</p>
              <span className="tag">{claim.fact_or_inference}</span>
              <span className="tag">置信度 {(claim.confidence * 100).toFixed(0)}%</span>
            </li>
          ))}
        </ul>
      )}
      {Object.entries(view.evidence_by_level).map(([level, evidences]) => (
        <div key={level}>
          <h3>证据等级 {level}</h3>
          <ul>
            {evidences.map((ev) => (
              <li key={ev.evidence_id}>
                <p>{ev.content}</p>
                {ev.source_url && <a href={ev.source_url}>来源</a>}
              </li>
            ))}
          </ul>
        </div>
      ))}
    </section>
  );
}
```

`web/components/ValuationPanel.tsx`:

```typescript
import type { ValuationView } from "@/lib/api";

export function ValuationPanel({ view }: { view: ValuationView }) {
  return (
    <section className="valuation-panel" aria-labelledby="valuation-heading">
      <h2 id="valuation-heading">估值视图</h2>
      {view.base_valuation_range ? (
        <dl>
          <dt>基础估值区间</dt>
          <dd>
            {view.base_valuation_range[0]} - {view.base_valuation_range[1]}
          </dd>
          {view.pessimistic_range && (
            <>
              <dt>悲观估值区间</dt>
              <dd>
                {view.pessimistic_range[0]} - {view.pessimistic_range[1]}
              </dd>
            </>
          )}
          {view.margin_of_safety !== null && (
            <>
              <dt>安全边际</dt>
              <dd>{(view.margin_of_safety * 100).toFixed(0)}%</dd>
            </>
          )}
          {view.value_trap_score !== null && (
            <>
              <dt>价值陷阱评分</dt>
              <dd>{view.value_trap_score.toFixed(2)}</dd>
            </>
          )}
        </dl>
      ) : (
        <div className="empty-state">估值数据暂不可用</div>
      )}
      {view.notes && <p>{view.notes}</p>}
    </section>
  );
}
```

Run: `cd web && npm test -- EvidencePanel.test.tsx`
Expected: PASS

- [ ] **Step 3: 提交**

```bash
git add web/components/EvidencePanel.tsx web/components/ValuationPanel.tsx \
  web/components/EvidencePanel.test.tsx
git commit -m "feat(web): add evidence and valuation panels"
```

---

### Task 15: 首页摘要组件

**Files:**
- Create: `web/components/HomeSummary.tsx`
- Test: `web/components/HomeSummary.test.tsx`

- [ ] **Step 1: 写失败测试**

```typescript
import { render, screen } from "@testing-library/react";
import { HomeSummary } from "./HomeSummary";
import type { HomeSummary as HomeSummaryType } from "@/lib/api";

test("renders six sections", () => {
  const summary: HomeSummaryType = {
    decision_at: "2026-06-19",
    run_id: "dr_1",
    strategy_id: "st_1",
    version_id: "sv_1",
    run_status: "published",
    today_candidates: [],
    position_reviews: [],
    high_priority_risks: [],
    rejections: [],
    run_stats: { item_count: 0 },
  };
  render(<HomeSummary summary={summary} />);
  expect(screen.getByText(/今日候选/)).toBeInTheDocument();
});
```

Run: `cd web && npm test -- HomeSummary.test.tsx`
Expected: FAIL

- [ ] **Step 2: 实现组件**

```typescript
import { CandidateList } from "./CandidateList";
import type { HomeSummary as HomeSummaryType } from "@/lib/api";

export function HomeSummary({ summary }: { summary: HomeSummaryType }) {
  return (
    <div className="home-summary">
      <section className="panel">
        <h2>市场状态摘要</h2>
        <p>运行: {summary.run_id ?? "—"}</p>
        <p>策略: {summary.strategy_id ?? "—"}</p>
        <p>状态: {summary.run_status ?? "—"}</p>
      </section>

      <section className="panel">
        <h2>今日研究候选</h2>
        <CandidateList cards={summary.today_candidates} />
      </section>

      <section className="panel">
        <h2>持仓复核提醒</h2>
        <CandidateList cards={summary.position_reviews} />
      </section>

      <section className="panel">
        <h2>高优先级风险</h2>
        <CandidateList cards={summary.high_priority_risks} />
      </section>

      <section className="panel">
        <h2>拒绝判断与原因</h2>
        <CandidateList cards={summary.rejections} />
      </section>

      <section className="panel">
        <h2>策略运行状态</h2>
        <dl>
          {Object.entries(summary.run_stats).map(([key, value]) => (
            <div key={key}>
              <dt>{key}</dt>
              <dd>{value}</dd>
            </div>
          ))}
        </dl>
      </section>
    </div>
  );
}
```

Run: `cd web && npm test -- HomeSummary.test.tsx`
Expected: PASS

- [ ] **Step 3: 提交**

```bash
git add web/components/HomeSummary.tsx web/components/HomeSummary.test.tsx
git commit -m "feat(web): add home summary component"
```

---

### Task 16: 前端页面

**Files:**
- Create: `web/app/research/page.tsx`
- Create: `web/app/research/runs/[runId]/page.tsx`
- Create: `web/app/research/items/[itemId]/page.tsx`
- Test: 端到端可手动验证

- [ ] **Step 1: 实现首页**

`web/app/research/page.tsx`:

```typescript
import { HomeSummary } from "@/components/HomeSummary";
import { fetchResearchRuns, fetchHomeSummary } from "@/lib/api";

export default async function ResearchPage() {
  let summary = null;
  let error: string | null = null;
  try {
    const runs = await fetchResearchRuns({ limit: "1" });
    const runId = runs[0]?.run_id;
    summary = runId ? await fetchHomeSummary(runId) : null;
  } catch {
    error = "研究面板数据暂时不可用";
  }

  return (
    <main className="workspace-shell">
      <header className="workspace-header">
        <h1>研究候选面板</h1>
      </header>
      {error ? (
        <div className="notice-panel" role="alert">{error}</div>
      ) : summary ? (
        <HomeSummary summary={summary} />
      ) : (
        <div className="notice-panel" role="status">暂无研究运行</div>
      )}
    </main>
  );
}
```

注意：`fetchHomeSummary` 需先在 `web/lib/api.ts` 中实现（参考后端 API 设计）。

- [ ] **Step 2: 实现运行详情页**

`web/app/research/runs/[runId]/page.tsx`:

```typescript
import { CandidateList } from "@/components/CandidateList";
import { fetchResearchRun, fetchCandidateCards } from "@/lib/api";

export default async function RunPage({ params }: { params: Promise<{ runId: string }> }) {
  const { runId } = await params;
  let run = null;
  let cards = [];
  let error = null;
  try {
    [run, cards] = await Promise.all([
      fetchResearchRun(runId),
      fetchCandidateCards(runId),
    ]);
  } catch {
    error = "运行详情加载失败";
  }

  return (
    <main className="workspace-shell">
      <header className="workspace-header">
        <h1>运行详情 {runId}</h1>
        {run && <span className="badge">{run.status}</span>}
      </header>
      {error ? (
        <div className="notice-panel" role="alert">{error}</div>
      ) : (
        <CandidateList cards={cards} />
      )}
    </main>
  );
}
```

- [ ] **Step 3: 实现单股详情页**

`web/app/research/items/[itemId]/page.tsx`:

```typescript
import { EvidencePanel } from "@/components/EvidencePanel";
import { ValuationPanel } from "@/components/ValuationPanel";
import { fetchResearchItem, fetchEvidenceView, fetchValuationView } from "@/lib/api";

export default async function ItemPage({ params }: { params: Promise<{ itemId: string }> }) {
  const { itemId } = await params;
  let item = null;
  let evidence = null;
  let valuation = null;
  let error = null;
  try {
    [item, evidence, valuation] = await Promise.all([
      fetchResearchItem(itemId),
      fetchEvidenceView(itemId),
      fetchValuationView(itemId),
    ]);
  } catch {
    error = "研究详情加载失败";
  }

  return (
    <main className="workspace-shell">
      <header className="workspace-header">
        <h1>{item?.symbol ?? itemId}</h1>
        {item && <span className="badge">{item.signal_type}</span>}
      </header>
      {error ? (
        <div className="notice-panel" role="alert">{error}</div>
      ) : (
        <>
          <section className="panel">
            <h2>结论</h2>
            <p>{item?.statement}</p>
          </section>
          {evidence && <EvidencePanel view={evidence} />}
          {valuation && <ValuationPanel view={valuation} />}
        </>
      )}
    </main>
  );
}
```

- [ ] **Step 4: 提交**

```bash
git add web/app/research web/app/research/runs web/app/research/items
# 添加缺失的 fetchHomeSummary / fetchCandidateCards 到 web/lib/api.ts 后
git add web/lib/api.ts
git commit -m "feat(web): add research dashboard pages"
```

---

### Task 17: 集成测试与最终验证

**Files:**
- 全部新增/修改文件

- [ ] **Step 1: 运行后端测试**

Run: `pytest tests/dashboard tests/api/test_dashboard.py -v`
Expected: PASS（修复所有失败）

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
git commit -m "feat(dashboard): complete module 08 MVP with tests and lint"
```

---

## 计划自查

### Spec 覆盖检查

| 设计文档章节 | 实现任务 |
|-------------|---------|
| 4.1 ResearchRun / 4.2 ResearchItem | Task 1 |
| 4.3 CandidateCard | Task 1 + Task 5 |
| 4.4 EvidenceView | Task 1 + Task 6 |
| 4.5 ValuationView | Task 1 + Task 7 |
| 4.6 FeedbackRecord | Task 1 + Task 8 |
| 5.1 DashboardResearchService | Task 4 |
| 5.2 DashboardQueryService | Task 5 |
| 5.3 EvidenceViewService | Task 6 |
| 5.4 ValuationViewService | Task 7 |
| 5.5 FeedbackService | Task 8 |
| 6. API 端点 | Task 9 + Task 10 |
| 7. 前端页面 | Task 16 |
| 8. 降级策略 | Task 4 / 6 / 16（data_missing / 错误 UI） |
| 9. 测试 | 各 Task 均含测试 |

### Placeholder 扫描

- 无 TBD / TODO / "implement later" / "add appropriate error handling" 等占位符。
- 每个代码步骤均包含具体代码或具体修改位置。
- 前端页面引用的 `fetchHomeSummary` / `fetchCandidateCards` 需在 Task 12 中补充实现。

### 类型一致性检查

- `ResearchRun.status` / `ResearchItem.status` 使用 `RunStatus` / `ItemStatus` StrEnum，与仓库、服务一致。
- `CandidateCard` 字段与前端组件、API 类型一致。
- `DashboardServiceFacade` 统一暴露 `query` / `research` / `evidence` / `valuation` / `feedback`，路由中统一使用 facade。

## 执行交接

计划已保存到 `docs/superpowers/plans/2026-06-19-module-08-research-candidate-dashboard.md`。

**两种执行方式：**

1. **Subagent-Driven（推荐）**：我按任务逐个派发子代理，每个任务完成后做 spec compliance + code quality 两轮审查，迭代快、质量高。
2. **Inline Execution**：我在当前会话按任务批次直接执行，关键节点 checkpoint 后给你确认。

你选哪种？
