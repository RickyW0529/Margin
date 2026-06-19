---
task_id: 0606
parent_module: 06-multi_agent_research
product_version: v0.1
doc_version: v0.1
source_refs: [架构设计 §12.1 Agent #1,#2; 产品设计 §5.2 量化初筛]
status: active
estimate_days: 5
depends_on: [0601]
---

# 0606 Universe Filter 与 Quant Research Agent — 实施计划

## 1. 任务目标

实现研究流程的量化初筛阶段：Universe Filter Agent（根据股票池和基础规则缩小范围）与 Quant Research Agent（计算因子、估值输入和基础排名）。对应晚间流程 §5.2 的「量化初筛」环节，产出初筛候选供下游 WebSearch/摘要/证据 Agent 使用。每个 Agent 有明确输入、工具权限、输出 Schema 与失败降级策略。

## 2. 工作项拆解

- 0606.1 Universe Filter Agent — 按股票池（沪深 300/自选池）与基础规则缩小范围。
- 0606.2 Quant Research Agent — 调用 FactorTool 计算因子、估值输入与基础排名。
- 0606.3 量化初筛候选输出 — 结构化候选列表，含排名与因子分数。
- 0606.4 下游衔接与降级 — 候选输出对接 WebSearch/Summary Agent，初筛失败时降级。

## 3. 依赖关系

- 前置：0601（Provider 与工具层，含 MarketDataTool/FactorTool）。
- 被依赖：0602（WebSearch Agent 基于初筛候选），0603 通过 0602 产出的文档与快照继续消费初筛上下文。
- 外部依赖：01 因子与候选数据、07 universe 配置。

## 4. 工时估算

- 0606.1：2 天
- 0606.2：2 天
- 0606.3：0.5 天
- 0606.4：0.5 天
- 合计：5 天。

## 5. 里程碑与交付物

- M1：Universe Filter Agent 可用（第 2 天）。
- M2：Quant Research Agent 因子与排名（第 4 天）。
- M3：初筛候选结构化输出（第 4.5 天）。
- M4：下游衔接与降级（第 5 天）。

## 6. 验收动作

- 量化初筛按股票池与基础规则缩小范围（对应产品 §5.2）；
- 候选含因子分数与排名，结构化输出（对应 spec 06 §3）；
- 初筛失败时按降级策略处理，不阻塞或伪造。

## 7. 审计追溯

- `source_refs`：架构 §12.1 #1/#2、产品 §5.2；
- 关联 spec：`spec/v0.1/06-multi_agent_research/spec.md` §4 / §8；
- 不可变产物：初筛候选列表、因子计算记录、Agent 调用 trace。
