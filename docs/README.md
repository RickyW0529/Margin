# Margin Documentation

Margin（安全边际）开源投资研究系统的文档集。文档按版本归档，便于审计与版本迭代。

## 目录结构

```
docs/
├── README.md                       本文件，总索引与目录格式约定
├── PROJECT_v0.1_OPEN_SOURCE.md     面向开源社区的 v0.1 项目文档
├── design/                         设计稿（产品 + 架构，中英双语）
│   └── v0.1/
│       ├── README.md               v0.1 当前设计索引、图表清单与实现映射
│       ├── product/                产品设计
│       └── architecture/           架构设计
├── spec/                           功能规格（按功能模块）
│   └── v0.1/
│       ├── README.md               v0.1 spec 总索引、模块清单与验收映射
│       └── NN-module/spec.md
├── plan/                           实施计划（按模块拆子任务）
│   └── v0.1/
│       ├── README.md               v0.1 plan 总索引、里程碑 Gantt 与编号规则
│       └── NN-module/NNKK-task.md
└── code/                           功能代码说明（按模块整理）
    └── v0.1/
        ├── README.md               v0.1 代码说明总索引（中文）
        ├── en/                     English code documentation
        │   └── README.md           v0.1 code docs index (English)
        └── NN-module.md            模块函数级说明
```

## 版本演进表

| 版本 | 状态 | 设计稿 | spec | plan | code 说明 | 说明 |
|------|------|--------|------|------|-----------|------|
| v0.1 | 已实现 | `design/v0.1/` | `spec/v0.1/` | `plan/v0.1/` | `code/v0.1/` | 首个完整版本，覆盖 10 个功能模块的本地闭环；支持 Docker Compose、PostgreSQL/pgvector、FastAPI、Next.js、Worker、Prometheus/Grafana |

> 后续版本（v0.2、v0.3…）按同样结构在 `design/`、`spec/`、`plan/`、`code/` 下新建版本目录。版本号同时表示文档版本与产品版本。旧版本目录保留，不删除。

## v0.1 设计稿

- 设计索引：`design/v0.1/README.md`
- 开源社区项目文档：`PROJECT_v0.1_OPEN_SOURCE.md`

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

## v0.1 功能模块（来自产品设计 §13.2）

| 编号 | 模块 | spec 路径 | plan 子任务数 |
|------|------|-----------|----------------|
| 01 | data_provider | `spec/v0.1/01-data_provider/` | 4 |
| 02 | holdings | `spec/v0.1/02-holdings/` | 3 |
| 03 | filing_websearch | `spec/v0.1/03-filing_websearch/` | 3 |
| 04 | text_indexing | `spec/v0.1/04-text_indexing/` | 3 |
| 05 | rag_evidence | `spec/v0.1/05-rag_evidence/` | 3 |
| 06 | multi_agent_research | `spec/v0.1/06-multi_agent_research/` | 6 |
| 07 | strategy_config | `spec/v0.1/07-strategy_config/` | 3 |
| 08 | research_candidate_dashboard | `spec/v0.1/08-research_candidate_dashboard/` | 3 |
| 09 | holdings_monitoring | `spec/v0.1/09-holdings_monitoring/` | 3 |
| 10 | deployment_audit | `spec/v0.1/10-deployment_audit/` | 4 |

合计 10 个 spec、35 个 plan 子任务。模块编号与子任务编号规则见仓库根 `AGENTS.md`。

## v0.1 功能代码说明

已按功能模块生成完整函数级代码说明，包含公共类/函数签名、FastAPI 接口、前端组件与跨模块依赖：

- 中文总索引：`code/v0.1/README.md`
- 英文总索引：`code/v0.1/en/README.md`
- 共享与核心横切组件：`code/v0.1/00-shared.md` / `code/v0.1/en/00-shared.md`
- 10 个功能模块：`code/v0.1/01-data_provider.md` ~ `code/v0.1/10-deployment_audit.md`，英文版在 `code/v0.1/en/`

代码说明与 `spec/`、`plan/` 一一对应，便于从实现回溯到需求规格与实施计划。
