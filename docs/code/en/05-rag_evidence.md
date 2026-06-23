# 05-rag_evidence Current Implementation

## 1. Responsibility

`src/margin/evidence/` is the authoritative Claim/Evidence boundary. It
normalizes persisted chunks from `04-text_indexing` and optional
NewsContextBundle links from `03-filing_websearch` into immutable, PIT-safe,
replayable evidence packages consumed by `06-multi_agent_research`.

It does not fetch documents, generate embeddings, or make the final investment
decision.

## 2. Implemented components

| File | Implemented behavior |
| --- | --- |
| `models.py` | Evidence, Claim, EvidencePackage, claim/evidence roles and statuses, conflicts, and source-level restrictions. |
| `package_builder.py` | Builds frozen packages from retrieval results with security-link and PIT checks plus stable IDs. |
| `locator.py` | Unified PDF/HTML/table locators, PIT checks, WebSearch snapshot checks, snapshot hash and quote replay. |
| `validator.py` | Claim evidence, source level, PIT, locator, snapshot, conflict, and minimum-evidence validation. |
| `conflicts.py` | Deterministic SUPPORTS/REFUTES conflict classification. |
| `repository.py` | Append-only PostgreSQL persistence and package revision creation. |
| `db_models.py` | v0.2 ORM tables and constraints. |
| `scripts/smoke_rag_evidence.py` | Database-backed package, claim, validation, and audit smoke. |

## 3. Evidence and packages

Evidence preserves the source identity, content/hash, security, source level,
PIT timestamps, locator fields, and snapshot identity of a persisted chunk.
Its stable ID is derived from:

```text
security_id + chunk_id + snapshot_id + content_hash
```

Chunks currently have no separate persisted retrieval timestamp. The builder
therefore uses immutable `chunk.available_at` as `Evidence.retrieved_at`, making
repeated construction of the same canonical Evidence ID idempotent.

An `EvidencePackage` contains:

```text
package_id / version
security_id / decision_at / scope_hash
questions[]
evidence_ids[] / claim_ids[] / conflict_ids[]
coverage / quality_status / max_available_at
retrieval_audit_id
parent_package_id / added_evidence_ids[]
```

Quality statuses are `USABLE`, `PARTIAL`, `ABSTAIN_REQUIRED`, and `INVALID`.
The builder rejects future evidence and chunks without a
`chunk_security_links` association.

`EvidenceRepository.create_package_revision(...)` creates `version + 1` under
the same package ID, leaves the parent immutable, and records the parent and
new evidence IDs. A root-version row lock serializes concurrent PostgreSQL
supplementation attempts.

## 4. Claims and source policy

Claim statuses:

- `SUPPORTED`
- `PARTIALLY_SUPPORTED`
- `CONFLICTED`
- `UNSUPPORTED`
- `ABSTAINED`

Claim-evidence roles:

- `SUPPORTS`
- `REFUTES`
- `CONTEXT`
- `CONFLICTS`

Source policy:

- L1-L3 may support research-state changes.
- L5 cannot support a state change on its own.
- L4 requires L1-L3 cross-validation; v0.2 workflows may choose ABSTAINED
  instead of the backward-compatible FAIL default.
- `available_at > decision_at` always fails.
- WebSearch evidence requires an original URL, structural locator, and
  compliant snapshot.
- Support/refute conflicts are persisted and cannot be silently ignored.

## 5. Locator replay

Supported locator fields include:

```text
page / bbox / section / paragraph_index / dom_path
table_id / row_id / column_id / quote_span
snapshot_id / snapshot_hash
```

Implemented deterministic checks:

- PDF page extraction from original bytes;
- HTML `dom_path` lookup;
- CSV `table-1 / row-N / column_id` cell lookup;
- snapshot existence and hash;
- quote-span bounds;
- located text versus Evidence text;
- PIT and WebSearch original-snapshot checks.

Replay reason codes include:

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

Unparseable PDF pages or table cells fail explicitly with
`pdf_page_not_found`, `pdf_parser_unavailable`, or `table_cell_not_found`; the
validator does not fabricate a successful location.

## 6. Validation, conflicts, and audit

`CitationValidator` checks:

1. claim evidence references;
2. evidence existence;
3. L4/L5 policy;
4. locator, PIT, and WebSearch original-source validity;
5. optional snapshot replay;
6. minimum valid evidence count;
7. conflicts and confidence caps.

It returns `PASS`, `FAIL`, or `ABSTAINED`. Validation results can be appended as
immutable `ValidationAuditRecord` rows.

`EvidenceConflictClassifier` turns concurrent SUPPORTS and REFUTES links into a
HIGH-severity `support_refute_conflict`.

## 7. PostgreSQL persistence

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

Evidence, Claim, package versions, conflicts, and validation audits are
append-only. Reusing an existing identity is accepted only when the complete
record is identical.

## 8. Verification and smoke

```bash
pytest tests/evidence -v
```

```bash
python scripts/verify_migrations.py \
  --database-url postgresql+psycopg://margin:margin@localhost:5432/margin_test \
  --database-name margin_test_verify_cli \
  --drop-existing
```

Local official sample:

```bash
python scripts/smoke_rag_evidence.py \
  --security-id 000001.SZ \
  --decision-at 2026-06-22T00:00:00Z \
  --create-sample
```

Existing indexed chunk:

```bash
python scripts/smoke_rag_evidence.py \
  --security-id 000001.SZ \
  --decision-at 2026-06-22T00:00:00Z \
  --chunk-id <chunk_id>
```

Successful stdout contains only:

```text
status package_id evidence_count claim_status validation_status
```
