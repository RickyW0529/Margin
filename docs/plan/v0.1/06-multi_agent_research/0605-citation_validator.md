---
task_id: 0605
parent_module: 06-multi_agent_research
product_version: v0.1
doc_version: v0.1
source_refs: [架构设计 §12.1 Agent #11,#12; §12.2 工作流状态; §5.4 不可变快照]
status: draft
estimate_days: 4
depends_on: [0604, 0703, 1002]
---

# 0605 研究信号生成与引用校验 — 实施计划

## 1. 任务目标

实现 Research Signal Composer（生成研究信号与面板卡片）与 Citation Validator（校验证据引用、来源等级、时点）。落地工作流状态机（Initialized→DataReady→EvidenceReady→AnalysisReady→ReviewReady→Published，及 Aborted/Abstained）与不可变研究信号快照（股票池/数据/策略/Prompt/工具/模型/检索/证据/输出/输入输出哈希）。

## 2. 工作项拆解

- 0605.1 Research Signal Composer — 生成 RESEARCH_CANDIDATE/WATCH/ABSTAINED 信号与面板卡片。
- 0605.2 Citation Validator — 校验引用、来源等级、时点，对接 05 模块。
- 0605.3 工作流状态机 — 状态流转与 Aborted/Abstained 分支。
- 0605.4 不可变研究信号快照 — 冻结全量快照，落库不可篡改。

## 3. 依赖关系

- 前置：0604（风险/反方/组合约束）、0703（Active 策略版本与 Prompt 约束）、1002（不可变快照存储）。
- 被依赖：0801（候选面板消费研究信号）。
- 外部依赖：05 Claim 校验、10 不可变快照存储。

## 4. 工时估算

- 0605.1：1 天
- 0605.2：1 天
- 0605.3：1 天
- 0605.4：1 天
- 合计：4 天。

## 5. 里程碑与交付物

- M1：Research Signal Composer 可用（第 1 天）。
- M2：Citation Validator 对接证据模块（第 2 天）。
- M3：工作流状态机完整（第 3 天）。
- M4：不可变研究信号快照落地（第 4 天）。

## 6. 验收动作

- 完整晚间工作流可运行（对应产品 §15 条目 3）；
- 所有研究信号保留不可变审计记录（对应产品 §15 条目 9）；
- 数据异常时工作流 Aborted，停止高置信信号（对应产品 §15 条目 8）。

## 7. 审计追溯

- `source_refs`：架构 §12.1 #11/#12、§12.2、§5.4；
- 关联 spec：`spec/v0.1/06-multi_agent_research/spec.md` §4 / §6 / §8；
- 不可变产物：研究运行快照、输入输出哈希、trace_id/agent_node/model_version。
