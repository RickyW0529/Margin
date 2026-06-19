---
task_id: 0503
parent_module: 05-rag_evidence
product_version: v0.1
doc_version: v0.1
source_refs: [架构设计 §10.2 RAG 工作流; §25 故障降级]
status: active
estimate_days: 7
depends_on: [0502]
---

# 0503 Claim 校验与 ABSTAINED — 实施计划

## 1. 任务目标

实现 Citation Validator：校验证据引用、来源等级与时点，Claim 通过/失败判定。证据不足、来源冲突或数据异常时输出 ABSTAINED。原则：宁可 ABSTAINED，也不输出虚假的高置信结论。冲突时提升反方审查并封顶置信度。

## 2. 工作项拆解

- 0503.1 引用与来源等级校验 — 校验 evidence_ids、source_level、时点。
- 0503.2 冲突处理 — 冲突 Claim 提升反方审查、置信度封顶。
- 0503.3 ABSTAINED 判定 — 证据不足/冲突过高时拒绝输出高置信结论。
- 0503.4 校验审计 — 记录校验通过/失败原因。

## 3. 依赖关系

- 前置：0502（引用定位字段）。
- 被依赖：0601（Provider 与工具层，对应 Gantt d3 after d2）、0605（Citation Validator Agent）。
- 外部依赖：无。

## 4. 工时估算

- 0503.1：2 天
- 0503.2：2 天
- 0503.3：2 天
- 0503.4：1 天
- 合计：7 天。

## 5. 里程碑与交付物

- M1：引用与来源等级校验可用（第 2 天）。
- M2：冲突处理与置信度封顶（第 4 天）。
- M3：ABSTAINED 判定逻辑（第 6 天）。
- M4：校验审计完整（第 7 天）。

## 6. 验收动作

- 引用校验失败的 Claim 不进入研究信号（对应 spec 05 §7）；
- 证据不足时输出 ABSTAINED（对应产品 §15 条目 8）；
- 对应产品 §12.1 引用校验失败率、无证据关键结论率指标。

## 7. 审计追溯

- `source_refs`：架构 §10.2 / §25；
- 关联 spec：`spec/v0.1/05-rag_evidence/spec.md` §7 / §8；
- 不可变产物：校验结果、ABSTAINED 记录、冲突标记。
