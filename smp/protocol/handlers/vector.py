"""Vector search handlers (smp/vector/search).

These handlers delegate to the :class:`smp.store.interfaces.VectorStore`
backend. The current default is :class:`smp.vector.mmap_vector.MMapVectorStore`.
"""

from __future__ import annotations

from typing import Any

import msgspec

from smp.core.models import VectorSearchParams
from smp.logging import get_logger
from smp.store.interfaces import VectorStore

log = get_logger(__name__)


async def vector_search(params: dict[str, Any], ctx: dict[str, Any]) -> dict[str, Any]:
    """Handle ``smp/vector/search`` — top-k similarity search.

    Params:
        embedding: list[float] - The query vector.
        top_k: int - Number of results.
        where: dict[str, Any] - Metadata filter.
    """
    p = msgspec.convert(params, VectorSearchParams)
    vector_store: VectorStore = ctx["vector_store"]

    results = await vector_store.query(
        embedding=p.embedding,
        top_k=p.top_k,
        where=p.where,
    )

    return {
        "results": results,
        "count": len(results),
    }


async def vector_upsert(params: dict[str, Any], ctx: dict[str, Any]) -> dict[str, Any]:
    """Handle ``smp/vector/upsert`` — insert or update embeddings.

    Params:
        ids: list[str]
        embeddings: list[list[float]]
        metadatas: list[dict[str, Any]]
        documents: list[str] | None
    """
    ids = params.get("ids", [])
    embeddings = params.get("embeddings", [])
    metadatas = params.get("metadatas", [])
    documents = params.get("documents")

    vector_store: VectorStore = ctx["vector_store"]
    await vector_store.upsert(
        ids=ids,
        embeddings=embeddings,
        metadatas=metadatas,
        documents=documents,
    )

    return {"upserted": len(ids)}


async def vector_delete(params: dict[str, Any], ctx: dict[str, Any]) -> dict[str, Any]:
    """Handle ``smp/vector/delete`` — remove embeddings by ID.

    Params:
        ids: list[str]
    """
    ids = params.get("ids", [])
    vector_store: VectorStore = ctx["vector_store"]
    removed = await vector_store.delete(ids)

    return {"deleted": removed}


__all__ = ["vector_search", "vector_upsert", "vector_delete"]
