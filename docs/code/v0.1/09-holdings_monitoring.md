# 09-holdings_monitoring 模块代码文档

## 目录

1. [模块概述](#模块概述)
2. [文件级摘要](#文件级摘要)
3. [领域模型](#领域模型)
4. [服务层](#服务层)
5. [Runner 与 Provider](#runner-与-provider)
6. [仓库层](#仓库层)
7. [FastAPI 接口](#fastapi-接口)
8. [Next.js 页面与 Server Actions](#nextjs-页面与-server-actions)
9. [React 组件](#react-组件)
10. [跨模块使用说明](#跨模块使用说明)

---

## 模块概述

`09-holdings_monitoring` 负责 Margin v0.1 的**投后持仓监控**。它以确定性规则对已持有头寸进行实时/准实时评估：

- 根据价格回撤、模型排名变化、行业暴露、策略失败、关键事件、负面新闻等触发 Alert。
- 以只追加（append-only）方式持久化 `AlertEvent` 与 `PositionReviewRecord`。
- 提供人工复盘入口，记录 `hold / reduce / exit / watch / ignore` 决策。
- 汇总交易、提醒、复盘三类记录，生成统一的操作历史（`OperationHistoryEntry`）。
- 计算行为指标（`BehaviorMetric`），量化从提醒触发到人工行动的延迟。

高优先级 Alert（`P0`、`P1`）会通过 `NotificationSink` 发出通知，默认实现写入结构化日志。

---

## 文件级摘要

| 文件路径 | 职责 |
| --- | --- |
| `src/margin/holdings_monitoring/__init__.py` | 模块公共导出，聚合模型、仓库、服务。 |
| `src/margin/holdings_monitoring/db_models.py` | SQLAlchemy ORM 映射：`AlertEventRow`、`PositionReviewRow`。 |
| `src/margin/holdings_monitoring/models.py` | Pydantic 领域模型与枚举：`AlertEvent`、`PositionMonitoringSnapshot`、`PositionReviewRecord`、`BehaviorMetric` 等。 |
| `src/margin/holdings_monitoring/repository.py` | 持久化协议 `MonitoringRepository`、内存实现、SQLAlchemy 实现及行模型转换函数。 |
| `src/margin/holdings_monitoring/runner.py` | 自动全量扫描 `HoldingsMonitoringRunner`，以及价格/新闻/通知适配器。 |
| `src/margin/holdings_monitoring/service.py` | 核心服务 `HoldingsMonitoringService` 与依赖注入容器 `MonitoringServiceBundle`。 |
| `src/margin/api/routes/monitoring.py` | FastAPI 路由：评估、查询 Alert、创建复盘、操作历史、行为指标。 |
| `web/app/positions/[positionId]/page.tsx` | Next.js Server Component，拉取持仓详情/Alert/历史并渲染 `PositionDetailView`。 |
| `web/app/positions/[positionId]/loading.tsx` | 该路由的加载占位。 |
| `web/app/positions/[positionId]/actions.ts` | Server Actions：`evaluatePositionAction`、`createPositionReviewAction`。 |
| `web/components/position-detail.tsx` | 持仓详情主组件，展示指标、买入逻辑、Alert、复盘表单、操作历史。 |
| `web/components/position-detail.test.tsx` | `PositionDetailView` 的 Vitest 单元测试。 |
| `web/components/position-review-badge.tsx` | 持仓/候选复盘状态徽标组件。 |

---

## 领域模型

源文件：`src/margin/holdings_monitoring/models.py`

### 枚举

| 枚举 | 取值 | 说明 |
| --- | --- | --- |
| `AlertPriority` | `P0` / `P1` / `P2` / `P3` | 提醒优先级，`P0` 最高。 |
| `AlertType` | `data_quality` / `new_disclosure` / `negative_event` / `price_invalidation` / `model_rank_change` / `industry_exposure` / `valuation_target` / `strategy_failure` / `key_event_pending` | 支持的确定性监控类型。 |
| `ReviewDecision` | `hold` / `reduce` / `exit` / `watch` / `ignore` | 人工复盘决策。 |

### `AlertEvent`

只追加的监控提醒事件。

| 字段 | 类型 | 默认值 / 约束 | 说明 |
| --- | --- | --- | --- |
| `alert_id` | `str` | `al_{uuid[:12]}` | 唯一标识。 |
| `portfolio_id` | `str` | 必填 | 所属组合。 |
| `position_id` | `str` | 必填 | 所属头寸。 |
| `symbol` | `str` | 必填 | 标的代码。 |
| `alert_type` | `AlertType` | 必填 | 提醒类型。 |
| `severity` | `AlertPriority` | `P2` | 优先级。 |
| `message` | `str` | 必填 | 可读消息。 |
| `rule_name` | `str` | 必填 | 触发规则名称。 |
| `triggered_at` | `datetime` | `utc_now()` | 触发时间（UTC 规范化）。 |
| `evidence_refs` | `list[str]` | `[]` | 关联证据 ID 列表。 |
| `changed_thesis` | `bool` | `False` | 是否导致投资逻辑状态变化。 |
| `acknowledged_at` | `datetime \| None` | `None` | 被确认时间。 |

- `model_config = {"frozen": True}`：实例创建后不可变。
- `normalize_timestamps`：将 `triggered_at` / `acknowledged_at` 规范为 UTC。

### `PositionMonitoringSnapshot`

单次确定性评估结果。

| 字段 | 类型 | 默认值 | 说明 |
| --- | --- | --- | --- |
| `position_id` | `str` | 必填 | 头寸 ID。 |
| `portfolio_id` | `str` | 必填 | 组合 ID。 |
| `symbol` | `str` | 必填 | 标的代码。 |
| `health_status` | `PositionHealthStatus` | 必填 | 头寸健康状态。 |
| `thesis_status` | `ThesisStatus` | 必填 | 投资逻辑状态。 |
| `evaluated_at` | `datetime` | `utc_now()` | 评估时间（UTC）。 |
| `reasons` | `list[str]` | `[]` | 触发原因说明。 |
| `alerts` | `list[AlertEvent]` | `[]` | 本次实际发出的 Alert（已考虑冷却）。 |
| `data_missing` | `bool` | `False` | 是否价格缺失。 |

### `PositionReviewRecord`

只追加的人工复盘记录。

| 字段 | 类型 | 默认值 | 说明 |
| --- | --- | --- | --- |
| `review_id` | `str` | `rv_{uuid[:12]}` | 唯一标识。 |
| `portfolio_id` | `str` | 必填 | 组合 ID。 |
| `position_id` | `str` | 必填 | 头寸 ID。 |
| `alert_id` | `str \| None` | `None` | 关联 Alert（可选）。 |
| `decision` | `ReviewDecision` | 必填 | 复盘决策。 |
| `rationale` | `str` | 必填 | 决策理由。 |
| `action_taken_at` | `datetime \| None` | `None` | 实际执行时间。 |
| `created_at` | `datetime` | `utc_now()` | 创建时间（UTC）。 |

### `BehaviorMetric`

从 Alert 与 Review 推导的用户行为指标。

| 字段 | 类型 | 默认值 | 说明 |
| --- | --- | --- | --- |
| `metric_id` | `str` | `bm_{uuid[:12]}` | 唯一标识。 |
| `portfolio_id` | `str` | 必填 | 组合 ID。 |
| `position_id` | `str` | 必填 | 头寸 ID。 |
| `alert_id` | `str` | 必填 | 触发 Alert ID。 |
| `review_id` | `str` | 必填 | 复盘记录 ID。 |
| `action_latency_seconds` | `int \| None` | `None` | 从 Alert 触发到 action_taken_at 的秒数。 |
| `signal_execution_gap` | `str \| None` | `None` | Review 决策值（如 `reduce`）。 |

### `OperationHistoryEntry`

统一操作历史条目。

| 字段 | 类型 | 默认值 | 说明 |
| --- | --- | --- | --- |
| `event_id` | `str` | 必填 | 事件 ID。 |
| `position_id` | `str` | 必填 | 头寸 ID。 |
| `event_type` | `str` | 必填 | `trade` / `alert` / `review`。 |
| `occurred_at` | `datetime` | 必填 | 发生时间（UTC）。 |
| `summary` | `str` | 必填 | 可读摘要。 |
| `metadata` | `dict[str, Any]` | `{}` | 扩展元数据。 |

---

## 服务层

源文件：`src/margin/holdings_monitoring/service.py`

### 关键常量

| 常量 | 值 | 含义 |
| --- | --- | --- |
| `PRICE_INVALIDATION_DRAWDOWN` | `0.10` | 价格较成本价下跌 10% 判定投资逻辑失效。 |
| `PRICE_RISK_DRAWDOWN` | `0.05` | 价格较成本价下跌 5% 触发风险提醒。 |
| `ALERT_COOLDOWN` | `timedelta(hours=6)` | 同一规则 6 小时内不重复发出 Alert。 |

### `HoldingsMonitoringService`

确定性持仓监控服务。

| 方法 | 签名 | 说明 |
| --- | --- | --- |
| `__init__` | `self, repository=None, portfolio_service=None` | 默认使用 `MemoryMonitoringRepository`；可注入 `PortfolioService` 用于按 ID 加载头寸。 |
| `evaluate_position` | `self, *, portfolio_id, position, thesis=None, current_price=None, evidence_refs=None, model_rank_delta=None, industry_exposure=None, strategy_failure=False, upcoming_event_at=None, news_events=None, decision_at=None` | 核心评估函数，按顺序检查价格缺失、价格失效/风险、复核时间、策略失败、模型排名下降、行业暴露、关键事件、新闻事件，返回 `PositionMonitoringSnapshot`。 |
| `evaluate_position_by_id` | `self, *, portfolio_id, position_id, ...` | 从 `PortfolioService` 加载头寸详情后再调用 `evaluate_position`；未配置 `portfolio_service` 时抛 `RuntimeError`。 |
| `list_alerts` | `self, portfolio_id, position_id=None` | 查询 Alert 列表。 |
| `record_review` | `self, *, portfolio_id, position_id, alert_id=None, decision, rationale, action_taken_at=None` | 创建并持久化复盘记录；若 `alert_id` 非空且不存在则抛 `KeyError`。 |
| `list_reviews` | `self, portfolio_id, position_id=None` | 查询复盘记录列表。 |
| `get_behavior_metrics` | `self, portfolio_id, position_id` | 将同一头寸的 Alert 与 Review 关联，计算 `action_latency_seconds` 与 `signal_execution_gap`。 |
| `get_operation_history` | `self, *, portfolio_id, position_id, trades=None` | 汇总交易、Alert、Review，按时间排序生成 `OperationHistoryEntry` 列表。 |
| `_build_alert` | `self, *, portfolio_id, position, alert_type, severity, rule_name, message, triggered_at, evidence_refs, changed_thesis=False` | 内部工厂方法，构造 `AlertEvent`。 |

`evaluate_position` 规则判定顺序：

1. **价格缺失**：`current_price` 与 `position.current_price` 均为空 → `DATA_MISSING` + `data_quality` Alert。
2. **价格失效**：现价 ≤ 成本价 × 0.9 → `INVALIDATED` / `THESIS_INVALIDATED` + `P0` `price_invalidation` Alert。
3. **价格风险**：现价 ≤ 成本价 × 0.95 → `RISK` / `RISK_ALERT` + `P1` `price_risk` Alert。
4. **复核到期**：`thesis.next_review_at` 已到期 → `EVENT_PENDING` + `key_event_pending` Alert。
5. **策略失败**：`strategy_failure=True` → `WATCH` + `strategy_failure` Alert。
6. **模型排名下降**：`model_rank_delta <= -30` → `WATCH` + `model_rank_change` Alert。
7. **行业暴露过高**：`industry_exposure >= 0.35` → `WATCH` + `industry_exposure` Alert。
8. **关键事件临近**：`upcoming_event_at` 非空 → `EVENT_PENDING` + `key_event_pending` Alert。
9. **新闻事件扫描**：对 `news_events` 中涉及该标的且已可用的事件，识别负面关键词（处罚、立案、亏损、下修、违约、诉讼、减持、风险）。若负面且 `can_change_research_state=True`，触发 `negative_event`（`P1`，`changed_thesis=True`）；否则触发 `new_disclosure`（`P2`）。

最终通过 `ALERT_COOLDOWN` 过滤同一规则短期重复触发，只追加未冷却的 Alert。

### `MonitoringServiceBundle`

FastAPI 依赖注入容器。

| 方法 | 签名 | 说明 |
| --- | --- | --- |
| `__init__` | `self, monitoring: HoldingsMonitoringService` | 持有监控服务实例。 |
| `in_memory` | `cls, *, portfolio_service=None, repository=None` | 构造使用内存仓库的 Bundle，用于测试或本地嵌入。 |
| `from_repositories` | `cls, *, repository, portfolio_service` | 构造基于指定仓库与 `PortfolioService` 的 Bundle。 |

### 模块私有函数

| 函数 | 签名 | 说明 |
| --- | --- | --- |
| `_ensure_dt` | `value: datetime \| None -> datetime` | 返回 UTC 时间，空值时取当前 UTC。 |
| `_position_from_detail` | `detail: object, portfolio_id: str -> Position` | 从头寸详情对象反射字段构造 `Position`。 |

---

## Runner 与 Provider

源文件：`src/margin/holdings_monitoring/runner.py`

### 协议

| 协议 | 方法 | 说明 |
| --- | --- | --- |
| `LatestPriceProvider` | `get_latest_prices(symbols, *, as_of) -> dict[str, float]` | 批量获取最新价格。 |
| `NotificationSink` | `notify(alert: AlertEvent) -> None` | 投递高优先级 Alert。 |
| `NewsEventProvider` | `get_recent_events(symbols, *, since, as_of) -> list[DocumentEvent]` | 获取时间窗口内、涉及指定标的的新闻事件。 |

### `AKShareLatestPriceProvider`

基于 AKShare 调整后日线获取最新价的适配器。

| 方法 | 签名 | 说明 |
| --- | --- | --- |
| `__init__` | `self, provider: AKShareProvider \| None = None` | 可注入 `AKShareProvider`，否则新建实例。 |
| `get_latest_prices` | `self, symbols, *, as_of` | 拉取 `as_of` 前 14 天日线，取每个标的最新收盘价；异常时记录 warning 并返回空字典。 |

### `RepositoryNewsEventProvider`

读取 `03-news` 模块已持久化的事件流。

| 方法 | 签名 | 说明 |
| --- | --- | --- |
| `__init__` | `self, repository: NewsRepository` | 注入 `NewsRepository`。 |
| `get_recent_events` | `self, symbols, *, since, as_of` | 过滤 `list_unique_events()` 中标的交集非空且 `since < available_at <= as_of` 的事件。 |

### `LoggingNotificationSink`

默认通知落地方案，写入结构化日志。

| 方法 | 签名 | 说明 |
| --- | --- | --- |
| `notify` | `self, alert: AlertEvent` | 以 `logger.warning` 输出 `holdings_monitoring_alert`，附带 alert_id / portfolio_id / position_id / symbol / severity / rule_name。 |

### `HoldingsMonitoringRunner`

自动全量持仓监控扫描器。

| 方法 | 签名 | 说明 |
| --- | --- | --- |
| `__init__` | `self, *, portfolio_service, monitoring_service, price_provider, news_provider=None, notifier=None` | 注入必要服务；`notifier` 默认 `LoggingNotificationSink`。 |
| `run_once` | `self, *, decision_at=None` | 遍历所有本地组合与头寸，批量查价、查新闻，对每个头寸调用 `evaluate_position`；对结果中的 `P0`/`P1` Alert 调用 `notifier.notify`。返回所有 `PositionMonitoringSnapshot`。 |

`run_once` 内部逻辑：

- `evaluated_at` 缺省为当前 UTC；`news_since` 缺省为上次检查时间或前一天。
- 通过 `portfolio_service.list_portfolios()` 与 `get_positions()` 获取头寸。
- 获取 `priced_positions`（传入 `prices` 后的 enriched positions）。
- 评估完成后更新 `self._last_news_check = evaluated_at`。

---

## 仓库层

源文件：`src/margin/holdings_monitoring/repository.py`

### `MonitoringRepository`（Protocol）

| 方法 | 签名 | 说明 |
| --- | --- | --- |
| `add_alert` | `self, alert: AlertEvent` | 追加 Alert。 |
| `list_alerts` | `self, portfolio_id, position_id=None` | 查询 Alert，可按头寸过滤。 |
| `get_alert` | `self, alert_id: str` | 按 ID 取 Alert。 |
| `get_latest_alert` | `self, portfolio_id, position_id, rule_name` | 取某规则最新一次 Alert。 |
| `add_review` | `self, review: PositionReviewRecord` | 追加复盘记录。 |
| `list_reviews` | `self, portfolio_id, position_id=None` | 查询复盘记录。 |

### `MemoryMonitoringRepository`

内存实现，用于测试与嵌入场景。

| 方法 | 签名 | 说明 |
| --- | --- | --- |
| `__init__` | `self` | 初始化内部 `_alerts` 与 `_reviews` 字典。 |
| `add_alert` | `self, alert` | 按 `alert_id` 存入字典。 |
| `list_alerts` | `self, portfolio_id, position_id=None` | 按组合/头寸过滤并按 `(triggered_at, alert_id)` 排序。 |
| `get_alert` | `self, alert_id` | 字典取值。 |
| `get_latest_alert` | `self, portfolio_id, position_id, rule_name` | 取触发时间最大的 Alert。 |
| `add_review` | `self, review` | 按 `review_id` 存入字典。 |
| `list_reviews` | `self, portfolio_id, position_id=None` | 按组合/头寸过滤并按 `(created_at, review_id)` 排序。 |

### `SQLAlchemyMonitoringRepository`

PostgreSQL 实现，基于短 SQLAlchemy 会话。

| 方法 | 签名 | 说明 |
| --- | --- | --- |
| `__init__` | `self, session_factory: Callable[[], Session]` | 保存会话工厂。 |
| `add_alert` | `self, alert` | 转换并写入 `AlertEventRow`。 |
| `list_alerts` | `self, portfolio_id, position_id=None` | 构造 `select AlertEventRow`，按时间/ID 排序，逐行转领域模型。 |
| `get_alert` | `self, alert_id` | `session.get(AlertEventRow, alert_id)` 后转模型。 |
| `get_latest_alert` | `self, portfolio_id, position_id, rule_name` | 按 `triggered_at desc` 取一条。 |
| `add_review` | `self, review` | 转换并写入 `PositionReviewRow`。 |
| `list_reviews` | `self, portfolio_id, position_id=None` | 构造 `select PositionReviewRow`，按时间/ID 排序。 |

### 行模型转换函数

| 函数 | 签名 | 说明 |
| --- | --- | --- |
| `_alert_to_row` | `alert: AlertEvent -> AlertEventRow` | 枚举转字符串，列表深拷贝。 |
| `_alert_from_row` | `row: AlertEventRow -> AlertEvent` | 字符串转枚举。 |
| `_review_to_row` | `review: PositionReviewRecord -> PositionReviewRow` | 枚举转字符串。 |
| `_review_from_row` | `row: PositionReviewRow -> PositionReviewRecord` | 字符串转枚举。 |

---

## FastAPI 接口

源文件：`src/margin/api/routes/monitoring.py`

路由前缀：`/api/v1`，标签：`monitoring`。

| 方法 | 路径 | 状态码 | 说明 | 请求体 / Query | 响应 |
| --- | --- | --- | --- | --- | --- |
| `POST` | `/positions/{position_id}/monitoring/evaluate` | `201` | 对指定头寸执行确定性监控评估。 | `MonitoringEvaluateRequest` | `PositionMonitoringSnapshot` |
| `GET` | `/positions/{position_id}/alerts` | `200` | 查询头寸的 Alert 列表。 | `portfolio_id` (Query, 必填) | `list[AlertEvent]` |
| `POST` | `/positions/{position_id}/reviews` | `201` | 为头寸追加人工复盘记录。 | `ReviewCreate` | `PositionReviewRecord` |
| `GET` | `/positions/{position_id}/history` | `200` | 查询统一操作历史。 | `portfolio_id` (Query, 必填) | `list[OperationHistoryEntry]` |
| `GET` | `/positions/{position_id}/behavior-metrics` | `200` | 查询行为指标。 | `portfolio_id` (Query, 必填) | `list[BehaviorMetric]` |

### 请求模型

`MonitoringEvaluateRequest`：

| 字段 | 类型 | 默认值 | 说明 |
| --- | --- | --- | --- |
| `portfolio_id` | `str` | 必填 | 组合 ID。 |
| `current_price` | `float \| None` | `None` | 覆盖现价。 |
| `evidence_refs` | `list[str]` | `[]` | 证据 ID 列表。 |
| `model_rank_delta` | `float \| None` | `None` | 模型排名变化。 |
| `industry_exposure` | `float \| None` | `None` | 行业暴露比例。 |
| `strategy_failure` | `bool` | `False` | 是否策略失败。 |
| `upcoming_event_at` | `datetime \| None` | `None` | 即将到来关键事件时间。 |
| `decision_at` | `datetime \| None` | `None` | 评估时间。 |

`ReviewCreate`：

| 字段 | 类型 | 默认值 | 说明 |
| --- | --- | --- | --- |
| `portfolio_id` | `str` | 必填 | 组合 ID。 |
| `alert_id` | `str \| None` | `None` | 关联 Alert ID。 |
| `decision` | `ReviewDecision` | 必填 | 复盘决策。 |
| `rationale` | `str` | 必填 | 决策理由。 |
| `action_taken_at` | `datetime \| None` | `None` | 实际执行时间。 |

错误处理：

- `_not_found(KeyError)` 将 `KeyError` 转为 `HTTPException(status.HTTP_404_NOT_FOUND)`。
- `evaluate_position_monitoring` 与 `create_position_review`、`get_position_history` 捕获 `KeyError` 后返回 404。

---

## Next.js 页面与 Server Actions

### `PositionPage`

源文件：`web/app/positions/[positionId]/page.tsx`

| 项目 | 说明 |
| --- | --- |
| 类型 | `async` Server Component（Next.js App Router）。 |
| Props | `params: Promise<{ positionId: string }>`、`searchParams: Promise<{ portfolioId?: string }>`。 |
| 默认 portfolioId | 若 URL 未提供，使用 `"demo"`。 |
| 数据获取 | 并行调用 `fetchPositionDetail`、`fetchPositionAlerts`、`fetchPositionHistory`。 |
| 错误处理 | 任一接口失败则设置 `error = "持仓数据暂时不可用"`。 |
| 渲染 | 将 `evaluateAction` 与 `reviewAction` 通过 `.bind(null, positionId)` 传入 `PositionDetailView`。 |

### `Loading`

源文件：`web/app/positions/[positionId]/loading.tsx`

| 项目 | 说明 |
| --- | --- |
| 类型 | Next.js Route Loading UI。 |
| 行为 | 渲染 `PageLoading`，眉标 `Position`，标题 `持仓详情`。 |

### Server Actions

源文件：`web/app/positions/[positionId]/actions.ts`

| 函数 | 签名 | 说明 |
| --- | --- | --- |
| `evaluatePositionAction` | `async (positionId: string, formData: FormData) -> void` | 解析表单，调用 `evaluatePositionMonitoring`，随后 `revalidatePath(\`/positions/${positionId}\`)`。 |
| `createPositionReviewAction` | `async (positionId: string, formData: FormData) -> void` | 解析表单，调用 `createPositionReview`，随后 `revalidatePath(\`/positions/${positionId}\`)`。 |
| `requiredText` | `(formData, key) -> string` | 必填文本字段，缺失抛错。 |
| `optionalText` | `(formData, key) -> string \| null` | 可选文本字段，trim 后空值返回 `null`。 |
| `optionalNumber` | `(formData, key) -> number \| null` | 可选数字字段，非有限值返回 `null`。 |
| `splitList` | `(value) -> string[]` | 按空白/逗号/分号/中文逗号分号切分字符串并过滤空值。 |
| `reviewDecision` | `(formData) -> ReviewDecision` | 解析 `decision` 字段，非法值回退为 `"watch"`。 |

`evaluatePositionAction` 解析字段：

- `portfolio_id`（必填）
- `current_price`（数字）
- `evidence_refs`（列表）
- `model_rank_delta`（数字）
- `industry_exposure`（数字）
- `strategy_failure`（复选框，值为 `"on"` 时 `true`）

`createPositionReviewAction` 解析字段：

- `portfolio_id`（必填）
- `rationale`（必填）
- `alert_id`（可选）
- `decision`（必填，默认 `watch`）

---

## React 组件

### `PositionDetailView`

源文件：`web/components/position-detail.tsx`

| Props | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `portfolioId` | `string` | 是 | 组合 ID。 |
| `evaluateAction` | `FormAction` | 是 | 已绑定 `positionId` 的监控评估 Server Action。 |
| `reviewAction` | `FormAction` | 是 | 已绑定 `positionId` 的复盘 Server Action。 |
| `detail` | `PositionDetail \| null` | 是 | 持仓详情数据。 |
| `alerts` | `AlertEvent[]` | 否 | Alert 列表，默认 `[]`。 |
| `history` | `OperationHistoryEntry[]` | 否 | 操作历史，默认 `[]`。 |
| `error` | `string \| null` | 是 | 错误信息。 |

行为：

- 若 `error` 存在，渲染错误提示面板。
- 若 `detail` 为空，渲染“数据加载中”。
- 否则渲染完整详情页：
  - 顶部：组合 ID、标的代码、`health_status` 徽标。
  - 指标网格：成本金额、成本价、市值、权重。
  - 主内容区：买入逻辑（`thesis`、持有条件、失效条件）+ 持仓监控（Alert 列表 + 重新评估表单）。
  - 侧边栏：盈亏信息、复盘记录表单、操作历史。
- `timeline` 优先使用传入的 `history`；为空时从 `detail.trade_history` 临时转换。

内部辅助组件：

| 组件 | 说明 |
| --- | --- |
| `MonitoringEvaluateForm` | 监控评估表单：当前价格、模型排名变化、行业暴露、证据 ID、策略失效复选框、提交按钮。 |
| `ReviewForm` | 复盘表单：关联 Alert 下拉框、决策下拉框、理由文本域、提交按钮。 |
| `Metric` | 单个指标卡片。 |
| `ConditionList` | 条件列表（持有/失效）。 |
| `tradesToHistory` | 将 `TradeHistoryItem[]` 转为 `OperationHistoryEntry[]`。 |
| `historySummary` | 对 `alert` 类型返回“触发提醒”，否则返回原始 `summary`。 |

### `PositionReviewBadge`

源文件：`web/components/position-review-badge.tsx`

| Props | 类型 | 说明 |
| --- | --- | --- |
| `status` | `string \| null` | 投资逻辑/复盘状态字符串。 |

| 状态值 | 显示文案 | 样式 tone |
| --- | --- | --- |
| `THESIS_VALID` | 逻辑有效 | `positive` |
| `REVIEW_REQUIRED` | 需要复核 | `watch` |
| `RISK_ALERT` | 风险提醒 | `data_missing` |
| `THESIS_INVALIDATED` | 逻辑失效 | `data_missing` |
| `null` / 空 | 未绑定组合 | 默认 badge |
| 其他 | 原样显示 | 根据是否含 `RISK`/`INVALID` 或 `REVIEW` 推断 tone |

tone 规则：

- 含 `RISK` 或 `INVALID` → `data_missing`
- 含 `REVIEW` → `watch`
- 其他 → `positive`

---

## 跨模块使用说明

| 依赖模块 | 使用点 | 说明 |
| --- | --- | --- |
| `margin.portfolio` | `service.py` / `runner.py` | 使用 `Position`、`PositionThesis`、`PositionHealthStatus`、`ThesisStatus`、`Trade`、`PortfolioService` 加载头寸与交易历史。 |
| `margin.news` | `runner.py` / `service.py` | 使用 `DocumentEvent`、`NewsRepository` 获取新闻事件并扫描负面关键词。 |
| `margin.data.providers.akshare_provider` | `runner.py` | `AKShareLatestPriceProvider` 包装 `AKShareProvider` 获取日线收盘价。 |
| `margin.api.dependencies` | `get_monitoring_services` | 生产环境构造 `SQLAlchemyMonitoringRepository` + `PortfolioService`，通过 `MonitoringServiceBundle.from_repositories` 注入路由。 |
| `web/lib/api.ts` | `fetchPositionAlerts` / `fetchPositionHistory` / `evaluatePositionMonitoring` / `createPositionReview` | 前端 HTTP 客户端封装对应 FastAPI 接口。 |
| `web/components/candidate-card.tsx` | `PositionReviewBadge` | 在研究候选卡片中复用该徽标展示 `position_review_status`。 |
| Alembic 迁移 | `alembic/versions/20260619_0008_holdings_monitoring.py` | 创建 `alert_events` 与 `position_reviews` 表及索引。 |
| SQLAlchemy ORM | `db_models.py` | `AlertEventRow`、`PositionReviewRow` 对应上述表，外键依赖 `portfolios` 表。 |

---

*文档结束。*
