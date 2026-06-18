"""Text vector database package.

Provides document chunking, dense/sparse embedding generation, hybrid retrieval,
and chunk-to-source citation/locator support for the Margin system.
"""

from margin.vector.chunker import (
    BaseChunker,
    Chunker,
    ChunkingError,
    FilingChunker,
    IRChunker,
    NewsChunker,
    ReportChunker,
    UserNoteChunker,
    infer_doc_type,
)
from margin.vector.embedding import (
    BM25Index,
    EmbeddingPipeline,
    EmbeddingProvider,
    IndexAuditor,
    IndexAuditRecord,
    VectorStore,
)
from margin.vector.models import (
    Chunk,
    DocType,
    RetrievalResult,
    compute_chunk_hash,
    make_chunk,
)
from margin.vector.retrieval import (
    HybridRetriever,
    HybridWeights,
    Reranker,
    RetrievalTool,
    SearchConstraints,
)

__all__ = [
    "BaseChunker",
    "BM25Index",
    "Chunk",
    "Chunker",
    "ChunkingError",
    "DocType",
    "EmbeddingPipeline",
    "EmbeddingProvider",
    "FilingChunker",
    "HybridRetriever",
    "HybridWeights",
    "IRChunker",
    "IndexAuditRecord",
    "IndexAuditor",
    "NewsChunker",
    "Reranker",
    "ReportChunker",
    "RetrievalResult",
    "RetrievalTool",
    "SearchConstraints",
    "UserNoteChunker",
    "VectorStore",
    "compute_chunk_hash",
    "infer_doc_type",
    "make_chunk",
]
