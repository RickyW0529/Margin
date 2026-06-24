# Margin Documentation

Margin（安全边际）开源投资研究系统的正式文档仅分为设计文档和代码文档。

## 目录结构

```
docs/
├── README.md                       本文件，总索引与目录格式约定
├── design/                         设计稿（产品 + 架构，中英双语）
│   ├── v0.1/                       已实现版本设计快照
│   ├── v0.2/
│   └── v0.3/
│       ├── README.md               v0.3 增量设计索引
│       ├── product/                产品设计
│       └── architecture/           架构设计
└── code/                           当前代码说明（不按版本归档）
    ├── README.md                   当前代码说明总索引（中文）
    ├── en/                         English code documentation
    │   └── README.md               Current code docs index
    └── NN-module.md                模块函数级说明
```

## 版本演进表

| 产品大版本 | 状态 | 设计稿 | 说明 |
|------|------|--------|------|
| v0.1 | 已实现 / 历史快照 | `design/v0.1/` | 首个完整版本设计，包含旧持仓/组合边界，仅作历史审计 |
| v0.2 | 历史实现快照 | `design/v0.2/` | 公司池、数据仓库、量化闸门、新闻/RAG、AI delta review、估值发现与研究候选面板 |
| v0.3 | 当前实现 | `design/v0.3/` | Tushare 独立源系统、量化需求闭包、质量筛选、统一仓库、非 ST/非退市公司池、Analysis Mart 第四层和真实量化/分析输出 |

> `design/` 只随产品大版本更新；`code/` 不分版本，每次功能代码完成后同步更新，始终表示当前最新实现。

## v0.3 设计稿

- 设计索引：`design/v0.3/README.md`
- 中文产品设计：`design/v0.3/product/Margin_产品设计_v0.3_中文.md`
- 中文架构设计：`design/v0.3/architecture/Margin_架构设计_v0.3_中文.md`
- English Product Design：`design/v0.3/product/Margin_Product_Design_v0.3_EN.md`
- English Architecture Design：`design/v0.3/architecture/Margin_Architecture_Design_v0.3_EN.md`

## v0.2 设计稿

- 设计索引：`design/v0.2/README.md`
- 中文产品设计：`design/v0.2/product/Margin_产品设计_v0.2_中文.md`
- 中文架构设计：`design/v0.2/architecture/Margin_架构设计_v0.2_中文.md`
- English Product Design：`design/v0.2/product/Margin_Product_Design_v0.2_EN.md`
- English Architecture Design：`design/v0.2/architecture/Margin_Architecture_Design_v0.2_EN.md`

## v0.1 设计稿

- 设计索引：`design/v0.1/README.md`

### 中文
- 产品设计：`design/v0.1/product/Margin_产品设计_v0.1_中文.md`
- 架构设计：`design/v0.1/architecture/Margin_架构设计_v0.1_中文.md`

### English
- Product Design：`design/v0.1/product/Margin_Product_Design_v0.1_EN.md`
- Architecture Design：`design/v0.1/architecture/Margin_Architecture_Design_v0.1_EN.md`

## v0.3 当前架构

v0.3 将数据链路明确为：

`Tushare / AKShare / future source systems -> quality screening -> unified warehouse -> canonical/company-pool/quant-input serving -> Analysis Mart -> upper services`

当前已打通 Tushare 主链路：独立 `source_tushare` schema、endpoint 专用 landing 表、量化需求 endpoint 目录、质量决策表、统一 warehouse publication、非 ST/非退市/非未来上市公司池快照，以及公司池到 QuantInputSnapshot、量化结果和 Analysis Mart 第四层分析结果的真实落库。AKShare 已建立独立 `source_akshare` schema 与 endpoint landing 表骨架；当前环境 AKShare 外部代理不可控时不阻断 Tushare 验收。

Analysis Mart 第四层由 `analysis_snapshots`、`analysis_metrics`、`analysis_findings` 与 `analysis_evidence_links` 组成，从第三层 canonical/company-pool/quant-input 与量化结果派生，向 Dashboard 和 LangGraph scoped read tools 提供可复用的数据分析摘要、指标、发现与 lineage。

滚动窗口默认近 24 个月，可通过 `/settings/data` 前端页面和 `/api/v1/data-policies` API 配置；只采集能回链量化需求的数据，排除龙虎榜、大宗交易、pledge detail 等无当前消费方数据，避免数据库膨胀。

## v0.2 架构基线

产品与架构围绕以下层组织：

1. 数据层（Data Layer）
2. 数据存储层（Data Storage Layer）
3. 新闻 / WebSearch 获取层（News / WebSearch Acquisition Layer）
4. 文本向量数据库（Text Vector Database）
5. AI 层（AI Layer）
   - Provider 接入层
   - RAG 证据系统
   - Scoped 只读工具系统
   - LangGraph delta review 编排
   - 模型路由
   - 模型网关与 Guardrail
6. 研究信号策略配置（Research Signal Strategy Configuration）
7. 公司池与估值发现（Universe & Valuation Discovery）
8. 研究候选面板（Research Candidate Dashboard）

所有图示使用 Mermaid 语法。

## v0.2 当前实现栈

| 层 | 当前实现 |
|----|----------|
| 前端 | Next.js App Router + TypeScript |
| API | FastAPI + Pydantic + SQLAlchemy |
| 数据库 | PostgreSQL + pgvector + Alembic |
| 后台任务 | APScheduler Worker |
| AI Provider | OpenAI-compatible LLM、OpenAI-compatible Embedding、可选 Rerank |
| 数据 Provider | AKShare、Tushare、Tavily WebSearch、OpenAI-compatible LLM/Embedding/Rerank |
| 可观测 | Prometheus `/metrics`、Grafana dashboard、结构化日志、trace id |
| 部署 | Docker Compose：postgres、migrate、bootstrap、api、worker、web、prometheus、grafana |

v0.2 明确不实现 MCP Server、MCP Gateway、自定义 HTTP 工具、自动下单、券商账户控制、持仓管理和多租户 SaaS。AI 工具通过 `ScopedToolFactory`、`ToolPolicyEngine`、`ToolExecutor`、类型化 Provider Adapter、权限版本和审计记录接入。

当前 `/api/v1/provider-status` 会真实探测已配置 Provider，并显式展示缺配置或外部不可达时的 degraded/unhealthy 状态；依赖 inactive/unhealthy Provider 的刷新入口会 fail-closed 为结构化 `service_not_configured`，不会返回 500 或伪装成功。v0.2 已删除 02/09 持仓相关实现；研究候选面板只展示公司池、量化/估值发现、RAG 证据与 AI delta review 结果。前端信息架构以研究工作台为入口：`/` 展示候选快照、推荐操作顺序和 Provider 状态，`/research` 承担候选筛选、刷新触发、Provider blocker 与只读 Copilot。

## 当前功能模块

| 编号 | 模块 | 当前代码文档 |
|------|------|--------------|
| 01 | data_provider | `code/01-data_provider.md` |
| 03 | filing_websearch | `code/03-filing_websearch.md` |
| 04 | text_indexing | `code/04-text_indexing.md` |
| 05 | rag_evidence | `code/05-rag_evidence.md` |
| 06 | multi_agent_research | `code/06-multi_agent_research.md` |
| 07 | strategy_config | `code/07-strategy_config.md` |
| 08 | research_candidate_dashboard | `code/08-research_candidate_dashboard.md` |
| 10 | deployment_audit | `code/10-deployment_audit.md` |
| 11 | valuation_discovery | `code/11-valuation_discovery.md` |

## 当前功能代码说明

已按功能模块生成完整函数级代码说明，包含公共类/函数签名、FastAPI 接口、前端组件与跨模块依赖：

- 中文总索引：`code/README.md`
- 英文总索引：`code/en/README.md`
- 共享与核心横切组件：`code/00-shared.md` / `code/en/00-shared.md`
- 当前功能模块见 `code/README.md`；02 与 09 仅保留历史编号，v0.2 已删除其实现。

代码说明随每次功能实现直接更新，不保留版本副本。产品设计历史以 `design/` 为准，代码历史以 Git 为准。
