---
task_id: 0604
parent_module: 06-multi_agent_research
product_version: v0.1
doc_version: v0.1
source_refs: [架构设计 §12.1 Agent #8,#9,#10]
status: active
estimate_days: 5
depends_on: [0603]
---

# 0604 风险、反方审查与组合约束 Agent — 实施计划

## 1. 任务目标

实现 Risk and Value-Trap Review Agent（输出风险评分而非未经校准的概率）、Reflect / Counter-Argument Agent（输出结构化反方理由、冲突标记与未知项）、Portfolio Constraint Agent（检查组合暴露与持仓逻辑）。反方审查强度由策略配置驱动。v0.1 不要求每条风险/反方理由绑定独立证据引用；逐条证据引用、locator 与中文输出约束进入 v0.2。

## 2. 工作项拆解

- 0604.1 Risk and Value-Trap Review Agent — 风险评分，不输出未校准概率。
- 0604.2 Reflect / Counter-Argument Agent — 结构化反方理由、冲突标记、未知项审查。
- 0604.3 Portfolio Constraint Agent — 组合暴露与持仓逻辑检查，对接 02。
- 0604.4 输出 Schema 与降级 — 结构化风险/反方/约束输出，单 Agent 失败按降级策略处理。

## 3. 依赖关系

- 前置：0603（摘要与证据）。
- 被依赖：0605（Research Signal Composer 与 Citation Validator）。
- 外部依赖：02 组合约束、07 策略反方审查强度。

## 4. 工时估算

- 0604.1：1 天
- 0604.2：2 天
- 0604.3：1 天
- 0604.4：1 天
- 合计：5 天。

## 5. 里程碑与交付物

- M1：Risk/Value-Trap Review Agent 可用（第 1 天）。
- M2：Reflect/Counter-Argument Agent 可用（第 3 天）。
- M3：Portfolio Constraint Agent 对接持仓（第 4 天）。
- M4：输出 Schema 与降级（第 5 天）。

## 6. 验收动作

- 风险评分为评分而非未校准概率（对应 spec 06 §4）；
- 反方审查覆盖反方理由、冲突标记与未知项；逐条证据绑定不属于 v0.1 验收；
- 组合约束超限时标记。

## 7. 审计追溯

- `source_refs`：架构 §12.1 #8/#9/#10；
- 关联 spec：`spec/v0.1/06-multi_agent_research/spec.md` §4 / §7；
- 不可变产物：风险评分、反方审查记录、约束检查结果。
