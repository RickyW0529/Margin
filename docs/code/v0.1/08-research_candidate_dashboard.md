# 模块 08：Research Candidate Dashboard 代码文档

## 目录

1. [模块概述](#1-模块概述)
2. [文件级摘要](#2-文件级摘要)
3. [领域模型](#3-领域模型)
4. [服务层](#4-服务层)
5. [持久层](#5-持久层)
6. [FastAPI 端点](#6-fastapi-端点)
7. [Next.js 页面与 Server Actions](#7-nextjs-页面与-server-actions)
8. [React 组件](#8-react-组件)
9. [跨模块使用说明](#9-跨模块使用说明)

---

## 1. 模块概述

`08-research_candidate_dashboard` 是 Margin v0.1 的研究候选面板模块，负责把模块 06（`margin.research`）产出的工作流结果转换为可人工审阅的候选卡片、证据展开、估值视图与研究报告，并通过 FastAPI + Next.js 页面暴露给用户。

主要职责：

- 批量触发研究运行（`DashboardResearchService.run_batch`），将每个标的的工作流结果聚合为 `ResearchRun` / `ResearchItem`。
- 提供只读查询服务（`DashboardQueryService`），生成首页摘要（`HomeSummary`）与候选卡片（`CandidateCard`）。
- 展开证据（`EvidenceViewService`）、估值（`ValuationViewService`）、审计（`AuditService`）与报告渲染（`ReportRenderer` / `ExportService`）。
- 接收用户对研究项的反馈（`FeedbackService`），以追加方式存储，不修改不可变的研究项。
- 暴露 Provider 健康状态（`ProviderStatusService`）与同步夜间运行任务（`JobService`）。
- 提供 Next.js 服务端页面（`/research`、`/research/runs/[runId]`、`/research/items/[itemId]`）及配套 React 组件。

---

## 2. 文件级摘要

| 文件路径 | 说明 |
| --- | --- |
| `src/margin/dashboard/__init__.py` | 模块公开接口，聚合模型、仓库与服务的导出。 |
| `src/margin/dashboard/db_models.py` | SQLAlchemy 行模型：`DashboardRunRow`、`DashboardItemRow`、`DashboardFeedbackRow`。 |
| `src/margin/dashboard/models.py` | Pydantic 领域模型与枚举：运行、研究项、卡片、证据、估值、报告、反馈等。 |
| `src/margin/dashboard/repository.py` | 仓库协议与实现：`DashboardRepository`、`MemoryDashboardRepository`、`SQLAlchemyDashboardRepository` 及行/模型转换函数。 |
| `src/margin/dashboard/service.py` | 业务服务：运行聚合、查询、证据、估值、反馈、审计、报告、导出、Provider 状态、任务与 `DashboardServiceBundle`。 |
| `src/margin/api/routes/dashboard.py` | FastAPI 路由，前缀 `/api/v1`，覆盖运行、项、证据、估值、审计、报告、导出、反馈、Provider 状态与任务。 |
| `web/app/research/page.tsx` | 研究候选面板首页，异步服务端组件。 |
| `web/app/research/loading.tsx` | 首页加载占位。 |
| `web/app/research/page.test.tsx` | 首页渲染测试。 |
| `web/app/research/actions.ts` | Server Action `createResearchRunAction`，提交表单后创建运行并重定向。 |
| `web/app/research/runs/[runId]/page.tsx` | 运行详情页，展示运行元信息与候选卡片列表。 |
| `web/app/research/runs/[runId]/loading.tsx` | 运行详情页加载占位。 |
| `web/app/research/items/[itemId]/page.tsx` | 研究项详情页，展示结论、估值、证据、报告与反馈表单。 |
| `web/app/research/items/[itemId]/loading.tsx` | 研究项详情页加载占位。 |
| `web/app/research/items/[itemId]/actions.ts` | Server Action `createResearchFeedbackAction`，提交研究项反馈。 |
| `web/components/candidate-card.tsx` | 单个候选卡片组件。 |
| `web/components/candidate-card.test.tsx` | 候选卡片渲染测试。 |
| `web/components/candidate-list.tsx` | 候选卡片列表容器。 |
| `web/components/evidence-panel.tsx` | 证据展开面板。 |
| `web/components/evidence-panel.test.tsx` | 证据面板渲染测试。 |
| `web/components/report-panel.tsx` | 研究报告与导出面板。 |
| `web/components/report-panel.test.tsx` | 报告面板渲染测试。 |
| `web/components/valuation-panel.tsx` | 估值视图面板。 |
| `web/components/home-summary.tsx` | 首页六宫格摘要。 |
| `web/components/home-summary.test.tsx` | 首页摘要渲染测试。 |
| `web/components/research-status-badge.tsx` | 研究状态徽章。 |
| `web/components/research-run-form.tsx` | 启动研究运行表单。 |
| `web/components/research-feedback-form.tsx` | 研究反馈表单。 |
| `web/components/provider-status-panel.tsx` | Provider 健康状态列表。 |
| `web/components/page-loading.tsx` | 通用页面骨架屏。 |

---

## 3. 领域模型

定义文件：`src/margin/dashboard/models.py`。

### 3.1 枚举

| 枚举 | 取值 | 说明 |
| --- | --- | --- |
| `RunStatus` | `published`、`abstained`、`aborted`、`partial` | 一次批量研究运行的终态。 |
| `ItemStatus` | `published`、`abstained`、`aborted`、`data_missing` | 单个研究项在面板中的状态。 |
| `FeedbackType` | `accept`、`reject`、`watch`、`comment` | 允许的用户反馈类型。 |
| `JobStatus` | `completed`、`failed` | v0.1 同步夜间任务的终态。 |
| `ReportFormat` | `markdown`、`json` | 报告/导出的支持格式。 |

### 3.2 `ResearchRun`

一次批量研究运行的不可变聚合。

| 字段 | 类型 | 默认值 | 说明 |
| --- | --- | --- | --- |
| `run_id` | `str` | `dr_<uuid前12位>` | 运行唯一标识。 |
| `decision_at` | `datetime` | 必填 | 决策时间，UTC 归一化。 |
| `strategy_id` | `str` | 必填 | 策略 ID。 |
| `version_id` | `str` | 必填 | 策略版本 ID。 |
| `portfolio_id` | `str \| None` | `None` | 关联组合 ID。 |
| `universe` | `list[str]` | `[]` | 标的列表。 |
| `status` | `RunStatus` | `published` | 运行终态。 |
| `summary` | `str` | `""` | 运行摘要。 |
| `item_count` | `int` | `0` | 项总数。 |
| `published_count` | `int` | `0` | 已发布项数。 |
| `abstained_count` | `int` | `0` | 已拒绝/放弃项数。 |
| `aborted_count` | `int` | `0` | 已中止项数。 |
| `created_at` | `datetime` | `utc_now()` | 创建时间，UTC 归一化。 |

校验器：`normalize_timestamps` 对 `decision_at`、`created_at` 执行 `ensure_utc`。

### 3.3 `ResearchItem`

由模块 06 工作流结果生成的标的级研究项。

| 字段 | 类型 | 默认值 | 说明 |
| --- | --- | --- | --- |
| `item_id` | `str` | `di_<uuid前12位>` | 项唯一标识。 |
| `run_id` | `str` | 必填 | 所属运行 ID。 |
| `symbol` | `str` | 必填 | 标的代码。 |
| `signal_type` | `str` | `""` | 信号类型。 |
| `confidence` | `float` | `0.0` | 置信度，必须在 `[0, 1]`。 |
| `statement` | `str` | `""` | 研究结论语句。 |
| `workflow_run_id` | `str` | `""` | 模块 06 工作流运行 ID。 |
| `snapshot_id` | `str \| None` | `None` | 快照 ID，用于追溯。 |
| `status` | `ItemStatus` | `published` | 项状态。 |
| `abstain_reason` | `str \| None` | `None` | 放弃原因。 |
| `rejection_reasons` | `list[str]` | `[]` | 拒绝原因列表。 |
| `evidence_ids` | `list[str]` | `[]` | 证据 ID 列表。 |
| `claim_ids` | `list[str]` | `[]` | Claim ID 列表。 |
| `risk_score` | `float \| None` | `None` | 风险分。 |
| `counter_arguments` | `list[str]` | `[]` | 反方理由。 |
| `portfolio_constraint_violations` | `list[str]` | `[]` | 组合约束违规。 |
| `created_at` | `datetime` | `utc_now()` | 创建时间，UTC 归一化。 |

校验器：`normalize_created_at` 归一化 `created_at`；`validate_confidence` 校验置信度范围。

### 3.4 `CandidateCard`

前端候选卡片使用的派生视图。

| 字段 | 类型 | 默认值 | 说明 |
| --- | --- | --- | --- |
| `item_id` | `str` | 必填 | 项 ID。 |
| `run_id` | `str` | 必填 | 运行 ID。 |
| `symbol` | `str` | 必填 | 标的代码。 |
| `signal_type` | `str` | `""` | 信号类型。 |
| `confidence` | `float` | `0.0` | 置信度。 |
| `statement` | `str` | `""` | 结论语句。 |
| `current_price` | `float \| None` | `None` | 当前价（预留）。 |
| `quantitative_rank` | `int \| None` | `None` | 量化排名（预留）。 |
| `research_status` | `str` | `""` | 研究状态。 |
| `position_review_status` | `str \| None` | `None` | 持仓复核状态。 |
| `valuation_range` | `tuple[float, float] \| None` | `None` | 估值区间。 |
| `margin_of_safety` | `float \| None` | `None` | 安全边际。 |
| `value_trap_score` | `float \| None` | `None` | 价值陷阱风险分。 |
| `event_window` | `str \| None` | `None` | 事件窗口（预留）。 |
| `catalysts` | `list[str]` | `[]` | 催化剂（预留）。 |
| `counter_arguments` | `list[str]` | `[]` | 反方理由。 |
| `evidence_summary` | `dict[str, Any]` | `{}` | 证据汇总。 |
| `watch_conditions` | `list[str]` | `[]` | 观察条件。 |
| `invalidation_conditions` | `list[str]` | `[]` | 失效条件。 |
| `strategy_version` | `str` | `""` | 策略版本。 |
| `disclaimer` | `str` | 系统默认免责声明 | 默认“本系统输出研究分析，不构成买卖指令。” |

### 3.5 `HomeSummary`

首页六宫格摘要。

| 字段 | 类型 | 默认值 | 说明 |
| --- | --- | --- | --- |
| `decision_at` | `datetime \| None` | `None` | 最近运行决策时间。 |
| `run_id` | `str \| None` | `None` | 最近运行 ID。 |
| `strategy_id` | `str \| None` | `None` | 策略 ID。 |
| `version_id` | `str \| None` | `None` | 策略版本。 |
| `run_status` | `str \| None` | `None` | 最近运行状态。 |
| `today_candidates` | `list[CandidateCard]` | `[]` | 今日候选卡片。 |
| `position_reviews` | `list[CandidateCard]` | `[]` | 现有持仓复核卡片（当前按信号类型派生）。 |
| `high_priority_risks` | `list[CandidateCard]` | `[]` | 高优先级风险卡片。 |
| `rejections` | `list[CandidateCard]` | `[]` | 被拒绝/中止卡片。 |
| `run_stats` | `dict[str, int]` | `{}` | 运行统计。 |

### 3.6 `EvidenceView`

研究项的证据展开视图。

| 字段 | 类型 | 默认值 | 说明 |
| --- | --- | --- | --- |
| `item_id` | `str` | 必填 | 项 ID。 |
| `claims` | `list[ClaimView]` | `[]` | Claim 列表。 |
| `evidence_by_level` | `dict[str, list[EvidenceLocator]]` | `{}` | 按来源层级分组的证据定位器。 |
| `source_distribution` | `dict[str, int]` | `{}` | 来源分布统计。 |
| `overall_confidence` | `float` | `0.0` | 综合置信度。 |
| `locators_available` | `bool` | `False` | 是否存在证据定位器。 |

### 3.7 `ValuationView`

研究项的估值视图。

| 字段 | 类型 | 默认值 | 说明 |
| --- | --- | --- | --- |
| `item_id` | `str` | 必填 | 项 ID。 |
| `base_valuation_range` | `tuple[float, float] \| None` | `None` | 基准估值区间。 |
| `pessimistic_range` | `tuple[float, float] \| None` | `None` | 悲观估值区间。 |
| `margin_of_safety` | `float \| None` | `None` | 安全边际（预留）。 |
| `value_trap_score` | `float \| None` | `None` | 价值陷阱风险分。 |
| `method` | `str \| None` | `None` | 估值方法，如 `pe`。 |
| `notes` | `str` | `""` | 估值说明。 |

### 3.8 其他模型（简要）

| 模型 | 说明 |
| --- | --- |
| `EvidenceLocator` | 证据定位器：`evidence_id`、`source_level`、`source_url`、`content`、`page`、`section`。 |
| `ClaimView` | 证据面板中的 Claim：`claim_id`、`statement`、`fact_or_inference`、`confidence`、`has_conflict`、`evidence_ids`。 |
| `FeedbackRecord` | 用户反馈记录：`feedback_id`、`item_id`、`feedback_type`、`comment`、`created_at`。 |
| `ProviderStatus` | Provider 健康元数据：`provider`、`status`、`message`。 |
| `JobRun` | 同步 MVP 任务记录：`job_run_id`、`run_id`、`status`、`payload_json`、`created_at`。 |
| `AuditView` | 审计追溯：`item_id`、`workflow_run_id`、`snapshot_id`、`workflow_state`、`input_hash`、`output_hash`、`trace_count`、`tool_call_ids`、`error`。 |
| `ResearchReport` | 渲染后的研究报告：`item_id`、`run_id`、`symbol`、`title`、`format`、`content`、`sections`、`generated_at`。 |
| `ReportExport` | 报告导出载荷：`item_id`、`format`、`filename`、`mime_type`、`content`、`generated_at`。 |

---

## 4. 服务层

定义文件：`src/margin/dashboard/service.py`。

### 4.1 `DashboardResearchService`

运行模块 06 工作流并把结果聚合为模块 08 的运行/研究项。

| 方法 | 签名 | 说明 |
| --- | --- | --- |
| `__init__` | `(research_service: Any, repository: DashboardRepository)` | 依赖研究服务与面板仓库。 |
| `run_batch` | `(*, decision_at, strategy_id, version_id, portfolio_id, symbols) -> ResearchRun` | 对 `symbols` 逐个调用研究服务，生成 `ResearchItem`，汇总计数与状态后持久化。 |
| `_item_from_result` | `(run_id, symbol, result: WorkflowResult) -> ResearchItem` | 将单个 `WorkflowResult` 转换为 `ResearchItem`，解析信号、错误、snapshot ID、证据与 Claim ID。 |

行为：

- `decision_at` 默认为当前 UTC 时间；`symbols` 默认为 `["000001.SZ"]`。
- 根据项状态统计 `published_count`、`abstained_count`、`aborted_count`，并派生 `RunStatus`。
- 生成的运行与项通过 `repository.add_run` / `add_items` 持久化。

### 4.2 `DashboardQueryService`

只读查询服务，提供运行、研究项、候选卡片与首页摘要。

| 方法 | 签名 | 说明 |
| --- | --- | --- |
| `__init__` | `(repository: DashboardRepository, research_repository: ResearchRepository)` | 依赖面板仓库与模块 06 研究仓库。 |
| `list_runs` | `(*, strategy_id, portfolio_id, status, limit=100) -> list[ResearchRun]` | 透传仓库查询运行列表。 |
| `get_run` | `(run_id: str) -> ResearchRun` | 按 ID 取运行，不存在抛 `KeyError`。 |
| `get_run_items` | `(run_id: str) -> list[ResearchItem]` | 校验运行存在后返回其所有项。 |
| `get_item` | `(item_id: str) -> ResearchItem` | 按 ID 取研究项，不存在抛 `KeyError`。 |
| `get_candidate_cards` | `(run_id: str) -> list[CandidateCard]` | 取运行与项，为每项生成 `CandidateCard`。 |
| `get_home_summary` | `(*, portfolio_id, strategy_id) -> HomeSummary` | 取最新运行并生成六宫格首页摘要；无运行返回空统计。 |
| `_card_from_item` | `(run: ResearchRun, item: ResearchItem) -> CandidateCard` | 内部方法，为单个项构造卡片，包含估值、证据统计、观察/失效条件。 |

### 4.3 `EvidenceViewService`

从研究项与模块 06 快照构建证据展开视图。

| 方法 | 签名 | 说明 |
| --- | --- | --- |
| `__init__` | `(repository: DashboardRepository, research_repository: ResearchRepository)` | 依赖面板仓库与研究仓库。 |
| `get_evidence_view` | `(item_id: str) -> EvidenceView` | 取项与快照，合并证据/Claim ID，生成 `ClaimView` 与 `EvidenceLocator` 列表。 |

行为：

- 若存在快照，优先使用快照中的 `evidence_ids`、`claim_ids` 与最大信号置信度。
- 当前证据定位器仅包含 `evidence_id`，`source_level` 等字段为空，按 `unknown` 层级分组。

### 4.4 `ValuationViewService`

从模块 06 快照的 `valuation_tool` 输出构建估值视图。

| 方法 | 签名 | 说明 |
| --- | --- | --- |
| `__init__` | `(repository: DashboardRepository, research_repository: ResearchRepository)` | 依赖面板仓库与研究仓库。 |
| `get_valuation_view` | `(item_id: str) -> ValuationView` | 解析快照 `agent_outputs_json` 中 `valuation_tool.value`，生成基准与悲观区间。 |

行为：

- 若快照无有效估值数值，返回 `notes="估值数据暂不可用"`。
- 基准区间为 `value * 0.9 ~ value * 1.1`，悲观区间为 `value * 0.7 ~ value * 0.9`。
- `value_trap_score` 优先取快照风险分，否则取项的 `risk_score`。

### 4.5 `FeedbackService`

追加用户反馈，不修改不可变研究项。

| 方法 | 签名 | 说明 |
| --- | --- | --- |
| `__init__` | `(repository: DashboardRepository)` | 依赖面板仓库。 |
| `record_feedback` | `(item_id, feedback_type, comment="") -> FeedbackRecord` | 校验项存在后创建并持久化反馈记录。 |

### 4.6 `AuditService`

返回研究项的模块 06 快照审计元数据。

| 方法 | 签名 | 说明 |
| --- | --- | --- |
| `__init__` | `(repository: DashboardRepository, research_repository: ResearchRepository)` | 依赖面板仓库与研究仓库。 |
| `get_audit_view` | `(item_id: str) -> AuditView` | 取项与快照，返回 `workflow_state`、`input_hash`、`output_hash`、trace 数量等；无快照返回 `error="snapshot unavailable"`。 |

### 4.7 `ReportRenderer`

将研究项渲染为可审计的研究报告。

| 方法 | 签名 | 说明 |
| --- | --- | --- |
| `__init__` | `(repository: DashboardRepository, research_repository: ResearchRepository)` | 依赖面板仓库与研究仓库。 |
| `render_report` | `(item_id: str) -> ResearchReport` | 取项、运行、证据、估值、审计，生成 Markdown 报告与结构化 `sections`。 |

报告 Markdown 由 `_render_markdown_report` 生成，包含：标题、免责声明、研究结论、估值、证据、反方与拒绝原因、审计追溯。

### 4.8 `ExportService`

以轻量级 MVP 格式导出已渲染报告。

| 方法 | 签名 | 说明 |
| --- | --- | --- |
| `__init__` | `(renderer: ReportRenderer)` | 依赖报告渲染器。 |
| `export_report` | `(item_id, report_format="markdown") -> ReportExport` | 渲染报告后输出 Markdown 或 JSON 格式，生成文件名与 MIME 类型。 |

### 4.9 `ProviderStatusService`

返回面板所需的 Provider 健康状态。

| 方法 | 签名 | 说明 |
| --- | --- | --- |
| `__init__` | `(providers: list[Any] \| None = None)` | 传入 Provider 对象列表。 |
| `list_status` | `() -> list[ProviderStatus]` | 遍历 Provider 调用 `healthcheck()`；异常时状态为 `unhealthy`。未传 Provider 时返回 `dashboard healthy` 占位。 |

### 4.10 `JobService`

v0.1 同步夜间运行任务注册表。

| 方法 | 签名 | 说明 |
| --- | --- | --- |
| `__init__` | `()` | 初始化内存任务字典。 |
| `record_completed_job` | `(run_id: str) -> JobRun` | 为完成的运行创建 `JobRun` 并记录。 |
| `get_job` | `(job_run_id: str) -> JobRun` | 按 ID 取任务，不存在抛 `KeyError`。 |

### 4.11 `DashboardServiceBundle`

FastAPI 依赖注入容器。

| 属性 | 类型 | 说明 |
| --- | --- | --- |
| `research` | `DashboardResearchService` | 批量运行服务。 |
| `query` | `DashboardQueryService` | 查询服务。 |
| `evidence` | `EvidenceViewService` | 证据服务。 |
| `valuation` | `ValuationViewService` | 估值服务。 |
| `feedback` | `FeedbackService` | 反馈服务。 |
| `audit` | `AuditService` | 审计服务。 |
| `reports` | `ReportRenderer` | 报告渲染。 |
| `exports` | `ExportService` | 报告导出。 |
| `providers` | `ProviderStatusService` | Provider 状态。 |
| `jobs` | `JobService` | 任务注册表。 |

| 类方法 | 签名 | 说明 |
| --- | --- | --- |
| `in_memory` | `(*, dashboard_repository, research_repository, research_service) -> DashboardServiceBundle` | 使用内存仓库构建 Bundle，用于测试与本地开发。 |
| `from_repositories` | `(*, dashboard_repository, research_repository, research_service, providers) -> DashboardServiceBundle` | 从指定仓库与 Provider 列表构建 Bundle。 |

### 4.12 内部辅助函数

| 函数 | 签名 | 说明 |
| --- | --- | --- |
| `_item_status` | `(state: WorkflowState, signal_type) -> ItemStatus` | 根据工作流状态与信号类型派生项状态。 |
| `_run_status` | `(published, abstained, aborted, total) -> RunStatus` | 根据项计数派生运行状态。 |
| `_must_get_item` | `(repository, item_id) -> ResearchItem` | 取项，不存在抛 `KeyError`。 |
| `_snapshot_prior_outputs` | `(snapshot) -> dict[str, Any]` | 解析快照 `agent_outputs_json` 为字典。 |
| `_coerce_report_format` | `(report_format) -> ReportFormat` | 将字符串强制转换为 `ReportFormat`。 |
| `_render_markdown_report` | `(title, sections) -> str` | 生成中文 Markdown 报告正文。 |

---

## 5. 持久层

定义文件：`src/margin/dashboard/repository.py`。

### 5.1 `DashboardRepository`（Protocol）

| 方法 | 签名 | 说明 |
| --- | --- | --- |
| `add_run` | `(run: ResearchRun) -> None` | 持久化运行。 |
| `get_run` | `(run_id: str) -> ResearchRun \| None` | 按 ID 取运行。 |
| `list_runs` | `(*, strategy_id, portfolio_id, status, limit=100) -> list[ResearchRun]` | 查询运行列表，默认按创建时间倒序。 |
| `add_items` | `(items: list[ResearchItem]) -> None` | 持久化项列表。 |
| `get_item` | `(item_id: str) -> ResearchItem \| None` | 按 ID 取项。 |
| `list_items` | `(run_id: str) -> list[ResearchItem]` | 取某运行的所有项。 |
| `add_feedback` | `(feedback: FeedbackRecord) -> None` | 追加反馈。 |
| `list_feedback` | `(item_id: str) -> list[FeedbackRecord]` | 取某项的反馈列表。 |

### 5.2 `MemoryDashboardRepository`

内存实现，用于测试与本地开发。

- 使用三个内部字典分别存储 `_runs`、`_items`、`_feedback`。
- `list_runs` 支持按 `strategy_id`、`portfolio_id`、`status` 过滤，按 `created_at` 倒序返回前 `limit` 条。
- `list_items` 按 `run_id` 过滤，按 `created_at` 升序返回。
- `list_feedback` 按 `item_id` 返回追加顺序列表。

### 5.3 `SQLAlchemyDashboardRepository`

PostgreSQL 实现。

- 接收 `session_factory: Callable[[], Session]`。
- 写入操作（`add_run`、`add_items`、`add_feedback`）使用 `session.begin()` 事务。
- 查询使用 `select(...)` 并透传过滤条件。
- 通过 `_run_to_row` / `_run_from_row`、`_item_to_row` / `_item_from_row` 完成 `ResearchRun`/`ResearchItem` 与 `DashboardRunRow`/`DashboardItemRow` 之间的字段映射。

### 5.4 映射函数

| 函数 | 说明 |
| --- | --- |
| `_run_to_row(run)` | `ResearchRun -> DashboardRunRow`。 |
| `_run_from_row(row)` | `DashboardRunRow -> ResearchRun`。 |
| `_item_to_row(item)` | `ResearchItem -> DashboardItemRow`。 |
| `_item_from_row(row)` | `DashboardItemRow -> ResearchItem`。 |

---

## 6. FastAPI 端点

定义文件：`src/margin/api/routes/dashboard.py`。

路由前缀：`/api/v1`，Tag：`dashboard`。

依赖：`Services = Annotated[DashboardServiceBundle, Depends(get_dashboard_services)]`。

请求模型：

- `ResearchRunCreate`：`strategy_id`（必填）、`version_id`（默认 `default`）、`decision_at`、`portfolio_id`、`symbols`。
- `FeedbackCreate`：`feedback_type`（默认 `comment`）、`comment`。

| 方法 | 路径 | 说明 | 请求 | 响应 |
| --- | --- | --- | --- | --- |
| `GET` | `/research-runs` | 列出研究运行 | Query: `strategy_id`、`portfolio_id`、`status`、`limit` | `list[ResearchRun]` |
| `POST` | `/research-runs` | 触发同步研究运行 | Body: `ResearchRunCreate` | `ResearchRun`（201） |
| `GET` | `/research-runs/{run_id}` | 获取单个运行 | Path: `run_id` | `ResearchRun` |
| `GET` | `/research-runs/{run_id}/items` | 获取运行的研究项 | Path: `run_id` | `list[ResearchItem]` |
| `GET` | `/research-runs/{run_id}/cards` | 获取运行的候选卡片 | Path: `run_id` | `list[CandidateCard]` |
| `GET` | `/research-home` | 首页摘要 | Query: `strategy_id`、`portfolio_id` | `HomeSummary` |
| `GET` | `/research-items/{item_id}` | 获取单个研究项 | Path: `item_id` | `ResearchItem` |
| `GET` | `/research-items/{item_id}/evidence` | 证据展开 | Path: `item_id` | `EvidenceView` |
| `GET` | `/research-items/{item_id}/valuation` | 估值视图 | Path: `item_id` | `ValuationView` |
| `GET` | `/research-items/{item_id}/audit` | 审计追溯 | Path: `item_id` | `AuditView` |
| `GET` | `/research-items/{item_id}/report` | 渲染报告 | Path: `item_id` | `ResearchReport` |
| `GET` | `/research-items/{item_id}/export` | 导出报告 | Path: `item_id`、Query: `format` | `ReportExport` |
| `POST` | `/research-items/{item_id}/feedback` | 提交反馈 | Path: `item_id`、Body: `FeedbackCreate` | `FeedbackRecord`（201） |
| `GET` | `/provider-status` | Provider 健康状态 | - | `list[ProviderStatus]` |
| `POST` | `/jobs/nightly-runs` | 触发夜间运行并记录任务 | Body: `ResearchRunCreate` | `JobRun`（201） |
| `GET` | `/jobs/{job_run_id}` | 获取任务记录 | Path: `job_run_id` | `JobRun` |

错误处理：所有按 ID 查询的端点在 `KeyError` 时转换为 `HTTPException(404)`。

---

## 7. Next.js 页面与 Server Actions

### 7.1 `ResearchDashboardPage`

文件：`web/app/research/page.tsx`

- 导出 `dynamic = "force-dynamic"`，禁用默认缓存。
- 并发拉取 `fetchResearchHome()`、`fetchResearchRuns()`、`fetchProviderStatus()`。
- 若存在最新运行，再拉取 `fetchResearchRunCards(runs[0].run_id)`。
- 出错时显示“研究候选数据暂时不可用”。
- 渲染结构：
  - `ResearchRunForm`（提交 `createResearchRunAction`）
  - `ProviderStatusPanel`
  - `HomeSummary`
  - 今日候选区 + `CandidateList`

### 7.2 `ResearchRunPage`

文件：`web/app/research/runs/[runId]/page.tsx`

- 接收 `params: Promise<{ runId: string }>`。
- 并发拉取 `fetchResearchRun(runId)` 与 `fetchResearchRunCards(runId)`。
- 出错时显示“研究运行数据暂时不可用”。
- 页面标题显示 `run_id`、状态与项数。
- 渲染 `CandidateList`。

### 7.3 `ResearchItemPage`

文件：`web/app/research/items/[itemId]/page.tsx`

- 接收 `params: Promise<{ itemId: string }>`。
- 并发拉取：
  - `fetchResearchItem`
  - `fetchResearchItemEvidence`
  - `fetchResearchItemValuation`
  - `fetchResearchItemAudit`
  - `fetchResearchItemReport`
  - `fetchResearchItemExport(itemId, "json")`
- 出错时显示“研究详情暂时不可用”。
- 渲染结构：
  - 标题 + `ResearchStatusBadge`
  - 研究结论区（置信度、运行 ID、Snapshot ID、Trace 数）
  - `ValuationPanel`
  - `EvidencePanel`
  - `ReportPanel`
  - `ResearchFeedbackForm`（绑定 `createResearchFeedbackAction(itemId)`）

### 7.4 `createResearchRunAction`

文件：`web/app/research/actions.ts`

- Server Action。
- 从 `FormData` 提取 `strategy_id`（必填）、`version_id`（必填）、`portfolio_id`、`symbols`。
- `symbols` 按空白、逗号、分号、中英文逗号分号拆分。
- 调用 `createResearchRun(...)` 创建运行。
- 成功后 `revalidatePath("/research")` 并重定向到 `/research/runs/${run.run_id}`。

### 7.5 `createResearchFeedbackAction`

文件：`web/app/research/items/[itemId]/actions.ts`

- Server Action，签名为 `(itemId: string, formData: FormData) => void`。
- 解析 `feedback_type`（限定 `accept`、`reject`、`watch`、`comment`，非法默认 `comment`）。
- 提取 `comment`。
- 调用 `createResearchItemFeedback(itemId, ...)`。
- 成功后 `revalidatePath(`/research/items/${itemId}`)`。

---

## 8. React 组件

### 8.1 `CandidateCard`

文件：`web/components/candidate-card.tsx`

| Props | 类型 | 说明 |
| --- | --- | --- |
| `card` | `ResearchCandidateCard` | 单个候选卡片数据。 |

行为：

- 标题 `symbol` 链接到 `/research/items/${card.item_id}`。
- 显示 `ResearchStatusBadge` 与 `PositionReviewBadge`。
- 展示结论语句、置信度、估值区间、价值陷阱风险分、证据数量。
- 若存在反方理由，渲染“最强反方理由”列表。
- 底部展示策略版本与免责声明。

内部辅助：

- `moneyRange(range)`：把 `[min, max]` 格式化为 `¥x.xx – ¥x.xx`，空则返回“估值暂不可用”。
- `score(value)`：把 0~1 数值格式化为百分比，空则返回 `--`。

### 8.2 `CandidateList`

文件：`web/components/candidate-list.tsx`

| Props | 类型 | 说明 |
| --- | --- | --- |
| `cards` | `ResearchCandidateCard[]` | 候选卡片数组。 |

行为：空数组时显示“暂无研究候选”；否则以网格渲染 `CandidateCard`。

### 8.3 `EvidencePanel`

文件：`web/components/evidence-panel.tsx`

| Props | 类型 | 说明 |
| --- | --- | --- |
| `evidence` | `EvidenceView \| null` | 证据视图数据。 |

行为：

- 若 `evidence` 不存在或 `locators_available=false`，显示“证据暂不可用”。
- 左栏展示 `claims`（结论、事实/推断、置信度）。
- 右栏展平 `evidence_by_level`，展示每个证据的 ID、章节、页码、原文链接。

### 8.4 `ReportPanel`

文件：`web/components/report-panel.tsx`

| Props | 类型 | 说明 |
| --- | --- | --- |
| `report` | `ResearchReport \| null` | 渲染后的报告。 |
| `exported` | `ReportExport \| null` | 导出载荷。 |

行为：

- 无报告时显示“报告暂不可用”。
- 展示报告标题、导出文件名、MIME 类型。
- 若存在 `exported`，提供 `data:` URL 下载链接。
- 以 `<pre>` 展示 Markdown 前 8 行预览。

### 8.5 `ValuationPanel`

文件：`web/components/valuation-panel.tsx`

| Props | 类型 | 说明 |
| --- | --- | --- |
| `valuation` | `ValuationView \| null` | 估值视图数据。 |

行为：

- 无数据时显示“估值数据暂不可用”。
- 展示基准估值区间、悲观估值区间、价值陷阱风险分、估值方法与说明。

### 8.6 `HomeSummary`

文件：`web/components/home-summary.tsx`

| Props | 类型 | 说明 |
| --- | --- | --- |
| `summary` | `ResearchHomeSummary \| null` | 首页摘要数据。 |

行为：渲染六个摘要卡片：市场状态摘要、今日候选、现有持仓复核、高优先级风险、拒绝判断、策略运行状态。

### 8.7 `ResearchStatusBadge`

文件：`web/components/research-status-badge.tsx`

| Props | 类型 | 说明 |
| --- | --- | --- |
| `status` | `string` | 状态字符串。 |

行为：

- 标签映射：`published`/`research_candidate` → 已发布/研究候选；`abstained` → 已拒绝；`aborted` → 已中止；`data_missing` → 数据缺失；`watch` → 观察。
- 根据状态自动选择视觉样式 `positive`、`watch`、`data_missing`。

### 8.8 `ResearchRunForm`

文件：`web/components/research-run-form.tsx`

| Props | 类型 | 说明 |
| --- | --- | --- |
| `action` | `(formData: FormData) => void \| Promise<void>` | 表单提交 Action。 |

行为：

- 包含字段：策略 ID（默认 `default`）、策略版本（默认 `v0.1`）、组合 ID（默认 `demo`）、标的代码（多行文本）。
- 提交按钮“启动研究运行”。

### 8.9 `ResearchFeedbackForm`

文件：`web/components/research-feedback-form.tsx`

| Props | 类型 | 说明 |
| --- | --- | --- |
| `action` | `(formData: FormData) => void \| Promise<void>` | 表单提交 Action。 |

行为：

- 下拉选择反馈类型：采纳、拒绝、加入观察、备注。
- 多行文本输入反馈说明。
- 提交按钮“提交研究反馈”。

### 8.10 `ProviderStatusPanel`

文件：`web/components/provider-status-panel.tsx`

| Props | 类型 | 说明 |
| --- | --- | --- |
| `providers` | `ProviderStatus[]` | Provider 状态列表。 |
| `title` | `string` | 可选标题，默认 `Provider 状态`。 |

行为：

- 显示 Provider 名称、消息、状态徽章。
- 空列表时显示“暂无 Provider 状态”。

### 8.11 `PageLoading`

文件：`web/components/page-loading.tsx`

| Props | 类型 | 说明 |
| --- | --- | --- |
| `eyebrow` | `string` | 顶部小标题。 |
| `title` | `string` | 页面标题。 |

行为：显示通用骨架屏，包含页面标题、状态条、四个统计占位矩形与两个面板占位。

### 8.12 `PositionReviewBadge`

文件：`web/components/position-review-badge.tsx`

| Props | 类型 | 说明 |
| --- | --- | --- |
| `status` | `string \| null` | 持仓复核状态。 |

行为：

- 映射 `THESIS_VALID`、`REVIEW_REQUIRED`、`RISK_ALERT`、`THESIS_INVALIDATED` 为中文标签。
- `null` 时显示“未绑定组合”。
- 根据状态选择视觉样式。

---

## 9. 跨模块使用说明

- **依赖模块 06（`margin.research`）**：`DashboardResearchService` 调用 `ResearchService.run()`；证据、估值、审计、报告均通过 `ResearchRepository.get_snapshot()` 读取模块 06 快照。涉及类型包括 `WorkflowResult`、`WorkflowState`、`SignalType`。
- **依赖模块 05（`margin.news`）**：模型时间戳使用 `margin.news.models` 中的 `utc_now` 与 `ensure_utc`。
- **依赖 FastAPI 依赖注入**：`margin.api.dependencies.get_dashboard_services` 构建 `DashboardServiceBundle`，创建 `SQLAlchemyDashboardRepository`、`SQLAlchemyResearchRepository`、生产级 `ResearchService` 与 Provider 状态列表，并通过 `lru_cache` 缓存。
- **前端 API 映射**：`web/lib/api.ts` 封装了 `/api/v1` 下所有面板相关端点，类型定义与后端 Pydantic 模型保持一致。
- **Next.js Server Actions**：使用 `revalidatePath` 刷新相关路由缓存；运行创建后通过 `redirect` 跳转到详情页。
- **与模块 09（holdings_monitoring）的关系**：模块 09 复用相同的依赖注入与前端 API 风格，但聚焦持仓监控与复核，研究项的 `position_review_status` 字段为后续跨模块集成预留。
- **Provider 状态**：`ProviderStatusService` 接收 `margin.api.dependencies.build_provider_status_providers` 构建的 Provider 列表，包含 LLM、Embedding、WebSearch、Rerank，缺失配置时以 `degraded` / `unhealthy` 占位，确保前端可见。
