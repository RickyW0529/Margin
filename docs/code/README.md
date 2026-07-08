# 代码模块怎么跑

一次“今日研究”大致按下面顺序跑。这里只解释模块协作关系，详细接口和字段再看对应模块文档。

| 顺序 | 模块 | 运行时做什么 |
| --- | --- | --- |
| 0 | `00-shared` | 提供数据库、配置、审计、日志、Worker 和通用 Provider 能力。 |
| 1 | `07-strategy_config` | 读取 Provider、研究范围、策略和 Prompt 配置，决定本次任务用什么设置。 |
| 2 | `01-data_provider` | 拉取并标准化行情、财务、指数成分等数据，通过质量检查后发布为可用数据。 |
| 3 | `11-valuation_discovery` | 基于公司池生成量化特征，运行 ML/量化筛选，并发布 Analysis Mart 结果。 |
| 4 | `03-filing_websearch` | 根据候选股票补公告、新闻和 WebSearch 资料，保存原文和快照。 |
| 5 | `04-text_indexing` | 把文本解析、分块、向量化，让后续检索能找到相关证据。 |
| 6 | `05-rag_evidence` | 把检索结果整理成证据包，保留引用定位和可追溯 evidence link。 |
| 7 | `06-multi_agent_research` | MainAgent 调度专家 Agent，综合量化结果、证据和风险，形成最终复核。 |
| 8 | `08-research_candidate_dashboard` | 展示推荐股票、理由、风险、证据、详情页和 Agent 任务进度。 |
| 9 | `10-deployment_audit` | 负责部署、迁移、健康检查、指标、降级和运行审计。 |

## 数据方向

```text
Data Provider
  -> Quant / Analysis Mart
  -> Evidence / RAG
  -> MainAgent Review
  -> Dashboard
```

02 和 09 是历史编号，当前实现已删除。
