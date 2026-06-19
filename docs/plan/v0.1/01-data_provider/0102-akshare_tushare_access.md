---
task_id: 0102
parent_module: 01-data_provider
product_version: v0.1
doc_version: v0.1
source_refs: [架构设计 §26-Phase1: AKShare/Tushare 接入; §4.2, §4.2.1]
status: active
estimate_days: 14
depends_on: [0101]
---

# 0102 AKShare/Tushare 接入 — 实施计划

## 1. 任务目标

实现 `AKShareProvider` 与 `TushareProvider` 两个 A 股结构化数据 Provider，覆盖行情、基础财务、指数成分、公司行动、股票元数据，并记录数据来源、Secret 引用、频率限制、字段授权说明、`fetched_at`、`available_at`、原始响应哈希。

## 2. 工作项拆解

- 0102.1 AKShareProvider 实现 — 行情、基础财务、指数、部分公告元数据。
- 0102.2 TushareProvider 实现 — 行情、财务、指数成分等补充数据，用户配置 token。
- 0102.3 MarketDataProvider 协议对接 — get_securities/get_bars/get_adjustment_factors/get_financials/get_index_members。
- 0102.4 频率限制与原始响应哈希 — 遵守 Tushare 授权与频率限制，记录响应哈希。

## 3. 依赖关系

- 前置：0101（Provider Registry）。
- 被依赖：0103（字段标准化）、0201（持仓基础服务 b1 依赖 a2）。
- 外部依赖：AKShare、Tushare API 与用户 token。

## 4. 工时估算

- 0102.1：4 天
- 0102.2：4 天
- 0102.3：3 天
- 0102.4：3 天
- 合计：14 天（对齐 Gantt a2）。

## 5. 里程碑与交付物

- M1：AKShareProvider 行情与财务可用（第 4 天）。
- M2：TushareProvider 补充数据可用（第 8 天）。
- M3：两个 Provider 对接 MarketDataProvider 协议（第 11 天）。
- M4：频率限制与响应哈希完整，交付两个 Provider（第 14 天）。

## 6. 验收动作

- 可配置至少一个 AKShare/Tushare 数据源（对应产品 §15 条目 2）；
- 行情、财务、指数成分、公司行动获取成功；
- 原始响应哈希与 `fetched_at` 落库。

## 7. 审计追溯

- `source_refs`：架构 §26-Phase1 a2、§4.2 / §4.2.1；
- 关联 spec：`spec/v0.1/01-data_provider/spec.md` §3 / §4；
- 不可变产物：Provider 调用记录、原始响应哈希。
