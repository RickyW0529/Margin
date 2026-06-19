---
task_id: 1003
parent_module: 10-deployment_audit
product_version: v0.1
doc_version: v0.1
source_refs: [架构设计 §22 安全设计; §23 可观测性]
status: active
estimate_days: 7
depends_on: [1001]
---

# 1003 安全设计与可观测性 — 实施计划

## 1. 任务目标

实现安全设计（API Key Secret、非 root 容器、内部工具权限分级、Prompt Guardrail、任意代码执行默认关闭、审计不可变）与 v0.1 可观测性基线（HTTP 请求/延迟、Provider 成功/失败/降级、结构化日志、trace_id、Grafana dashboard）。更细业务指标在后续版本按模块增量接入。

## 2. 工作项拆解

- 1003.1 安全设计落地 — Secret/最小权限/内部工具分级/Injection 防护/文件限制/代码执行关闭。
- 1003.2 指标采集 — HTTP 与 Provider 核心指标接入 Prometheus，预留业务指标扩展。
- 1003.3 Trace 字段 — 全链路 trace 注入与 Grafana 展示。
- 1003.4 责任边界 — `.env.example` 与设计文档明确数据源授权、WebSearch Key、新闻版权和用户上传责任；设置页归入 v0.2 Provider 配置界面。

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
- M2：HTTP/Provider 核心指标接入 Prometheus（第 4 天）。
- M3：Trace 字段全链路注入（第 6 天）。
- M4：责任边界配置模板与文档（第 7 天）。

## 6. 验收动作

- 用户 Prompt 试图覆盖 Guardrail 时被拒绝（对应架构 §22）；
- 持仓数据默认不上传（对应架构 §22）；
- 指标与 Trace 在 Grafana 可观测（对应架构 §23）。

## 7. 审计追溯

- `source_refs`：架构 §22 / §23；
- 关联 spec：`spec/v0.1/10-deployment_audit/spec.md` §4 / §8；
- 不可变产物：安全配置、指标时序、Trace 记录。
