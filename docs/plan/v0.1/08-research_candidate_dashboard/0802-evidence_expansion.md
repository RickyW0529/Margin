---
task_id: 0802
parent_module: 08-research_candidate_dashboard
product_version: v0.1
doc_version: v0.1
source_refs: [产品设计 §7.3, §7.4, §9.1; 架构设计 §16.1]
status: draft
estimate_days: 7
depends_on: [0801]
---

# 0802 证据展开与研究详情 — 实施计划

## 1. 任务目标

实现证据展开视图（结论 + 事实证据 + 系统推断 + 置信度）、研究详情页（结论/量化因子/估值/证据/催化剂/风险/反方分析/历史研究信号）与研究/持仓状态展示（RESEARCH_CANDIDATE/WATCH/ABSTAINED 与 THESIS_VALID/REVIEW_REQUIRED/RISK_ALERT/THESIS_INVALIDATED）。Evidence View Service 与 Valuation View Service 支撑。

## 2. 工作项拆解

- 0802.1 Evidence View Service — 证据展开，定位原文。
- 0802.2 研究详情页 — 八维度详情视图。
- 0802.3 状态展示 — 研究信号状态与持仓复核状态。
- 0802.4 API 对接 — /research-items/{id}/evidence、/valuation、/audit。

## 3. 依赖关系

- 前置：0801（候选卡片与首页）。
- 被依赖：0803（拒绝判断）。
- 外部依赖：05 证据 Claim、06 估值结果。

## 4. 工时估算

- 0802.1：2 天
- 0802.2：2 天
- 0802.3：1 天
- 0802.4：2 天
- 合计：7 天。

## 5. 里程碑与交付物

- M1：Evidence View Service 可用（第 2 天）。
- M2：研究详情页八维度（第 4 天）。
- M3：状态展示齐全（第 5 天）。
- M4：API 对接完成（第 7 天）。

## 6. 验收动作

- 研究结论包含证据引用与定位（对应产品 §15 条目 4）；
- 证据可展开至原文页码/章节（对应 spec 08 §4）；
- 状态区分研究信号与持仓复核，避免误表达成交易指令。

## 7. 审计追溯

- `source_refs`：产品 §7.3 / §7.4 / §9.1、架构 §16.1；
- 关联 spec：`spec/v0.1/08-research_candidate_dashboard/spec.md` §4 / §8；
- 不可变产物：证据视图基于 item_id 快照。
