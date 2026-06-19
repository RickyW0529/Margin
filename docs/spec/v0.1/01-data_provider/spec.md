---
module_id: 01-data_provider
product_version: v0.1
doc_version: v0.1
source_refs: [产品设计 §4.1, §4.3.1, §13.2-1; 架构设计 §4, §8.1, §26-Phase1, §26-Phase2]
status: active
---

# 01 数据 Provider 模块 — 功能规格

## 1. 模块目标

标准化接入 A 股结构化数据（行情、财务、指数成分、公司行动、股票元数据、行业与宏观），满足 Point-in-Time 时点要求与防未来数据泄漏约束。本模块只负责获取与标准化，不承担长期存储（存储见 10-deployment_audit）。MVP 内置 AKShare 与 Tushare 两个 Provider，并通过 Provider Registry 支持后续扩展。

## 2. 输入 / 输出

- **输入**：AKShare / Tushare API、用户配置的 token 与频率限制、股票池（沪深 300 / 自选池）、`decision_at` 决策时点。
- **触发**：晚间批处理调度、按需工具调用（MarketDataTool / FinancialTool）。
- **输出**：标准化数据事件（行情、财务、指数成分、复权因子、公司行动），写入存储层 ODS→DWD→PIT 分层；并产出 `fetched_at`、`available_at`、原始响应哈希等审计字段。
- **消费方**：02-holdings（成本与估值）、03-filing_websearch（公告元数据）、04-text_indexing（证券映射）、06-multi_agent_research（MarketDataTool / FinancialTool / FactorTool）。

## 3. 接口契约

数据连接器统一协议（架构 §4.2）：

```python
class MarketDataProvider(Protocol):
    def get_securities(self, as_of: datetime): ...
    def get_bars(self, symbols, start, end, frequency="1d"): ...
    def get_adjustment_factors(self, symbols, start, end): ...
    def get_financials(self, symbols, start, end): ...
    def get_index_members(self, index_code, as_of): ...
```

Provider Registry 能力：健康检查、限流、重试、成本统计、Secret 引用、版本号、审计日志（架构 §8.1）。每个 Provider 必须记录数据来源、API Key 的本地 Secret 引用、调用频率限制、字段授权说明、`fetched_at`、`available_at`、原始响应哈希（架构 §4.2.1）。

## 4. 数据模型

数据域（架构 §4.1）：行情（日线/分钟线、成交量、成交额、复权因子）、财务（三大报表、财务指标、分红、预测）、股票元数据（代码、行业、上市状态、指数成分）、公司行动（分红、送转、拆并股、停复牌、退市）、行业与宏观、用户数据、衍生特征。

时点字段（架构 §4.4），每条关键记录至少包含：

```text
event_at       事件发生时间
published_at   对外公开时间
available_at   系统允许用于决策的时间
fetched_at     系统获取时间
revised_at     后续修订时间
```

## 5. 与其他模块依赖

- **上游**：AKShare / Tushare 外部 API、用户 Secret 配置。
- **下游**：02-holdings、03-filing_websearch、04-text_indexing、06-multi_agent_research、09-holdings_monitoring（盘中价格轮询）。
- **规避循环**：本模块不消费研究信号，仅向上单向供给数据。

## 6. 验收标准

对应产品设计 §15「产品验收标准」：

- 条目 2：可配置至少一个 AKShare / Tushare 数据源，完成行情、财务、指数成分、公司行动获取；
- 条目 8：数据异常或缺失时，停止高置信研究信号输出（由本模块向下游发送数据质量事件触发）。

## 7. 风险与降级

对应架构 §25「故障降级」：

- 数据源失败 → 切换备用源（Tushare ↔ AKShare 互备），或使用旧数据并显式降级标记；
- 字段缺失或修订 → 记录 `revised_at`，下游引用须按 `available_at <= decision_at` 校验；
- 限流/授权异常 → 告警并降级，不静默继续。

## 8. 审计追溯

- `source_refs` 指向产品设计 §4.1 / §4.3.1、架构设计 §4 / §8.1 / §26 Phase1-Phase2；
- 每次 Provider 调用保留原始响应哈希、`fetched_at`、`available_at`、Provider 版本号，落库后不可篡改；
- 字段映射与代码映射规则随版本记录，变更需新建版本目录。
