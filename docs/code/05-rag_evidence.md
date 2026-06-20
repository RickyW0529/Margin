# 05-rag_evidence 模块文档

## 目录

- [1. 模块概览](#1-模块概览)
- [2. 文件级摘要](#2-文件级摘要)
- [3. 领域模型](#3-领域模型)
  - [3.1 Evidence](#31-evidence)
  - [3.2 Claim](#32-claim)
  - [3.3 ConflictRecord](#33-conflictrecord)
  - [3.4 工厂与辅助函数](#34-工厂与辅助函数)
  - [3.5 detect_conflicts](#35-detect_conflicts)
  - [3.6 check_l5_restriction](#36-check_l5_restriction)
- [4. 引用定位器 (Locator)](#4-引用定位器-locator)
  - [4.1 SourceType](#41-sourcetype)
  - [4.2 CitationLocator](#42-citationlocator)
  - [4.3 WebSearchVerificationResult](#43-websearchverificationresult)
  - [4.4 PointInTimeCheckResult](#44-pointintimecheckresult)
  - [4.5 LocatorValidationResult](#45-locatorvalidationresult)
  - [4.6 构建函数](#46-构建函数)
  - [4.7 校验函数](#47-校验函数)
- [5. 校验器 (Validator)](#5-校验器-validator)
  - [5.1 ValidationStatus / FailReason](#51-validationstatus--failreason)
  - [5.2 ValidationResult](#52-validationresult)
  - [5.3 ValidationAuditRecord](#53-validationauditrecord)
  - [5.4 ValidationAuditor](#54-validationauditor)
  - [5.5 ValidationReport](#55-validationreport)
  - [5.6 CitationValidator](#56-citationvalidator)
  - [5.7 validate_claims_with_audit](#57-validate_claims_with_audit)
- [6. 仓库 (Repository)](#6-仓库-repository)
  - [6.1 ResearchEvidenceLink](#61-researchevidencelink)
  - [6.2 EvidenceRepository](#62-evidencerepository)
  - [6.3 行映射辅助函数](#63-行映射辅助函数)
- [7. 跨模块使用说明](#7-跨模块使用说明)

---

## 1. 模块概览

`05-rag_evidence` 是 Margin 当前实现 的 RAG 证据子系统，负责把检索到的原始文本块 (Chunk) 转换为可审计、可定位、可验证的证据记录 (Evidence)，并在此基础上生成结构化 Claim，完成冲突检测、引用校验与持久化。

核心职责：

- 将 `04-text_indexing` 产出的 Chunk 封装为 `Evidence`，保留完整的来源定位字段。
- 定义 `Claim` 模型，对研究结论做事实/推断标记、证据引用、置信度与冲突记录。
- 提供 `CitationLocator` 及其构建函数，支持 PDF、HTML、表格等多源引用定位。
- 校验引用：时点检查 (point-in-time)、WebSearch 原文落地校验、定位可达性校验。
- 检测证据冲突并执行置信度封顶 (conflict cap)。
- 执行 L5 来源使用限制：L5 证据只能触发进一步调查，不能直接改变研究/持仓状态。
- 通过 `EvidenceRepository` 将 Evidence、Claim、ValidationAudit、ResearchEvidenceLink 持久化到 PostgreSQL。

对应设计：

- 产品与架构边界见对应大版本的 `docs/design/`
- 当前实现重点对应 architecture §4.5、§5.3、§6.1、§6.2.1、§10.1、§10.2、§10.3、§25

---

## 2. 文件级摘要

| 文件 | 职责 |
| --- | --- |
| `src/margin/evidence/__init__.py` | 暴露模块公共 API，聚合 models、locator、validator、repository 的导出符号。 |
| `src/margin/evidence/models.py` | 领域模型：`Evidence`、`Claim`、`ConflictRecord`、`ClaimType`、`FactOrInference`、`ConflictSeverity`；冲突检测、`L5` 限制、质量分映射等核心逻辑。 |
| `src/margin/evidence/locator.py` | `CitationLocator` 及其按 PDF/HTML/表格构建函数；WebSearch 原文校验、时点检查、综合定位校验。 |
| `src/margin/evidence/validator.py` | `CitationValidator`、`ValidationReport`、`ValidationAuditor` 等；实现 Claim 级校验、冲突封顶、ABSTAINED 降级与审计记录。 |
| `src/margin/evidence/repository.py` | `EvidenceRepository`：基于 SQLAlchemy 的 PostgreSQL 持久化边界，支持 Evidence、Claim、ValidationAudit、ResearchEvidenceLink 的写入与查询。 |
| `src/margin/evidence/db_models.py` | SQLAlchemy ORM 行模型：`EvidenceRecordRow`、`EvidenceClaimRow`、`EvidenceValidationAuditRow`、`ResearchEvidenceRow`。 |

---

## 3. 领域模型

### 3.1 Evidence

`Evidence` 对应架构 §5.3 中的 `EVIDENCE_CLAIM` 实体，由 `04-text_indexing` 产出的 Chunk 构建而来，记录来源、内容、定位字段与质量信息。

**类属性**

| 属性 | 类型 | 说明 |
| --- | --- | --- |
| `evidence_id` | `str` | 唯一标识。 |
| `chunk_id` | `str` | 来源 Chunk ID。 |
| `document_id` | `str` | 来源文档 ID。 |
| `source_type` | `str` | 来源类型，如 `filing_pdf`、`web_page`、`table`、`api_record`、`user_file`。 |
| `source_url` | `str \| None` | 原始来源 URL。 |
| `source_name` | `str \| None` | 可读来源名称。 |
| `source_level` | `SourceLevel` | 来源优先级 L1-L5。 |
| `content_hash` | `str` | 内容哈希。 |
| `content` | `str` | 证据文本内容。 |
| `symbol` | `str \| None` | 关联股票代码。 |
| `quality_score` | `float \| None` | 可选质量分 [0, 1]。 |
| `published_at` | `datetime` | 发布时间 (UTC)。 |
| `available_at` | `datetime` | 可用时间 (UTC)。 |
| `retrieved_at` | `datetime` | 检索时间 (UTC)。 |
| `page` | `int \| None` | PDF 页码。 |
| `section` | `str \| None` | 章节名称。 |
| `paragraph_index` | `int \| None` | HTML 段落索引。 |
| `table_id` | `str \| None` | 表格 ID。 |
| `row_id` | `str \| None` | 表格行 ID。 |
| `quote_span` | `tuple[int, int] \| None` | 引用字符区间。 |
| `snapshot_id` | `str \| None` | 快照 ID。 |
| `snapshot_hash` | `str \| None` | 快照内容哈希。 |

**类方法**

| 方法 | 签名 | 说明 |
| --- | --- | --- |
| `normalize_timestamps` | `@field_validator("published_at", "available_at", "retrieved_at")` | 将时间字段统一归一化为 UTC。 |
| `validate_quality_score` | `@field_validator("quality_score")` | 校验质量分是否在 [0, 1] 区间。 |
| `from_chunk` | `classmethod from_chunk(chunk: Any, source_type: str \| None = None) -> Evidence` | 从 Chunk 构造 Evidence；`source_type` 为空时根据 `chunk.doc_type` 推断。 |

**实例属性 (property)**

| 属性 | 返回类型 | 说明 |
| --- | --- | --- |
| `can_change_research_state` | `bool` | 仅 L1-L3 来源可直接改变研究/持仓状态。 |
| `effective_quality_score` | `float` | 显式质量分或按来源等级默认值。 |
| `is_locatable` | `bool` | 是否具备 `source_url` 与至少一个结构定位字段。 |

### 3.2 Claim

`Claim` 是研究结论的封装，包含类型、陈述、事实/推断标记、证据引用、置信度、冲突、生效时点与引用定位快照。

**类属性**

| 属性 | 类型 | 说明 |
| --- | --- | --- |
| `claim_id` | `str` | 唯一标识。 |
| `claim_type` | `ClaimType` | Claim 分类。 |
| `statement` | `str` | 陈述文本。 |
| `fact_or_inference` | `FactOrInference` | `fact` / `inference` / `unknown`。 |
| `evidence_ids` | `list[str]` | 引用的 Evidence ID 列表。 |
| `confidence` | `float` | 置信度 [0, 1]。 |
| `conflicts` | `list[ConflictRecord]` | 关联冲突记录。 |
| `effective_at` | `datetime` | 生效时间 (UTC)。 |
| `locator` | `dict[str, Any] \| None` | 主要引用定位快照。 |
| `symbol` | `str \| None` | 关联股票代码。 |

**类方法**

| 方法 | 签名 | 说明 |
| --- | --- | --- |
| `normalize_effective_at` | `@field_validator("effective_at")` | 将生效时间归一化为 UTC。 |
| `validate_confidence` | `@field_validator("confidence")` | 校验置信度在 [0, 1] 区间。 |

**实例属性 (property)**

| 属性 | 返回类型 | 说明 |
| --- | --- | --- |
| `has_conflict` | `bool` | 是否存在冲突。 |
| `has_evidence` | `bool` | 是否引用证据。 |
| `conflict_confidence_cap` | `float` | 存在冲突时的封顶置信度；高严重冲突封顶 0.3，否则 0.5。 |
| `is_fact` | `bool` | 是否标记为事实。 |
| `is_inference` | `bool` | 是否标记为推断。 |

### 3.3 ConflictRecord

`ConflictRecord` 记录多条证据对同一 Claim 产生相反支撑时的冲突信息。

| 属性 | 类型 | 说明 |
| --- | --- | --- |
| `conflict_id` | `str` | 唯一标识。 |
| `claim_id` | `str` | 所属 Claim ID。 |
| `conflicting_evidence_ids` | `list[str]` | 相互冲突的证据 ID。 |
| `description` | `str` | 人工可读描述。 |
| `severity` | `ConflictSeverity` | 严重级别：`low` / `medium` / `high`。 |

### 3.4 工厂与辅助函数

| 函数 | 签名 | 说明 |
| --- | --- | --- |
| `make_claim` | `make_claim(statement, claim_type=ClaimType.CUSTOM, fact_or_inference=FactOrInference.UNKNOWN, evidence_ids=None, confidence=0.0, conflicts=None, locator=None, symbol=None, effective_at=None) -> Claim` | 自动生成 `claim_id` 创建 Claim。 |
| `make_conflict` | `make_conflict(claim_id, conflicting_evidence_ids, description="", severity=ConflictSeverity.MEDIUM) -> ConflictRecord` | 自动生成 `conflict_id` 创建冲突记录。 |
| `quality_score_for_level` | `quality_score_for_level(source_level: SourceLevel) -> float` | 将来源等级映射为默认质量分：L1=1.0、L2=0.88、L3=0.76、L4=0.52、L5=0.2。 |
| `_infer_source_type` | `_infer_source_type(chunk: Any) -> str` | 根据 `chunk.doc_type` 推断 `source_type`。 |

### 3.5 detect_conflicts

| 项目 | 说明 |
| --- | --- |
| 签名 | `detect_conflicts(claims: list[Claim], evidences: dict[str, Evidence]) -> dict[str, list[ConflictRecord]]` |
| 功能 | 检测 Claim 间的冲突。 |
| 规则 | 1) 同 `claim_type` 且陈述方向相反（如“改善”与“恶化”）视为冲突；2) 同一 Claim 的证据中同时出现 L5 与 L1-L2，视为高严重冲突。 |
| 返回 | `claim_id -> 冲突记录列表` 的映射。 |

### 3.6 check_l5_restriction

| 项目 | 说明 |
| --- | --- |
| 签名 | `check_l5_restriction(claim: Claim, evidences: dict[str, Evidence]) -> bool` |
| 功能 | 校验 L5 使用限制。 |
| 规则 | 若 Claim 仅依赖 L5 证据或无证据，返回 `False`；只要存在一条非 L5 证据，返回 `True`。 |
| 说明 | L5 证据只能触发调查，不能直接改变研究或持仓状态。 |

---

## 4. 引用定位器 (Locator)

### 4.1 SourceType

`SourceType` 枚举定义定位器可识别的来源类型。

| 枚举值 | 说明 |
| --- | --- |
| `FILING_PDF` | `filing_pdf` |
| `WEB_PAGE` | `web_page` |
| `TABLE` | `table` |
| `API_RECORD` | `api_record` |
| `USER_FILE` | `user_file` |

### 4.2 CitationLocator

`CitationLocator` 是统一引用定位结构，字段与 `Evidence` 对齐，支持从 Evidence 或 Chunk 构造。

| 属性 | 类型 | 说明 |
| --- | --- | --- |
| `evidence_id` | `str` | 关联 Evidence ID。 |
| `document_id` | `str` | 来源文档 ID。 |
| `source_type` | `SourceType` | 来源类型。 |
| `source_url` | `str \| None` | 原始 URL。 |
| `source_level` | `SourceLevel` | 来源等级。 |
| `content_hash` | `str` | 内容哈希。 |
| `published_at` | `datetime` | 发布时间。 |
| `available_at` | `datetime` | 可用时间。 |
| `retrieved_at` | `datetime` | 检索时间。 |
| `page` | `int \| None` | 页码。 |
| `section` | `str \| None` | 章节。 |
| `paragraph_index` | `int \| None` | 段落索引。 |
| `table_id` | `str \| None` | 表格 ID。 |
| `row_id` | `str \| None` | 行 ID。 |
| `quote_span` | `tuple[int, int] \| None` | 引用字符区间。 |
| `snapshot_id` | `str \| None` | 快照 ID。 |
| `snapshot_hash` | `str \| None` | 快照哈希。 |

**类方法 / 属性**

| 名称 | 签名 | 说明 |
| --- | --- | --- |
| `normalize_timestamps` | `@field_validator("published_at", "available_at", "retrieved_at")` | 时间归一化为 UTC。 |
| `is_locatable` | `property` | 需要 `source_url` 且至少一个结构定位字段。 |
| `has_snapshot` | `property` | 是否存在 `snapshot_id`。 |
| `from_evidence` | `classmethod from_evidence(evidence: Evidence) -> CitationLocator` | 由 Evidence 构造。 |
| `from_chunk` | `classmethod from_chunk(chunk: Any) -> CitationLocator` | 先转 Evidence，再转 Locator。 |

### 4.3 WebSearchVerificationResult

WebSearch 原文落地校验结果。

| 属性 | 类型 | 说明 |
| --- | --- | --- |
| `evidence_id` | `str` | 被校验 Evidence ID。 |
| `passed` | `bool` | 是否通过。 |
| `reason` | `str` | 结果说明。 |

### 4.4 PointInTimeCheckResult

时点校验结果。

| 属性 | 类型 | 说明 |
| --- | --- | --- |
| `evidence_id` | `str` | 被校验 Evidence ID。 |
| `passed` | `bool` | `available_at <= decision_at` 是否成立。 |
| `reason` | `str` | 说明。 |
| `available_at` | `datetime \| None` | 使用的可用时间。 |
| `decision_at` | `datetime \| None` | 使用的决策时间。 |

### 4.5 LocatorValidationResult

综合定位校验结果。

| 属性 | 类型 | 说明 |
| --- | --- | --- |
| `evidence_id` | `str` | 被校验 Evidence ID。 |
| `is_locatable` | `bool` | 是否可定位。 |
| `pit_passed` | `bool` | 时点检查是否通过。 |
| `websearch_passed` | `bool \| None` | WebSearch 校验结果；非 web_page 来源为 `None`。 |
| `reasons` | `list[str]` | 失败原因列表。 |
| `all_passed` | `property -> bool` | 所有检查是否全部通过。 |

### 4.6 构建函数

| 函数 | 签名 | 说明 |
| --- | --- | --- |
| `build_locator_from_pdf` | `build_locator_from_pdf(chunk: Any, page=None, section=None, quote_span=None) -> CitationLocator` | 针对 PDF 来源，优先使用 `page`、`section`、`quote_span`；参数优先，否则取 chunk 字段。 |
| `build_locator_from_html` | `build_locator_from_html(chunk: Any, paragraph_index=None) -> CitationLocator` | 针对 HTML 来源，设置 `paragraph_index`，清空 `page`、`table_id`、`row_id`。 |
| `build_locator_from_table` | `build_locator_from_table(chunk: Any, table_id=None, row_id=None) -> CitationLocator` | 针对表格来源，设置 `table_id`、`row_id`，保留 `page`，清空 `quote_span`。 |

### 4.7 校验函数

| 函数 | 签名 | 说明 |
| --- | --- | --- |
| `verify_websearch_original` | `verify_websearch_original(locator: CitationLocator, require_snapshot: bool = True, snapshot_resolver: SnapshotResolver \| None = None) -> WebSearchVerificationResult` | 校验 WebSearch 结果是否落到原始页面或合规快照，而非仅引用搜索摘要。 |
| `check_point_in_time` | `check_point_in_time(locator: CitationLocator, decision_at: datetime) -> PointInTimeCheckResult` | 单条时点检查：`available_at <= decision_at`，防止未来数据泄露。 |
| `check_locators_point_in_time` | `check_locators_point_in_time(locators: list[CitationLocator], decision_at: datetime) -> tuple[list[CitationLocator], list[PointInTimeCheckResult]]` | 批量时点检查，返回通过的 Locator 列表与全部结果。 |
| `validate_locator` | `validate_locator(locator: CitationLocator, decision_at: datetime, check_websearch: bool = True, snapshot_resolver: SnapshotResolver \| None = None) -> LocatorValidationResult` | 综合校验：可定位性、时点、WebSearch 原文落地。 |

---

## 5. 校验器 (Validator)

### 5.1 ValidationStatus / FailReason

`ValidationStatus` 枚举：

| 值 | 说明 |
| --- | --- |
| `PASS` | 通过。 |
| `FAIL` | 失败，不进入研究信号。 |
| `ABSTAINED` | 弃权，证据不足或冲突过高。 |

`FailReason` 枚举：

| 值 | 说明 |
| --- | --- |
| `NO_EVIDENCE` | Claim 无证据引用。 |
| `EVIDENCE_NOT_FOUND` | 引用的 Evidence 不存在。 |
| `NOT_LOCATABLE` | 定位器无法回溯原文。 |
| `LOOKAHEAD` | 时点检查失败。 |
| `L5_ONLY` | 仅依赖 L5 证据。 |
| `WEBSEARCH_NO_ORIGINAL` | WebSearch 未落到原文/快照。 |
| `CONFLICT_HIGH` | 高严重冲突。 |
| `INSUFFICIENT_EVIDENCE` | 证据不足。 |
| `L4_NO_CROSS_VALIDATION` | L4 证据缺少 L1-L3 交叉验证。 |

### 5.2 ValidationResult

单条 Claim 的校验结果。

| 属性 | 类型 | 说明 |
| --- | --- | --- |
| `claim_id` | `str` | Claim ID。 |
| `status` | `ValidationStatus` | 校验状态。 |
| `reason` | `str` | 说明。 |
| `fail_reason` | `FailReason \| None` | 失败原因。 |
| `original_confidence` | `float` | 原始置信度。 |
| `capped_confidence` | `float` | 封顶后置信度。 |
| `conflicts_found` | `int` | 发现的冲突数。 |
| `evidences_checked` | `int` | 校验的证据数。 |
| `evidences_passed` | `int` | 通过校验的证据数。 |
| `requires_counter_review` | `bool` | 是否需要反方审查。 |
| `checked_at` | `datetime` | 校验时间。 |
| `should_suppress` | `property -> bool` | 状态为 FAIL/ABSTAINED 时返回 `True`。 |

### 5.3 ValidationAuditRecord

校验审计记录，落库后不可变。

| 属性 | 类型 | 说明 |
| --- | --- | --- |
| `audit_id` | `str` | 审计记录 ID。 |
| `claim_id` | `str` | Claim ID。 |
| `status` / `reason` / `fail_reason` | - | 同 `ValidationResult`。 |
| `original_confidence` / `capped_confidence` | `float` | 原始与封顶置信度。 |
| `conflicts_found` / `evidences_checked` / `evidences_passed` | `int` | 统计信息。 |
| `requires_counter_review` | `bool` | 是否需要反方审查。 |
| `checked_at` | `datetime` | 校验时间。 |

### 5.4 ValidationAuditor

内存审计器，记录每次 `ValidationResult`。

| 方法 / 属性 | 签名 | 说明 |
| --- | --- | --- |
| `log` | `log(result: ValidationResult) -> ValidationAuditRecord` | 记录校验结果并返回审计记录。 |
| `records` | `property -> list[ValidationAuditRecord]` | 返回全部审计记录。 |
| `pass_count` / `fail_count` / `abstained_count` | `property -> int` | 各状态计数。 |

### 5.5 ValidationReport

批量校验报告。

| 属性 | 类型 | 说明 |
| --- | --- | --- |
| `results` | `list[ValidationResult]` | 所有结果。 |
| `total` / `passed` / `failed` / `abstained` | `int` | 统计计数。 |
| `checked_at` | `datetime` | 报告生成时间。 |
| `should_suppress_research` | `property -> bool` | 存在 ABSTAINED、FAIL 或高置信冲突需审查时，停止高置信研究信号输出。 |
| `passed_claims` / `failed_claims` / `abstained_claims` | `property -> list[ValidationResult]` | 按状态筛选结果。 |

### 5.6 CitationValidator

`CitationValidator` 是 Claim 级校验的核心类，执行架构 §10.2 RAG 工作流中的校验步骤。

**初始化参数**

| 参数 | 类型 | 默认值 | 说明 |
| --- | --- | --- | --- |
| `min_evidence_count` | `int` | `1` | Claim 至少需要几条通过校验的证据。 |
| `conflict_cap` | `float` | `0.5` | 普通冲突时的置信度封顶。 |
| `high_conflict_cap` | `float` | `0.3` | 高严重冲突时的置信度封顶。 |
| `high_confidence_threshold` | `float` | `0.7` | 高置信阈值，用于判断是否需要反方审查。 |
| `snapshot_resolver` | `SnapshotResolver \| None` | `None` | 快照查找函数。 |

**方法**

| 方法 | 签名 | 说明 |
| --- | --- | --- |
| `validate_claim` | `validate_claim(claim: Claim, evidences: dict[str, Evidence], decision_at: datetime, precomputed_conflicts: list \| None = None) -> ValidationResult` | 校验单个 Claim：证据存在性、L5 限制、L4 交叉验证、定位与时点校验、冲突封顶。 |
| `validate_batch` | `validate_batch(claims: list[Claim], evidences: dict[str, Evidence], decision_at: datetime) -> ValidationReport` | 批量校验，先调用 `detect_conflicts` 得到冲突映射，再逐条校验。 |
| `_fail` | 内部方法 | 构造 FAIL 结果。 |
| `_abstain` | 内部方法 | 构造 ABSTAINED 结果。 |

**校验流程**

1. 引用存在性：`evidence_ids` 非空且每条 Evidence 存在。
2. 来源等级：L5 不能单独支撑；L4 必须与 L1-L3 交叉验证。
3. 时点：`available_at <= decision_at`。
4. 定位：每条 Evidence 的 locator 可回溯原文。
5. WebSearch 原文落地：`web_page` 类型需有 snapshot。
6. 冲突检测：同类型相反陈述或 L5 与 L1-L2 混用产生冲突，置信度封顶并标记审查。
7. 证据不足：通过校验的证据数少于阈值则 ABSTAINED。

### 5.7 validate_claims_with_audit

| 项目 | 说明 |
| --- | --- |
| 签名 | `validate_claims_with_audit(claims, evidences, decision_at, validator=None, auditor=None) -> tuple[ValidationReport, ValidationAuditor]` |
| 功能 | 便捷函数：批量校验 Claim 并记录审计。 |
| 参数 | `validator` 与 `auditor` 可自定义，否则使用默认实例。 |
| 返回 | `(ValidationReport, ValidationAuditor)`。 |

---

## 6. 仓库 (Repository)

### 6.1 ResearchEvidenceLink

ResearchEvidenceLink 表示研究项、Claim、Evidence 之间的关联。

| 属性 | 类型 | 说明 |
| --- | --- | --- |
| `research_item_id` | `str` | 研究项 ID。 |
| `claim_id` | `str` | Claim ID。 |
| `evidence_id` | `str` | Evidence ID。 |
| `role` | `str` | 角色，如 `support`、`oppose`。 |
| `rank` | `int` | 排序权重。 |
| `created_at` | `datetime` | 创建时间。 |

### 6.2 EvidenceRepository

`EvidenceRepository` 是基于 SQLAlchemy 的 PostgreSQL 持久化边界，所有写入均为追加/幂等，拒绝变更。

**初始化**

| 方法 | 签名 | 说明 |
| --- | --- | --- |
| `__init__` | `__init__(session_factory: Callable[[], Session]) -> None` | 接收返回 SQLAlchemy `Session` 的工厂函数。 |

**方法**

| 方法 | 签名 | 说明 |
| --- | --- | --- |
| `add_evidence` | `add_evidence(evidence: Evidence) -> None` | 幂等写入 Evidence；若已存在且内容不一致则抛出 `ValueError`。 |
| `get_evidence` | `get_evidence(evidence_id: str) -> Evidence \| None` | 按 ID 查询 Evidence。 |
| `add_claim` | `add_claim(claim: Claim) -> None` | 幂等写入 Claim；内容不一致则报错。 |
| `get_claim` | `get_claim(claim_id: str) -> Claim \| None` | 按 ID 查询 Claim。 |
| `add_validation_audit` | `add_validation_audit(audit: ValidationAuditRecord) -> None` | 追加写入审计记录。 |
| `list_validation_audits` | `list_validation_audits(claim_id: str) -> list[ValidationAuditRecord]` | 按 Claim ID  chronological 顺序列出审计记录。 |
| `link_research_evidence` | `link_research_evidence(*, research_item_id, claim_id, evidence_id, role, rank) -> None` | 幂等写入研究-证据关联；`rank` 不一致则报错。 |
| `list_research_evidence` | `list_research_evidence(research_item_id: str) -> list[ResearchEvidenceLink]` | 按研究项列出关联证据，按 `rank`、`created_at` 排序。 |

### 6.3 行映射辅助函数

Repository 内部通过以下私有函数完成 `Pydantic` 模型与 `SQLAlchemy` Row 的双向转换：

| 函数 | 说明 |
| --- | --- |
| `_evidence_to_row` / `_evidence_from_row` | Evidence 与 `EvidenceRecordRow` 互转。 |
| `_claim_to_row` / `_claim_from_row` | Claim 与 `EvidenceClaimRow` 互转；`conflicts` 以 JSON 列表存储。 |
| `_audit_to_row` / `_audit_from_row` | ValidationAuditRecord 与 `EvidenceValidationAuditRow` 互转。 |
| `_research_evidence_from_row` | `ResearchEvidenceRow` 转 `ResearchEvidenceLink`。 |

---

## 7. 跨模块使用说明

### 7.1 与 `04-text_indexing` 的关系

- `Evidence.from_chunk` 接收 `04-text_indexing` 产出的 Chunk，提取 `chunk_id`、`document_id`、`source_url`、`source_level`、`content_hash`、`content` 及定位字段。
- `_infer_source_type` 根据 `chunk.doc_type` 将 `annual_report`、`quarterly_report`、`filing` 映射为 `filing_pdf`，`news` / `ir` 映射为 `web_page`，`user_note` 映射为 `user_file`，含 `table` 的映射为 `table`。

### 7.2 与 `margin.news.models` 的关系

- 复用 `SourceLevel`（L1-L5 枚举）。
- 复用 `RawSnapshot` 类型作为 `SnapshotResolver` 的返回类型。
- 复用 `ensure_utc` / `utc_now` 进行时间归一化。

### 7.3 与 `06-research` 的关系

- `ResearchEvidenceLink` 与 `EvidenceRepository.link_research_evidence` 为研究项 (research_item_id) 与证据/Claim 建立多对多关联。
- 研究模块生成的 Claim 应通过 `CitationValidator` 校验，并通过 `ValidationAuditor` 记录审计，方可进入下游信号。

### 7.4 与 `08-research_candidate_dashboard` / `09-holdings_monitoring` 的关系

- Dashboard 与监控模块可读取 `EvidenceRepository` 中持久化的 Claim、Evidence 与 ValidationAudit，用于展示候选卡片、证据展开、拒绝原因、持仓状态等。
- `ValidationReport.should_suppress_research` 可直接用于控制是否暂停高置信研究信号输出。

### 7.5 典型调用链路

```text
Chunk (04-text_indexing)
  -> Evidence.from_chunk
  -> CitationLocator.from_evidence / build_locator_from_*
  -> validate_locator (时点 + 定位 + WebSearch)
  -> make_claim
  -> CitationValidator.validate_claim / validate_batch
  -> ValidationAuditor.log
  -> EvidenceRepository.add_evidence / add_claim / add_validation_audit
```

### 7.6 不变性约定

- `Evidence`、`Claim`、`CitationLocator` 及其校验结果类均配置 `model_config = {"frozen": True}`，运行时不可变。
- Repository 写入为幂等：相同主键重复写入相同内容会静默通过；内容不一致会抛出 `ValueError`。
- `ValidationAuditRecord` 为追加写，不支持修改。
