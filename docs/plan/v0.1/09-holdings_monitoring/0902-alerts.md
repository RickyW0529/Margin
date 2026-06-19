---
task_id: 0902
parent_module: 09-holdings_monitoring
product_version: v0.1
doc_version: v0.1
source_refs: [架构设计 §19 盘中监控架构; 产品设计 §10, §5.3]
status: active
estimate_days: 7
depends_on: [0901]
---

# 0902 提醒引擎与盘中监控 — 实施计划

## 1. 任务目标

实现盘中监控（Price Poller + DocumentEvent Poller → 规则引擎 → 快照证据关联 → 逻辑改变? → P0/P1 或 P2/P3 提醒）与提醒分级。v0.1 使用确定性解释与结构化证据引用，LLM 解释为可选增强；盘中不执行重新训练、全市场研究、任意 Agent 长链或自动下单。

## 2. 工作项拆解

- 0902.1 Price/News Poller — 盘中价格与新闻轮询。
- 0902.2 规则引擎 — 确定性规则检测（价格触及失效阈值、行业暴露超限等）。
- 0902.3 证据关联与轻量解释 — 触发后关联模块 03 已快照、已分级的 DocumentEvent；Provider 不可用时保持规则型解释。
- 0902.4 提醒分级与通知 — P0–P3 分级，NotificationProvider 输出。

## 3. 依赖关系

- 前置：0901（投资逻辑状态）。
- 被依赖：0903（复盘记录）。
- 外部依赖：01 盘中价格、03 公告/新闻、05 证据检索。

## 4. 工时估算

- 0902.1：2 天
- 0902.2：2 天
- 0902.3：2 天
- 0902.4：1 天
- 合计：7 天。

## 5. 里程碑与交付物

- M1：Price/News Poller 可用（第 2 天）。
- M2：规则引擎九类提醒类型（第 4 天）。
- M3：证据检索与轻量解释（第 6 天）。
- M4：提醒分级与通知（第 7 天）。

## 6. 验收动作

- 价格触及失效阈值时触发提醒并经 RAG 验证（对应产品 §5.3）；
- 盘中不执行自动下单或任意 Agent 长链（对应 spec 09 §1）；
- 提醒按 P0–P3 分级输出。

## 7. 审计追溯

- `source_refs`：架构 §19、产品 §10 / §5.3；
- 关联 spec：`spec/v0.1/09-holdings_monitoring/spec.md` §3 / §4；
- 不可变产物：alert_event、触发规则、证据引用。
