---
task_id: 0701
parent_module: 07-strategy_config
product_version: v0.1
doc_version: v0.1
source_refs: [架构设计 §26-Phase5: 策略配置中心; §15.1, 产品设计 §6.1, §6.2]
status: active
estimate_days: 7
depends_on: [0601]
---

# 0701 策略模板与配置结构 — 实施计划

## 1. 任务目标

实现预置策略模板（价值质量、低估修复、高股息、成长合理估值、周期反转、用户完全自定义）与策略配置结构（universe/horizon/valuation/quality/risk/ai/evidence/decision）。策略编辑器经 Schema 校验与安全规则合并后生成策略版本。

## 2. 工作项拆解

- 0701.1 策略配置 Schema — universe/horizon/valuation/quality/risk/ai/evidence/decision 字段定义。
- 0701.2 预置策略模板 — 6 个模板实现。
- 0701.3 策略编辑器与 Schema 校验 — 编辑、校验、安全规则合并。
- 0701.4 策略版本生成 — 每次修改生成 strategy_version_id。

## 3. 依赖关系

- 前置：0601（Provider、模型网关与 Guardrail 基础可用，用于策略 Schema 的模型/Provider 引用与安全规则合并）。
- 被依赖：0702（自定义 Prompt）、0703（版本管理）。
- 外部依赖：01 universe/因子数据源引用。

## 4. 工时估算

- 0701.1：2 天
- 0701.2：2 天
- 0701.3：2 天
- 0701.4：1 天
- 合计：7 天。

## 5. 里程碑与交付物

- M1：策略配置 Schema 可用（第 2 天）。
- M2：6 个预置模板（第 4 天）。
- M3：策略编辑器与校验（第 6 天）。
- M4：策略版本生成（第 7 天）。

## 6. 验收动作

- 用户可创建自定义策略（对应产品 §15 条目 5）；
- 策略配置含 prohibited_outputs（GUARANTEED_RETURN/DIRECT_BUY_SELL_ORDER 被禁）；
- 对应 spec 07 §3 / §4。

## 7. 审计追溯

- `source_refs`：架构 §26-Phase5 e1、§15.1、产品 §6.1 / §6.2；
- 关联 spec：`spec/v0.1/07-strategy_config/spec.md` §3 / §4；
- 不可变产物：strategy_version_id、Schema 校验记录。
