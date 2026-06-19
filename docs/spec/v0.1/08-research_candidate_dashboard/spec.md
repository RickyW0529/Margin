---
module_id: 08-research_candidate_dashboard
product_version: v0.1
doc_version: v0.1
source_refs: [产品设计 §7, §9.1, §13.2-8; 架构设计 §16, §26-Phase5]
status: active
---

# 08 研究候选面板模块 — 功能规格

## 1. 模块目标

呈现研究候选、证据展开、估值、催化剂、风险、反方理由、条件式观察计划与拒绝判断原因。以可审计的 run/item 模型组织查询，避免只按「今日候选」查询导致无法回放。明确提示卡片不是买卖指令，区分研究信号状态与持仓复核状态。

## 2. 输入 / 输出

- **输入**：06-multi_agent_research 的研究运行与研究项、05-rag_evidence 的证据、07-strategy_config 的策略版本、02-holdings 的持仓上下文。
- **触发**：用户浏览面板、晚间研究运行完成后刷新。
- **输出**：候选卡片、证据展开视图、估值视图、拒绝判断列表、研究详情页、任务运行状态。
- **消费方**：用户（研究阅读与决策）、09-holdings_monitoring（候选进入持仓后的复核闭环）。

## 3. 接口契约

后端组件（架构 §16.1）：Research Run Query Service、Dashboard BFF、Evidence View Service、Valuation View Service、Strategy Status Service、Report Renderer、Export Service。

API（架构 §16.3），以可审计的 run/item 模型组织：

```text
GET  /api/v1/research-runs?date=&strategy_id=&portfolio_id=&universe_id=&status=
POST /api/v1/research-runs
GET  /api/v1/research-runs/{run_id}
GET  /api/v1/research-runs/{run_id}/items
GET  /api/v1/research-items/{item_id}
GET  /api/v1/research-items/{item_id}/evidence
GET  /api/v1/research-items/{item_id}/valuation
GET  /api/v1/research-items/{item_id}/audit
POST /api/v1/research-items/{item_id}/feedback
GET  /api/v1/provider-status
POST /api/v1/jobs/nightly-runs
GET  /api/v1/jobs/{job_run_id}
```

关键查询参数：`date`、`strategy_id`/`strategy_version_id`、`portfolio_id`、`universe_id`、`run_id`（不可变研究运行快照）、`decision_at`（时点一致性校验）。

## 4. 数据模型

首页信息层级（产品 §7.1 / 架构 §16.2）：市场状态摘要、今日候选、现有持仓复核、高优先级风险、拒绝判断、策略运行状态。

候选卡片必含字段（产品 §7.2）：股票名称与代码、当前价格、量化排名、研究/持仓状态、基准估值区间、悲观估值区间、估值安全边际、价值陷阱风险评分、20/60/120 日事件关注窗口、主要催化剂、最强反方理由、证据数量和等级、进入研究观察条件、逻辑失效条件、观察窗口、使用的策略版本、明确提示「该卡片不是买卖指令」。

研究信号状态（产品 §7.3）：RESEARCH_CANDIDATE（满足候选门槛）、WATCH（有潜力但条件未满足）、ABSTAINED（信息不足/冲突/不确定性过高，拒绝输出高置信结论）。持仓复核状态：THESIS_VALID、REVIEW_REQUIRED、RISK_ALERT、THESIS_INVALIDATED。

证据展开（产品 §9.1）：结论 + 事实证据（来源/页码/数据）+ 系统推断 + 置信度。

核心实体（架构 §5.3）：`RESEARCH_RUN` 1→N `RESEARCH_ITEM` N→1 `SECURITY`、`RESEARCH_ITEM` 1→N `RESEARCH_EVIDENCE`。

## 5. 与其他模块依赖

- **上游**：06-multi_agent_research、05-rag_evidence、07-strategy_config、02-holdings。
- **下游**：09-holdings_monitoring（候选→持仓后的复核闭环）、用户反馈（feedback API）。
- **规避循环**：面板只读消费研究信号，不反向改写；用户 feedback 走独立接口记录。

## 6. 验收标准

对应产品设计 §15：

- 条目 6：用户可在研究候选面板查看候选与拒绝判断；
- 条目 4：研究结论包含证据引用（证据展开视图可定位原文）。

## 7. 风险与降级

对应架构 §25：

- 研究运行 Aborted/Abstained → 面板展示拒绝判断与原因，不展示虚假候选；
- 证据视图加载失败 → 降级展示证据摘要与定位字段，不展示无证据结论；
- BFF 查询超时 → 展示最近可用运行快照并标记时间。

## 8. 审计追溯

- `source_refs` 指向产品设计 §7 / §9.1、架构设计 §16 / §26 Phase5；
- 面板所有视图基于不可变 `run_id`/`item_id` 快照查询，支持回放任意历史研究运行；
- 用户 feedback 与审计接口 `/research-items/{item_id}/audit` 记录可追溯。
