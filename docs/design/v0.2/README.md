# Margin v0.2 设计文档索引

本目录是 Margin v0.2 的产品与架构设计快照。它由 `design/v0.1/` 直接复制后增量迭代：保留 v0.1 已实现架构作为基线，只在 v0.2 文档中增加公司池、量化闸门、行业估值、事件驱动 AI 研究和用户配置边界。

## 1. 当前版本状态

| 项目 | 状态 |
| --- | --- |
| 产品版本 | v0.2 |
| 文档版本 | v0.2 |
| 设计状态 | draft |
| 实现状态 | 尚未实现；当前代码仍为 v0.1 基线 |
| 后端 | FastAPI + SQLAlchemy + PostgreSQL/pgvector + APScheduler |
| 前端 | Next.js App Router + TypeScript |
| 部署 | Docker Compose: postgres, migrate, seed, api, worker, web, prometheus, grafana |
| AI Provider | OpenAI-compatible LLM；OpenAI-compatible Embedding；可选 Tavily WebSearch；可选 Rerank |
| 默认实测配置 | DeepSeek LLM + 智谱 Embedding-3；Tavily/Rerank 缺配置时显式 degraded |

v0.2 的核心变化是把产品入口从“用户输入证券代码后研究”改为“系统动态加载公司池并持续维护内在价值判断”。第一期公司池为动态沪深 300；全部公司都展示，先经过确定性量化闸门，再对通过闸门或发生实质信息变化的公司运行 AI 深度研究。

## 2. 文件清单

| 语言 | 产品设计 | 架构设计 |
| --- | --- | --- |
| 中文 | [Margin_产品设计_v0.2_中文.md](./product/Margin_产品设计_v0.2_中文.md) | [Margin_架构设计_v0.2_中文.md](./architecture/Margin_架构设计_v0.2_中文.md) |
| English | [Margin_Product_Design_v0.2_EN.md](./product/Margin_Product_Design_v0.2_EN.md) | [Margin_Architecture_Design_v0.2_EN.md](./architecture/Margin_Architecture_Design_v0.2_EN.md) |

相关文档：

- [当前代码说明](../../code/README.md)
- [协作约定](../../../AGENTS.md)

本目录只描述 v0.2 产品大版本设计。设计确认后的模块 spec 与详细 plan 由 Superpowers 写入被 Git 忽略的 `docs/superpowers/`，不属于正式项目文档。

## 3. v0.2 增量范围

| 增量 | v0.2 设计 |
| --- | --- |
| 研究入口 | 用户不再必须输入证券代码；系统动态加载公司池 |
| 首期公司池 | 沪深 300 当前成分股，保存成分股时点快照；后续扩展中证 500、行业池、全 A |
| 量化层 | 全部公司计算估值、质量、风险和数据完整度；明显不合适者停止在量化层，但仍展示原因 |
| AI 层 | 仅对量化通过或出现实质信息变化的公司深度分析；无变化时复用上次 AI 结论 |
| 更新模式 | 每日增量同步价格、财务、公告和新闻；新财报、重大公告、实质新闻、行业变化或复核到期触发 AI 更新 |
| 估值输出 | 内在价值区间、估值置信区间、低估置信度、价值陷阱风险、观察价格区间、持有周期、失效条件 |
| 用户配置 | Provider、公司池、量化闸门、AI 投资风格 Prompt |
| 系统管理 | 证据护栏、结构化输出 Schema、行业估值模型、Agent 编排、工具权限 |
| 新模块 | `11-valuation_discovery`：公司池快照、量化闸门、行业估值模型、估值快照和刷新事件 |

## 4. 与当前代码的对应关系

| 设计模块 | 当前代码/目录 | 当前交付 |
| --- | --- | --- |
| 01 数据 Provider | `src/margin/data/`, `src/margin/core/registry.py` | AKShare/Tushare Provider、字段标准化、质量检查、ProviderRegistry |
| 02 持仓 | `src/margin/portfolio/`, `src/margin/api/routes/portfolios.py` | 手工交易/CSV 导入、成本与持仓计算、组合概览、持仓详情 |
| 03 公告与 WebSearch | `src/margin/news/` | 交易所公告模型、raw snapshot、DocumentEvent、outbox、Tavily adapter、去重与合规边界 |
| 04 文本索引 | `src/margin/vector/` | parser/chunker、EmbeddingProvider、pgvector 持久化、混合检索、indexing runner |
| 05 RAG 证据 | `src/margin/evidence/` | Evidence/Claim 模型、locator、source level、claim validation、证据视图 |
| 06 多 Agent 研究 | `src/margin/research/` | ToolRegistry、LLM provider、研究 workflow、summary/reflect/citation/universe agent；Signal Composer 正常路径优先 LLM，硬性降级与 LLM 失败时使用规则 |
| 07 策略配置 | `src/margin/strategy/`, `src/margin/api/routes/strategy.py` | 策略模板、自定义策略、版本生命周期、prompt 合成与沙箱验证 |
| 08 研究候选面板 | `src/margin/dashboard/`, `web/app/research/` | research run、candidate card、证据/估值/审计/报告/导出、真实 Provider status |
| 09 持仓监控 | `src/margin/holdings_monitoring/`, `web/app/positions/` | 持仓监控快照、P0-P3 alert、复盘记录、操作历史、行为指标 |
| 10 部署与审计 | `docker-compose.yml`, `src/margin/core/`, `src/margin/worker.py` | Docker 一键启动、migrate/seed、Worker、Prometheus/Grafana、不可变 audit、降级与健康检查 |
| 11 公司池与估值发现 | 待新增 | v0.2 设计范围，尚未实现 |

## 5. 图表清单

架构设计文档中的 Mermaid 图均为文本形式，便于 GitHub 渲染、代码审查和版本 diff。

| 图 | 所在文档 | 用途 |
| --- | --- | --- |
| 产品闭环图 | 产品设计 | 说明用户从数据导入、研究、候选、持仓到复盘的闭环 |
| 页面信息架构图 | 产品设计 | 说明首页、组合、持仓详情、研究首页、研究详情的页面关系 |
| 整体架构图 | 架构设计 | 展示 web/api/worker/db/provider/observability 的端到端关系 |
| 分层架构图 | 架构设计 | 展示 v0.1 的 10 个基线模块、v0.2 新增模块 11 与横切能力边界 |
| 部署拓扑图 | 架构设计 | 展示 Docker Compose 服务依赖 |
| 研究数据流图 | 架构设计 | 展示 DocumentEvent → 索引 → 检索 → Agent → Dashboard → Audit |
| 数据设计图 | 架构设计 | 展示主要数据域与数据生命周期 |
| ER 图 | 架构设计 | 展示 29 张 public tables 的核心关系 |

## 6. v0.2 不做什么

为避免误开发，v0.2 明确不包含：

- MCP Server、MCP Gateway 或自定义第三方工具运行时；
- 用户自定义 HTTP 工具；
- 多产品共享工具平台；
- 自动下单或券商账户控制；
- 多租户权限系统；
- 云端托管平台；
- 研报全文分发或绕过付费墙抓取。

工具能力统一通过内部 `ToolRegistry`、类型化 Provider Adapter、固定权限等级和审计记录接入。后续 v0.3 继续从本目录复制并增量迭代，不回写 v0.2 的审计边界。

## 7. 当前外部凭据要求

| 配置 | 必需性 | 说明 |
| --- | --- | --- |
| `MARGIN_LLM_API_KEY` | 研究链路需要 | OpenAI-compatible chat completions，例如 DeepSeek |
| `MARGIN_EMBEDDING_API_KEY` | 持久化索引需要 | OpenAI-compatible embeddings，例如智谱 Embedding-3 |
| `MARGIN_WEBSEARCH_API_KEY` | 可选 | Tavily WebSearch；缺失时 WebSearch 工具降级 |
| `MARGIN_SECRET_TUSHARE_TOKEN` | 可选 | Tushare 数据补充；缺失时 AKShare 和本地数据仍可运行 |
| `MARGIN_RERANK_API_KEY` | 可选 | Rerank Provider；缺失时使用基础混合召回排序 |

所有密钥只允许进入本地 `.env` 或运行环境变量，不能提交到 Git。

`GET /api/v1/provider-status` 当前展示 `openai_llm`、`openai_embedding`、`tavily_websearch`、`http_rerank` 四类状态。LLM 与 Embedding 有配置时执行真实远端 healthcheck；Tavily / Rerank 未配置时返回 `degraded`，不会被静默隐藏。

## 8. 当前已知产品/实现边界

- v0.1 的 `risk_review` 与 `reflect_counter_argument` 已使用 LLM 输出结构化风险、反方理由与未知项，但不强制每条风险/反方理由绑定证据引用；逐条 evidence-grounded risk/reflect 属于 v0.2。
- v0.1 的 `signal_composer` 正常路径优先 LLM 生成结构化研究信号；当行情退化、组合约束违规、引用校验失败或 LLM 失败时，系统使用规则型保守输出或 `ABSTAINED`。
- v0.1 前端支持查看 Provider 状态和触发研究运行；Provider 配置 UI、公司池和量化闸门配置属于 v0.2。

## 9. 变更说明

- 2026-06-20：由 v0.1 设计直接复制建立 v0.2；新增动态沪深 300 公司池、量化闸门、行业估值、事件驱动 AI 更新与四类用户配置边界。
- 2026-06-20：同步最新代码状态：Provider status 改为真实探测 LLM/Embedding 并显式展示 Tavily/Rerank degraded；Signal Composer 正常路径优先 LLM；risk/reflect 逐条证据约束列入 v0.2。
- 2026-06-19：继承 v0.1 已实现设计基线，包括部署、监控、审计、Dashboard、持仓监控和数据库 ER 图。
- 2026-06-19：继承 v0.1 的内部工具注册、工具仓库和权限模式，不引入 MCP Server / MCP Gateway / 自定义 HTTP 工具。
