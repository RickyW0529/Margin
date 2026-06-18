# AGENTS.md — Margin 项目协作约定

本文件定义 Margin 项目的文档目录结构、spec/plan 模板规范、编号规则与版本迭代规则。所有 agent 与协作者在新增或修改 spec/plan 时必须遵循本约定，保证可审计与版本可迭代。

---

## 1. 仓库目录结构

```
Margin/
├── AGENTS.md                         本文件，协作约定与模板规范
└── docs/
    ├── README.md                     总索引与版本演进表
    ├── design/                       设计稿（产品 + 架构，中英双语）
    │   └── <version>/                版本目录，如 v0.1
    │       ├── README.md
    │       ├── product/
    │       └── architecture/
    ├── spec/                         功能规格，按功能模块
    │   └── <version>/
    │       ├── README.md
    │       └── NN-module/spec.md
    └── plan/                         实施计划，按模块拆子任务
        └── <version>/
            ├── README.md
            └── NN-module/NNKK-task.md
```

- `<version>` 同时表示文档版本与产品版本（如 v0.1）。后续版本（v0.2、v0.3…）按同样结构新建版本目录，不复用旧目录。
- 设计稿、spec、plan 三者版本号必须一致。

---

## 2. 版本号规则

- 版本号格式：`v<major>.<minor>`，如 `v0.1`。
- 版本号 = 文档版本 = 产品版本。三者统一，不分离。
- 新增一个版本目录意味着一次可审计的快照。修改旧版本目录内的内容需同步更新该目录 README 的变更说明，并尽量新建版本而非就地覆盖。
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

- 模块编号一旦分配不再变更。新增模块续编为 11、12…
- 目录命名：`NN-module_slug`，如 `01-data_provider`。

---

## 4. 子任务编号规则（NNKK）

- 子任务编号 = 模块编号（NN）+ 模块内序号（KK），共 4 位，如 `0102` = 模块 01 的第 2 个子任务。
- 子任务编号取自架构设计文档 §26「实施顺序」Gantt 中的任务项，保证可追溯到设计稿。
- 文件命名：`NNKK-task_slug.md`，如 `0102-akshare_tushare_access.md`。
- 子任务的工作项在 plan 文件内再以 `NNKK.N` 细分（如 `0102.1`、`0102.2`）。

---

## 5. spec.md 模板

每个模块一份 `spec/v0.1/NN-module/spec.md`，使用以下 frontmatter 与章节：

```markdown
---
module_id: NN-module_slug
product_version: v0.1
doc_version: v0.1
source_refs: [产品设计 §X.Y; 架构设计 §Z]
status: draft
---

# NN 模块中文名 — 功能规格

## 1. 模块目标
本模块要解决的问题与交付边界。

## 2. 输入 / 输出
输入数据、触发条件；输出产物、消费方。

## 3. 接口契约
对外接口、Provider 协议、API 端点或函数签名。

## 4. 数据模型
涉及的数据库实体、字段、时点字段、不可变快照。

## 5. 与其他模块依赖
上游依赖、下游消费、循环依赖规避。

## 6. 验收标准
对应产品设计 §15「产品验收标准」的条目编号与具体可测条件。

## 7. 风险与降级
对应架构设计 §25「故障降级」的降级策略。

## 8. 审计追溯
source_refs 指向的设计稿章节、不可变快照要求、版本追溯链。
```

---

## 6. plan.md（子任务）模板

每个子任务一份 `plan/v0.1/NN-module/NNKK-task.md`，使用以下 frontmatter 与章节：

```markdown
---
task_id: NNKK
parent_module: NN-module_slug
product_version: v0.1
doc_version: v0.1
source_refs: [架构设计 §26-PhaseN: 任务名]
status: draft
estimate_days: N
depends_on: [NNKK, ...]
---

# NNKK 任务名 — 实施计划

## 1. 任务目标
本子任务要交付的具体成果。

## 2. 工作项拆解
- NNKK.1 工作项名称 — 说明
- NNKK.2 工作项名称 — 说明

## 3. 依赖关系
前置任务（depends_on）、被依赖任务、外部依赖。

## 4. 工时估算
按工作项给出天数，合计对齐 estimate_days。

## 5. 里程碑与交付物
可验证的阶段性产出。

## 6. 验收动作
如何确认本子任务完成（对应 spec 验收标准条目）。

## 7. 审计追溯
source_refs、关联 spec 模块、不可变产物。
```

---

## 7. 溯源与可审计约定

- 每个 spec 与 plan 必须在 frontmatter `source_refs` 中标注来源的设计稿章节，保证可从实施文件回溯到设计依据。
- `status` 字段取值：`draft` → `review` → `active` → `deprecated`。
- 研究信号、策略版本、数据快照等运行时产物遵循架构设计 §5.4「不可变研究信号快照」要求，落库后不可篡改。
- 修改已 `active` 的 spec/plan 应新建版本目录而非就地覆盖，旧版本保留供审计。

---

## 8. 版本迭代流程

1. 新版本启动时，在 `design/`、`spec/`、`plan/` 下新建 `<version>/` 目录；
2. 复制或迁移上一版本设计稿到新目录，更新版本号与变更说明；
3. 按新版本范围重写或新增 spec/plan，模块编号沿用不变；
4. 更新 `docs/README.md` 版本演进表与本文件相关条目；
5. 旧版本目录保留，`status` 标记为 `deprecated`，不得删除。

---

## 9. 当前版本

- 当前版本：`v0.1`
- 设计稿：`docs/design/v0.1/`
- spec：`docs/spec/v0.1/`（10 个模块）
- plan：`docs/plan/v0.1/`（35 个子任务）

## 10. lint / typecheck 命令

项目进入实现阶段后，每次变更必须运行以下命令：

```bash
# 安装（含 dev 依赖）
pip install -e ".[dev]"

# lint
ruff check src tests

# 测试
pytest

# 自动修复 import 排序等可自动修复的 lint 问题
ruff check --fix src tests
```

- `ruff check` 必须 0 error。
- `pytest` 必须全绿。
- 当前已实现子任务：`0101-provider_registry`、`0102-akshare_tushare_access`、`0103-field_standardization`、`0104-point_in_time_and_quality`、`0201-manual_csv_import`、`0202-cost_and_position`。
- 部分实现：`0203-basic_dashboard` 已有 PortfolioService 与概览/明细模型，FastAPI 端点和 Next.js 页面待实现。
- 部分实现：`0301-filing_acquisition` 已有来源注册、下载、快照、解析和证券映射，Scheduler、增量游标、真实交易所 Connector、表格定位与 Event Publisher 待实现。
- 部分实现：`0302-websearch_provider` 已有 Provider、Secret 注入、原文校验与快照审计，真实搜索 API 适配、robots 执行和查询记录持久化待实现。
- 部分实现：`0303-dedup_and_compliance` 已有 URL/哈希/标题时间/SimHash 去重和来源评分，向量相似度与持久化转载链待实现。
