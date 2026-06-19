---
task_id: 0101
parent_module: 01-data_provider
product_version: v0.1
doc_version: v0.1
source_refs: [架构设计 §26-Phase1: Provider Registry; §8.1]
status: active
estimate_days: 10
depends_on: []
---

# 0101 Provider Registry — 实施计划

## 1. 任务目标

实现轻量级 Provider 注册中心，统一管理 MarketDataProvider / WebSearchProvider / LLMProvider / EmbeddingProvider / RerankProvider / VectorStoreProvider / NotificationProvider 的注册、健康检查、限流、重试、成本统计、Secret 引用、版本号与审计日志，避免业务流程直接耦合某供应商。

## 2. 工作项拆解

- 0101.1 Provider 注册与能力元数据结构 — 定义 Provider 描述符（name/version/capabilities/healthcheck）。
- 0101.2 健康检查、限流、重试、Fallback 通用机制 — 按 Provider 类型可配置策略。
- 0101.3 Secret 引用与审计日志 — API Key 走本地 Secret，每次调用记录参数摘要与结果状态。
- 0101.4 成本统计与版本号 — 记录调用成本、Provider 版本，支持可审计回放。

## 3. 依赖关系

- 前置：无（Phase 1 起点，对应 Gantt a1）。
- 被依赖：0102（AKShare/Tushare 接入）、1001（Docker Compose 与基础服务编排）。
- 外部依赖：10-deployment_audit 的 Secret 配置机制。

## 4. 工时估算

- 0101.1：3 天
- 0101.2：3 天
- 0101.3：2 天
- 0101.4：2 天
- 合计：10 天（对齐 estimate_days）。

## 5. 里程碑与交付物

- M1：Provider 描述符与注册接口可用（第 3 天）。
- M2：健康检查/限流/重试机制通过单测（第 6 天）。
- M3：Secret 引用与审计日志接入（第 8 天）。
- M4：成本统计与版本号完整，交付 Provider Registry 模块（第 10 天）。

## 6. 验收动作

- 注册一个 mock Provider，健康检查/限流/重试行为符合预期；
- 调用记录含 `provider_version`、`fetched_at`、审计字段；
- 对应 spec 01 §3 接口契约。

## 7. 审计追溯

- `source_refs`：架构 §26-Phase1 a1、§8.1；
- 关联 spec：`spec/v0.1/01-data_provider/spec.md` §3；
- 不可变产物：Provider 调用审计日志。
