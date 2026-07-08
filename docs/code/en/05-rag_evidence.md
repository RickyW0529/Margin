# 05-rag_evidence — RAG Evidence

This module turns retrieved text into auditable evidence that can be cited and reviewed.

## What It Does

- Manages EvidencePackage, Claim, Evidence, and Citation Locator records.
- Checks that evidence can be replayed to the original source.
- Validates whether claims are supported, contradicted, or missing evidence.
- Records evidence_id, source_id, snapshot, PIT timestamp, and locator.

## How It Runs

```text
retrieved text
  -> evidence tiering and locator checks
  -> claim validation
  -> frozen EvidencePackage
  -> linked research / Agent output
```

AI output must either link back to evidence or clearly state that evidence is insufficient.

## Main Entry Points

- `src/margin/evidence/`
- `src/margin/research/evidence_tools.py`

## Who Uses It

Agents use it for citations and review. Dashboard uses it to show evidence summaries and source locators.
