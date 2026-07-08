# 08-research_candidate_dashboard 模块文档

本文件描述当前仓库中的研究候选面板实现。v0.2 已删除持仓/交易相关页面，以及 v0.1 同步 research run、候选卡片、首页摘要、证据/估值/report/export 独立端点；当前 Dashboard 是一个只读为主的用户入口，默认把 Provider、Scope、BFF、run 等底层概念收进后端和设置页，面向用户展示问答、今日推荐、证据理由与置信度。

## 1. 模块职责

`08-research_candidate_dashboard` 负责把后端已经落库的候选公司与研究复核结果整理为前端可用的页面数据。

当前职责：

- 服务端分页查询今日推荐可见候选列表；
- 在 `/dashboard/items/[itemId]` 子页展示单个公司的 current review、effective assessment、量化可视化和 RAG 证据；
- 展示量化分数、风险标记、证据 locator 与版本信息；
- 提供问答首页入口；实际问答请求经 `06-multi_agent_research` 的 MainAgent API 路由到数据分析师专家 agent；
- 提供今日推荐大屏，展示推荐股票、推荐理由、置信度、量化评分、估值折价和风险提示；
- 在今日推荐大屏提供“一键刷新今日研究”，使用默认 `scope-current` 与当前时间启动 valuation discovery，API 接受后会 best-effort 唤醒一次 worker，并用 React Flow 弹出最近一次刷新节点图，实时展示已完成/运行中/排队中/未开始/失败状态；最近一次 run 非终态时禁用再次刷新，避免重复入队；
- 最新量化 run 完成后先发布 dashboard projection，今日推荐页无需等待耗时 AI 复核；同一决策时间下按 `created_at`、`item_count`、`run_id` 稳定选择更新且更完整的投影，避免旧单票 run 遮挡新全市场结果。
- dashboard item 已支持 ML 仓位投影字段：`target_weight`、`adjusted_weight`、`agent_adjustment`。量化 ML 默认把 `target_weight` 同步为 `adjusted_weight` 并标记 `agent_adjustment.source=quant_default`；`ValuationPublisherAdapter` 注入 `StockAnalystAgent` 后会在默认量化投影之后发布 adjusted run，删除风险候选或下调仓位，并把最新列表切到专家调整后的投影。
- 提供 Provider 密钥配置页面，密钥只写不读，保存/测试后清空输入。
- 提供简化前端信息架构：用户侧页面只保留问答、今日推荐、设置及设置子页；底层 Provider、scope、run、candidate 等概念由后端默认值和设置页承接。

不再承担：

- 不触发同步的旧 `POST /api/v1/research-runs`；
- 不提供旧 `CandidateCard` / `HomeSummary` 视图；
- 不提供旧 evidence、valuation、audit、report、export 分散端点；
- 不展示或管理持仓、仓位、券商账户、买卖动作。

## 2. 文件级摘要

| 路径 | 当前职责 |
| --- | --- |
| `src/margin/dashboard/models.py` | Dashboard DTO：run/item 兼容聚合模型、候选列表/详情 DTO、feedback、provider status、scope/provider settings view、job run。 |
| `src/margin/dashboard/db_models.py` | `dashboard_runs`、`dashboard_items`、`dashboard_feedback` SQLAlchemy 行模型。 |
| `src/margin/dashboard/repository.py` | 内存/PostgreSQL repository；提供候选列表分页、过滤、排序、facets 与反馈存取。 |
| `src/margin/dashboard/service.py` | `DashboardQueryService`、`FeedbackService`、`ProviderStatusService`、`JobService` 与 `DashboardServiceBundle`。 |
| `src/margin/dashboard/detail_context.py` | 详情页上下文 loader；通过统一 SQL query factory 读取 research context、AI delta review、effective assessment、news documents，并从 warehouse 读取 PIT 趋势。 |
| `src/margin/api/routes/dashboard.py` | `/api/v1/research`、`/api/v1/research/items/{item_id}`、feedback、provider status、job 端点。 |
| `src/margin/api/routes/valuation_discovery.py` | Dashboard 刷新入口：`POST /api/v1/valuation-discovery/refreshes` 与 `GET /api/v1/valuation-discovery/runs/{run_id}`；创建 refresh 后后台唤醒一次 valuation worker，避免新任务长时间停在排队态。 |
| `web/app/layout.tsx` | 全局应用框架；Tailwind v4 + Vercel Geist 设计系统，侧栏只暴露问答、今日推荐、设置，顶栏提供语言切换。 |
| `web/app/page.tsx` | 问答优先首页；第一屏只保留自然语言输入，提交后调用 MainAgent 问答 API。 |
| `web/app/dashboard/page.tsx` / `web/components/recommendation-dashboard-view.tsx` | 今日推荐大屏；服务端读取最新 dashboard 投影，客户端按语言展示推荐列表、关键理由、置信度、量化评分和估值折价；顶部提供一键刷新研究。 |
| `web/app/dashboard/items/[itemId]/page.tsx` | 今日推荐详情子页；展示公司 current review、effective assessment、量化可视化、风险复核和 RAG 证据。 |
| `web/app/settings/page.tsx` | 设置中心入口；把密钥、数据、研究范围、自动研究计划、策略配置分成子页。 |
| `web/app/settings/` | Provider、scope、strategy、data 配置子页；scope 页用公司池选择器切换中证500、全 A、沪深300，scope/strategy 的高级版本列表使用 `ConfigVersionList` 触发 append-only 激活。 |
| `web/lib/api.ts` | 前端 API client；v0.2 dashboard、valuation discovery、provider settings、strategy，补齐 `createVersionedConfig`/`activateVersionedConfig`、`createProviderConfig`/`activateProviderConfig`、`fetchNewsRun`、`fetchJobRun`。 |
| `web/lib/utils.ts` | `cn` 类名合并 + 日期/分数/百分比/带符号百分比格式化。 |
| `web/components/sidebar.tsx` | 深色侧栏 client 组件，`usePathname` active 高亮，保留已实现导航入口。 |
| `web/components/ui/` | shadcn 风格 UI 原语：Button（CVA + asChild/loading）、Card、Badge（positive/caution/negative/neutral/muted/accent）、Input、Label、Textarea、Select、Dialog、Tabs、Tooltip、ScrollArea、Separator、Skeleton。 |
| `web/components/valuation-bar.tsx` | 内在价值区间条 + 现价标记，缺数据时静默降级。 |
| `web/components/factor-score-bar.tsx` | 因子分数横向条。 |
| `web/components/metric-trend-chart.tsx` | 详情页紧凑 SVG 趋势图，用固定尺寸展示价格、估值、ROE、利润等关键序列。 |
| `web/components/config-version-list.tsx` | 通用版本化配置列表 + append-only 激活按钮（universe/indicator/quant/style/scope）。 |
| `web/components/company-pool-selector.tsx` | 用户侧公司池选择器；反显中证500、全 A、沪深300的真实成员数和当前使用状态，缺少真实成员时禁用切换，自定义公司池入口暂为后续开放。 |
| `web/lib/i18n.tsx` / `web/components/language-toggle.tsx` | 中文/英文界面切换与共享文案字典。 |
| `web/components/current-vs-effective-panel.tsx` | 当前复核 vs 生效结论展示，用户可见标签走语言字典。 |
| `web/components/evidence-locator-list.tsx` | 证据摘要展示；默认隐藏 locator/snapshot/PIT 技术定位，所有外部文本均按文本渲染。 |
| `web/hooks/use-dashboard-refresh-run.ts` | 今日推荐页最近一次 refresh run 状态管理；负责启动、加载最近 run、轮询 run detail、打开/收起状态，并在最近 run 非终态时阻止重复启动。 |
| `web/lib/refresh-run-graph.ts` | 将 valuation discovery sparse step payload 标准化为固定 React Flow 节点状态，区分 completed、active、queued、pending、waiting、failed。 |
| `web/components/dashboard-refresh-control.tsx` | 今日推荐页刷新控制器；隐藏 scope/decision 参数，默认启动 valuation discovery，以浮层弹窗展示最近一次刷新节点图，并在已有非终态 run 时禁用“刷新今日研究”。 |
| `web/components/dashboard-refresh-node-graph.tsx` | React Flow 节点图；固定展示 valuation discovery 12 个阶段，运行中节点脉冲闪烁，完成为绿色，排队/等待为黄色，未开始为灰色，失败/上游阻断为红色。 |
| `web/components/recommendation-chat-panel.tsx` | 首页问答组件；输入框提交到 MainAgent 问答 API，展示 loading/error/disabled/success、折叠调用记录和业务化引用标签。 |
| `web/components/stock-analysis-schedule-panel.tsx` | 自动研究计划设置；用户只配置启用状态和每日时间，scope/universe 由后端默认值承接。 |
| `web/components/provider-settings-panel.tsx` | Provider 密钥配置。 |

## 3. 后端模型

### 3.1 内部兼容聚合模型

`ResearchRun` 与 `ResearchItem` 仍作为当前 dashboard repository 的内部聚合 DTO 使用，用于把上游已完成的候选/研究结果转换为列表与详情。它们不再对应公开的同步 research-run 创建 API。

| 模型 | 关键字段 |
| --- | --- |
| `ResearchRun` | `run_id`、`decision_at`、`strategy_id`、`version_id`、`universe`、`status`、`item_count`、`published_count`、`abstained_count`、`aborted_count`、`created_at`。 |
| `ResearchItem` | `item_id`、`run_id`、`symbol`、`signal_type`、`confidence`、`statement`、`workflow_run_id`、`snapshot_id`、`status`、`abstain_reason`、`rejection_reasons`、`evidence_ids`、`claim_ids`、`risk_score`、`target_weight`、`adjusted_weight`、`agent_adjustment`、`counter_arguments`、`created_at`。 |

### 3.2 当前公开 DTO

| 模型 | 说明 |
| --- | --- |
| `DashboardFilters` | `screening_status`、`data_status`、`review_required`、`assessment_freshness`、`query`。 |
| `DashboardSort` | 允许 `final_score`、`confidence`、`last_checked_at`、`symbol`；方向为 `asc` 或 `desc`。 |
| `DashboardPageInfo` | cursor 分页元信息。 |
| `ResearchCandidateListItemV2` | 候选行：security、scope、筛选状态、数据状态、风险标记、当前复核、有效 assessment、分数、目标仓位、调整后仓位、专家调整摘要、置信度、检查时间。 |
| `ResearchCandidateListResponse` | 候选页：`items`、`page_info`、`facets`、`as_of`、`scope_version_id`。 |
| `ResearchItemDetailV2` | 公司详情聚合：`item`、`current_review`、`effective_assessment`、`factors`、`thesis`、`evidence`、`versions`。 |
| `FeedbackRecord` | append-only 用户反馈。 |
| `ProviderStatus` | Provider 健康状态。 |
| `JobRun` | 后台 job 查询兼容记录。 |

## 4. 后端服务

| 服务 | 方法 | 说明 |
| --- | --- | --- |
| `DashboardQueryService` | `list_research_candidates_v2(...)` | 调用 repository 返回服务端分页候选列表，并用量化 profile 反填中文名等展示字段。 |
| `DashboardQueryService` | `get_item_detail_v2(item_id)` | 返回公司详情聚合，合并量化 profile、research context、AI delta review、news documents、effective assessment、估值状态与关键趋势。 |
| `FeedbackService` | `record_feedback(item_id, feedback_type, comment)` | 校验 item 存在后追加反馈，不修改原研究项。 |
| `ProviderStatusService` | `list_status()` | 调用已配置 provider 的 healthcheck；异常时返回 unhealthy/degraded 信息。 |
| `JobService` | `record_completed_job(run_id)` / `get_job(job_run_id)` | 保存和查询轻量 job record。 |
| `DashboardServiceBundle` | `in_memory(...)` / `from_repositories(...)` | FastAPI 依赖注入容器。 |

## 5. Repository 与分页

`DashboardRepository.list_research_candidates_v2(...)` 只读取同一 scope 下最新 dashboard run 的 item，在服务端完成过滤、排序、cursor 分页和 facets 统计，避免历史 run 的候选混入今日推荐。同一 scope 的 run 按 `decision_at desc, created_at desc, item_count desc, run_id desc` 选择；当手动/自动刷新使用相同 PIT 时，较新的完整投影会覆盖旧的单票投影。

过滤字段：

- `screening_status`
- `data_status`
- `review_required`
- `assessment_freshness`
- `query`（匹配 symbol/name/security）

排序字段：

- `final_score`
- `confidence`
- `last_checked_at`
- `symbol`

分页策略：

- 使用 base64 JSON cursor；
- cursor 中保存上一条排序键和 item id；
- repository 返回 `DashboardPageInfo`，前端不把全市场数据一次性加载到浏览器。

## 6. FastAPI 端点

所有端点位于 `/api/v1` 前缀下。

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| `GET` | `/research` | 查询候选列表。参数：`scope_version_id`、`universe`、`limit`、`cursor`、`screening_status`、`data_status`、`review_required`、`assessment_freshness`、`query`、`sort_field`、`sort_direction`。 |
| `GET` | `/research/items/{item_id}` | 查询公司详情聚合。 |
| `POST` | `/research-items/{item_id}/feedback` | 追加用户反馈。 |
| `GET` | `/provider-status` | 查询 Provider 状态。 |
| `GET` | `/jobs/{job_run_id}` | 查询后台 job record。 |
| `POST` | `/valuation-discovery/refreshes` | 启动估值发现 refresh；个人本地模式无需 local admin/CSRF，仍需要 idempotency key；请求返回后会 best-effort 唤醒一次 worker，持久 worker 继续按配置轮询兜底。 |
| `GET` | `/valuation-discovery/runs/{run_id}` | 查询 valuation discovery refresh/run 进度。 |

已删除的公开端点：

- `/research-runs`
- `/research-runs/{run_id}`
- `/research-runs/{run_id}/items`
- `/research-runs/{run_id}/cards`
- `/research-home`
- `/research-items/{item_id}/evidence`
- `/research-items/{item_id}/valuation`
- `/research-items/{item_id}/audit`
- `/research-items/{item_id}/report`
- `/research-items/{item_id}/export`
- `/jobs/nightly-runs`
- `/research/copilot`

## 7. 前端页面

| 页面 | 数据来源 | 说明 |
| --- | --- | --- |
| `/` | `askMainAgentQna` | 问答首页；第一屏是自然语言输入，提交后经 MainAgent 路由到专家 agent，默认只读，不触发交易。 |
| `/dashboard` | `fetchResearchCandidates`、`startValuationDiscoveryRefresh`、`fetchValuationDiscoveryRuns`、`fetchResearchRunDetailV2` | 今日推荐大屏；展示最新可见候选列表、理由标签、置信度、量化评分和估值折价；顶部“刷新今日研究”用默认参数启动 valuation discovery，并用浮层弹窗展示/更新最近一次刷新 React Flow 节点图；点击推荐卡进入详情子页。 |
| `/dashboard/items/[itemId]` | `fetchResearchItemDetailV2` | 今日推荐详情子页；展示研究结论、量化可视化、current/effective review、风险复核和 RAG 证据 locator。 |
| `/settings` | 静态子页索引 | 设置中心；把密钥配置、数据配置、研究范围、自动研究计划、策略配置分成子页，主流程不直接暴露底层配置。 |
| `/settings/providers` | provider config API | 配置 Tushare、Tavily、LLM、Embedding、Rerank 等密钥。 |
| `/settings/scope` | scope config API | 配置用户可见公司池与指标视图；公司池区直接展示中证500、全 A、沪深300三种默认池和当前使用状态，切换后滚动新的 active Research Scope。 |
| `/settings/strategy` | strategy config API | 配置策略模板、自定义 prompt 与版本。 |
| `/settings/schedule` | agent schedule API | 配置每日自动研究时间；保存到 `agent_runtime_schedules`，worker 到点触发 MainAgent 固定流程。 |

## 8. 前端组件

| 组件 | 说明 |
| --- | --- |
| `DashboardRefreshControl` | 今日推荐页的一键刷新入口；点击后用 `scope-current` 与当前时间调用 refresh API，成功后用浮层弹窗展示最近一次刷新节点图，不挤压列表内容；最近一次 run 非终态时按钮显示“刷新进行中”并禁用，失败时显示业务化配置提示；不再跳转内部 run 详情页。 |
| `DashboardRefreshNodeGraph` | React Flow 运行节点图；运行中节点脉冲闪烁，完成节点绿色，排队/等待节点黄色，未开始节点灰色，失败或 `upstream_failed` 节点红色。 |
| `CompanyPoolSelector` | 研究范围页的用户侧公司池配置；只允许切换已落库且有真实成员的默认池，当前池禁用并显示“当前使用”。 |
| `RecommendationChatPanel` | 用户首页问答，调用 MainAgent 问答 API，展示 loading/disabled/error/success、折叠调用记录和业务化引用标签。 |
| `CurrentVsEffectivePanel` | 区分本轮 current review 与当前生效结论。 |
| `EvidenceLocatorList` | 默认展示证据摘要、来源等级、新闻摘要和是否关联本股票；locator、snapshot、PIT 放入折叠的技术定位；外部文本不解释为 HTML。 |
| `MetricTrendChart` | 展示详情页关键指标趋势；不足两点时显示稳定空态。 |
| `ProviderSettingsPanel` | Provider 密钥写入；前端永不回显完整密钥。 |
| `ProviderStatusPanel` | Provider 健康状态列表，标题区展示 healthy/blocker 数量。 |
| `ValuationBar` | 内在价值区间条 + 现价标记。 |
| `FactorScoreBar` | 因子分数横向条。 |
| `ConfigVersionList` | 通用版本化配置列表 + 激活按钮。 |
| `Sidebar` | 深色侧栏，active 路由高亮。 |
| `PageLoading` | 路由级 Skeleton 占位。 |
| `ui/*` | shadcn 风格 UI 原语（Button/Card/Badge/Input/Dialog/Tabs 等）。 |

## 8.1 设计系统

前端已迁移到 Tailwind CSS v4（`@tailwindcss/postcss`）+ shadcn 风格 token，配色采用 Vercel Geist 体系：

- 背景 `#ffffff`、前景 `#111111`、强调/聚焦环 `#0070f3`（Vercel blue）；
- 深色侧栏 `#111111` + `sidebar-accent` 高亮；
- 语义色 positive `#0b9e5b` / caution `#c47f17` / negative `#e5484d`，各配 soft 背景用于 Badge；
- 字体统一 Inter（`next/font/google` 自托管），数字用 tabular-nums；
- 圆角 0.5rem，间距档位 4/8/12/16/24/32；
- 替换 v0.1 手写 1700 行 `globals.css` 为 Tailwind utility + token，删除 Fraunces 衬线与暖米配色，转向简约专业。

## 9. 验证

后端覆盖：

- candidate list 分页/过滤/facets；
- item detail current/effective 分离；
- detail context 合并中文名、AI 延期状态、新闻证据、估值缺失状态和趋势图数据；
- MainAgent 问答 guardrail 拒绝收益保证等不合规输入；
- feedback append-only；
- repository 内存与 PostgreSQL 行模型转换；
- provider status 错误降级。

前端覆盖：

- 问答首页、MainAgent 问答接口和折叠调用记录；
- 今日推荐大屏的推荐列表、详情子页、量化可视化、RAG 证据、指标和空状态；
- 今日推荐大屏一键刷新的默认参数、后端 worker 唤醒、非终态 run 禁重复触发、最近一次 React Flow 节点图、排队/运行状态、实时轮询、打开/收起和错误提示；
- 设置中心子页入口；
- 全局导航只暴露问答、今日推荐、设置三个用户入口；
- Tavily/service_not_configured 等 refresh blocker 的用户提示；
- provider settings；
- current/effective、evidence locator、问答、刷新节点图和设置组件。
- evidence locator 新闻摘要/股票关联状态与 metric trend chart 空态。

常用命令：

```bash
pytest -q tests/api/test_dashboard_v02.py tests/dashboard
cd web && npx vitest run
cd web && npm run lint
cd web && npm run build
python scripts/smoke_dashboard_e2e.py --base-url http://localhost:3000
```

## 10. 跨模块关系

| 模块 | 关系 |
| --- | --- |
| `07-strategy_config` | 设置子页依赖版本化配置和 Secret Store；主导航隐藏底层配置细节。 |
| `11-valuation_discovery` | `DASHBOARD_REFRESH` 将最新 quant run 的 pass/near_threshold/watchlist 结果发布为 dashboard 投影；`/dashboard` 和首页预览消费该投影；`/dashboard` 顶部可一键触发 refresh，并通过最近一次 run status 渲染 React Flow 节点图。详情页通过 research context 和 Analysis Mart lineage 展示中文名、news 文档、估值空态和关键趋势。 |
| `06-multi_agent_research` | `/dashboard/items/[itemId]` 详情展示 AI delta review 的 current/effective 结果。 |
| `05-rag_evidence` | `/dashboard/items/[itemId]` 详情展示 evidence locator，为后续 RAG 证据系统服务。 |
| `10-deployment_audit` | Provider status、job、trace 和 smoke 验证依赖部署审计与可观测能力。 |
