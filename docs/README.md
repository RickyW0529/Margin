# Margin Documentation

Margin（安全边际）开源投资研究系统的文档集。文档按版本归档，便于审计与版本迭代。

## 目录结构

```
docs/
├── README.md                       本文件，总索引与目录格式约定
├── design/                         设计稿（产品 + 架构，中英双语）
│   └── v0.1/
│       ├── README.md               v0.1 设计稿变更说明与旧名映射
│       ├── product/                产品设计
│       └── architecture/           架构设计
├── spec/                           功能规格（按功能模块）
│   └── v0.1/
│       ├── README.md               v0.1 spec 总索引、模块清单与验收映射
│       └── NN-module/spec.md
└── plan/                           实施计划（按模块拆子任务）
    └── v0.1/
        ├── README.md               v0.1 plan 总索引、里程碑 Gantt 与编号规则
        └── NN-module/NNKK-task.md
```

## 版本演进表

| 版本 | 状态 | 设计稿 | spec | plan | 说明 |
|------|------|--------|------|------|------|
| v0.1 | 草案 | `design/v0.1/` | `spec/v0.1/` | `plan/v0.1/` | 首个完整版本，覆盖 10 个功能模块的完整闭环 |

> 后续版本（v0.2、v0.3…）按同样结构在 `design/`、`spec/`、`plan/` 下新建版本目录。版本号同时表示文档版本与产品版本。

## v0.1 设计稿

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
   - MCP
   - 模型网关与 Guardrail
6. 研究信号策略配置（Research Signal Strategy Configuration）
7. 研究候选面板（Research Candidate Dashboard）
8. 当前持仓面板（Current Holdings Dashboard）

所有图示使用 Mermaid 语法。

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
| 10 | deployment_audit | `spec/v0.1/10-deployment_audit/` | 3 |

合计 10 个 spec、35 个 plan 子任务。模块编号与子任务编号规则见仓库根 `AGENTS.md`。
