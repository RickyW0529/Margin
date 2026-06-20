---
task_id: 0803
parent_module: 08-research_candidate_dashboard
product_version: v0.1
doc_version: v0.1
source_refs: [架构设计 §16.3 API; 产品设计 §7.1 拒绝判断]
status: active
estimate_days: 5
depends_on: [0802]
---

# 0803 拒绝判断与 API 完整化 — 实施计划

## 1. 任务目标

实现拒绝判断列表（ABSTAINED 候选与拒绝原因）、任务运行状态视图、provider-status 查询、nightly-runs 触发与 feedback 接口。完成研究候选面板全部 API（架构 §16.3）。研究运行 Aborted/Abstained 时面板展示拒绝判断与原因，不展示虚假候选。

## 2. 工作项拆解

- 0803.1 拒绝判断列表 — ABSTAINED 与拒绝原因展示。
- 0803.2 任务运行状态 — jobs/nightly-runs/job_run_id 查询。
- 0803.3 provider-status 与 feedback — Provider 状态、用户反馈接口；provider-status 展示 LLM、Embedding、Tavily WebSearch、Rerank，缺配置时显式 degraded。
- 0803.4 Report Renderer 与 Export Service — 报告渲染与导出。

## 3. 依赖关系

- 前置：0802（证据展开与详情）。
- 被依赖：无（面板模块终点）。
- 外部依赖：06 任务运行、01 provider-status。

## 4. 工时估算

- 0803.1：1 天
- 0803.2：1 天
- 0803.3：1 天
- 0803.4：2 天
- 合计：5 天。

## 5. 里程碑与交付物

- M1：拒绝判断列表可用（第 1 天）。
- M2：任务运行状态视图（第 2 天）。
- M3：provider-status 与 feedback（第 3 天），包含缺配置 Provider 的 degraded 状态。
- M4：Report Renderer 与 Export Service（第 5 天）。

## 6. 验收动作

- 用户可查看候选与拒绝判断（对应产品 §15 条目 6）；
- Aborted/Abstained 运行展示拒绝原因（对应 spec 08 §7）；
- 完整 API（架构 §16.3）可用。

## 7. 审计追溯

- `source_refs`：架构 §16.3、产品 §7.1；
- 关联 spec：`spec/v0.1/08-research_candidate_dashboard/spec.md` §3 / §7；
- 不可变产物：feedback 记录、audit 接口输出。
