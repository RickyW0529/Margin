---
module_id: 02-holdings
product_version: v0.1
doc_version: v0.1
source_refs: [产品设计 §4.8, §8, §13.2-2; 架构设计 §17, §26-Phase2]
status: draft
---

# 02 持仓模块 — 功能规格

## 1. 模块目标

提供持仓与交易记录的录入、成本计算、仓位与组合暴露度量，并支撑基础持仓面板。MVP 阶段支持手工录入与 CSV/Excel 导入，不默认连接券商账户、不保存券商密码、不自动下单。

## 2. 输入 / 输出

- **输入**：用户手工录入的交易、CSV/Excel 导入文件、券商导出文件适配插件；市场数据（成本与盈亏计算所需行情）来自 01-data_provider。
- **触发**：用户导入动作、每日收盘后成本与盈亏重算。
- **输出**：持仓（数量、成本、市值、盈亏）、组合风险指标（行业集中度、单票仓位、风格暴露、相关性、流动性、波动率、回撤、事件集中风险）、交易记录。
- **消费方**：08-research_candidate_dashboard（组合约束检查）、09-holdings_monitoring（投资逻辑跟踪与提醒）、06-multi_agent_research（PortfolioTool / Portfolio Constraint Agent）。

## 3. 接口契约

持仓 API（架构 §17.3）：

```text
GET  /api/v1/portfolios/{id}
GET  /api/v1/portfolios/{id}/positions
POST /api/v1/portfolios/{id}/trades
POST /api/v1/portfolios/{id}/imports
GET  /api/v1/portfolios/{id}/risk
GET  /api/v1/positions/{id}/thesis
PUT  /api/v1/positions/{id}/thesis
GET  /api/v1/positions/{id}/alerts
```

Portfolio Service 内部能力：成本与数量计算、组合风险引擎、投资逻辑跟踪（架构 §17）。

## 4. 数据模型

核心实体（架构 §5.3）：`PORTFOLIO` 1→N `POSITION`、`PORTFOLIO` 1→N `TRADE`、`POSITION` 1→N `POSITION_THESIS`、`POSITION_THESIS` 1→N `ALERT_EVENT`。

投资逻辑对象（架构 §17.1）：

```json
{
  "position_id": "pos_001",
  "entry_recommendation_id": "rec_001",
  "thesis": "现金流改善与估值修复",
  "entry_conditions": [],
  "hold_conditions": [],
  "invalidation_conditions": [],
  "target_horizon": [60, 120],
  "next_review_at": "2026-08-25"
}
```

组合风险维度（架构 §17.2）：单票仓位、行业集中度、风格暴露、相关性、流动性、波动率、回撤、事件集中风险。

## 5. 与其他模块依赖

- **上游**：01-data_provider（行情用于成本与盈亏）、用户导入。
- **下游**：06-multi_agent_research（PortfolioTool、Portfolio Constraint Agent）、08-research_candidate_dashboard、09-holdings_monitoring。
- **规避循环**：持仓状态由研究信号更新，但持仓模块不反向驱动研究，仅提供约束输入。

## 6. 验收标准

对应产品设计 §15：

- 条目 7：用户可在持仓面板查看盈亏、风险和投资逻辑状态；
- 条目 10：系统默认不执行真实交易，不保存券商密码。

## 7. 风险与降级

对应架构 §25：

- 行情缺失 → 盈亏沿用上一可用快照并标记 `DATA_MISSING`；
- 导入文件格式异常 → 拒绝写入并提示字段错误，不静默丢弃；
- 组合风险计算失败 → 降级为单票仓位校验，停止高置信组合结论。

## 8. 审计追溯

- `source_refs` 指向产品设计 §4.8 / §8、架构设计 §17 / §26 Phase2；
- 每笔交易记录含录入时间、来源（手工/CSV/插件）、原始行哈希，落库不可篡改；
- 投资逻辑对象的 `thesis`、`invalidation_conditions` 变更生成新版本，旧版本保留。
