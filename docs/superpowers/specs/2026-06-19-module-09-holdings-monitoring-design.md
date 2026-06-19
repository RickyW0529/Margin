# 模块 09：持仓监控（Holdings Monitoring）设计文档

> 对应产品 §5.3 / §8 / §10 / §15、架构 §17 / §19 / §25 / §26-Phase5、spec `docs/spec/v0.1/09-holdings_monitoring/spec.md` 及计划 `docs/plan/v0.1/09-holdings_monitoring/`。

## 1. 目标

为 Margin 构建「持仓监控」模块，持续验证当前持仓的投资逻辑是否仍成立、组合风险是否需要复核，并在盘中与盘后按规则触发分级提醒。模块必须：

- 只做确定性规则检测，盘中不调用 LLM、不执行 Agent 长链、不自动下单；
- 生成不可变的 `AlertEvent` 与 `PositionReviewRecord`，支持复盘与行为指标度量；
- 在持仓详情页展示健康状态、提醒列表与操作历史；
- 为研究候选面板（模块 08）预留 `position_review_status` 与 `position_reviews` 字段，后续可回填持仓复核信号。

## 2. 关键决策

### 2.1 盘中安全边界

采用纯确定性规则引擎：

- 价格数据缺失 → `DATA_MISSING` + P2 数据异常提醒；
- 价格跌破成本价 10% → `INVALIDATED` + P0 价格失效提醒（`changed_thesis=True`）；
- 价格跌破成本价 5% → `RISK` + P1 风险提醒；
- 到达 `next_review_at` / 关键事件窗口 → `EVENT_PENDING` + P2 提醒；
- 策略失败、模型排名下降 ≥30、行业暴露 ≥35% → `WATCH` + P2 提醒。

不触发重新训练、全市场研究或任意 Agent 长链。

### 2.2 不可变审计

`AlertEvent` 与 `PositionReviewRecord` 均为 append-only，落库后不可修改。`OperationHistoryEntry` 通过交易记录、提醒、复盘记录按时间聚合生成，不单独持久化。

### 2.3 复用模块 02 领域模型

直接使用 `margin.portfolio.models` 中的 `Position`、`PositionThesis`、`PositionHealthStatus`、`ThesisStatus`、`Trade`，不反向改写持仓数据。投资逻辑变更由模块 02 的 thesis API 负责，模块 09 只读取。

## 3. 模块边界

新增 `src/margin/holdings_monitoring/` 模块：

| 文件 | 职责 |
|------|------|
| `src/margin/holdings_monitoring/models.py` | `AlertEvent`、`PositionMonitoringSnapshot`、`PositionReviewRecord`、`OperationHistoryEntry`、`BehaviorMetric` 等不可变 Pydantic 模型 |
| `src/margin/holdings_monitoring/db_models.py` | SQLAlchemy 行模型 `AlertEventRow`、`PositionReviewRow` |
| `src/margin/holdings_monitoring/repository.py` | `MonitoringRepository` Protocol；`MemoryMonitoringRepository` 与 `SQLAlchemyMonitoringRepository` |
| `src/margin/holdings_monitoring/service.py` | `HoldingsMonitoringService` 规则引擎、`MonitoringServiceBundle` DI 容器 |
| `src/margin/holdings_monitoring/__init__.py` | 公共导出 |
| `src/margin/api/routes/monitoring.py` | FastAPI 路由，实现架构 §17.3 端点 |
| `alembic/versions/20260619_0008_holdings_monitoring.py` | `alert_events`、`position_reviews` 表迁移 |

前端新增/修改：

| 文件 | 职责 |
|------|------|
| `web/lib/api.ts` | `AlertEvent`、`OperationHistoryEntry` 类型与 `fetchPositionAlerts`、`fetchPositionHistory` |
| `web/app/positions/[positionId]/page.tsx` | 并行获取持仓详情、提醒、操作历史 |
| `web/components/position-detail.tsx` | 渲染持仓监控面板与操作历史 |
| `web/components/position-review-badge.tsx` | 持仓复核状态徽章 |
| `web/components/research-status-badge.tsx` | 研究状态徽章（与模块 08 共享） |
| `web/components/position-detail.test.tsx` | 持仓详情渲染测试 |

后端测试：

| 文件 | 职责 |
|------|------|
| `tests/holdings_monitoring/test_service.py` | 规则引擎状态推导与提醒生成 |
| `tests/holdings_monitoring/test_repository.py` | 内存/SQLAlchemy 仓库 append-only 行为 |
| `tests/api/test_monitoring.py` | 监控 API 端点契约 |

## 4. 数据模型

### 4.1 AlertEvent

```text
alert_id: str                 # al_<hex>
portfolio_id: str
position_id: str
symbol: str
alert_type: AlertType         # data_quality | new_disclosure | negative_event | price_invalidation | model_rank_change | industry_exposure | valuation_target | strategy_failure | key_event_pending
severity: AlertPriority       # P0 | P1 | P2 | P3
message: str
rule_name: str
triggered_at: datetime
evidence_refs: list[str]
changed_thesis: bool
acknowledged_at: datetime | None
```

### 4.2 PositionMonitoringSnapshot

```text
position_id: str
portfolio_id: str
symbol: str
health_status: PositionHealthStatus   # HEALTHY | WATCH | RISK | INVALIDATED | DATA_MISSING | EVENT_PENDING
thesis_status: ThesisStatus           # THESIS_VALID | REVIEW_REQUIRED | RISK_ALERT | THESIS_INVALIDATED
evaluated_at: datetime
reasons: list[str]
alerts: list[AlertEvent]
data_missing: bool
```

### 4.3 PositionReviewRecord

```text
review_id: str                # rv_<hex>
portfolio_id: str
position_id: str
alert_id: str | None
decision: ReviewDecision      # hold | reduce | exit | watch | ignore
rationale: str
action_taken_at: datetime | None
created_at: datetime
```

### 4.4 OperationHistoryEntry

```text
event_id: str
position_id: str
event_type: str               # trade | alert | review
occurred_at: datetime
summary: str
metadata: dict[str, Any]
```

### 4.5 BehaviorMetric

```text
metric_id: str
portfolio_id: str
position_id: str
alert_id: str
review_id: str
action_latency_seconds: int | None
signal_execution_gap: str | None
```

## 5. 核心服务

### 5.1 HoldingsMonitoringService

- `evaluate_position(...)` — 对给定 `Position` + `PositionThesis` 执行确定性规则，返回 `PositionMonitoringSnapshot`，并将生成的 `AlertEvent` 追加到仓库。
- `evaluate_position_by_id(...)` — 通过 `PortfolioService` 加载 `PositionDetail` 后执行评估。
- `record_review(...)` — 校验 `alert_id` 存在（若提供），追加 `PositionReviewRecord`。
- `list_alerts(...)` / `list_reviews(...)` — 按 portfolio/position 查询。
- `get_operation_history(...)` — 合并交易、提醒、复盘记录为时间线。
- `get_behavior_metrics(...)` — 计算 alert 到 review 的处理时长度量。

### 5.2 MonitoringServiceBundle

DI 容器，暴露 `monitoring: HoldingsMonitoringService`，支持 `in_memory()` 测试工厂与 `from_repositories()` 生产工厂。

## 6. API 端点

前缀 `/api/v1`：

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/positions/{position_id}/monitoring/evaluate` | 执行持仓监控评估 |
| GET | `/positions/{position_id}/alerts` | 查询持仓提醒 |
| POST | `/positions/{position_id}/reviews` | 提交复盘记录 |
| GET | `/positions/{position_id}/history` | 查询操作历史 |
| GET | `/positions/{position_id}/behavior-metrics` | 查询处理时长度量 |

## 7. 前端页面

### 7.1 `/positions/{positionId}`

- 顶部：股票代码 + `health_status` 徽章；
- 指标区：成本金额、成本价、市值、权重；
- 买入逻辑面板：thesis、持有条件、失效条件；
- 持仓监控面板：提醒列表（含 P0/P1/P2/P3 徽章）与证据数；
- 盈亏面板：浮动盈亏、收益率、行业；
- 操作历史面板：交易 / 提醒 / 复盘记录时间线。

## 8. 降级策略

对应架构 §25：

| 场景 | 降级行为 |
|------|----------|
| 价格数据缺失 | `DATA_MISSING` + P2 提醒，停止输出高置信持仓判断 |
| 证据检索为空 | 仍按价格/时间规则生成提醒，不阻塞规则检测 |
|  PortfolioService 不可用 | `evaluate_position_by_id` 抛出 `RuntimeError`，API 返回 500 |
| 复盘时 alert_id 不存在 | 抛出 `KeyError`，API 返回 404 |

## 9. 测试策略

### 9.1 后端测试

`tests/holdings_monitoring/`：

- `test_service.py`：价格失效/风险/数据缺失/复核到期/策略失败/模型排名/行业暴露等状态推导；
- `test_repository.py`：内存与 SQLAlchemy 仓库的 append-only 查询行为。

`tests/api/test_monitoring.py`：

- 端到端测试 evaluate / alerts / reviews / history / behavior-metrics 端点。

### 9.2 前端测试

`web/components/position-detail.test.tsx`：

- 渲染持仓指标、买入逻辑、失效条件、操作历史、监控面板、P0 提醒与复盘记录。

### 9.3 TDD 纪律

每个新函数/方法先写失败测试，再实现最小代码，验证通过后重构。

## 10. 验收标准

- [ ] 价格触及失效阈值时触发 P0 提醒并标记 `changed_thesis=True`；
- [ ] 价格接近失效阈值时触发 P1 提醒；
- [ ] 数据缺失时触发 P2 提醒并标记 `DATA_MISSING`；
- [ ] 复盘记录可追加，且能关联到已有 alert；
- [ ] 操作历史按时间聚合交易、提醒、复盘；
- [ ] 处理时长度量可计算；
- [ ] 持仓详情页正确展示提醒与历史；
- [ ] 后端 `ruff check src tests` 通过；
- [ ] 后端 `pytest` 全绿；
- [ ] 前端 `npm run lint` 与 `npm test` 通过。

## 11. 后续扩展

- 接入真实盘中价格 / 新闻 Poller，定时触发 `evaluate_position_by_id`；
- 在研究候选面板回填 `position_reviews` 与 `position_review_status`；
- 增加通知 Provider（邮件/钉钉/WebSocket）输出 P0/P1 提醒；
- 支持用户在前端直接标记 alert 已读/已处理。
