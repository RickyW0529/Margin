---
task_id: 0602
parent_module: 06-multi_agent_research
product_version: v0.1
doc_version: v0.1
source_refs: [架构设计 §12.1 Agent #3,#4; §6.2.1]
status: draft
estimate_days: 5
depends_on: [0606]
---

# 0602 WebSearch Agent 与 Document Collector — 实施计划

## 1. 任务目标

实现 WebSearch Agent（通过 WebSearch Provider 发现相关新闻、公告入口与网页来源）与 Document Collector Agent（下载或快照合规原文，记录来源、时间、哈希）。两个 Agent 有明确输入、工具权限、输出 Schema 与失败降级策略。

## 2. 工作项拆解

- 0602.1 WebSearch Agent — 调用 WebSearchProvider，输出候选 URL/标题/摘要。
- 0602.2 Document Collector Agent — 下载原文、快照、记录来源/时间/哈希。
- 0602.3 工具权限与输出 Schema — 限定检索/下载权限，结构化输出。
- 0602.4 失败降级 — WebSearch 限流/失败时降级为已有公告与快照。

## 3. 依赖关系

- 前置：0606（Universe Filter 与 Quant Research Agent 产出初筛候选）。
- 被依赖：0603（Text Summary Agent 消费收集到的文档）。
- 外部依赖：03 WebSearchProvider、03 文档快照机制。

## 4. 工时估算

- 0602.1：2 天
- 0602.2：1 天
- 0602.3：1 天
- 0602.4：1 天
- 合计：5 天。

## 5. 里程碑与交付物

- M1：WebSearch Agent 可用（第 2 天）。
- M2：Document Collector Agent 可用（第 3 天）。
- M3：工具权限与输出 Schema（第 4 天）。
- M4：失败降级（第 5 天）。

## 6. 验收动作

- WebSearch Agent 输出候选来源并经合规校验（对应 spec 06 §4）；
- Document Collector 记录来源/时间/哈希；
- 限流时降级为已有快照。

## 7. 审计追溯

- `source_refs`：架构 §12.1 #3/#4、§6.2.1；
- 关联 spec：`spec/v0.1/06-multi_agent_research/spec.md` §4 / §8；
- 不可变产物：Agent 调用记录、文档快照哈希。
