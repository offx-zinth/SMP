"""FAISS index wrapper for fast vector search.

This module provides a high-level wrapper around the FAISS library to enable
approximate nearest neighbor (ANN) search. It is designed to be used as an
in-memory acceleration layer on top of a durable vector store.
"""

from __future__ import annotations

import faiss  # type: ignore[import-untyped]
import numpy as np


class FaissIndex:
    """Wrapper around a FAISS index for cosine similarity.

    Uses IndexHNSWFlat for fast O(log N) search and high recall.
    """

    def __init__(self, dimension: int, m: int = 32) -> None:
        self.dimension = dimension
        self.index = faiss.IndexHNSWFlat(dimension, m)
        self.index.hnsw.efConstruction = 200
        self.index.hnsw.efSearch = 64

    def add(self, embeddings: np.ndarray) -> None:
        """Add embeddings to the index. Vectors must be normalized for cosine similarity."""
        embeddings = embeddings.astype("float32")
        faiss.normalize_L2(embeddings)
        self.index.add(embeddings)

    def search(self, query_embedding: np.ndarray, top_k: int) -> tuple[np.ndarray, np.ndarray]:
        """Search for top_k nearest neighbours.

        Returns:
            tuple: (distances, indices)
        """
        query_embedding = query_embedding.astype("float32").reshape(1, -1)
        faiss.normalize_L2(query_embedding)

        # HNSW returns at most efSearch candidates; raise it so large
        # top_k queries recall the full result set.
        previous_ef = int(self.index.hnsw.efSearch)
        try:
            if top_k > previous_ef:
                self.index.hnsw.efSearch = top_k
            distances, indices = self.index.search(query_embedding, top_k)
        finally:
            self.index.hnsw.efSearch = previous_ef
        return distances[0], indices[0]

    def reset(self) -> None:
        """Reset the index."""
        self.index = faiss.IndexHNSWFlat(self.dimension, 32)

    @property
    def ntotal(self) -> int:
        """Number of vectors in the index."""
        return int(self.index.ntotal)
