---
task_id: 1003
parent_module: 10-deployment_audit
product_version: v0.1
doc_version: v0.1
source_refs: [架构设计 §22 安全设计; §23 可观测性]
status: draft
estimate_days: 7
depends_on: [1001]
---

# 1003 安全设计与可观测性 — 实施计划

## 1. 任务目标

实现安全设计（API Key Secret、数据库最小权限、MCP 工具权限分级、Prompt Injection 防护、用户 Prompt 不能覆盖 Guardrail、文件类型与大小限制、任意代码执行默认关闭、持仓数据默认不上传、审计日志不可修改、数据源授权与版权责任边界在设置页展示）与可观测性（指标：数据源可用率/缺失率/新闻延迟/解析成功率/向量索引延迟/RAG 命中率/引用校验失败率/Agent 节点耗时/模型成本/研究信号拒绝率/提醒延迟/策略成功率；Trace 字段：trace_id/job_run_id/strategy_version_id/research_run_id/symbol/agent_node/model_version/provider_version）。

## 2. 工作项拆解

- 1003.1 安全设计落地 — Secret/最小权限/MCP 分级/Injection 防护/文件限制/代码执行关闭。
- 1003.2 指标采集 — 12 类指标接入 Prometheus。
- 1003.3 Trace 字段 — 全链路 trace 注入与 Grafana 展示。
- 1003.4 责任边界展示 — 设置页展示数据源授权/WebSearch Key/新闻版权/用户上传责任。

## 3. 依赖关系

- 前置：1001（部署与 Prometheus/Grafana）。
- 被依赖：1004（故障降级依赖指标与告警）。
- 外部依赖：无。

## 4. 工时估算

- 1003.1：2 天
- 1003.2：2 天
- 1003.3：2 天
- 1003.4：1 天
- 合计：7 天。

## 5. 里程碑与交付物

- M1：安全设计要点落地（第 2 天）。
- M2：12 类指标接入 Prometheus（第 4 天）。
- M3：Trace 字段全链路注入（第 6 天）。
- M4：责任边界设置页（第 7 天）。

## 6. 验收动作

- 用户 Prompt 试图覆盖 Guardrail 时被拒绝（对应架构 §22）；
- 持仓数据默认不上传（对应架构 §22）；
- 指标与 Trace 在 Grafana 可观测（对应架构 §23）。

## 7. 审计追溯

- `source_refs`：架构 §22 / §23；
- 关联 spec：`spec/v0.1/10-deployment_audit/spec.md` §4 / §8；
- 不可变产物：安全配置、指标时序、Trace 记录。
