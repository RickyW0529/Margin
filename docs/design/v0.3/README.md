# Margin v0.3 设计文档索引

本目录是 Margin v0.3 的产品与架构设计快照。它由 `design/v0.2/` 直接复制后增量迭代，完整保留 v0.2 审计基线。v0.3 的唯一主增量是把结构化数据链路重构为“独立数据源系统 → 质量筛选层 → 统一数据仓库层 → 公司池视图层 → 上层服务”，并以尽可能完整的 Tushare Pro 股票数据、非 ST 全 A 公司池和真实量化公司结果作为验收。

## 1. 当前版本状态

| 项目 | 状态 |
| --- | --- |
| 产品版本 | v0.3 |
| 文档版本 | v0.3 |
| 设计状态 | review |
| 上一版本基线 | v0.2 active |
| 本版本增量 | 独立数据源系统、质量筛选层、统一仓库、非 ST 公司池视图、真实量化产出 |
| 实现状态 | 开发中；当前源码仍以 v0.2 通用 Raw/Fact/Canonical 链路为基线 |
| 后端 | FastAPI + SQLAlchemy + PostgreSQL/pgvector + APScheduler |
| 前端 | Next.js App Router + TypeScript |
| 部署 | Docker Compose: postgres, migrate, bootstrap, api, worker, web, prometheus, grafana |
| AI Provider | OpenAI-compatible LLM；OpenAI-compatible Embedding；可选 Tavily WebSearch；可选 Rerank |
| 默认实测配置 | DeepSeek LLM + 智谱 Embedding-3；Tavily/Rerank 缺配置时显式 degraded |

v0.3 不改变 v0.2 已确认的研究与估值产品主线，只重做其数据底座。每个 Provider 是独立源系统；质量筛选层是进入统一仓库的唯一入口；公司池视图只能读取统一仓库；量化和其他上层服务只能读取公司池视图或仓库服务接口，禁止跨层直连。

## 2. 文件清单

| 语言 | 产品设计 | 架构设计 |
| --- | --- | --- |
| 中文 | [Margin_产品设计_v0.3_中文.md](./product/Margin_产品设计_v0.3_中文.md) | [Margin_架构设计_v0.3_中文.md](./architecture/Margin_架构设计_v0.3_中文.md) |
| English | [Margin_Product_Design_v0.3_EN.md](./product/Margin_Product_Design_v0.3_EN.md) | [Margin_Architecture_Design_v0.3_EN.md](./architecture/Margin_Architecture_Design_v0.3_EN.md) |

相关文档：

- [当前代码说明](../../code/README.md)
- [协作约定](../../../AGENTS.md)

本目录只描述 v0.3 产品大版本设计。设计确认后的模块 spec 与详细 plan 由 Superpowers 写入被 Git 忽略的 `docs/superpowers/`，不属于正式项目文档。

## 3. v0.3 增量范围

| 增量 | v0.3 设计 |
| --- | --- |
| 数据源系统层 | Tushare、AKShare 和未来 Provider 各自使用独立 schema、接口目录、运行/分片/调用审计、Raw Snapshot 与 endpoint 专用 landing 表 |
| 质量筛选层 | 独立执行 Schema、完整性、重复、PIT、范围、异常值、跨源冲突和发布判定；失败数据隔离但不删除 |
| 数据仓库层 | 保存统一证券维度、多源标准事实、专用市场/财务事实和 Canonical 服务值；只接收质量层发布 |
| 公司池视图层 | 从仓库生成双时态公司池快照；`ALL_A_NON_ST` 排除 ST/*ST、退市整理和非普通 A 股并保留原因 |
| 上层服务 | QuantInput、量化、估值、News/AI 和 Dashboard 只通过稳定仓库/公司池接口消费 |
| Tushare 覆盖 | 对量化需求相关 Pro 接口建立目录并真实探测当前席位，约 95% 置信度确认量化所需可用接口已基本穷尽 |
| 采集准入 | endpoint 必须回链 QuantFeatureSet、硬过滤、公司池、PIT/复权或 benchmark 需求；无量化消费方的数据禁止采集 |
| 滚动窗口 | 默认保留并服务最近 24 个月，可由前端在 12–60 个月范围内创建版本并激活；同步每日滚动推进 |
| 量化验收 | 使用真实非 ST 全 A 快照，持久化每家公司过滤/评分结果并输出具体公司、排名、分数和分析明细 |
| 降级边界 | AKShare 网络/代理失败不阻断 Tushare 主链路；未知接口保留审计状态，不伪装为成功 |

## 4. v0.3 设计决策

| 决策 | 结论 |
| --- | --- |
| 主入口 | `/research` 不再以手工输入 symbol 为主，而是以公司池研究面板为主 |
| 首期公司池 | 支持沪深 300、中证 500 和全 A；后续通过 `rule_code + rule_config` 增加公司池，不修改数据库 enum |
| 展示策略 | 全部公司展示：低估候选、AI 待研究、量化淘汰、数据不足都可见 |
| 底层采集范围 | 用户公司池和指标选择不裁剪采集任务；全部启用 endpoint 采用首次回填 + 增量游标 + 修订窗口回抓 |
| Endpoint 启用 | 由版本化 `QuantDataRequirementCatalog` 计算需求闭包，不因 Provider “能提供”就默认采集 |
| 数据窗口 | `DataAcquisitionPolicy` 默认 `rolling_window_months=24`，按运行 `decision_at` 计算窗口；前端只能提交服务端允许范围内的新版本 |
| Raw 存储 | Provider 完整响应压缩保存到本地 snapshot volume；PostgreSQL 保存 URI、hash、Schema 指纹和审计元数据 |
| 指标演进 | 源字段发现、标准指标目录和 Provider 映射均版本化；新增、缺失、类型变化、废弃和替代不删除历史 |
| 多源事实 | AKShare/Tushare 同一指标事实并存；Canonical 层记录候选、推荐值、冲突原因和 resolver version |
| 公司池历史 | `universe_memberships` 使用业务有效期 + 系统认知有效期的双时态拉链；快照表保留每次完整生成审计 |
| 数据事实来源 | 量化和 AI 只读研究作用域解析后的 canonical PIT 数据；Provider 和 Raw Snapshot 不直接服务业务判断 |
| 用户指标视图 | `ALL`、`INCLUDE`、`EXCLUDE` 只控制 Dashboard 和 AI 展示，不控制底层同步，也不能裁剪量化策略必需指标 |
| 量化输入快照 | 量化前冻结 `QuantInputSnapshot`；量化只消费该快照，AI 在量化/新闻后消费引用该快照的 `ResearchContext` |
| 量化实现边界 | 量化子包放在 `src/margin/valuation_discovery/quant/`；输入只来自 `QuantDataAdapter` 和数据仓库，不接 AKShare/Tushare、不读 Raw Snapshot |
| 因子体系 | Phase 1 使用 Quality 35%、Value 25%、Growth 15%、Momentum 15%、Risk 10%；行业内 winsorize/percentile rank，缺失字段降低 confidence |
| 量化输出 | 拆分 `screening_status`、`data_status`、`risk_flags`、`review_required`、`research_guardrail`，保存分数、原因、缺失字段、排名和摘要 |
| 回测范围 | 回测、绩效归因和报告导出属于 Phase 2，不阻塞 v0.3 主链路的单日截面筛选 |
| AI 调用策略 | 当日研究目标全部进入 NewsRefresh 队列，不按固定 top-N 截断；只有重要证据、首次研究或复核到期进入 LLM |
| 价格变化 | 普通价格变化只重算估值；观察区间触发可先搜新闻，只有发现重要证据才触发 AI |
| 启动同步 | API/Web 启动不等待外部 Provider；Provider 失败时使用最近有效快照并标记 stale/degraded |
| 手动兜底 | 前端保留“同步数据/重试同步”按钮，只创建后台同步任务，不阻塞页面 |
| 后端编排 | `valuation_refresh_runs` 表示端到端刷新，`valuation_refresh_steps` 表示阶段状态；失败、降级、重试和输出引用都写入业务表 |
| News 获取 | `NewsTargetSelector` 持久化当日完整研究目标；Provider 限流只影响批次/重试。官方公告全局增量采集，WebSearch 按目标定向执行 |
| 新闻/公告 | 公告和新闻先入 raw snapshot、`document_events`、公司关联、重要度评分、chunks/embedding 和 `news_context_bundles`，再进入 AI 上下文 |
| AI 增量复核 | 只有本轮数据/新闻检查完整才能零 LLM 写 `CARRY_FORWARD_VERIFIED`；失败时 `REVIEW_DEFERRED/ABSTAIN`，保留但标记上一版有效结论 stale |
| LangGraph 边界 | `AIDeltaReviewGraph` 只接受冻结的 `context_snapshot_id`；不编排公司池、量化、实时 WebSearch、抓取、持仓约束、数据同步或 Dashboard 发布 |
| LangGraph 路由 | `CARRY_FORWARD_FAST_PATH`、`DELTA_REVIEW`、`FULL_REVIEW`、`ABSTAIN`；模糊变化影响才调用 ChangeImpactClassifier |
| LangGraph 约束 | 四类分析并行；最多一次定向补证、一次引用修复；step/LLM/retrieval/repair 均有预算上限 |
| LangGraph 审计 | PostgreSQL checkpoint + `ai_graph_runs` / `ai_graph_node_runs`，记录节点哈希、模型/Prompt、token、工具调用、错误与恢复状态 |
| 节点反思 | 关键 LLM 节点先做确定性检查，再由 critic 输出 ACCEPT/REVISE/NEEDS_EVIDENCE/ABSTAIN；每节点最多一次反思和一次修订 |
| 工具工厂 | `ScopedToolFactory` 按节点、冻结作用域、策略版本和预算生成 ToolManifest；默认拒绝，模型看不到全局工具目录 |
| 工具权限 | capability + node grant + scope + PIT + budget + Schema 六层校验；实时 WebSearch、Provider、抓取和写工具不进入图 |
| 提示词工厂 | `PromptFactory` 版本化组合系统护栏、节点任务、用户风格、最小上下文、ToolManifest、输出 Schema 和预算；Draft/Reflection/Revision 分开版本化 |
| LLM 调用 | LangGraph 只编排；`LLMExecutionService + ModelRouter` 负责 bind scoped tools、结构化输出、幂等、重试、token/cost 和审计 |
| Prompt 开放 | 用户只配置投资风格 Prompt；系统 guardrail、证据要求、Schema 和工具权限不开放 |
| Provider 密钥 | 前端只写配置，本地 Secret Store 加密保存、永不回显、版本化轮换、日志脱敏并审计；主密钥通过环境注入 |
| 工具扩展 | v0.3 使用内部工具定义目录、ScopedToolFactory、ToolPolicyEngine 和 ToolExecutor，不做 MCP Server 或用户自定义工具 |
| 持仓分析 | v0.3 不实现；历史源码、API、页面、调度和数据库表已删除 |
| 置信度 | 低估置信度由系统校准，LLM 不能直接生成最终概率 |
| 交付拆分 | 设计确认后按功能模块拆 Superpowers 临时 spec/plan，不写正式 `docs/spec` / `docs/plan` |

## 5. P0 / P1 / P2 交付顺序

| 层级 | 交付边界 | 模块 |
| --- | --- | --- |
| P0 | 数据仓库、PIT、双时态公司池/行业、公司行动、QuantInputSnapshot、量化筛选、DB-backed 编排 | 01、07、10、11 |
| P1 | 完整目标 NewsRefresh、官方公告、文本索引、RAG 证据、ResearchContext、AIDeltaReviewGraph、工具/Prompt/反思 | 03、04、05、06、11 |
| P2 | 全公司 Dashboard、Provider Secret UI、安全/容量/恢复治理、完整 E2E/smoke 和文档收口 | 07、08、10、跨模块 |

必须先完成并验收全部模块 spec，再完成全部模块 plan，然后按 P0 → P1 → P2 和模块依赖逐个开发。单个模块完成测试、自我反思和 `docs/code/` 同步后才能进入下一模块。

## 6. v0.3 后续拆分建议

设计确认后，开发过程文档应按下列模块拆分到被 Git 忽略的 `docs/superpowers/`：

| 模块 | 临时 spec/plan 边界 |
| --- | --- |
| 01 data_provider | Provider Endpoint、全范围增量同步、完整 Raw Snapshot、字段发现、指标目录/映射、多源事实、Canonical、PIT/质量检查 |
| 03 filing_websearch | 面向量化目标公司的 NewsRefreshService、公告/新闻快照、公司关联、重要度判定、合规和事件去重 |
| 04 text_indexing | 公告/新闻内容快照、按内容 hash 解析分块、Embedding、PIT 安全幂等索引 |
| 05 rag_evidence | 估值假设、风险、反方理由的 evidence/claim 引用约束 |
| 06 multi_agent_research | 受控 `AIDeltaReviewGraph`、ScopedToolFactory、PromptFactory、节点反思、确定性 carry-forward、并行分析、有限补证/修复、checkpoint 和结构化 delta decision |
| 07 strategy_config | Provider、公司池、指标集、量化闸门、投资风格 Prompt 和研究作用域的版本化配置 |
| 08 research_candidate_dashboard | 全公司估值发现面板、状态筛选、淘汰原因、估值区间展示 |
| 10 deployment_audit | 启动 freshness 检查、每日增量任务、手动同步兜底、run/step 审计、重试、降级和指标 |
| 11 valuation_discovery | 双时态公司池、作用域解析、DB-backed Orchestrator、`valuation_discovery/quant` 多因子量化筛选、行业估值、置信度校准、ResearchContext、刷新事件和估值快照 |

## 7. 与当前代码的对应关系

v0.3 已删除 v0.1 的组合、持仓和持仓监控实现，包括源码、API、页面、Worker 调度与数据库表。模块编号 02/09 仅用于历史审计。

| 设计模块 | 当前代码/目录 | 当前交付 |
| --- | --- | --- |
| 01 数据 Provider | `src/margin/data/`, `src/margin/core/registry.py` | AKShare/Tushare Provider、字段标准化、质量检查、ProviderRegistry |
| 02 持仓 | 已删除 | 仅保留历史编号 |
| 03 公告与 WebSearch | `src/margin/news/` | 交易所公告模型、raw snapshot、DocumentEvent、outbox、Tavily adapter、去重与合规边界 |
| 04 文本索引 | `src/margin/vector/` | parser/chunker、EmbeddingProvider、pgvector 持久化、混合检索、indexing runner |
| 05 RAG 证据 | `src/margin/evidence/` | Evidence/Claim 模型、locator、source level、claim validation、证据视图 |
| 06 多 Agent 研究 | `src/margin/research/` | LangGraph AI delta review、ScopedToolFactory、PromptFactory、NodeExecutionRunner 反思、checkpoint、LLM/tool hash-only 审计和 delta review outbox |
| 07 策略配置 | `src/margin/strategy/`, `src/margin/api/routes/strategy.py` | 策略模板、自定义策略、版本生命周期、prompt 合成与沙箱验证 |
| 08 研究候选面板 | `src/margin/dashboard/`, `src/margin/api/routes/dashboard.py`, `web/app/research/`, `web/app/settings/` | 服务端分页候选列表、公司详情 current/effective 分离、证据 locator、只读 Copilot、Provider 状态和前端 Provider/scope/strategy 配置 |
| 09 持仓监控 | 已删除 | 仅保留历史编号 |
| 10 部署与审计 | `docker-compose.yml`, `src/margin/core/`, `src/margin/worker.py` | Docker 一键启动、migrate/bootstrap、Worker、Prometheus/Grafana、不可变 audit、降级与健康检查 |
| 11 公司池与估值发现 | `src/margin/valuation_discovery/`, `src/margin/api/routes/valuation_discovery.py`，量化子包为 `src/margin/valuation_discovery/quant` | DB-backed `ValuationDiscoveryOrchestrator`、Phase 1 多因子量化筛选、refresh run/step、effective assessment pointer 和发布链路 |

## 8. 图表清单

架构设计文档中的 Mermaid 图均为文本形式，便于 GitHub 渲染、代码审查和版本 diff。

| 图 | 所在文档 | 用途 |
| --- | --- | --- |
| 产品闭环图 | 产品设计 | 说明用户从公司池、量化闸门、NewsRefresh、AI 增量复核到估值发现面板的闭环 |
| 页面信息架构图 | 产品设计 | 说明首页、研究首页、公司详情、研究运行详情的页面关系 |
| 整体架构图 | 架构设计 | 展示 web/api/worker/db/provider/observability 的端到端关系 |
| 分层架构图 | 架构设计 | 展示 v0.1 的 10 个基线模块、v0.3 新增模块 11 与横切能力边界 |
| 部署拓扑图 | 架构设计 | 展示 Docker Compose 服务依赖 |
| 后端编排流程图 | 架构设计 | 展示 APScheduler trigger、DB-backed Orchestrator、NewsRefresh、LangGraph AI 内部图和 Dashboard 发布 |
| 研究数据流图 | 架构设计 | 展示量化目标 → NewsRefresh → DocumentEvent → 索引 → NewsContextBundle → AI DeltaReview → Audit |
| 数据设计图 | 架构设计 | 展示结构化数据、新闻快照、向量索引、研究上下文与复核记录的数据生命周期 |
| ER 图 | 架构设计 | 展示 v0.3 目标仓库关系和 v0.1 历史迁移审计表关系 |

## 9. v0.3 不做什么

为避免误开发，v0.3 明确不包含：

- MCP Server、MCP Gateway 或自定义第三方工具运行时；
- 用户自定义 HTTP 工具；
- 多产品共享工具平台；
- 自动下单或券商账户控制；
- 持仓分析、持仓监控、买入后 thesis 复盘；
- 多租户权限系统；
- 云端托管平台；
- 无边界全网新闻爬取；
- 研报全文分发或绕过付费墙抓取。

工具能力统一通过内部工具定义目录、`ScopedToolFactory`、`ToolPolicyEngine`、`ToolExecutor`、类型化 Provider Adapter、固定权限等级和审计记录接入。后续 v0.3 继续从本目录复制并增量迭代，不回写 v0.3 的审计边界。

## 10. 当前外部凭据要求

| 配置 | 必需性 | 说明 |
| --- | --- | --- |
| `MARGIN_LLM_API_KEY` | 研究链路需要 | OpenAI-compatible chat completions，例如 DeepSeek |
| `MARGIN_EMBEDDING_API_KEY` | 持久化索引需要 | OpenAI-compatible embeddings，例如智谱 Embedding-3 |
| `MARGIN_WEBSEARCH_API_KEY` | 可选 | Tavily WebSearch；缺失时 WebSearch 工具降级 |
| `MARGIN_TUSHARE_TOKEN` | 可选 | Tushare 数据补充；缺失时 AKShare 和本地数据仍可运行；`MARGIN_SECRET_TUSHARE_TOKEN` 仅作为旧 smoke fallback 兼容 |
| `MARGIN_RERANK_API_KEY` | 可选 | Rerank Provider；缺失时使用基础混合召回排序 |

v0.3 支持前端只写录入 Provider 密钥并保存到本地加密 Secret Store。环境变量只用于 Secret Store 主密钥、首次迁移和无 UI 运维预置；任何真实密钥都不能提交到 Git、写入文档或出现在日志/测试输出。

`GET /api/v1/provider-status` 当前展示 `openai_llm`、`openai_embedding`、`tavily_websearch`、`http_rerank` 四类状态。LLM 与 Embedding 有配置时执行真实远端 healthcheck；Tavily / Rerank 未配置时返回 `degraded`，不会被静默隐藏。

## 11. 当前已知产品/实现边界

- 当前 `risk_review`、`counter_argument`、`delta_decision` 均在冻结上下文和 evidence package 上运行；引用失败进入有限修复，仍失败则 ABSTAIN。
- 当前 AI 输出只产生 current review 与 effective assessment pointer，不输出 BUY/SELL，也不读取持仓约束。
- 当前前端支持 Provider 配置、scope/strategy 配置、valuation discovery refresh、研究候选列表、运行进度、公司详情与只读 Copilot。

## 12. 变更说明

- 2026-06-22：补充 LangGraph 节点执行基础设施：关键节点增加一次受控反思/修订；`ScopedToolFactory` 生成节点专属工具和权限 manifest；`PromptFactory` 生成版本化 Draft/Reflection/Revision Prompt；`LLMExecutionService` 统一模型路由、结构化输出、幂等、预算和审计。
- 2026-06-22：细化 `AIDeltaReviewGraph` 内部编排：确定性变化检测和零 LLM carry-forward 快路径；首次研究/实质变化/复核到期进入有限 LLM 路径；四类分析并行，最多一次补证和一次引用修复，并以 PostgreSQL checkpoint、`ai_graph_runs`、`ai_graph_node_runs` 支持恢复与审计。
- 2026-06-22：补充量化内部实现设计：`src/margin/valuation_discovery/quant/` 作为 Module 11 子包，Phase 1 做单日截面多因子筛选；明确 `QuantDataAdapter`、硬过滤、五大因子组、行业内标准化、状态/guardrail、`quant_screen_runs` 和 `quant_screen_results` 字段与约束。
- 2026-06-22：补充后端编排设计：APScheduler 只负责 trigger，`ValuationDiscoveryOrchestrator` 使用 `valuation_refresh_runs` 与 `valuation_refresh_steps` 作为 DB-backed 状态机，LangGraph 只用于 AI 内部 `AIDeltaReviewGraph`。
- 2026-06-22：补充量化目标驱动的 NewsRefresh 设计：量化通过、接近阈值、状态变化、复核到期或价格触发观察区间的公司进入 `news_refresh_targets`，由统一 `NewsRefreshService` 搜索、抓取和入库。
- 2026-06-22：补充新闻文本存储与 RAG 设计：新闻/公告先形成 raw snapshot、`document_events`、公司关联、重要度评分、内容 hash 分块、Embedding 和 `news_context_bundles`，低重要度内容可入库但默认不进主上下文。
- 2026-06-22：补充 AI 增量复核设计：AI 读取上一版有效结论、当前量化结果、当日重要新闻和 RAG 证据，检查完整时输出 `CARRY_FORWARD_VERIFIED`，检查失败时输出 `REVIEW_DEFERRED/ABSTAIN` 并保留有效结论。
- 2026-06-22：将数据层升级为“底层全量采集、上层逻辑作用域”：用户公司池和指标集不裁剪 Provider 同步，量化与 AI 只读取作用域内 canonical PIT 数据。
- 2026-06-22：补充字段级生产数据模型：Provider endpoint、完整 Raw Snapshot、源字段发现、标准指标目录/映射、多源事实、Canonical 推荐值、证券主数据和研究作用域。
- 2026-06-22：首期公司池扩展为沪深 300、中证 500 和全 A；成员采用业务时间 + 系统时间双时态拉链，同时保留每次生成快照。
- 2026-06-22：指标集支持 `ALL`、`INCLUDE`、`EXCLUDE`；新增、失效、类型变化和替代指标通过版本化目录与映射处理。
- 2026-06-20：补充数据自动同步策略：启动 freshness 检查、过期后台增量同步、Provider 失败不阻断启动、前端手动同步兜底。
- 2026-06-20：明确数据 Provider 模式为“采集入库优先”：Provider 只负责 raw snapshot、标准化、PIT/质量检查和入库；量化读库，AI 读 `ResearchContext` 与 RAG 证据。
- 2026-06-20：补充 v0.3 设计决策和后续按功能模块拆 Superpowers 临时 spec/plan 的边界。
- 2026-06-23：删除持仓分析/持仓监控的源码、API、页面、调度与数据库表，本版本只保留公司池估值发现主线。
- 2026-06-20：由 v0.1 设计直接复制建立 v0.3；新增动态沪深 300 公司池、量化闸门、行业估值、事件驱动 AI 更新与四类用户配置边界。
- 2026-06-20：同步最新代码状态：Provider status 改为真实探测 LLM/Embedding 并显式展示 Tavily/Rerank degraded；Signal Composer 正常路径优先 LLM；risk/reflect 逐条证据约束列入 v0.3。
- 2026-06-19：继承 v0.1 已实现设计基线，包括部署、监控、审计、Dashboard 和数据库 ER 图。
- 2026-06-19：继承 v0.1 的内部工具注册、工具仓库和权限模式，不引入 MCP Server / MCP Gateway / 自定义 HTTP 工具。
