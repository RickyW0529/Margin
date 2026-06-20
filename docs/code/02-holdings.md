# 02-holdings 模块文档

## 目录

1. [模块概述](#模块概述)
2. [文件级摘要](#文件级摘要)
3. [领域模型](#领域模型)
4. [服务层](#服务层)
5. [仓储层](#仓储层)
6. [成本引擎](#成本引擎)
7. [风险引擎](#风险引擎)
8. [导入器](#导入器)
9. [FastAPI 接口](#fastapi-接口)
10. [前端页面与组件](#前端页面与组件)
11. [跨模块使用说明](#跨模块使用说明)

---

## 模块概述

`02-holdings`（portfolio 包）是 Margin 当前实现 的持仓核心模块，负责投资组合的创建、交易记录、成本计算、风险聚合、投资论点管理和数据导入。该模块向上为 FastAPI 路由和前端看板提供统一服务，向下通过仓储协议隔离内存与 PostgreSQL 两种持久化实现。

### 主要职责

- 投资组合（Portfolio）与交易记录（Trade）的增删查。
- 基于移动加权平均法的持仓成本、市值、已实现/未实现盈亏计算。
- CSV/Excel/券商导出文件的交易导入与审计。
- 八维组合风险度量（单一仓位、行业集中度、风格暴露、相关性、流动性、波动率、回撤、事件集中度）。
- 投资论点（PositionThesis）的版本化追加存储。
- 为 `/portfolios/[portfolioId]` 页面提供看板与持仓列表数据。

---

## 文件级摘要

| 文件 | 层级 | 职责 |
| --- | --- | --- |
| `src/margin/portfolio/__init__.py` | 包入口 | 导出 cost、importer、models、repository、risk、service 的公共 API。 |
| `src/margin/portfolio/models.py` | 领域模型 | 定义 `Portfolio`、`Position`、`Trade`、`PositionThesis`、`ImportRecord`、`AlertEvent` 及枚举。 |
| `src/margin/portfolio/db_models.py` | ORM 模型 | 定义 SQLAlchemy 持久化表：`PortfolioRow`、`TradeRow`、`PositionThesisRow`。 |
| `src/margin/portfolio/repository.py` | 仓储 | 定义 `PortfolioRepository` 协议，提供 `MemoryPortfolioRepository` 与 `SQLAlchemyPortfolioRepository`。 |
| `src/margin/portfolio/cost.py` | 成本引擎 | `CostCalculator` 使用移动加权平均法从交易序列推导持仓与盈亏。 |
| `src/margin/portfolio/risk.py` | 风险引擎 | `PortfolioRiskEngine` 计算八维风险指标并生成 `PortfolioRiskReport`。 |
| `src/margin/portfolio/importer.py` | 导入器 | `TradeImporter` 支持手动录入、CSV/Excel、券商插件导入并生成审计记录。 |
| `src/margin/portfolio/service.py` | 服务层 | `PortfolioService` 整合仓储、导入器、成本与风险引擎，提供 `PortfolioOverview`、`PositionDetail` 等视图。 |
| `src/margin/api/routes/portfolios.py` | API 路由 | FastAPI 路由，暴露组合、持仓、交易、导入、风险、论点相关 REST 接口。 |
| `src/margin/api/schemas.py` | API 模式 | 定义 `TradeCreate`、`CSVImportRequest`、`ThesisUpdate`、`PortfolioDashboardResponse` 等请求/响应模型。 |
| `web/app/portfolios/[portfolioId]/page.tsx` | Next.js 页面 | 异步服务端页面，拉取看板与持仓数据并渲染 `PortfolioWorkspace`。 |
| `web/app/portfolios/[portfolioId]/loading.tsx` | Next.js 加载页 | 显示 "组合看板" 加载状态。 |
| `web/app/portfolios/[portfolioId]/page.test.tsx` | 页面测试 | 验证页面正确解析路由参数并调用 API。 |
| `web/components/portfolio-workspace.tsx` | React 组件 | 组合看板工作区，展示指标卡、持仓表、行业/风格暴露、事件、风险。 |
| `web/components/portfolio-workspace.test.tsx` | 组件测试 | 验证工作区渲染、空态、错误态。 |

---

## 领域模型

本节说明 `src/margin/portfolio/models.py` 中的核心领域对象。

### 枚举

| 枚举 | 值 | 说明 |
| --- | --- | --- |
| `TradeSide` | `buy`, `sell`, `dividend`, `split` | 交易方向。 |
| `TradeSource` | `manual`, `csv`, `excel`, `broker_plugin` | 交易来源，用于审计。 |
| `PositionHealthStatus` | `healthy`, `watch`, `risk`, `invalidated`, `data_missing`, `event_pending` | 持仓健康状态。 |
| `ThesisStatus` | `thesis_valid`, `review_required`, `risk_alert`, `thesis_invalidated` | 投资论点生命周期状态。 |

### `Portfolio`

用户拥有的投资组合。

| 属性 | 类型 | 说明 |
| --- | --- | --- |
| `portfolio_id` | `str` | 唯一标识符。 |
| `user_id` | `str` | 所有者用户 ID。 |
| `name` | `str` | 组合名称。 |
| `cash` | `float` | 现金余额，默认为 `0.0`。 |
| `created_at` | `datetime` | 创建时间，默认 UTC 当前时间。 |

### `Trade`

不可变的单笔交易记录。

| 属性 | 类型 | 说明 |
| --- | --- | --- |
| `trade_id` | `str` | 唯一标识符。 |
| `portfolio_id` | `str` | 所属组合 ID。 |
| `symbol` | `str` | 标准化后的交易代码。 |
| `side` | `TradeSide` | 交易方向。 |
| `quantity` | `float` | 成交数量。 |
| `price` | `float` | 成交价格。 |
| `amount` | `float` | 总金额（含手续费/税），未提供时自动计算。 |
| `fee` | `float` | 手续费，默认 `0.0`。 |
| `tax` | `float` | 税费，默认 `0.0`。 |
| `traded_at` | `datetime` | 成交时间。 |
| `source` | `TradeSource` | 来源，默认 `MANUAL`。 |
| `source_ref` | `str \| None` | 外部来源引用。 |
| `raw_hash` | `str \| None` | 原始导入行哈希，用于去重审计。 |
| `imported_at` | `datetime` | 导入/创建时间。 |
| `note` | `str \| None` | 备注。 |

### `Position`

由交易序列推导出的持仓。

| 属性 | 类型 | 说明 |
| --- | --- | --- |
| `position_id` | `str` | 唯一标识符，由 `portfolio_id` 与 `symbol` 哈希生成。 |
| `portfolio_id` | `str` | 所属组合 ID。 |
| `symbol` | `str` | 标准化后的代码。 |
| `quantity` | `float` | 当前持有数量，默认 `0.0`。 |
| `cost_price` | `float` | 平均成本价，默认 `0.0`。 |
| `cost_amount` | `float` | 总成本金额，默认 `0.0`。 |
| `current_price` | `float \| None` | 最新市场价。 |
| `market_value` | `float \| None` | 当前市值。 |
| `unrealized_pnl` | `float \| None` | 未实现盈亏。 |
| `unrealized_pnl_pct` | `float \| None` | 未实现盈亏百分比。 |
| `industry` | `str \| None` | 行业分类。 |
| `health_status` | `PositionHealthStatus` | 健康状态，默认 `HEALTHY`。 |
| `thesis` | `PositionThesis \| None` | 关联的最新投资论点。 |
| `updated_at` | `datetime` | 更新时间。 |

### `PositionThesis`

追加式投资论点，每次更新生成新版本。

| 属性 | 类型 | 说明 |
| --- | --- | --- |
| `thesis_id` | `str` | 论点版本 ID。 |
| `position_id` | `str` | 关联持仓 ID。 |
| `thesis` | `str` | 投资逻辑文本。 |
| `entry_conditions` | `list[str]` | 建仓条件。 |
| `hold_conditions` | `list[str]` | 持有条件。 |
| `invalidation_conditions` | `list[str]` | 失效条件。 |
| `target_horizon` | `list[int]` | 目标复盘窗口（天），默认 `[60, 120]`。 |
| `next_review_at` | `datetime \| None` | 下次复盘时间。 |
| `status` | `ThesisStatus` | 论点状态。 |
| `version` | `int` | 版本号，从 `1` 开始。 |
| `created_at` | `datetime` | 创建时间。 |

### `ImportRecord`

导入审计记录。

| 属性 | 类型 | 说明 |
| --- | --- | --- |
| `import_id` | `str` | 导入会话 ID。 |
| `portfolio_id` | `str` | 目标组合 ID。 |
| `source` | `TradeSource` | 导入来源。 |
| `file_name` | `str \| None` | 文件名。 |
| `trade_count` | `int` | 成功导入交易数。 |
| `rejected_count` | `int` | 被拒绝行数。 |
| `imported_at` | `datetime` | 导入时间。 |
| `raw_hash` | `str \| None` | 原始数据哈希。 |
| `errors` | `list[str]` | 错误信息列表。 |

### 工厂函数

| 函数 | 签名 | 说明 |
| --- | --- | --- |
| `make_trade` | `(portfolio_id, symbol, side, quantity, price, traded_at, **kwargs) -> Trade` | 生成 `trade_id` 并对 `symbol` 标准化后创建 `Trade`。 |

---

## 服务层

本节说明 `src/margin/portfolio/service.py`。

### `PortfolioOverview`

组合概览视图模型。

| 属性 | 类型 | 说明 |
| --- | --- | --- |
| `portfolio_id` | `str` | 组合 ID。 |
| `portfolio_name` | `str` | 组合名称。 |
| `total_assets` | `float` | 总资产 = 现金 + 市值。 |
| `cash` | `float` | 现金余额。 |
| `market_value` | `float` | 持仓总市值。 |
| `today_pnl` | `float \| None` | 当日盈亏。 |
| `cumulative_pnl` | `float` | 累计未实现盈亏。 |
| `portfolio_volatility` | `float \| None` | 组合波动率。 |
| `max_drawdown` | `float \| None` | 最大回撤。 |
| `industry_exposure` | `dict[str, float]` | 行业权重分布。 |
| `style_exposure` | `dict[str, float]` | 成长/价值风格权重。 |
| `high_risk_count` | `int` | 高风险或已失效持仓数量。 |
| `upcoming_events` | `list[dict]` | 近期事件列表。 |
| `position_count` | `int` | 持仓数量。 |
| `updated_at` | `datetime` | 生成时间。 |

### `PositionDetail`

单持仓详情视图模型。

| 属性 | 类型 | 说明 |
| --- | --- | --- |
| `position_id`, `symbol`, `quantity`, `cost_price`, `cost_amount` | — | 基础持仓字段。 |
| `current_price`, `market_value`, `unrealized_pnl`, `unrealized_pnl_pct` | — | 市场与盈亏字段。 |
| `industry` | `str \| None` | 行业。 |
| `health_status` | `PositionHealthStatus` | 健康状态。 |
| `thesis` | `PositionThesis \| None` | 最新投资论点。 |
| `trade_history` | `list[dict]` | 该代码的历史交易摘要。 |
| `weight` | `float \| None` | 组合权重。 |
| `updated_at` | `datetime` | 生成时间。 |

### `PortfolioService`

组合服务核心类，协调仓储、导入器、成本与风险引擎。

#### 构造

| 参数 | 类型 | 默认值 | 说明 |
| --- | --- | --- | --- |
| `cost_calculator` | `CostCalculator \| None` | 新实例 | 成本计算器。 |
| `risk_engine` | `PortfolioRiskEngine \| None` | 新实例 | 风险引擎。 |
| `repository` | `PortfolioRepository \| None` | `MemoryPortfolioRepository()` | 仓储实现。 |

#### 公共方法

| 方法 | 参数 | 返回 | 说明 |
| --- | --- | --- | --- |
| `create_portfolio` | `user_id, name, cash=0.0` | `Portfolio` | 创建新组合并持久化。 |
| `get_portfolio` | `portfolio_id` | `Portfolio` | 获取组合，不存在时抛出 `KeyError`。 |
| `list_portfolios` | — | `list[Portfolio]` | 列出所有组合。 |
| `add_trade` | `portfolio_id, symbol, side, quantity, price, traded_at, fee=0.0, tax=0.0, note=None` | `Trade` | 手动添加交易并更新现金。 |
| `import_csv` | `portfolio_id, content, field_mapping=None` | `tuple[list[Trade], ImportRecord]` | 从 CSV 字符串导入交易。 |
| `import_csv_file` | `portfolio_id, file_path, field_mapping=None` | `tuple[list[Trade], ImportRecord]` | 从 CSV 文件路径导入交易。 |
| `get_trades` | `portfolio_id` | `list[Trade]` | 获取组合全部交易。 |
| `get_positions` | `portfolio_id, current_prices=None` | `list[Position]` | 推导当前持仓并附加最新论点。 |
| `get_risk` | `portfolio_id, current_prices=None, prices_history=None, upcoming_events=None` | `PortfolioRiskReport` | 生成风险报告。 |
| `get_overview` | 同 `get_risk` | `PortfolioOverview` | 生成组合概览看板。 |
| `get_position_detail` | `portfolio_id, position_id, current_prices=None` | `PositionDetail` | 生成单持仓详情。 |
| `update_thesis` | `portfolio_id, position_id, thesis, entry_conditions=None, hold_conditions=None, invalidation_conditions=None, target_horizon=None, next_review_at=None, status=THESIS_VALID` | `PositionThesis` | 追加新的论点版本。 |
| `get_thesis_history` | `portfolio_id, position_id` | `list[PositionThesis]` | 获取某持仓的论点版本历史。 |

#### 内部方法

| 方法 | 说明 |
| --- | --- |
| `_ensure_portfolio` | 校验组合存在，否则抛出 `KeyError`。 |
| `_append_trades` | 将交易写入仓储并触发现金调整。 |
| `_apply_cash_delta` | 根据交易对组合现金进行加减。 |

#### 现金影响辅助函数

| 函数 | 说明 |
| --- | --- |
| `_cash_delta(trade)` | 计算单笔交易对现金的影响：买入为负，卖出/分红为正。 |

---

## 仓储层

本节说明 `src/margin/portfolio/repository.py`。

### `PortfolioRepository`（协议）

服务层消费的持久化契约。

| 方法 | 参数 | 返回 | 说明 |
| --- | --- | --- | --- |
| `add_portfolio` | `portfolio: Portfolio` | `None` | 持久化新组合。 |
| `get_portfolio` | `portfolio_id: str` | `Portfolio \| None` | 按 ID 查询组合。 |
| `list_portfolios` | — | `list[Portfolio]` | 列出所有组合。 |
| `update_portfolio` | `portfolio: Portfolio` | `None` | 更新组合。 |
| `add_trades` | `trades: list[Trade]` | `None` | 批量写入交易。 |
| `list_trades` | `portfolio_id: str` | `list[Trade]` | 查询组合交易。 |
| `add_thesis` | `portfolio_id: str, thesis: PositionThesis` | `None` | 写入论点版本。 |
| `list_theses` | `portfolio_id: str, position_id=None` | `list[PositionThesis]` | 查询论点历史。 |

### `MemoryPortfolioRepository`

内存实现，用于测试与嵌入式场景。

| 方法 | 说明 |
| --- | --- |
| `add_portfolio` | ID 已存在时抛出 `ValueError`。 |
| `get_portfolio` | 返回内存字典值。 |
| `list_portfolios` | 按创建时间 + ID 排序。 |
| `update_portfolio` | 不存在时抛出 `KeyError`。 |
| `add_trades` | 组合不存在时抛出 `KeyError`。 |
| `list_trades` | 返回交易列表副本。 |
| `add_thesis` | 追加到内存列表。 |
| `list_theses` | 按 `position_id` 与 `version` 排序。 |

### `SQLAlchemyPortfolioRepository`

PostgreSQL 实现，基于短 SQLAlchemy 会话。

| 方法 | 说明 |
| --- | --- |
| `__init__(session_factory)` | 接收返回 `Session` 的可调用对象。 |
| `add_portfolio` | 将 `Portfolio` 转为 `PortfolioRow` 写入。 |
| `get_portfolio` | 使用 `session.get` 按主键读取并转换。 |
| `list_portfolios` | 按 `created_at`、`portfolio_id` 排序查询。 |
| `update_portfolio` | 更新 `user_id`、`name`、`cash` 字段。 |
| `add_trades` | 批量转换为 `TradeRow` 写入。 |
| `list_trades` | 按 `traded_at`、`trade_id` 排序。 |
| `add_thesis` | 转换为 `PositionThesisRow` 写入。 |
| `list_theses` | 支持按 `position_id` 过滤，按版本排序。 |

#### 私有转换函数

| 函数 | 说明 |
| --- | --- |
| `_portfolio_to_row` / `_portfolio_from_row` | `Portfolio` 与 `PortfolioRow` 互转。 |
| `_trade_to_row` / `_trade_from_row` | `Trade` 与 `TradeRow` 互转（含枚举值映射）。 |
| `_thesis_to_row` / `_thesis_from_row` | `PositionThesis` 与 `PositionThesisRow` 互转。 |

---

## 成本引擎

本节说明 `src/margin/portfolio/cost.py`。

### `_make_position_id`

| 参数 | 返回 | 说明 |
| --- | --- | --- |
| `portfolio_id: str`, `symbol: str` | `str` | 对 `portfolio_id:symbol` 取 SHA256 前 12 位并前缀 `pos_`，保证同一组合-代码生成稳定 ID。 |

### `_CostTracker`

内部按代码成本追踪器，采用移动加权平均法。

| 属性 | 类型 | 说明 |
| --- | --- | --- |
| `symbol` | `str` | 交易代码。 |
| `quantity` | `float` | 当前数量。 |
| `cost_amount` | `float` | 当前总成本。 |
| `realized_pnl` | `float` | 累计已实现盈亏。 |
| `trade_count` | `int` | 已应用交易数。 |

| 方法/属性 | 说明 |
| --- | --- |
| `cost_price` | 当前加权平均成本价；数量 `<=0` 时返回 `0.0`。 |
| `apply(trade)` | 根据交易方向更新数量、成本与已实现盈亏；卖出数量超过持仓时抛出 `ValueError`。 |

### `CostCalculator`

从交易序列计算持仓的成本计算器。

| 方法 | 参数 | 返回 | 说明 |
| --- | --- | --- | --- |
| `calculate` | `portfolio_id, trades, current_prices=None` | `list[Position]` | 按时间排序交易，逐代码聚合，生成数量大于 0 的持仓；附加当前价格时计算市值与未实现盈亏，缺失价格时标记 `DATA_MISSING`。 |
| `calculate_realized_pnl` | `trades` | `dict[str, float]` | 计算每个代码的已实现盈亏，返回非零项。 |

---

## 风险引擎

本节说明 `src/margin/portfolio/risk.py`。

### `RiskMetric`

单个风险指标。

| 属性 | 类型 | 说明 |
| --- | --- | --- |
| `name` | `str` | 指标名称。 |
| `value` | `float` | 计算值。 |
| `threshold` | `float \| None` | 阈值。 |
| `breached` | `bool` | 是否突破阈值。 |
| `details` | `dict[str, Any]` | 附加详情。 |

### `PortfolioRiskReport`

组合风险报告。

| 属性/方法 | 类型/返回 | 说明 |
| --- | --- | --- |
| `portfolio_id` | `str` | 组合 ID。 |
| `total_value` | `float` | 多头持仓总市值。 |
| `metrics` | `list[RiskMetric]` | 指标列表。 |
| `computed_at` | `datetime` | 计算时间。 |
| `max_single_position` | `float` | 单一仓位阈值，默认 `0.05`。 |
| `max_industry_exposure` | `float` | 行业暴露阈值，默认 `0.20`。 |
| `has_breach` | `bool` | 是否有指标突破阈值。 |
| `breached_metrics` | `list[RiskMetric]` | 返回所有已突破的指标。 |

### `PortfolioRiskEngine`

组合风险引擎，计算八维风险指标。

#### 构造

| 参数 | 类型 | 默认值 | 说明 |
| --- | --- | --- | --- |
| `max_single_position` | `float` | `0.05` | 单一仓位权重上限。 |
| `max_industry_exposure` | `float` | `0.20` | 行业暴露上限。 |

#### 主要方法

| 方法 | 参数 | 返回 | 说明 |
| --- | --- | --- | --- |
| `calculate` | `portfolio_id, positions, prices_history=None, upcoming_events=None` | `PortfolioRiskReport` | 计算完整风险报告；当市场数据缺失时回退到单一仓位验证，避免给出高置信度组合结论。 |

#### 私有维度计算方法

| 方法 | 维度 | 说明 |
| --- | --- | --- |
| `_single_position_risk` | 单一仓位 | 最大持仓权重及阈值比较。 |
| `_industry_concentration` | 行业集中度 | 按 `Position.industry` 聚合市值并计算最大行业权重。 |
| `_style_exposure` | 风格暴露 | 以当前价较成本价上涨 20% 以上为成长，其余为价值。 |
| `_correlation_risk` | 相关性 | 以同行业持仓数量占比作为简化代理。 |
| `_liquidity_risk` | 流动性 | 以最大仓位市值占比作为简化代理。 |
| `_volatility` | 波动率 | 按日收益率标准差加权。 |
| `_drawdown` | 回撤 | 按历史价格的加权最大回撤。 |
| `_event_concentration` | 事件集中度 | 未来 30 天内有事件的持仓占比。 |

---

## 导入器

本节说明 `src/margin/portfolio/importer.py`。

### 异常

| 异常 | 说明 |
| --- | --- |
| `ImportValidationError` | 导入文件校验失败，包含 `errors`（行级错误）与 `record`（审计记录）。 |
| `TradeValidationError` | 单条交易记录校验失败。 |

### `BrokerImportPlugin`

券商导出文件适配插件协议。

| 抽象属性/方法 | 返回/参数 | 说明 |
| --- | --- | --- |
| `name` | `str` | 插件名称。 |
| `supported_extensions` | `list[str]` | 支持的文件扩展名。 |
| `parse(file_path)` | `list[dict[str, Any]]` | 解析券商导出文件并返回原始行字典。 |

### `validate_trade_fields`

| 参数 | 说明 |
| --- | --- |
| `symbol, side, quantity, price, traded_at` | 校验代码非空、方向合法、数量/价格为正、`traded_at` 不在未来。 |

### `compute_raw_hash`

| 参数 | 返回 | 说明 |
| --- | --- | --- |
| `rows: list[dict]` | `str` | 对原始行 JSON 序列化后计算 SHA256，返回 `sha256:<hex>`。 |

### `TradeImporter`

交易导入器，支持手动录入、CSV、Excel 与券商插件导入。

#### 公共方法

| 方法 | 参数 | 返回 | 说明 |
| --- | --- | --- | --- |
| `register_broker_plugin` | `plugin: BrokerImportPlugin` | `None` | 注册券商插件。 |
| `add_trade_manual` | `portfolio_id, symbol, side, quantity, price, traded_at, fee=0.0, tax=0.0, note=None` | `Trade` | 手动录入单笔交易。 |
| `import_csv` | `portfolio_id, file_path, field_mapping=None` | `tuple[list[Trade], ImportRecord]` | 从 CSV 文件导入。 |
| `import_csv_bytes` | `portfolio_id, content, field_mapping=None` | `tuple[list[Trade], ImportRecord]` | 从 CSV 字符串导入（常用于 API/测试）。 |
| `import_excel` | `portfolio_id, file_path, field_mapping=None` | `tuple[list[Trade], ImportRecord]` | 从 Excel 文件导入，需要安装 `pandas`。 |
| `import_broker` | `portfolio_id, file_path, plugin_name, field_mapping=None` | `tuple[list[Trade], ImportRecord]` | 使用已注册插件导入券商导出文件。 |

#### 内部方法

| 方法 | 说明 |
| --- | --- |
| `_process_rows` | 映射字段、逐行校验、生成交易并记录审计；任一失败即整体拒绝。 |
| `_row_to_trade` | 将映射后的行转换为 `Trade`。 |
| `_record_import` | 创建并保存 `ImportRecord`。 |

#### 属性

| 属性 | 返回 | 说明 |
| --- | --- | --- |
| `import_records` | `list[ImportRecord]` | 返回所有审计记录副本。 |

#### 默认字段映射

`_DEFAULT_CSV_MAPPING` 将标准列名映射到标准字段：`symbol`、`side`、`quantity`、`price`、`traded_at`、`fee`、`tax`、`note`。

---

## FastAPI 接口

本节说明 `src/margin/api/routes/portfolios.py`。

| 方法 | 路径 | 响应模型 | 说明 |
| --- | --- | --- | --- |
| `GET` | `/api/v1/portfolios/{portfolio_id}` | `PortfolioDashboardResponse` | 返回组合身份与概览看板。 |
| `GET` | `/api/v1/portfolios/{portfolio_id}/positions` | `list[Position]` | 返回组合当前持仓。 |
| `GET` | `/api/v1/portfolios/{portfolio_id}/positions/{position_id}` | `PositionDetail` | 返回单持仓详情与交易历史。 |
| `POST` | `/api/v1/portfolios/{portfolio_id}/trades` | `Trade` | 手动录入交易。 |
| `POST` | `/api/v1/portfolios/{portfolio_id}/imports` | `CSVImportResponse` | 从 CSV 内容批量导入交易。 |
| `GET` | `/api/v1/portfolios/{portfolio_id}/risk` | `PortfolioRiskReport` | 返回组合风险报告。 |
| `GET` | `/api/v1/positions/{position_id}/thesis` | `PositionThesis` | 返回某持仓最新论点（需 `portfolio_id` 查询参数）。 |
| `PUT` | `/api/v1/positions/{position_id}/thesis` | `PositionThesis` | 创建新的论点版本。 |

### 路由辅助函数

| 函数 | 说明 |
| --- | --- |
| `_not_found(exc)` | 将 `KeyError` 转换为 HTTP 404 异常。 |

### 请求/响应模式（`src/margin/api/schemas.py`）

| 模式 | 用途 |
| --- | --- |
| `TradeCreate` | 手动录入交易请求体。 |
| `CSVImportRequest` | CSV 导入请求体（`content` + 可选 `field_mapping`）。 |
| `CSVImportResponse` | CSV 导入响应（`trades` + `record`）。 |
| `ThesisUpdate` | 论点更新请求体。 |
| `PortfolioDashboardResponse` | 组合看板响应（`portfolio` + `overview`）。 |

---

## 前端页面与组件

### `PortfolioPage`

文件：`web/app/portfolios/[portfolioId]/page.tsx`

Next.js 服务端异步页面。

| Props | 类型 | 说明 |
| --- | --- | --- |
| `params` | `Promise<{ portfolioId: string }>` | 路由参数，Next.js 15 异步参数。 |

#### 行为

1. 等待 `params` 并解构 `portfolioId`。
2. 并行调用 `fetchPortfolioDashboard(portfolioId)` 与 `fetchPortfolioPositions(portfolioId)`。
3. 任意请求失败时，设置 `error` 为 `"组合数据暂时不可用"`。
4. 将 `dashboard`、`positions`、`error` 传入 `PortfolioWorkspace`。

### `Loading`

文件：`web/app/portfolios/[portfolioId]/loading.tsx`

渲染 `PageLoading`， eyebrow 为 `Portfolio`，标题为 `组合看板`。

### `PortfolioWorkspace`

文件：`web/components/portfolio-workspace.tsx`

组合看板工作区组件。

| Props | 类型 | 说明 |
| --- | --- | --- |
| `dashboard` | `PortfolioDashboard \| null` | 看板数据。 |
| `positions` | `Position[]` | 持仓列表。 |
| `error` | `string \| null` | 错误信息。 |

#### 渲染状态

| 状态 | 表现 |
| --- | --- |
| `error` 存在 | 显示警告面板 `notice-panel`。 |
| `dashboard` 为空 | 显示 "数据加载中"。 |
| 正常 | 渲染头部、指标卡、持仓表、行业/风格暴露、即将发生事件、风险摘要。 |

#### 内部辅助函数

| 函数 | 说明 |
| --- | --- |
| `money(value)` | 格式化为人民币，空值显示 `"--"`。 |
| `ratio(value)` | 格式化为百分比，空值显示 `"--"`。 |
| `signedMoney(value)` | 带正负号的人民币格式。 |
| `metricTone(value)` | 根据数值返回 `neutral` / `positive` / `negative`，用于样式。 |

#### 子组件

| 组件 | 说明 |
| --- | --- |
| `MetricTile` | 指标卡，显示图标、标签、数值与色调。 |
| `ExposurePanel` | 暴露面板，显示 `industry_exposure` 或 `style_exposure` 的条形图。 |

#### 持仓表列

代码、数量、成本、市值、盈亏、状态。代码列链接到 `/positions/{position_id}?portfolioId={portfolio_id}`。

---

## 跨模块使用说明

### 与 API 依赖的集成

`src/margin/api/dependencies.py` 中的 `get_portfolio_service()` 通过 `lru_cache` 缓存生产级 `PortfolioService`：

1. 调用 `build_database_engine(get_settings())` 创建 SQLAlchemy 引擎。
2. 使用 `create_session_factory(engine)` 生成会话工厂。
3. 构造 `SQLAlchemyPortfolioRepository(session_factory)` 并注入 `PortfolioService`。

该依赖被 `portfolios.py` 以及 holdings monitoring 的 `get_monitoring_services()` 复用。

### 与 holdings monitoring 模块的交互

`holdings_monitoring` 通过 `PortfolioService` 读取持仓与交易，生成监控快照和告警。`Position` 中的 `health_status` 与 `AlertEvent` 模型为监控模块提供了基础数据结构。

### 与研究/策略模块的交互

研究模块（`research`）产生候选卡与估值区间，策略模块（`strategy`）提供组合约束；这些结果可在未来通过 `PortfolioService.update_thesis` 与 `add_trade` 写入组合，实现研究-持仓闭环。

### 前端数据流

1. `PortfolioPage` 在服务端并行拉取 `/api/v1/portfolios/{id}` 和 `/api/v1/portfolios/{id}/positions`。
2. `PortfolioWorkspace` 纯展示，不直接调用 API。
3. 持仓代码链接到 `positions/[positionId]` 详情页，详情页使用 `fetchPositionDetail`。

### 注意事项

- `CostCalculator` 当前未处理卖空；卖出数量超过持仓时直接抛出 `ValueError`。
- `PortfolioRiskEngine` 的波动率与回撤依赖外部传入的 `prices_history`，否则跳过这两个维度。
- 行业、风格、事件风险依赖 `Position.industry`、`current_price` 与 `upcoming_events` 等外部输入。
- `Trade` 模型为 `frozen=True`，所有字段在创建后不可变。
- `PositionThesis` 采用追加写，更新会生成新版本，旧版本保留用于审计。
