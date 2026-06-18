---
task_id: 0901
parent_module: 09-holdings_monitoring
product_version: v0.1
doc_version: v0.1
source_refs: [架构设计 §26-Phase5: 持仓面板增强; §17.1, 产品设计 §8.3]
status: draft
estimate_days: 7
depends_on: [0703]
---

# 0901 投资逻辑状态跟踪 — 实施计划

## 1. 任务目标

实现投资逻辑对象（thesis/entry_conditions/hold_conditions/invalidation_conditions/target_horizon/next_review_at）与持仓健康状态（HEALTHY/WATCH/RISK/INVALIDATED/DATA_MISSING/EVENT_PENDING）。投资逻辑变更生成新版本 POSITION_THESIS，旧版本保留。晚间研究状态回写持仓。

## 2. 工作项拆解

- 0901.1 投资逻辑对象模型 — thesis 与条件字段落库。
- 0901.2 持仓健康状态判定 — 六状态计算。
- 0901.3 研究状态回写 — 晚间研究后更新持仓研究状态。
- 0901.4 thesis API — GET/PUT /positions/{id}/thesis。

## 3. 依赖关系

- 前置：0703（策略版本，对应 Gantt e3 after e1）。
- 被依赖：0902（提醒引擎）。
- 外部依赖：02 持仓、06 研究状态回写。

## 4. 工时估算

- 0901.1：2 天
- 0901.2：2 天
- 0901.3：2 天
- 0901.4：1 天
- 合计：7 天（对齐 Gantt e3）。

## 5. 里程碑与交付物

- M1：投资逻辑对象模型可用（第 2 天）。
- M2：持仓健康状态判定（第 4 天）。
- M3：研究状态回写（第 6 天）。
- M4：thesis API 可用（第 7 天）。

## 6. 验收动作

- 用户可查看投资逻辑状态（对应产品 §15 条目 7）；
- 投资逻辑变更生成新版本，旧版本保留（对应 spec 09 §8）；
- DATA_MISSING 时标记并降级。

## 7. 审计追溯

- `source_refs`：架构 §26-Phase5 e3、§17.1、产品 §8.3；
- 关联 spec：`spec/v0.1/09-holdings_monitoring/spec.md` §4 / §8；
- 不可变产物：POSITION_THESIS 版本、健康状态变更记录。
