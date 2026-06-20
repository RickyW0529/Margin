# AGENTS.md — Margin 项目协作约定

本文件定义 Margin 项目的文档目录结构、模块编号、版本迭代和验证规则。所有 agent 与协作者必须遵循本约定，保证设计可审计、代码文档与实现一致。

---

## 1. 仓库目录结构

```
Margin/
├── AGENTS.md                         本文件，协作约定
└── docs/
    ├── README.md                     总索引与版本演进表
    ├── design/                       设计稿（产品 + 架构，中英双语）
    │   └── <version>/                版本目录，如 v0.1
    │       ├── README.md
    │       ├── product/
    │       └── architecture/
    └── code/                         当前代码说明，不按产品版本分目录
        ├── README.md
        ├── en/
        └── NN-module.md
```

- 仅维护 `docs/design/` 与 `docs/code/` 两类正式项目文档。
- `docs/design/` 使用产品版本目录并承担历史审计职责。
- `docs/code/` 始终描述当前代码，不建立 `code/v0.1`、`code/v0.2` 等目录。
- 不再建立或维护正式的 `docs/spec/`、`docs/plan/`。
- Superpowers 生成的临时 spec、plan 等开发过程文档统一放在 `docs/superpowers/`，该目录必须被 Git 忽略，不属于正式文档。

---

## 2. 文档更新规则

- 产品大版本格式：`v<major>.<minor>`，如 `v0.1`、`v0.2`。这里的“大版本”指正式产品迭代，不是单个功能、任务或提交。
- `design/` 仅在启动新的产品大版本时建立新目录；普通功能开发不得新增 design 版本。
- `design/<version>` 必须从上一产品大版本设计复制后进行增量迭代，保留旧版本完整内容，并在新版本 README 与设计正文中明确增量范围。
- `code/` 不使用产品版本号，也不承担历史审计职责；每次功能代码完成后必须同步更新 `docs/code/`，使其始终表示当前仓库的最新实现状态。
- 新增 `design/<version>` 意味着一次可审计设计快照。旧版本设计目录不得删除或被新版本内容覆盖。
- 文件名中产品标识一律使用当前版本号（如 `Margin_产品设计_v0.1_中文.md`），不使用 `V2` 等历史标识。

---

## 3. 模块编号规则（NN）

功能模块来自产品设计文档 §13.2「按功能模块打通」，固定编号：

| 编号 | 模块名（英文 slug） | 中文名 |
|------|----------------------|--------|
| 01 | data_provider | 数据 Provider 模块 |
| 02 | holdings | 持仓模块 |
| 03 | filing_websearch | 公告与 WebSearch 模块 |
| 04 | text_indexing | 文本索引模块 |
| 05 | rag_evidence | RAG 证据模块 |
| 06 | multi_agent_research | 多 Agent 研究流程模块 |
| 07 | strategy_config | 策略配置模块 |
| 08 | research_candidate_dashboard | 研究候选面板模块 |
| 09 | holdings_monitoring | 持仓监控模块 |
| 10 | deployment_audit | 部署与审计模块 |
| 11 | valuation_discovery | 公司池与估值发现模块 |

- 模块编号一旦分配不再变更。新增模块续编为 11、12…
- 目录命名：`NN-module_slug`，如 `01-data_provider`。

---

## 4. 溯源与可审计约定

- 设计文档状态取值：`draft` → `review` → `active` → `deprecated`。
- 每个版本设计必须说明上一版本基线、本版本增量、验收标准、风险与降级边界。
- 研究信号、策略版本、数据快照等运行时产物遵循架构设计 §5.4「不可变研究信号快照」要求，落库后不可篡改。
- 修改已 `active` 设计的产品边界时，应新建版本目录，不回写旧版本。
- `docs/code/` 与当前实现不一致时，以源码和测试为准，并在同一变更中修正文档。

---

## 5. 版本设计与开发流程

1. 新产品大版本启动时，先复制上一版本 `design/<previous_version>/` 到 `design/<new_version>/`；
2. 用户与 agent 共同打磨新版本产品设计和架构设计，明确范围、模块边界、接口、数据流、验收标准、风险与降级；
3. 设计确认后，才允许进入开发拆解；
4. 使用 Superpowers 将已确认设计拆成临时 spec 和详细 plan，统一写入被 Git 忽略的 `docs/superpowers/`；
5. spec 必须按功能模块拆分：一个模块一份独立 spec；跨模块能力拆成多份模块 spec，并明确接口、依赖与实施顺序，禁止把整个版本写成一份巨型 spec；
6. plan 必须对应具体模块 spec 拆解到可实现、可测试的任务；一个 plan 只负责一个明确模块或一个边界清晰的模块内增量；
7. 按 plan 完成功能代码、数据库迁移、测试和必要的端到端验证；
8. 每个功能完成时，在同一变更中更新对应的无版本 `docs/code/NN-module.md`；公共能力同步更新 `docs/code/00-shared.md`，索引变化同步更新 `docs/code/README.md` 与英文文档；
9. `docs/code/` 只描述已经实现并验证的当前状态，不记录尚未实现的设计目标；
10. 更新 `docs/README.md` 版本演进表、本文件当前状态及相关索引；
11. 旧版本 `design/` 目录完整保留，不得删除；只有被新版本正式替代时才将旧设计状态标记为 `deprecated`。

建议的临时过程文档结构：

```text
docs/superpowers/
├── specs/
│   └── <version>/
│       └── NN-module_slug.md
└── plans/
    └── <version>/
        └── NN-module_slug.md
```

---

## 6. 当前版本

- 当前已实现版本：`v0.1`
- 当前设计迭代版本：`v0.2`
- v0.2 设计稿：`docs/design/v0.2/`（由 v0.1 设计复制后增量更新）
- 当前代码说明：`docs/code/`（无版本目录，随代码持续更新）
- 正式文档范围：`docs/design/`、`docs/code/`
- 忽略的过程文档：`docs/superpowers/`

## 7. lint / typecheck 命令

项目进入实现阶段后，每次变更必须运行以下命令：

```bash
# 安装（含 dev 与数据 Provider 依赖）
pip install -e ".[dev,data]"

# lint
ruff check src tests

# 测试
pytest

# 自动修复 import 排序等可自动修复的 lint 问题
ruff check --fix src tests
```

- `ruff check` 必须 0 error。
- `pytest` 必须全绿。
- 当前已实现子任务：`0101-provider_registry`、`0102-akshare_tushare_access`、`0103-field_standardization`、`0104-point_in_time_and_quality`、`0201-manual_csv_import`、`0202-cost_and_position`、`0203-basic_dashboard`、`0301-filing_acquisition`、`0302-websearch_provider`、`0303-dedup_and_compliance`、`0401-parse_and_chunk`、`0402-embedding_pipeline`、`0403-hybrid_recall`、`0501-evidence_tiering`、`0502-citation_locator`、`0503-claim_validation`、`0601-provider_and_tools`、`0602-websearch_agent`、`0603-summary_agent`、`0604-reflect_agent`、`0605-citation_validator`、`0606-universe_quant_agent`、`0701-strategy_template`、`0702-custom_prompt`、`0703-version_management`、`0801-candidate_card`、`0802-evidence_expansion`、`0803-rejection_reason`、`0901-thesis_state`、`0902-alerts`、`0903-review_record`、`1001-docker_compose`、`1002-storage_snapshot`、`1003-logging_observability`、`1004-failure_degradation`。
- `0203-basic_dashboard` 已补齐 PostgreSQL repository、FastAPI 端点、Next.js App Router 面板、前端测试与 build 验证。
- `0301-filing_acquisition` 已补齐 PostgreSQL 游标/快照/事件/outbox、SSE/SZSE discovery adapter、增量 runner 与 DocumentEventPublisher；真实交易所实网 smoke 需要网络与目标站点可访问。
- `0302-websearch_provider` 已补齐 Tavily adapter、robots 执行、查询/结果持久化与原文校验前审计；实网 smoke 需要 `MARGIN_WEBSEARCH_API_KEY`。
- `0303-dedup_and_compliance` 已补齐向量相似度回调、跨进程持久化去重决策与转载链。
- `0401-parse_and_chunk` 已补齐结构化 HTML/PDF/CSV/JSON/Text parser、表格/页码/quote_span 定位与 structured block 分块。
- `0402-embedding_pipeline` 已补齐 OpenAI-compatible EmbeddingProvider、pgvector 持久化 chunk/vector/index audit；实网 smoke 需要 `MARGIN_EMBEDDING_API_KEY`、`MARGIN_EMBEDDING_BASE_URL`、`MARGIN_EMBEDDING_MODEL`、`MARGIN_EMBEDDING_DIMENSION`。
- `0403-hybrid_recall` 已补齐 HTTP RerankProvider、持久化检索 audit 与 replay；实网 smoke 需要 `MARGIN_RERANK_API_KEY`、`MARGIN_RERANK_BASE_URL`、`MARGIN_RERANK_MODEL`。
- `0501-evidence_tiering` 已补齐 Evidence/Claim 结构、source level 质量评分、locator 快照字段、跨 Claim 冲突检测、L4/L5 限制与 PostgreSQL append-only Claim/Evidence 持久化。
- `0502-citation_locator` 已补齐 PDF/HTML/表格 locator、PIT 校验、WebSearch 原文/快照校验与 snapshot resolver，可接 `NewsRepository.get_snapshot` 校验快照 URL/hash/status。
- `0503-claim_validation` 已补齐 CitationValidator 批量冲突校验、引用失败具体 FAIL reason、ABSTAINED 判定、反方审查标记、校验审计持久化与 `research_evidence` 关联表。
- `0601`-`0606` 已补齐多 Agent 研究工作流、工具调用、摘要/反思/校验链路、研究快照与持久化审计；`signal_composer` 正常路径优先真实 LLM，硬性降级或 LLM 失败时使用规则输出；`risk_review` / `reflect_counter_argument` 逐条证据引用属于 v0.2。
- `0701`-`0703` 已补齐策略模板、自定义 Prompt、版本生命周期、校验/沙箱执行与 API 持久化。
- `0801`-`0803` 已补齐研究候选面板 Candidate Card、证据展开、估值/反方/反馈视图、调度入口、Provider 状态、API 与 Next.js 页面；`/api/v1/provider-status` 真实探测 LLM/Embedding，并显式展示 Tavily/Rerank 缺配置 degraded。
- `0901`-`0903` 已补齐持仓健康状态判定、确定性盘中规则引擎、P0-P3 提醒、alert_event 持久化、复盘记录、操作历史与处理时长度量。
- `1001`-`1004` 已补齐 migrate/seed/web/api/worker/postgres/prometheus/grafana 一键部署、测试库隔离、不可变审计、结构化日志、Trace/指标、Grafana dashboard、Provider 降级与 CI 验证。
