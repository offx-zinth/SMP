"""ChromaDB-backed vector store implementation."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

import chromadb

from smp.logging import get_logger
from smp.store.interfaces import VectorStore

log = get_logger(__name__)


class ChromaVectorStore(VectorStore):
    """Persist embeddings in ChromaDB with metadata filtering."""

    def __init__(
        self,
        collection_name: str = "smp_code_embeddings",
        persist_dir: str | None = None,
    ) -> None:
        self._collection_name = collection_name
        self._persist_dir = persist_dir
        self._client: Any = None
        self._collection: Any = None

    async def connect(self) -> None:
        if self._persist_dir is not None:
            self._client = chromadb.PersistentClient(path=self._persist_dir)
        else:
            self._client = chromadb.Client()
        self._collection = self._client.get_or_create_collection(name=self._collection_name)
        log.info("chroma_connected", collection=self._collection_name, persist_dir=self._persist_dir)

    async def close(self) -> None:
        self._client = None
        self._collection = None
        log.info("chroma_closed", collection=self._collection_name)

    async def clear(self) -> None:
        if self._client is None:
            raise RuntimeError("ChromaVectorStore is not connected")
        self._client.delete_collection(name=self._collection_name)
        self._collection = self._client.get_or_create_collection(name=self._collection_name)
        log.info("chroma_cleared", collection=self._collection_name)

    async def upsert(
        self,
        ids: Sequence[str],
        embeddings: Sequence[Sequence[float]],
        metadatas: Sequence[dict[str, Any]],
        documents: Sequence[str] | None = None,
    ) -> None:
        if self._collection is None:
            raise RuntimeError("ChromaVectorStore is not connected")
        self._collection.upsert(
            ids=list(ids),
            embeddings=[list(e) for e in embeddings],
            metadatas=list(metadatas),
            documents=list(documents) if documents is not None else None,
        )
        log.info("chroma_upserted", count=len(ids))

    async def query(
        self,
        embedding: Sequence[float],
        top_k: int = 5,
        where: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        if self._collection is None:
            raise RuntimeError("ChromaVectorStore is not connected")
        result = self._collection.query(
            query_embeddings=[list(embedding)],
            n_results=top_k,
            where=where,
        )
        return _normalise_query_result(result)

    async def get(self, ids: Sequence[str]) -> list[dict[str, Any] | None]:
        if self._collection is None:
            raise RuntimeError("ChromaVectorStore is not connected")
        result = self._collection.get(ids=list(ids))
        return _normalise_get_result(result)

    async def delete(self, ids: Sequence[str]) -> int:
        if self._collection is None:
            raise RuntimeError("ChromaVectorStore is not connected")
        self._collection.delete(ids=list(ids))
        log.info("chroma_deleted", count=len(ids))
        return len(ids)

    async def delete_by_file(self, file_path: str) -> int:
        if self._collection is None:
            raise RuntimeError("ChromaVectorStore is not connected")
        self._collection.delete(where={"file_path": file_path})
        log.info("chroma_deleted_by_file", file_path=file_path)
        return -1

    async def add_code_embedding(
        self,
        node_id: str,
        embedding: list[float],
        metadata: dict[str, Any],
        document: str = "",
    ) -> None:
        await self.upsert(
            ids=[node_id],
            embeddings=[embedding],
            metadatas=[metadata],
            documents=[document],
        )

    async def query_similar(
        self,
        embedding: list[float],
        top_k: int = 5,
        where: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        return await self.query(embedding=embedding, top_k=top_k, where=where)


def _normalise_query_result(result: dict[str, Any]) -> list[dict[str, Any]]:
    ids_batch = result.get("ids", [[]])
    distances_batch = result.get("distances", [[]])
    metadatas_batch = result.get("metadatas", [[]])
    documents_batch = result.get("documents", [[]])
    out: list[dict[str, Any]] = []
    for i, entry_id in enumerate(ids_batch[0]):
        out.append(
            {
                "id": entry_id,
                "score": distances_batch[0][i] if distances_batch and i < len(distances_batch[0]) else None,
                "metadata": metadatas_batch[0][i] if metadatas_batch and i < len(metadatas_batch[0]) else {},
                "document": documents_batch[0][i] if documents_batch and i < len(documents_batch[0]) else "",
            }
        )
    return out


def _normalise_get_result(result: dict[str, Any]) -> list[dict[str, Any] | None]:
    ids = result.get("ids", [])
    metadatas = result.get("metadatas", [])
    documents = result.get("documents", [])
    out: list[dict[str, Any] | None] = []
    for i, entry_id in enumerate(ids):
        out.append(
            {
                "id": entry_id,
                "metadata": metadatas[i] if metadatas and i < len(metadatas) else {},
                "document": documents[i] if documents and i < len(documents) else "",
            }
        )
    return out
