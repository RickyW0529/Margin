# Margin Documentation

Margin（安全边际）开源投资研究系统的正式文档仅分为设计文档和代码文档。

## 目录结构

```
docs/
├── README.md                       本文件，总索引与目录格式约定
├── design/                         设计稿（产品 + 架构，中英双语）
│   ├── v0.1/                       已实现版本设计快照
│   └── v0.2/
│       ├── README.md               v0.2 增量设计索引
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
| v0.1 | 已实现 | `design/v0.1/` | 首个完整版本，覆盖 10 个功能模块的本地闭环 |
| v0.2 | 设计中 | `design/v0.2/` | 从 v0.1 设计增量迭代公司池、量化闸门、行业估值与事件驱动 AI 研究 |

> `design/` 只随产品大版本更新；`code/` 不分版本，每次功能代码完成后同步更新，始终表示当前最新实现。

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

## v0.1 八层架构

产品与架构围绕八层组织：

1. 数据层（Data Layer）
2. 数据存储层（Data Storage Layer）
3. 新闻 / WebSearch 获取层（News / WebSearch Acquisition Layer）
4. 文本向量数据库（Text Vector Database）
5. AI 层（AI Layer）
   - Provider 接入层
   - RAG 证据系统
   - 工具系统
   - 多 Agent 编排
   - 模型路由
   - 模型网关与 Guardrail
6. 研究信号策略配置（Research Signal Strategy Configuration）
7. 研究候选面板（Research Candidate Dashboard）
8. 当前持仓面板（Current Holdings Dashboard）

所有图示使用 Mermaid 语法。

## v0.1 当前实现栈

| 层 | 当前实现 |
|----|----------|
| 前端 | Next.js App Router + TypeScript |
| API | FastAPI + Pydantic + SQLAlchemy |
| 数据库 | PostgreSQL + pgvector + Alembic |
| 后台任务 | APScheduler Worker |
| AI Provider | OpenAI-compatible LLM、OpenAI-compatible Embedding、可选 Rerank |
| 数据 Provider | AKShare、可选 Tushare、可选 Tavily WebSearch |
| 可观测 | Prometheus `/metrics`、Grafana dashboard、结构化日志、trace id |
| 部署 | Docker Compose：postgres、migrate、seed、api、worker、web、prometheus、grafana |

v0.1 明确不实现 MCP Server、MCP Gateway、自定义 HTTP 工具、自动下单、券商账户控制和多租户 SaaS。AI 工具统一通过内部 `ToolRegistry`、类型化 Provider Adapter、权限等级和审计记录接入。

当前 `/api/v1/provider-status` 会真实探测已配置的 LLM / Embedding，并显式展示 Tavily WebSearch / Rerank 缺配置时的 `degraded` 状态。v0.1 的 `risk_review` / `reflect_counter_argument` 是结构化 LLM 输出，但不强制逐条绑定证据引用；该能力列入 v0.2。

## 当前功能模块

| 编号 | 模块 | 当前代码文档 |
|------|------|--------------|
| 01 | data_provider | `code/01-data_provider.md` |
| 02 | holdings | `code/02-holdings.md` |
| 03 | filing_websearch | `code/03-filing_websearch.md` |
| 04 | text_indexing | `code/04-text_indexing.md` |
| 05 | rag_evidence | `code/05-rag_evidence.md` |
| 06 | multi_agent_research | `code/06-multi_agent_research.md` |
| 07 | strategy_config | `code/07-strategy_config.md` |
| 08 | research_candidate_dashboard | `code/08-research_candidate_dashboard.md` |
| 09 | holdings_monitoring | `code/09-holdings_monitoring.md` |
| 10 | deployment_audit | `code/10-deployment_audit.md` |

## 当前功能代码说明

已按功能模块生成完整函数级代码说明，包含公共类/函数签名、FastAPI 接口、前端组件与跨模块依赖：

- 中文总索引：`code/README.md`
- 英文总索引：`code/en/README.md`
- 共享与核心横切组件：`code/00-shared.md` / `code/en/00-shared.md`
- 当前功能模块：`code/01-data_provider.md` ~ `code/10-deployment_audit.md`，英文版在 `code/en/`

代码说明随每次功能实现直接更新，不保留版本副本。产品设计历史以 `design/` 为准，代码历史以 Git 为准。
