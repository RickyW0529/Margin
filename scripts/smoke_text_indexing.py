#!/usr/bin/env python3
"""Token-safe real embedding/indexing smoke for module 04.

The script uses a synthetic non-copyright document chunk so it can verify the
text-indexing path without printing source text or provider secrets. It exits
with code 2 when embedding configuration is incomplete, and never prints secret
values.
"""

from __future__ import annotations

import argparse
import os
import sys
from datetime import UTC, datetime

from margin.news.models import SourceLevel
from margin.settings import MarginSettings
from margin.storage.database import (
    DatabaseSettings,
    create_database_engine,
    create_session_factory,
)
from margin.vector.models import (
    Chunk,
    ChunkSecurityLink,
    DocType,
    IndexedDocument,
    SourceLocator,
    TrustLevel,
    compute_chunk_hash,
    make_stable_chunk_id,
)
from margin.vector.persistent_pipeline import PersistentIndexingPipeline
from margin.vector.providers.openai_embedding import OpenAIEmbeddingProvider
from margin.vector.repository import VectorRepository
from margin.vector.retrieval import HybridRetriever

PARSER_VERSION = "smoke-text-indexing-v0.2"


def main() -> int:
    """Run a real embedding/write/retrieval smoke and return an exit code."""
    args = _parse_args()
    config = _embedding_config()
    missing = [
        name
        for name, value in config.items()
        if name != "dimension" and not str(value or "").strip()
    ]
    if not str(config["dimension"] or "").strip():
        missing.append("dimension")
    if missing:
        print(
            "provider=embedding "
            "status=blocked "
            "external_blocker=missing_embedding_config "
            f"missing_fields={','.join(sorted(missing))}"
        )
        return 2

    try:
        dimension = int(str(config["dimension"]))
    except ValueError:
        print(
            "provider=embedding "
            "status=blocked "
            "external_blocker=invalid_embedding_dimension"
        )
        return 2

    settings = MarginSettings()
    database_url = args.database_url or str(settings.database_url)
    decision_at = _parse_decision_at(args.decision_at)
    repository = _build_repository(database_url, dimension=dimension)
    provider = OpenAIEmbeddingProvider(
        api_key=str(config["api_key"]),
        base_url=str(config["base_url"]),
        model=str(config["model"]),
        dimension=dimension,
    )

    chunk = _build_smoke_chunk(args.security_id, decision_at)
    link = ChunkSecurityLink(
        chunk_id=chunk.chunk_id,
        security_id=args.security_id,
        link_type="smoke_subject",
        confidence=1.0,
    )

    try:
        repository.upsert_chunks([chunk], links=[link])
        embedding_keys = PersistentIndexingPipeline(
            repository=repository,
            embedding_provider=provider,
            embedding_dimension=dimension,
        ).embed_and_persist([chunk])
        repository.upsert_indexed_document(
            IndexedDocument(
                document_id=chunk.document_id,
                event_id="smoke_text_indexing_event",
                parser_version=PARSER_VERSION,
                input_hash=chunk.content_hash,
                chunk_ids=(chunk.chunk_id,),
                embedding_keys=tuple(embedding_keys),
                created_at=decision_at,
            )
        )
        results = HybridRetriever(repository, embedding_provider=provider).search(
            "平安银行 文本索引 PIT 检索",
            top_k=1,
            security_ids=(args.security_id,),
            decision_at=decision_at,
        )
    except Exception as exc:  # noqa: BLE001 - smoke only reports classified status
        print(
            "provider=embedding "
            "status=failed "
            "external_blocker=provider_or_database_error "
            f"error_type={type(exc).__name__}"
        )
        return 3

    top_chunk_id = results[0].chunk.chunk_id if results else "none"
    print(
        "provider=embedding "
        "status=ok "
        f"model={config['model']} "
        f"dimension={dimension} "
        "chunk_count=1 "
        f"link_count={repository.count_chunk_security_links()} "
        f"vector_count={repository.count_embeddings()} "
        f"top_chunk_id={top_chunk_id}"
    )
    return 0


def _parse_args() -> argparse.Namespace:
    """Parse command-line arguments for the text-indexing smoke."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database-url", default="")
    parser.add_argument("--security-id", default="000001.SZ")
    parser.add_argument("--decision-at", default="")
    return parser.parse_args()


def _embedding_config() -> dict[str, str | None]:
    """Resolve explicit smoke embedding provider config from environment."""
    return {
        "api_key": os.getenv("MARGIN_EMBEDDING_API_KEY"),
        "base_url": os.getenv("MARGIN_EMBEDDING_BASE_URL"),
        "model": os.getenv("MARGIN_EMBEDDING_MODEL") or "text-embedding-3-small",
        "dimension": os.getenv("MARGIN_EMBEDDING_DIMENSION") or "1536",
    }


def _parse_decision_at(value: str) -> datetime:
    """Parse an ISO 8601 datetime or return current UTC time."""
    if not value:
        return datetime.now(UTC)
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(UTC)


def _build_repository(database_url: str, *, dimension: int) -> VectorRepository:
    """Build a VectorRepository from a database URL."""
    engine = create_database_engine(DatabaseSettings(url=database_url))
    return VectorRepository(create_session_factory(engine), dimension=dimension)


def _build_smoke_chunk(security_id: str, available_at: datetime) -> Chunk:
    """Build a synthetic news chunk for the text-indexing smoke."""
    content = "文本索引 smoke 验证：PIT 检索、chunk-security link 和向量写入。"
    content_hash = compute_chunk_hash(content)
    document_id = "smoke_text_indexing_doc"
    return Chunk(
        chunk_id=make_stable_chunk_id(
            document_id=document_id,
            content_hash=content_hash,
            parser_version=PARSER_VERSION,
            chunk_index=0,
        ),
        document_id=document_id,
        content=content,
        content_hash=content_hash,
        symbol=security_id,
        source_level=SourceLevel.L4,
        doc_type=DocType.NEWS,
        published_at=available_at,
        available_at=available_at,
        source_url="https://example.invalid/margin/smoke-text-indexing",
        source_name="margin-smoke",
        snapshot_id="smoke_text_indexing_snapshot",
        snapshot_hash=content_hash,
        locator=SourceLocator(paragraph_index=0, quote_span=(0, len(content))),
        trust_level=TrustLevel.UNTRUSTED_SOURCE_CONTENT,
        keywords=("文本", "索引", "PIT"),
        chunk_index=0,
        total_chunks=1,
    )


if __name__ == "__main__":
    sys.exit(main())
