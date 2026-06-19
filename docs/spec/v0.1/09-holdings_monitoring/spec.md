---
module_id: 09-holdings_monitoring
product_version: v0.1
doc_version: v0.1
source_refs: [产品设计 §5.3, §8, §10, §13.2-9; 架构设计 §17, §19, §26-Phase5]
status: active
---

# 09 持仓监控模块 — 功能规格

## 1. 模块目标

持续验证当前持仓的投资逻辑是否仍成立、组合风险是否需要复核，并在盘中与盘后按规则触发分级提醒。盘中只做确定性规则检测、已快照公告/新闻证据关联与可选轻量解释，不执行重新训练、全市场研究、任意 Agent 长链、自动下单或无规则限制的自由研究结论。

## 2. 输入 / 输出

- **输入**：02-holdings 的持仓与投资逻辑对象、01-data_provider 的盘中价格轮询、03-filing_websearch 的新公告与新闻、05-rag_evidence 的证据校验。
- **触发**：交易时段价格/新闻轮询、新公告事件、晚间研究状态回写。
- **输出**：持仓健康状态、分级提醒（P0–P3）、复盘记录、操作历史。
- **消费方**：用户（盘中决策与复盘）、08-research_candidate_dashboard（持仓复核视图）。

## 3. 接口契约

盘中监控流程（架构 §19）：AKShare Price Poller + 模块 03 DocumentEvent Poller → 规则引擎 → 关联快照证据 → 逻辑改变? → P0/P1 提醒（逻辑改变）或 P2/P3 提醒（未改变）。外部 Provider 不可用时降级为 DATA_MISSING/规则型提醒。

盘中持仓流程（产品 §5.3）：交易时间 → 更新持仓价格 → 确定性规则检测 → 触发阈值? → 查询最新公告与新闻 → RAG 验证是否有新证据 → 投资逻辑是否改变? → 普通提醒 / 高优先级风险提醒 → 用户手工决策。

持仓 API（架构 §17.3）：`GET /api/v1/positions/{id}/thesis`、`PUT /api/v1/positions/{id}/thesis`、`GET /api/v1/positions/{id}/alerts`、`GET /api/v1/portfolios/{id}/risk`。

## 4. 数据模型

持仓健康状态（产品 §8.3）：HEALTHY（逻辑与风险正常）、WATCH（某项指标恶化尚未失效）、RISK（接近失效条件）、INVALIDATED（投资逻辑已失效）、DATA_MISSING（关键数据缺失）、EVENT_PENDING（等待关键公告或财报）。

提醒类型（产品 §10.1）：数据异常、新公告、重大负面事件、价格触及失效阈值、模型排名明显变化、行业暴露超限、估值达到目标区间、策略运行失败、关键事件即将发生。

提醒优先级（产品 §10.2）：P0 立即通知并置顶、P1 交易时段通知、P2 面板展示+晚间汇总、P3 仅进入研究日志。

投资逻辑对象（架构 §17.1）：`thesis`、`entry_conditions`、`hold_conditions`、`invalidation_conditions`、`target_horizon`、`next_review_at`。

核心实体（架构 §5.3）：`POSITION` 1→N `POSITION_THESIS` 1→N `ALERT_EVENT`。

## 5. 与其他模块依赖

- **上游**：02-holdings、01-data_provider（盘中价格）、03-filing_websearch（公告/新闻）、05-rag_evidence（证据校验）。
- **下游**：08-research_candidate_dashboard（持仓复核视图）、用户通知。
- **规避循环**：盘中监控不反向改写研究信号；投资逻辑变更生成新版本 `POSITION_THESIS`，旧版本保留。

## 6. 验收标准

对应产品设计 §15：

- 条目 7：用户可在持仓面板查看盈亏、风险和投资逻辑状态；
- 条目 8：数据异常时停止高置信研究信号输出（DATA_MISSING 触发降级）。

## 7. 风险与降级

对应架构 §25：

- 价格数据缺失 → 沿用上一可用快照并标记 DATA_MISSING；
- 证据检索失败 → 降级为规则型提醒，不输出 AI 高置信解释；
- 盘中 Agent 失败 → 退回确定性规则检测，不触发任意长链。

## 8. 审计追溯

- `source_refs` 指向产品设计 §5.3 / §8 / §10、架构设计 §17 / §19 / §26 Phase5；
- 每条提醒记录 `alert_event`、触发规则、触发时间、证据引用，落库不可篡改；
- 投资逻辑对象变更生成新版本，复盘记录与操作历史完整保留。
