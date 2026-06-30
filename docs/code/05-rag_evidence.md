# 05-rag_evidence 当前代码说明

## 1. 模块定位

`src/margin/evidence/` 是 Claim/Evidence 的唯一权威边界。它接收
`04-text_indexing` 已持久化的 Chunk 和 `03-filing_websearch` 的
NewsContextBundle 关联，将它们规范化为不可变、PIT-safe、可重新定位的证据包，
供 `06-multi_agent_research` 消费。

本模块不抓取新闻、不生成 Embedding，也不负责最终投资结论。

## 2. 当前实现

| 文件 | 已实现能力 |
| --- | --- |
| `models.py` | `Evidence`、`Claim`、`EvidencePackage`、Claim/Evidence 角色、Claim 状态、冲突模型与来源等级限制。 |
| `package_builder.py` | 从检索结果构建冻结 EvidencePackage；执行 security link 和 `available_at <= decision_at` 校验；通过 `make_stable_evidence_id` 生成稳定 Evidence ID，并生成稳定 Package ID。 |
| `locator.py` | PDF/HTML/表格统一 locator、PIT 检查、WebSearch 原文快照检查、snapshot hash 与 quote replay。 |
| `validator.py` | Claim 引用存在性、来源等级、PIT、locator、原文快照、冲突与最低证据数校验；输出 PASS/FAIL/ABSTAINED。 |
| `conflicts.py` | 根据结构化 SUPPORTS/REFUTES link 生成确定性高严重度冲突。 |
| `repository.py` | PostgreSQL append-only Evidence/Claim/Package/Conflict/ValidationAudit 持久化及 package revision。 |
| `db_models.py` | v0.2 ORM 表与约束。 |
| `scripts/smoke_rag_evidence.py` | DB-backed sample/indexed-chunk smoke，构建 package、校验 claim 并写入审计。 |

## 3. 核心领域模型

### 3.1 Evidence

Evidence 由一个已持久化 Chunk 规范化生成，保留：

- `evidence_id / chunk_id / document_id`
- `source_type / source_url / source_name / source_level`
- `content / content_hash`
- `symbol`
- `published_at / available_at / retrieved_at`
- `page / bbox / section / paragraph_index / dom_path`
- `table_id / row_id / column_id / quote_span`
- `snapshot_id / snapshot_hash`

Evidence ID 基于 `security_id + chunk_id + snapshot_id + content_hash` 稳定生成。
Chunk 暂无独立持久化 retrieval timestamp，因此 builder 使用不可变
`chunk.available_at` 作为 Evidence 的 `retrieved_at`，保证同一 Chunk 重跑时
append-only 幂等。

### 3.2 EvidencePackage

字段：

```text
package_id / version
security_id / decision_at / scope_hash
questions[]
evidence_ids[] / claim_ids[] / conflict_ids[]
coverage / quality_status / max_available_at
retrieval_audit_id
parent_package_id / added_evidence_ids[]
```

质量状态：

- `USABLE`：本轮请求的检索结果全部形成有效 Evidence。
- `PARTIAL`：只有部分结果通过 PIT/security 校验。
- `ABSTAIN_REQUIRED`：没有可用 Evidence。
- `INVALID`：保留给显式无效包状态。

`EvidencePackageBuilder` 在落库前执行：

1. `chunk.available_at <= decision_at`；
2. Chunk 必须通过 `chunk_security_links` 关联目标公司；
3. Evidence ID 稳定、写入幂等；
4. 可选写入 `news_context_evidence`；
5. package 冻结 `evidence_ids` 和 `max_available_at`。

`EvidenceRepository.create_package_revision(...)` 在同一 `package_id` 下创建
`version + 1`，保留旧版本，记录 `parent_package_id` 和本轮
`added_evidence_ids`。PostgreSQL 使用根版本行锁串行化并发补证。

### 3.3 Agent 检索输出

`06-multi_agent_research` 的 `src/margin/research/evidence_tools.py` 负责把
`04-text_indexing` 的 PIT-safe 检索结果转换为上层 Agent 可消费的结构，并在配置
`EvidencePackageBuilder` 时写入本模块的不可变 EvidencePackage。

工具输出的每个 `evidence_blocks[]` 包含：

```text
rank / evidence_id / chunk_id / document_id
source_url / source_name / source_level / doc_type
content / content_hash
score / vector_score / keyword_score
published_at / available_at
snapshot_id / snapshot_hash
locator
```

当 package builder 可用时，只有通过本模块 PIT/security 校验并成功冻结进
EvidencePackage 的 Evidence 会返回给 Agent；未配置 builder 时，工具仍返回基于
`make_stable_evidence_id` 的稳定 evidence ID，供后续补证和审计链路复用。

### 3.4 Claim

Claim 状态：

| 状态 | 语义 |
| --- | --- |
| `SUPPORTED` | 引用存在且通过当前验证策略。 |
| `PARTIALLY_SUPPORTED` | 部分关键内容有支持，仍有缺口。 |
| `CONFLICTED` | 同时存在支持和反驳证据。 |
| `UNSUPPORTED` | 当前证据不能支持该 Claim。 |
| `ABSTAINED` | 证据不足或策略要求拒绝形成结论。 |

Claim-Evidence 角色：

- `SUPPORTS`
- `REFUTES`
- `CONTEXT`
- `CONFLICTS`

关系落在 `claim_evidence_links`，包含稳定 role 和展示 `rank`。

## 4. 来源等级与验证规则

- L1：交易所、监管或公司正式披露。
- L2：经审计财务或权威结构化数据。
- L3：可信媒体原始采访或独立分析。
- L4：转载、聚合内容。
- L5：论坛、社交或不可验证来源。

执行规则：

- L5 不能单独改变研究状态。
- L4 单独支持关键 Claim 时默认 FAIL；v0.2 工作流可配置为 ABSTAINED。
- L4 需要 L1-L3 交叉验证。
- `available_at > decision_at` 直接 FAIL。
- WebSearch 页面必须有原始 URL、结构 locator 和合规 snapshot。
- snapshot hash、quote span 或定位文本不一致时 FAIL。
- 支持/反驳并存会形成结构化 EvidenceConflict，不得静默忽略。

## 5. Locator replay

`CitationLocator` 支持：

```text
page / bbox / section / paragraph_index / dom_path
table_id / row_id / column_id / quote_span
snapshot_id / snapshot_hash
```

已实现的确定性 replay：

- PDF 原始 bytes 按页提取；
- HTML `dom_path` 定位；
- CSV `table-1 / row-N / column_id` 单元格定位；
- snapshot 内容/hash 校验；
- quote span 边界校验；
- 定位文本与 Evidence 内容校验；
- PIT 与 WebSearch 原文快照校验。

主要 reason code：

```text
ok
snapshot_not_found
snapshot_hash_mismatch
dom_path_not_found
quote_span_out_of_range
quote_text_mismatch
table_cell_not_found
pdf_page_not_found
pdf_parser_unavailable
locator_missing
```

无法解析的 PDF 页或表格单元格不会被猜测为成功，而是返回
`pdf_page_not_found`、`pdf_parser_unavailable` 或 `table_cell_not_found`。

## 6. 冲突与 Claim 校验

`EvidenceConflictClassifier` 对同一 Claim 的 SUPPORTS/REFUTES link 生成
`support_refute_conflict`，默认严重度为 HIGH。

`CitationValidator` 校验顺序：

1. Claim 是否引用 Evidence；
2. 所有 Evidence ID 是否存在；
3. L4/L5 来源限制；
4. locator、PIT 和 WebSearch 原文校验；
5. 可选 snapshot replay；
6. 最低有效 Evidence 数；
7. 冲突检测与置信度封顶。

输出为 `ValidationResult`，状态是 `PASS / FAIL / ABSTAINED`。每次结果可转换为
不可变 `ValidationAuditRecord` 并追加写入数据库。

## 7. PostgreSQL 表

```text
evidence_records
evidence_claims
claim_evidence_links
evidence_conflicts
evidence_packages
evidence_package_items
evidence_validation_audits
research_evidence
news_context_evidence
```

Evidence、Claim、Package version、Conflict 和 Audit 都是 append-only：
同一主键重复写入仅允许内容完全一致；任何内容变更都会被拒绝。

## 8. 验证与 replay 命令

模块测试：

```bash
pytest tests/evidence -v
```

迁移验证：

```bash
python scripts/verify_migrations.py \
  --database-url postgresql+psycopg://margin:margin@localhost:5432/margin_test \
  --database-name margin_test_verify_cli \
  --drop-existing
```

使用本地官方 sample 走完整 EvidencePackage/Claim/ValidationAudit 链路：

```bash
python scripts/smoke_rag_evidence.py \
  --security-id 000001.SZ \
  --decision-at 2026-06-22T00:00:00Z \
  --create-sample
```

使用现有 indexed chunk：

```bash
python scripts/smoke_rag_evidence.py \
  --security-id 000001.SZ \
  --decision-at 2026-06-22T00:00:00Z \
  --chunk-id <chunk_id>
```

成功 stdout 只包含：

```text
status package_id evidence_count claim_status validation_status
```
