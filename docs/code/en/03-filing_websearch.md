# 03-filing_websearch — Filings, News, And WebSearch

This module adds text material so recommendations are not based only on quant scores.

## What It Does

- Builds news, filing, and WebSearch targets for selected stocks.
- Fetches official filings, news, web results, and source snapshots.
- Deduplicates content and records compliance, robots, and source metadata.
- Provides traceable material for indexing and evidence.

## How It Runs

```text
quant candidates
  -> build news/filing targets
  -> fetch provider material
  -> save raw text and snapshots
  -> deduplicate and check compliance
  -> send to text indexing
```

This module finds and stores material. It does not make investment conclusions.

## Main Entry Points

- `src/margin/news/`
- `src/margin/sql/news_queries.py`

## Who Uses It

`04-text_indexing` indexes the material, `05-rag_evidence` turns it into evidence, and Agents use that evidence for review.
