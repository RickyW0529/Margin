---
task_id: 0104
parent_module: 01-data_provider
product_version: v0.1
doc_version: v0.1
source_refs: [架构设计 §26-Phase2: 时点与数据质量校验; §4.4, §4.5]
status: active
estimate_days: 14
depends_on: [0103, 1002]
---

# 0104 时点与数据质量校验 — 实施计划

## 1. 任务目标

落实 Point-in-Time 时点字段（event_at/published_at/available_at/fetched_at/revised_at）与防未来数据泄漏校验（available_at <= decision_at），并实现数据质量检查：缺失、修订、异常隔离。数据异常时向下游发送数据质量事件，触发停止高置信研究信号输出。

## 2. 工作项拆解

- 0104.1 时点字段落库 — 每条关键记录含五项时点字段。
- 0104.2 防未来数据泄漏校验 — 特征请求按 decision_at 过滤 available_at。
- 0104.3 数据质量检查 — 缺失率、修订追踪（revised_at）、异常隔离。
- 0104.4 数据质量事件发布 — 异常时发事件，下游据此降级（对应架构 §25）。

## 3. 依赖关系

- 前置：0103（字段标准化）、1002（ODS/DWD/PIT 存储分层与快照机制就绪，对应 Gantt b2 after a3）。
- 被依赖：0301（公告获取 c1 依赖 b2）。
- 外部依赖：10-deployment_audit 的 PIT 时点层。

## 4. 工时估算

- 0104.1：3 天
- 0104.2：4 天
- 0104.3：4 天
- 0104.4：3 天
- 合计：14 天（对齐 Gantt b2）。

## 5. 里程碑与交付物

- M1：时点字段落库（第 3 天）。
- M2：防泄漏校验通过单测（第 7 天）。
- M3：数据质量检查与异常隔离可用（第 11 天）。
- M4：数据质量事件发布，交付时点与质量校验（第 14 天）。

## 6. 验收动作

- 构造未来数据样本，校验拒绝进入特征并记录泄漏风险；
- 数据缺失时下游收到质量事件并降级（对应产品 §15 条目 8）；
- 对应 spec 01 §4 / §7。

## 7. 审计追溯

- `source_refs`：架构 §26-Phase2 b2、§4.4 / §4.5；
- 关联 spec：`spec/v0.1/01-data_provider/spec.md` §4 / §7；
- 不可变产物：时点字段、数据质量事件、泄漏风险记录。
