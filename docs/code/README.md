# Margin 当前功能代码说明索引

本目录按功能模块组织 Margin 当前实现的完整函数级代码说明，覆盖后端 Python 模块、FastAPI 接口、前端 Next.js 页面与 React 组件，以及部署与可观测性配置。

- 英文版请见 [`en/README.md`](./en/README.md)。

## 目录结构

```
docs/code/
├── README.md                         本文件，模块索引与使用说明
├── 00-shared.md                      共享与核心横切组件
├── 01-data_provider.md               数据 Provider 模块
├── 02-holdings.md                    持仓模块
├── 03-filing_websearch.md            公告与 WebSearch 模块
├── 04-text_indexing.md               文本索引模块
├── 05-rag_evidence.md                RAG 证据模块
├── 06-multi_agent_research.md        多 Agent 研究流程模块
├── 07-strategy_config.md             策略配置模块
├── 08-research_candidate_dashboard.md 研究候选面板模块
├── 09-holdings_monitoring.md         持仓监控模块
└── 10-deployment_audit.md            部署与审计模块
```

## 模块索引

| 编号 | 模块（英文 slug） | 中文名 | 代码说明文档 | 对应源码路径 |
|------|-------------------|--------|--------------|--------------|
| 00 | shared | 共享与核心横切组件 | [00-shared.md](./00-shared.md) | `src/margin/settings.py`、`src/margin/worker.py`、`src/margin/storage/`、`src/margin/api/`、`src/margin/core/provider.py`、`src/margin/core/registry.py`、`src/margin/core/resilience.py`、`src/margin/core/secret.py` |
| 01 | data_provider | 数据 Provider 模块 | [01-data_provider.md](./01-data_provider.md) | `src/margin/data/`、`src/margin/core/provider.py`、`src/margin/core/registry.py` |
| 02 | holdings | 持仓模块 | [02-holdings.md](./02-holdings.md) | `src/margin/portfolio/`、`src/margin/api/routes/portfolios.py`、`web/app/portfolios/`、`web/components/portfolio-workspace.tsx` |
| 03 | filing_websearch | 公告与 WebSearch 模块 | [03-filing_websearch.md](./03-filing_websearch.md) | `src/margin/news/` |
| 04 | text_indexing | 文本索引模块 | [04-text_indexing.md](./04-text_indexing.md) | `src/margin/vector/` |
| 05 | rag_evidence | RAG 证据模块 | [05-rag_evidence.md](./05-rag_evidence.md) | `src/margin/evidence/` |
| 06 | multi_agent_research | 多 Agent 研究流程模块 | [06-multi_agent_research.md](./06-multi_agent_research.md) | `src/margin/research/`、`src/margin/api/routes/research.py` |
| 07 | strategy_config | 策略配置模块 | [07-strategy_config.md](./07-strategy_config.md) | `src/margin/strategy/`、`src/margin/api/routes/strategy.py` |
| 08 | research_candidate_dashboard | 研究候选面板模块 | [08-research_candidate_dashboard.md](./08-research_candidate_dashboard.md) | `src/margin/dashboard/`、`src/margin/api/routes/dashboard.py`、`web/app/research/`、`web/components/candidate-*.tsx`、`web/components/evidence-panel.tsx`、`web/components/report-panel.tsx`、`web/components/valuation-panel.tsx`、`web/components/home-summary.tsx` |
| 09 | holdings_monitoring | 持仓监控模块 | [09-holdings_monitoring.md](./09-holdings_monitoring.md) | `src/margin/holdings_monitoring/`、`src/margin/api/routes/monitoring.py`、`web/app/positions/`、`web/components/position-detail.tsx`、`web/components/position-review-badge.tsx` |
| 10 | deployment_audit | 部署与审计模块 | [10-deployment_audit.md](./10-deployment_audit.md) | `src/margin/core/`（audit、snapshot、degradation、logging、metrics）、`src/margin/api/middleware.py`、`src/margin/api/metrics.py`、`src/margin/api/routes/health.py`、`Dockerfile`、`web/Dockerfile`、`docker-compose.yml`、`.github/workflows/ci.yml`、`scripts/`、`docker/prometheus.yml` |

## 文档约定

- 每份模块文档均包含：模块概述、文件级摘要、公共类/函数说明、FastAPI 接口表、前端组件说明、跨模块依赖说明。
- 类方法与函数以 Markdown 表格形式列出签名、参数与返回值；签名优先保留源码中的类型注解。
- 若源码存在 docstring，文档直接引用；否则根据代码语义补充说明。
- 文档只描述公共接口与关键实现，不展开业务无关的内部细节。

## 如何使用

- **按模块查找**：直接打开对应编号 markdown 文件。
- **跨模块追踪**：每份文档末尾的「跨模块使用说明」列出本模块消费或提供的服务、Provider 与数据流。
- **与设计对照**：代码文档描述当前实现；产品目标与模块边界查看对应大版本的 `docs/design/<version>/`。

## 更新说明

- `docs/code/` 不按产品版本建立子目录，始终描述当前仓库代码。
- 每次功能代码完成后，应在同一变更中更新本目录中的对应模块文档。
- 产品设计历史由 `docs/design/<version>/` 承担，代码实现历史由 Git 承担。

---

*本索引由代码自动生成脚本基于当前源码整理，未修改源码。*
