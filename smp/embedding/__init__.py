"""Embedding service for SMP — wraps the Qwen3-Embedding-0.6B GGUF model.

Provides a thread-safe, lazy-loaded embedding client backed by
``llama-cpp-python``.  The model produces 1024-dimensional embeddings
suitable for semantic search over code nodes.
"""

from __future__ import annotations

from smp.embedding.service import (
    DEFAULT_MODEL_PATH,
    EMBEDDING_DIM,
    QwenEmbeddingService,
    get_embedding_service,
)

__all__ = [
    "DEFAULT_MODEL_PATH",
    "EMBEDDING_DIM",
    "QwenEmbeddingService",
    "get_embedding_service",
]
