# 08-research_candidate_dashboard 模块文档

本文件描述当前仓库中的研究候选面板实现。v0.2 已删除持仓/交易相关页面，以及 v0.1 同步 research run、候选卡片、首页摘要、证据/估值/report/export 独立端点；当前 Dashboard 是一个只读为主的 BFF，展示 valuation discovery 与 AI delta review 产生的候选公司、有效结论、证据定位和 Provider 状态。

## 1. 模块职责

`08-research_candidate_dashboard` 负责把后端已经落库的候选公司与研究复核结果整理为前端可用的页面数据。

当前职责：

- 服务端分页查询研究候选列表；
- 展示单个公司的 current review 与 effective assessment；
- 展示量化分数、风险标记、证据 locator、版本信息和用户反馈；
- 提供只读 Copilot，只能基于候选列表回答，拒绝同步、刷新、配置、交易等写意图；
- 提供 Provider 状态展示；
- 提供启动 valuation discovery refresh 的前端表单；
- 提供 Provider 密钥配置页面，密钥只写不读，保存/测试后清空输入。
- 提供面向研究流程的前端信息架构：先处理 Provider/Scope，再查看候选与证据，不展示持仓或交易入口。

不再承担：

- 不触发同步的旧 `POST /api/v1/research-runs`；
- 不提供旧 `CandidateCard` / `HomeSummary` 视图；
- 不提供旧 evidence、valuation、audit、report、export 分散端点；
- 不展示或管理持仓、仓位、券商账户、买卖动作。

## 2. 文件级摘要

| 路径 | 当前职责 |
| --- | --- |
| `src/margin/dashboard/models.py` | Dashboard DTO：run/item 兼容聚合模型、候选列表/详情 DTO、feedback、provider status、scope/provider settings view、只读 Copilot response、job run。 |
| `src/margin/dashboard/db_models.py` | `dashboard_runs`、`dashboard_items`、`dashboard_feedback` SQLAlchemy 行模型。 |
| `src/margin/dashboard/repository.py` | 内存/PostgreSQL repository；提供候选列表分页、过滤、排序、facets 与反馈存取。 |
| `src/margin/dashboard/service.py` | `DashboardQueryService`、`FeedbackService`、`ProviderStatusService`、`JobService` 与 `DashboardServiceBundle`。 |
| `src/margin/api/routes/dashboard.py` | `/api/v1/research`、`/api/v1/research/items/{item_id}`、`/api/v1/research/copilot`、feedback、provider status、job 端点。 |
| `src/margin/api/routes/valuation_discovery.py` | Dashboard 刷新入口：`POST /api/v1/valuation-discovery/refreshes` 与 `GET /api/v1/valuation-discovery/runs/{run_id}`。 |
| `web/app/layout.tsx` | 全局应用框架；Tailwind v4 + Vercel Geist 设计系统，深色侧栏（`Sidebar` client 组件 + active 路由高亮）+ 顶栏 guardrail + `AdminGate`（Radix Dialog）。 |
| `web/app/page.tsx` | 研究工作台首页，从 v0.2 candidate API 读取摘要数据，展示候选快照、推荐操作顺序和 Provider blocker。 |
| `web/app/research/runs/[runId]/page.tsx` | 估值发现运行进度页，调用 valuation-discovery run status API。 |
| `web/app/research/items/[itemId]/page.tsx` | 公司研究详情页，展示 current/effective、thesis、量化快照、FactorScoreBar、证据 locators、反馈。 |
| `web/app/research/universe/page.tsx` | 公司池/Universe 状态页，按 universe 查询候选 facets。 |
| `web/app/strategies/[strategyId]/strategy-detail-client.tsx` | 策略详情 client，版本生命周期（validate/backtest/paper-trade/activate/archive）+ Prompt 预览。 |
| `web/app/settings/` | Provider、scope、strategy、data 配置页面；scope/strategy 使用 `ConfigVersionList` 触发 append-only 激活。 |
| `web/lib/api.ts` | 前端 API client；v0.2 dashboard、valuation discovery、provider settings、strategy，补齐 `createVersionedConfig`/`activateVersionedConfig`、`createProviderConfig`/`activateProviderConfig`、`fetchNewsRun`、`fetchJobRun`。 |
| `web/lib/utils.ts` | `cn` 类名合并 + 日期/分数/百分比/带符号百分比格式化。 |
| `web/components/sidebar.tsx` | 深色侧栏 client 组件，`usePathname` active 高亮，保留已实现导航入口。 |
| `web/components/ui/` | shadcn 风格 UI 原语：Button（CVA + asChild/loading）、Card、Badge（positive/caution/negative/neutral/muted/accent）、Input、Label、Textarea、Select、Dialog、Tabs、Tooltip、ScrollArea、Separator、Skeleton。 |
| `web/components/valuation-bar.tsx` | 内在价值区间条 + 现价标记，缺数据时静默降级。 |
| `web/components/factor-score-bar.tsx` | 因子分数横向条。 |
| `web/components/config-version-list.tsx` | 通用版本化配置列表 + append-only 激活按钮（universe/indicator/quant/style/scope）。 |
| `web/components/research-run-form.tsx` | 启动 valuation discovery refresh 的表单。 |
| `web/components/research-filter-bar.tsx` | 候选列表筛选控件。 |
| `web/components/research-results-table.tsx` | 候选公司表格。 |
| `web/components/current-vs-effective-panel.tsx` | 当前复核 vs 生效结论展示。 |
| `web/components/evidence-locator-list.tsx` | 证据 locator 展示，所有外部文本均按文本渲染。 |
| `web/components/read-only-copilot-panel.tsx` | 只读 Copilot。 |
| `web/components/provider-settings-panel.tsx` | Provider 密钥配置。 |
| `web/components/research-run-progress.tsx` | valuation discovery 运行进度展示。 |

## 3. 后端模型

### 3.1 内部兼容聚合模型

`ResearchRun` 与 `ResearchItem` 仍作为当前 dashboard repository 的内部聚合 DTO 使用，用于把上游已完成的候选/研究结果转换为列表与详情。它们不再对应公开的同步 research-run 创建 API。

| 模型 | 关键字段 |
| --- | --- |
| `ResearchRun` | `run_id`、`decision_at`、`strategy_id`、`version_id`、`universe`、`status`、`item_count`、`published_count`、`abstained_count`、`aborted_count`、`created_at`。 |
| `ResearchItem` | `item_id`、`run_id`、`symbol`、`signal_type`、`confidence`、`statement`、`workflow_run_id`、`snapshot_id`、`status`、`abstain_reason`、`rejection_reasons`、`evidence_ids`、`claim_ids`、`risk_score`、`counter_arguments`、`created_at`。 |

### 3.2 当前公开 DTO

| 模型 | 说明 |
| --- | --- |
| `DashboardFilters` | `screening_status`、`data_status`、`review_required`、`assessment_freshness`、`query`。 |
| `DashboardSort` | 允许 `final_score`、`confidence`、`last_checked_at`、`symbol`；方向为 `asc` 或 `desc`。 |
| `DashboardPageInfo` | cursor 分页元信息。 |
| `ResearchCandidateListItemV2` | 候选行：security、scope、筛选状态、数据状态、风险标记、当前复核、有效 assessment、分数、置信度、检查时间。 |
| `ResearchCandidateListResponse` | 候选页：`items`、`page_info`、`facets`、`as_of`、`scope_version_id`。 |
| `ResearchItemDetailV2` | 公司详情聚合：`item`、`current_review`、`effective_assessment`、`factors`、`thesis`、`evidence`、`versions`。 |
| `FeedbackRecord` | append-only 用户反馈。 |
| `ProviderStatus` | Provider 健康状态。 |
| `ReadOnlyCopilotResponse` | 只读 Copilot 回答与引用。 |
| `JobRun` | 后台 job 查询兼容记录。 |

## 4. 后端服务

| 服务 | 方法 | 说明 |
| --- | --- | --- |
| `DashboardQueryService` | `list_research_candidates_v2(...)` | 调用 repository 返回服务端分页候选列表。 |
| `DashboardQueryService` | `get_item_detail_v2(item_id)` | 返回公司详情聚合，分离 current review 与 effective assessment。 |
| `FeedbackService` | `record_feedback(item_id, feedback_type, comment)` | 校验 item 存在后追加反馈，不修改原研究项。 |
| `ProviderStatusService` | `list_status()` | 调用已配置 provider 的 healthcheck；异常时返回 unhealthy/degraded 信息。 |
| `JobService` | `record_completed_job(run_id)` / `get_job(job_run_id)` | 保存和查询轻量 job record。 |
| `DashboardServiceBundle` | `in_memory(...)` / `from_repositories(...)` | FastAPI 依赖注入容器。 |

## 5. Repository 与分页

`DashboardRepository.list_research_candidates_v2(...)` 在服务端完成过滤、排序、cursor 分页和 facets 统计。

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
| `POST` | `/research/copilot` | 只读 Copilot；写意图返回 `403 copilot_read_only`。 |
| `POST` | `/research-items/{item_id}/feedback` | 追加用户反馈。 |
| `GET` | `/provider-status` | 查询 Provider 状态。 |
| `GET` | `/jobs/{job_run_id}` | 查询后台 job record。 |
| `POST` | `/valuation-discovery/refreshes` | 启动估值发现 refresh，需要 local admin、CSRF、idempotency key。 |
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

## 7. 前端页面

| 页面 | 数据来源 | 说明 |
| --- | --- | --- |
| `/` | `fetchResearchCandidates`、`fetchProviderStatus`、provider configs | 研究工作台首页；展示候选摘要、最新候选快照、推荐操作顺序和 Provider 状态。 |
| `/research` | `fetchResearchCandidates`、`startValuationDiscoveryRefresh` | 研究候选工作台；用户先筛选候选，再在右侧触发 valuation discovery refresh 并查看 Provider blocker。 |
| `/research/runs/[runId]` | `fetchResearchRunDetailV2` → `/api/v1/valuation-discovery/runs/{run_id}` | 运行进度页，展示 target count、completed、pending、failed、wait state、trace。 |
| `/research/items/[itemId]` | `fetchResearchItemDetailV2` | 公司详情页，展示 current/effective、factor snapshot、证据 locator、反馈表单。 |
| `/research/universe` | 静态/配置说明 | 展示沪深300、中证500、全 A 等公司池配置逻辑。 |
| `/settings/providers` | provider config API | 配置 Tushare、Tavily、LLM、Embedding、Rerank 等密钥。 |
| `/settings/scope` | scope config API | 配置用户可见公司池与指标视图。 |
| `/settings/strategy` | strategy config API | 配置策略模板、自定义 prompt 与版本。 |

## 8. 前端组件

| 组件 | 说明 |
| --- | --- |
| `ResearchRunForm` | 启动 valuation discovery refresh；不再创建旧 research run；对 local admin、Provider/scope 未配置、Tavily 未激活等错误给出明确操作提示。 |
| `ResearchFilterBar` | 服务端筛选候选列表。 |
| `ResearchResultsTable` | 表格展示候选公司、状态、风险、分数和 effective assessment。 |
| `ResearchRunProgress` | 展示 valuation discovery run 进度。 |
| `CurrentVsEffectivePanel` | 区分本轮 current review 与当前生效结论。 |
| `EvidenceLocatorList` | 展示 evidence id、source level、locator、snapshot id。 |
| `ReadOnlyCopilotPanel` | 提交只读问题；拒绝写意图。 |
| `ProviderSettingsPanel` | Provider 密钥写入；前端永不回显完整密钥。 |
| `ProviderStatusPanel` | Provider 健康状态列表，标题区展示 healthy/blocker 数量。 |
| `ResearchFeedbackForm` | 追加用户反馈。 |
| `ResearchStatusBadge` | 状态徽章。 |
| `ValuationBar` | 内在价值区间条 + 现价标记。 |
| `FactorScoreBar` | 因子分数横向条。 |
| `ConfigVersionList` | 通用版本化配置列表 + 激活按钮。 |
| `Sidebar` | 深色侧栏，active 路由高亮。 |
| `AdminGate` | 顶栏管理员解锁（Radix Dialog + localStorage 凭据）。 |
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
- read-only Copilot 写意图拒绝；
- feedback append-only；
- repository 内存与 PostgreSQL 行模型转换；
- provider status 错误降级。

前端覆盖：

- 首页候选摘要；
- 全局导航只暴露已实现入口；
- `/research` refresh 表单与候选表；
- Tavily/service_not_configured 等 refresh blocker 的用户提示；
- valuation discovery run 进度页；
- item detail 页；
- provider settings；
- current/effective、evidence locator、read-only Copilot、filter/table 组件。

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
| `07-strategy_config` | Provider settings、scope、strategy 页面依赖版本化配置和 Secret Store。 |
| `11-valuation_discovery` | `/research` 的启动按钮触发 refresh；运行页读取 valuation discovery run 状态。 |
| `06-multi_agent_research` | 详情页展示 AI delta review 的 current/effective 结果。 |
| `05-rag_evidence` | 详情页展示 evidence locator，为后续 RAG 证据系统服务。 |
| `10-deployment_audit` | Provider status、job、trace 和 smoke 验证依赖部署审计与可观测能力。 |
