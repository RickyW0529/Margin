---
task_id: 0702
parent_module: 07-strategy_config
product_version: v0.1
doc_version: v0.1
source_refs: [架构设计 §15.2 Prompt 分层; 产品设计 §6.3]
status: draft
estimate_days: 7
depends_on: [0701]
---

# 0702 自定义 Prompt 与分层 — 实施计划

## 1. 任务目标

实现 Prompt 分层合并（System Guardrail + Platform Research + Strategy Template + User Custom + Current Task Context + Retrieved Evidence）与用户自定义 Prompt 编辑（研究目标/风格偏好/重点指标/排除公司类型/信息源/输出风格/风险偏好/反方审查强度）。用户 Prompt 不得覆盖证据引用要求、数据时点限制、风险披露、结构化输出 Schema、禁止收益承诺、禁止自动下单、系统安全策略。

## 2. 工作项拆解

- 0702.1 Prompt 分层合并机制 — 五层叠加产出最终 Prompt。
- 0702.2 用户自定义 Prompt 编辑 — 8 项可编辑字段。
- 0702.3 不可覆盖项守卫 — 用户 Prompt 不能覆盖系统 Guardrail。
- 0702.4 Prompt 版本化 — Prompt 版本随策略版本冻结。

## 3. 依赖关系

- 前置：0701（策略配置结构）。
- 被依赖：0703（版本管理）。
- 外部依赖：06 模型网关 Prompt 版本。

## 4. 工时估算

- 0702.1：2 天
- 0702.2：2 天
- 0702.3：2 天
- 0702.4：1 天
- 合计：7 天。

## 5. 里程碑与交付物

- M1：Prompt 分层合并可用（第 2 天）。
- M2：用户自定义 Prompt 编辑（第 4 天）。
- M3：不可覆盖项守卫生效（第 6 天）。
- M4：Prompt 版本化（第 7 天）。

## 6. 验收动作

- 用户 Prompt 试图覆盖 Guardrail 时被拒绝（对应 spec 07 §4）；
- 最终 Prompt 含证据引用与时点约束；
- 对应架构 §22 用户 Prompt 不能覆盖系统 Guardrail。

## 7. 审计追溯

- `source_refs`：架构 §15.2、产品 §6.3；
- 关联 spec：`spec/v0.1/07-strategy_config/spec.md` §4 / §8；
- 不可变产物：Prompt 版本、分层合并记录。
