# 04-text_indexing — Text Parsing And Vector Indexing

This module turns raw documents into structured chunks that RAG can retrieve.

## What It Does

- Parses PDF, HTML, CSV, JSON, and plain text.
- Preserves page numbers, tables, quote spans, URLs, hashes, and locators.
- Splits long documents into stable chunks.
- Generates embeddings and stores chunk/vector/index audit records.

## How It Runs

```text
raw snapshot
  -> parser
  -> structured chunks
  -> embedding provider
  -> chunk / vector / index storage
  -> RAG retrieval
```

It does not decide whether a stock is good. It makes text searchable and replayable.

## Main Entry Points

- `src/margin/vector/`
- `src/margin/news/structured_parser.py`

## Who Uses It

`05-rag_evidence` retrieves evidence from this index. Agents access it through RAG tools.
