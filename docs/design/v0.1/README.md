# Margin v0.1 设计文档索引

本目录是 Margin v0.1 的产品与架构设计快照。当前版本已经从“计划文档”更新为“实现对齐文档”：文档描述以当前代码、迁移、Docker Compose、前端页面、API 路由、Provider 配置和测试结果为准。

## 1. 当前版本状态

| 项目 | 状态 |
| --- | --- |
| 产品版本 | v0.1 |
| 文档版本 | v0.1 |
| 设计状态 | active |
| 实现状态 | 10 个 v0.1 模块已打通 |
| 后端 | FastAPI + SQLAlchemy + PostgreSQL/pgvector + APScheduler |
| 前端 | Next.js App Router + TypeScript |
| 部署 | Docker Compose: postgres, migrate, seed, api, worker, web, prometheus, grafana |
| AI Provider | OpenAI-compatible LLM；OpenAI-compatible Embedding；可选 Rerank |
| 默认实测配置 | DeepSeek LLM + 智谱 Embedding-3 |

v0.1 的产品边界是本地优先、证据驱动、用户决策保留的个人投资研究系统。系统不自动下单、不保存券商密码、不输出无条件买卖指令；当行情、证据、引用或 Provider 质量不足时，默认降级为 `ABSTAINED` 或 `DATA_MISSING`。

## 2. 文件清单

| 语言 | 产品设计 | 架构设计 |
| --- | --- | --- |
| 中文 | [Margin_产品设计_v0.1_中文.md](./product/Margin_产品设计_v0.1_中文.md) | [Margin_架构设计_v0.1_中文.md](./architecture/Margin_架构设计_v0.1_中文.md) |
| English | [Margin_Product_Design_v0.1_EN.md](./product/Margin_Product_Design_v0.1_EN.md) | [Margin_Architecture_Design_v0.1_EN.md](./architecture/Margin_Architecture_Design_v0.1_EN.md) |

相关文档：

- [功能规格索引](../../spec/v0.1/README.md)
- [实施计划索引](../../plan/v0.1/README.md)
- [开源社区项目文档](../../PROJECT_v0.1_OPEN_SOURCE.md)
- [协作约定](../../../AGENTS.md)

## 3. 与当前代码的对应关系

| 设计模块 | 当前代码/目录 | 当前交付 |
| --- | --- | --- |
| 01 数据 Provider | `src/margin/data/`, `src/margin/core/registry.py` | AKShare/Tushare Provider、字段标准化、质量检查、ProviderRegistry |
| 02 持仓 | `src/margin/portfolio/`, `src/margin/api/routes/portfolios.py` | 手工交易/CSV 导入、成本与持仓计算、组合概览、持仓详情 |
| 03 公告与 WebSearch | `src/margin/news/` | 交易所公告模型、raw snapshot、DocumentEvent、outbox、Tavily adapter、去重与合规边界 |
| 04 文本索引 | `src/margin/vector/` | parser/chunker、EmbeddingProvider、pgvector 持久化、混合检索、indexing runner |
| 05 RAG 证据 | `src/margin/evidence/` | Evidence/Claim 模型、locator、source level、claim validation、证据视图 |
| 06 多 Agent 研究 | `src/margin/research/` | ToolRegistry、LLM provider、研究 workflow、summary/reflect/citation/universe agent |
| 07 策略配置 | `src/margin/strategy/`, `src/margin/api/routes/strategy.py` | 策略模板、自定义策略、版本生命周期、prompt 合成与沙箱验证 |
| 08 研究候选面板 | `src/margin/dashboard/`, `web/app/research/` | research run、candidate card、证据/估值/审计/报告/导出、Provider status |
| 09 持仓监控 | `src/margin/holdings_monitoring/`, `web/app/positions/` | 持仓监控快照、P0-P3 alert、复盘记录、操作历史、行为指标 |
| 10 部署与审计 | `docker-compose.yml`, `src/margin/core/`, `src/margin/worker.py` | Docker 一键启动、migrate/seed、Worker、Prometheus/Grafana、不可变 audit、降级与健康检查 |

## 4. 图表清单

架构设计文档中的 Mermaid 图均为文本形式，便于 GitHub 渲染、代码审查和版本 diff。

| 图 | 所在文档 | 用途 |
| --- | --- | --- |
| 产品闭环图 | 产品设计 | 说明用户从数据导入、研究、候选、持仓到复盘的闭环 |
| 页面信息架构图 | 产品设计 | 说明首页、组合、持仓详情、研究首页、研究详情的页面关系 |
| 整体架构图 | 架构设计 | 展示 web/api/worker/db/provider/observability 的端到端关系 |
| 分层架构图 | 架构设计 | 展示 10 个模块与横切能力的分层边界 |
| 部署拓扑图 | 架构设计 | 展示 Docker Compose 服务依赖 |
| 研究数据流图 | 架构设计 | 展示 DocumentEvent → 索引 → 检索 → Agent → Dashboard → Audit |
| 数据设计图 | 架构设计 | 展示主要数据域与数据生命周期 |
| ER 图 | 架构设计 | 展示 29 张 public tables 的核心关系 |

## 5. v0.1 不做什么

为避免误开发，v0.1 明确不包含：

- MCP Server、MCP Gateway 或自定义第三方工具运行时；
- 用户自定义 HTTP 工具；
- 多产品共享工具平台；
- 自动下单或券商账户控制；
- 多租户权限系统；
- 云端托管平台；
- 研报全文分发或绕过付费墙抓取。

工具能力统一通过内部 `ToolRegistry`、类型化 Provider Adapter、固定权限等级和审计记录接入。后续如进入 v0.2/v0.3，再按新版本目录新增设计文档，不回写 v0.1 的边界。

## 6. 当前外部凭据要求

| 配置 | 必需性 | 说明 |
| --- | --- | --- |
| `MARGIN_LLM_API_KEY` | 研究链路需要 | OpenAI-compatible chat completions，例如 DeepSeek |
| `MARGIN_EMBEDDING_API_KEY` | 持久化索引需要 | OpenAI-compatible embeddings，例如智谱 Embedding-3 |
| `MARGIN_WEBSEARCH_API_KEY` | 可选 | Tavily WebSearch；缺失时 WebSearch 工具降级 |
| `MARGIN_SECRET_TUSHARE_TOKEN` | 可选 | Tushare 数据补充；缺失时 AKShare 和本地数据仍可运行 |
| `MARGIN_RERANK_API_KEY` | 可选 | Rerank Provider；缺失时使用基础混合召回排序 |

所有密钥只允许进入本地 `.env` 或运行环境变量，不能提交到 Git。

## 7. 变更说明

- 2026-06-19：将 v0.1 设计文档更新为当前实现快照，补齐部署、监控、审计、Dashboard、持仓监控和数据库 ER 图。
- 2026-06-19：删除 v0.1 中 MCP Server / MCP Gateway / 自定义 HTTP 工具误导描述，统一为内部工具注册、工具仓库和权限模式。
- 2026-06-19：根 README 与开源社区文档同步为当前 v0.1 状态。
