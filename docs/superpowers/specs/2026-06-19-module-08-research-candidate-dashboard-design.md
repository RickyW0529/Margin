# 模块 08：研究候选面板（Research Candidate Dashboard）设计文档

> 对应产品 §7 / §9.1 / §15、架构 §16 / §25 / §26-Phase5、spec `docs/spec/v0.1/08-research_candidate_dashboard/spec.md` 及计划 `docs/plan/v0.1/08-research_candidate_dashboard/`。

## 1. 目标

为 Margin 构建「研究候选面板」模块，把模块 06 产生的研究信号与模块 07 的策略配置聚合为可交互的候选列表、单股详情和首页概览。面板必须：

- 展示今日研究候选与历史运行批次；
- 支持候选卡片、证据展开、估值视图、反方分析；
- 显式提示「不是买卖指令」；
- 对 Aborted / Abstained / 证据缺失 / 持仓缺失等情况做优雅降级；
- 提供 API 与 Next.js 前端页面，为后续持仓复核面板（模块 09）提供数据接口。

## 2. 关键决策

### 2.1 run/item 聚合归属

采用「模块 08 自行聚合」方案：

- 模块 06 保持现有 per-symbol 工作流与 `ResearchSnapshot` 不变；
- 模块 08 定义 `ResearchRun` / `ResearchItem` 聚合，通过 `workflow_run_id` / `snapshot_id` 引用模块 06 结果；
- 批量运行由 `DashboardResearchService`  orchestrate，对每个 symbol 调用 `ResearchService.run()`，再汇总为 run/item。

理由：MVP 风险最小，模块 06 已测试完成，模块 08 拥有真正的不可变晚间运行聚合，便于审计与回放。

## 3. 模块边界

新增 `src/margin/dashboard/` 模块：

| 文件 | 职责 |
|------|------|
| `models.py` | `ResearchRun`、`ResearchItem`、`CandidateCard`、`EvidenceView`、`ValuationView`、`FeedbackRecord`、`JobRun` 等不可变 Pydantic 模型 |
| `repository.py` | `DashboardRepository` 接口；`MemoryDashboardRepository` 与 `SQLAlchemyDashboardRepository` 实现 |
| `db_models.py` | SQLAlchemy 行模型（`dashboard_runs`、`dashboard_items`、`dashboard_feedback` 等） |
| `service.py` | `DashboardResearchService`、`DashboardQueryService`、`EvidenceViewService`、`ValuationViewService`、`FeedbackService` |
| `renderer.py` | `ReportRenderer` / `ExportService`，导出 JSON / Markdown |
| `api/routes/dashboard.py` | FastAPI 路由，实现架构 §16.3 端点 |
| `__init__.py` | 公共导出 |

前端新增/修改：

| 文件 | 职责 |
|------|------|
| `web/app/research/page.tsx` | 研究候选面板首页 |
| `web/app/research/runs/[runId]/page.tsx` | 单次运行详情 |
| `web/app/research/items/[itemId]/page.tsx` | 单股研究详情 |
| `web/components/CandidateCard.tsx` | 候选卡片 |
| `web/components/CandidateList.tsx` | 候选列表与过滤 |
| `web/components/EvidencePanel.tsx` | 证据展开视图 |
| `web/components/ValuationPanel.tsx` | 估值视图 |
| `web/components/ResearchStatusBadge.tsx` | 研究状态徽章 |
| `web/components/PositionReviewBadge.tsx` | 持仓复核状态徽章 |
| `web/components/HomeSummary.tsx` | 首页六类信息聚合 |
| `web/lib/api.ts` | 新增 dashboard API 调用 |
| `src/margin/api/routes/dashboard.py` | BFF 路由 |
| `src/margin/api/dependencies.py` | 新增 `get_dashboard_service()` |
| `src/margin/api/main.py` | 注册 dashboard router |

## 4. 数据模型

### 4.1 ResearchRun

```text
run_id: str                    # dr_<hex>
decision_at: datetime          # 决策时点（UTC）
strategy_id: str
version_id: str
portfolio_id: str | None
universe: list[str]
status: RunStatus               # published / abstained / aborted / partial
summary: str
item_count: int
published_count: int
abstained_count: int
aborted_count: int
created_at: datetime
```

### 4.2 ResearchItem

```text
item_id: str                   # di_<hex>
run_id: str
symbol: str
signal_type: str               # research_candidate / watch / abstained
confidence: float              # [0, 1]
statement: str
workflow_run_id: str           # 引用模块 06 run_id
snapshot_id: str | None        # 引用模块 06 snapshot_id
status: ItemStatus              # published / abstained / aborted / data_missing
abstain_reason: str | None
rejection_reasons: list[str]
created_at: datetime
```

### 4.3 CandidateCard

派生视图，用于前端候选卡片：

```text
item_id: str
run_id: str
symbol: str
signal_type: str
confidence: float
statement: str
current_price: float | None
quantitative_rank: int | None
research_status: str
position_review_status: str | None
valuation_range: tuple[float, float] | None
margin_of_safety: float | None
value_trap_score: float | None
event_window: str | None
catalysts: list[str]
counter_arguments: list[str]
evidence_summary: EvidenceSummary
watch_conditions: list[str]
invalidation_conditions: list[str]
strategy_version: str
disclaimer: str                # 固定「不是买卖指令」
```

### 4.4 EvidenceView

```text
item_id: str
claims: list[ClaimView]        # 结论、事实/推断标记、置信度、冲突
evidence_by_level: dict[str, list[EvidenceLocator]]
source_distribution: dict[str, int]
overall_confidence: float
locators_available: bool
```

### 4.5 ValuationView

```text
item_id: str
base_valuation_range: tuple[float, float] | None
pessimistic_range: tuple[float, float] | None
margin_of_safety: float | None
value_trap_score: float | None
method: str | None
notes: str
```

### 4.6 FeedbackRecord

```text
feedback_id: str
item_id: str
feedback_type: str             # accept / reject / watch / comment
comment: str
created_at: datetime
```

## 5. 核心服务

### 5.1 DashboardResearchService

- `run_batch(decision_at, strategy_id, portfolio_id=None, symbols=None) -> ResearchRun`
  1. 通过 `StrategyService` 获取策略版本配置；
  2. 若 `symbols` 为空，从策略 `universe` 读取；
  3. 对每个 symbol 调用 `ResearchService.run(symbol, decision_at, portfolio_id)`；
  4. 将每个 `WorkflowResult` 转为 `ResearchItem`；
  5. 汇总状态、计数、摘要，创建 `ResearchRun`；
  6. 持久化并返回 run_id。

### 5.2 DashboardQueryService

- `list_runs(filters) -> list[ResearchRun]`
- `get_run(run_id) -> ResearchRun`
- `get_run_items(run_id) -> list[ResearchItem]`
- `get_item(item_id) -> ResearchItem`
- `get_candidate_cards(run_id, portfolio_id=None) -> list[CandidateCard]`
- `get_home_summary(portfolio_id=None, strategy_id=None) -> HomeSummary`

### 5.3 EvidenceViewService

- `get_evidence_view(item_id) -> EvidenceView`
  - 通过 `snapshot_id` 读取模块 06 `ResearchSnapshot`；
  - 提取 claims 与 evidences；
  - 按证据等级分组，保留 locator 字段；
  - 返回 `EvidenceView`。

### 5.4 ValuationViewService

- `get_valuation_view(item_id) -> ValuationView`
  - 从 agent 输出或策略配置解析估值区间、安全边际、价值陷阱评分；
  - 若解析失败返回空视图。

### 5.5 FeedbackService

- `record_feedback(item_id, feedback_type, comment="") -> FeedbackRecord`
  - 追加反馈记录，不修改 `ResearchItem`。

## 6. API 端点

前缀 `/api/v1`：

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/research-runs` | 列表查询，支持 `date`、`strategy_id`、`portfolio_id`、`status` |
| POST | `/research-runs` | 触发批量研究运行 |
| GET | `/research-runs/{run_id}` | 运行详情 |
| GET | `/research-runs/{run_id}/items` | 运行下的 item 列表 |
| GET | `/research-items/{item_id}` | item 详情 |
| GET | `/research-items/{item_id}/evidence` | 证据展开视图 |
| GET | `/research-items/{item_id}/valuation` | 估值视图 |
| GET | `/research-items/{item_id}/audit` | 审计轨迹 |
| POST | `/research-items/{item_id}/feedback` | 提交反馈 |
| GET | `/provider-status` | 各 provider 健康状态 |
| POST | `/jobs/nightly-runs` | 触发晚间批量任务 |
| GET | `/jobs/{job_run_id}` | 查询任务状态 |

## 7. 前端页面

### 7.1 `/research` 首页

展示六类信息：

1. 市场状态摘要（运行日期、策略版本、状态）；
2. 今日研究候选（候选卡片列表）；
3. 持仓复核提醒（已持有标的对应的信号状态）；
4. 高优先级风险（信号为 watch / abstained 且持仓中的标的）；
5. 拒绝判断与原因（abstained / aborted 列表）；
6. 策略运行状态（最近一次运行统计）。

### 7.2 `/research/runs/{runId}`

- 运行元信息；
- 候选列表（可过滤 published / watch / abstained / aborted）；
- 拒绝/放弃原因汇总。

### 7.3 `/research/items/{itemId}`

- 顶部：股票代码、当前价、研究信号、置信度；
- 标签页或分区：结论 / 量化因子 / 估值区间 / 证据链 / 催化剂 / 风险 / 反方分析 / 历史信号；
- 底部：免责声明、反馈按钮。

## 8. 降级策略

对应架构 §25：

| 场景 | 降级行为 |
|------|----------|
| 运行 Aborted/Abstained | 面板展示拒绝判断与原因，不展示虚假候选 |
| 证据视图加载失败 | 展示证据摘要与定位字段，不展示无证据结论 |
| BFF 查询超时 | 展示最近可用运行快照并标记时间 |
| 模块 06 快照缺失 | item 状态标记为 `data_missing`，卡片显示「证据暂不可用」 |
| 持仓上下文缺失 | 持仓复核状态栏显示「未绑定组合」 |
| 估值解析失败 | 估值视图显示「估值数据暂不可用」 |

## 9. 测试策略

### 9.1 后端测试

`tests/dashboard/`：

- `test_models.py`：Pydantic 模型验证、UTC 归一化、不可变约束；
- `test_repository.py`：Memory / SQLAlchemy 仓库 append-only 行为；
- `test_dashboard_research_service.py`：批量运行聚合、状态推导、失败降级；
- `test_query_service.py`：run/item 查询、候选卡片派生、首页聚合；
- `test_evidence_view_service.py`：证据展开视图、证据等级分组；
- `test_valuation_view_service.py`：估值视图解析；
- `test_feedback_service.py`：反馈追加；
- `test_api.py`：FastAPI 端点契约与错误码。

### 9.2 前端测试

`web/components/`：

- `CandidateCard.test.tsx`：字段渲染、免责声明存在；
- `EvidencePanel.test.tsx`：证据展开交互；
- `HomeSummary.test.tsx`：六类信息聚合。

### 9.3 TDD 纪律

每个新函数/方法先写失败测试，再实现最小代码，验证通过后重构。

## 10. 验收标准

- [ ] 可创建批量研究运行并生成 run/item；
- [ ] 首页正确展示六类信息；
- [ ] 候选卡片包含必填字段与免责声明；
- [ ] 证据展开视图展示结论、事实/推断、证据等级与定位；
- [ ] 估值视图展示估值区间、安全边际、价值陷阱评分；
- [ ] Aborted/Abstained/证据缺失场景有明确降级 UI；
- [ ] API 端点与架构 §16.3 对齐；
- [ ] 后端测试覆盖率不低于现有模块（>95% 通过）；
- [ ] `ruff check src tests` 通过；
- [ ] 前端 `npm run lint` 与 `npm test` 通过。

## 11. 后续扩展

- 接入真实市场数据与模块 05 evidence 检索；
- 支持模块 09 持仓复核面板的数据消费；
- 增加邮件/钉钉告警输出；
- 支持导出 PDF 研究报告。
