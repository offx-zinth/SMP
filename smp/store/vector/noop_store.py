"""No-op vector store — used when enrichment is disabled.

Satisfies the VectorStore interface but performs no operations.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from smp.logging import get_logger
from smp.store.interfaces import VectorStore

log = get_logger(__name__)


class NoOpVectorStore(VectorStore):
    """Vector store that silently discards all operations.

    Use this when enrichment is disabled and no vector storage is needed.
    """

    async def connect(self) -> None:
        log.info("noop_vector_connected")

    async def close(self) -> None:
        log.info("noop_vector_closed")

    async def clear(self) -> None:
        pass

    async def upsert(
        self,
        ids: Sequence[str],
        embeddings: Sequence[Sequence[float]],
        metadatas: Sequence[dict[str, Any]],
        documents: Sequence[str] | None = None,
    ) -> None:
        pass

    async def query(
        self,
        embedding: Sequence[float],
        top_k: int = 5,
        where: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        return []

    async def get(self, ids: Sequence[str]) -> list[dict[str, Any] | None]:
        return [None] * len(ids)

    async def delete(self, ids: Sequence[str]) -> int:
        return 0

    async def delete_by_file(self, file_path: str) -> int:
        return 0
