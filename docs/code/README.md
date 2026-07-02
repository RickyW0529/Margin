# Margin 当前功能代码说明索引

本目录按功能模块组织 Margin 当前实现的完整函数级代码说明，覆盖后端 Python 模块、FastAPI 接口、前端 Next.js 页面与 React 组件，以及部署与可观测性配置。

- 英文版请见 [`en/README.md`](./en/README.md)。

## 目录结构

```
docs/code/
├── README.md                         本文件，模块索引与使用说明
├── 00-shared.md                      共享与核心横切组件
├── 01-data_provider.md               数据 Provider 模块
├── 03-filing_websearch.md            公告与 WebSearch 模块
├── 04-text_indexing.md               文本索引模块
├── 05-rag_evidence.md                RAG 证据模块
├── 06-multi_agent_research.md        多 Agent 研究流程模块
├── 07-strategy_config.md             策略配置模块
├── 08-research_candidate_dashboard.md 研究候选面板模块
├── 10-deployment_audit.md            部署与审计模块
└── 11-valuation_discovery.md         公司池与估值发现模块
```

## 模块索引

| 编号 | 模块（英文 slug） | 中文名 | 代码说明文档 | 对应源码路径 |
|------|-------------------|--------|--------------|--------------|
| 00 | shared | 共享与核心横切组件 | [00-shared.md](./00-shared.md) | `src/margin/settings.py`、`src/margin/worker.py`、`src/margin/storage/`、`src/margin/api/`、`src/margin/core/provider.py`、`src/margin/core/registry.py`、`src/margin/core/resilience.py`、`src/margin/core/secret.py`、`src/margin/documents/` |
| 01 | data_provider | 数据 Provider 模块 | [01-data_provider.md](./01-data_provider.md) | `src/margin/data/`、`src/margin/core/provider.py`、`src/margin/core/registry.py` |
| 03 | filing_websearch | 公告与 WebSearch 模块 | [03-filing_websearch.md](./03-filing_websearch.md) | `src/margin/news/` |
| 04 | text_indexing | 文本索引模块 | [04-text_indexing.md](./04-text_indexing.md) | `src/margin/vector/` |
| 05 | rag_evidence | RAG 证据模块 | [05-rag_evidence.md](./05-rag_evidence.md) | `src/margin/evidence/`、`src/margin/research/evidence_tools.py` |
| 06 | multi_agent_research | 多 Agent 研究流程模块 | [06-multi_agent_research.md](./06-multi_agent_research.md) | `src/margin/research/` |
| 07 | strategy_config | 策略配置模块 | [07-strategy_config.md](./07-strategy_config.md) | `src/margin/strategy/`、`src/margin/strategy/bootstrap.py`、`src/margin/core/secret_store.py`、`src/margin/api/routes/strategy.py`、`src/margin/api/routes/strategy_config.py`、`web/components/provider-settings-panel.tsx` |
| 08 | research_candidate_dashboard | 研究候选面板模块 | [08-research_candidate_dashboard.md](./08-research_candidate_dashboard.md) | `src/margin/dashboard/`、`src/margin/api/routes/dashboard.py`、`src/margin/api/routes/valuation_discovery.py`、`web/app/layout.tsx`、`web/app/page.tsx`、`web/app/dashboard/`、`web/app/settings/`、`web/components/company-pool-selector.tsx`、`web/components/dashboard-refresh-control.tsx`、`web/components/dashboard-refresh-node-graph.tsx`、`web/components/recommendation-chat-panel.tsx`、`web/components/current-vs-effective-panel.tsx`、`web/components/evidence-locator-list.tsx`、`web/components/metric-trend-chart.tsx`、`web/components/provider-settings-panel.tsx` |
| 10 | deployment_audit | 部署与审计模块 | [10-deployment_audit.md](./10-deployment_audit.md) | `src/margin/core/`（audit、snapshot、degradation、logging、metrics、run_states、orchestration、capacity、outbox）、`src/margin/api/middleware.py`、`src/margin/api/metrics.py`、`src/margin/api/routes/health.py`、`Dockerfile`、`web/Dockerfile`、`docker-compose.yml`、`.github/workflows/ci.yml`、`scripts/`（dev supervisor / migration / worker / smoke）、`docker/prometheus.yml`、`docker/grafana/` |
| 11 | valuation_discovery | 公司池与估值发现模块 | [11-valuation_discovery.md](./11-valuation_discovery.md) | `src/margin/valuation_discovery/`、`src/margin/api/routes/valuation_discovery.py`、`scripts/smoke_valuation_discovery_p0.py`、`scripts/smoke_valuation_discovery_p1.py` |

## 文档约定

- 每份模块文档均包含：模块概述、文件级摘要、公共类/函数说明、FastAPI 接口表、前端组件说明、跨模块依赖说明。
- 类方法与函数以 Markdown 表格形式列出签名、参数与返回值；签名优先保留源码中的类型注解。
- 若源码存在 docstring，文档直接引用；否则根据代码语义补充说明。
- 文档只描述公共接口与关键实现，不展开业务无关的内部细节。

## 如何使用

- **按模块查找**：直接打开对应编号 markdown 文件。
- **跨模块追踪**：每份文档末尾的「跨模块使用说明」列出本模块消费或提供的服务、Provider 与数据流。
- **与设计对照**：代码文档描述当前实现；产品目标与模块边界查看对应大版本的 `docs/design/<version>/`。

## v0.3 当前新增实现摘要

- `01-data_provider` 已新增 Tushare 独立源系统、量化 endpoint 准入目录、滚动采集策略、质量筛选层、warehouse publisher 和真实两年行情/财务/benchmark 回填脚本。
- `07-strategy_config` / `08-research_candidate_dashboard` 已支持用户在设置页切换默认公司池：中证500、全 A、沪深300；CSI300/CSI500 从 Tushare 指数成分生成真实成员版本，切换后滚动 active Research Scope。
- `08-research_candidate_dashboard` 详情页已从 quant profile、research context、AI delta review、news documents、effective assessment 和 warehouse PIT 趋势合并展示中文名、AI 延期原因、新闻证据、估值缺失状态和关键指标趋势图。
- `11-valuation_discovery` 已接入数据层公司池快照，并新增第四层 Quant Feature Mart + Analysis Mart；第三层 ETL 事务性发布 `quant_feature_snapshots/rows` 供量化只读，Feature Mart 从原始 `n_income_attr_p` 年度历史派生 `net_profit_y1/y2`，财务 freshness canary 使用 `roe_ttm`；停牌硬过滤优先使用 `suspend_d` 发布的 `is_suspended`，缺行情兜底只使用覆盖率达标的最新市场日期；量化结果再事务性发布为 `analysis_snapshots`、metrics、findings 和 lineage。最新全 A 真实量化 run `qr_ee2c66c6199f4a76` 使用 5304 家非 ST/非退市/非未来上市公司，输出 3 家 pass、55 家 near-threshold；2026-07-02 CSI300 端到端刷新 run `vdr_abcdbd61a870a9e1e8024343` 真实输入 300 家，输出 1 家 near-threshold。
- `06-multi_agent_research` 已注册 `analysis_snapshot_get`、`analysis_metrics_list`、`analysis_findings_list`、`quant_feature_snapshot_get`、`quant_feature_rows_list` 五个 scoped read tools；新增 `rag_evidence_retrieve`/`evidence_retrieve` RAG evidence 工具，向上给 Agent 返回可定位 `evidence_blocks`，并可冻结写入 EvidencePackage。
- `/settings/data` 与 `/api/v1/data-policies` 暴露近两年滚动窗口等数据采集策略配置。

## 更新说明

- `docs/code/` 不按产品版本建立子目录，始终描述当前仓库代码。
- 每次功能代码完成后，应在同一变更中更新本目录中的对应模块文档。
- 产品设计历史由 `docs/design/<version>/` 承担，代码实现历史由 Git 承担。
- 模块编号 02 与 09 保留用于历史审计；其实现已在 v0.2 中删除，因此没有当前代码文档。

---

*本索引描述当前源码状态；02 与 09 为历史编号，当前实现已删除。*
