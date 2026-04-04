"""ChromaDB-backed vector store implementation.

Uses in-process ChromaDB (no server required) for the MVP.
"""

from __future__ import annotations

# Monkey-patch sqlite3 with pysqlite3-binary (required by ChromaDB on older systems)
try:
    __import__("pysqlite3")
    import sys
    sys.modules["sqlite3"] = sys.modules.pop("pysqlite3")
except ImportError:
    pass

from pathlib import Path
from typing import Any, Sequence

import chromadb
from chromadb.api.models.Collection import Collection

from smp.logging import get_logger
from smp.store.interfaces import VectorStore

log = get_logger(__name__)

_DEFAULT_COLLECTION = "smp_nodes"


def _sanitize_metadata(meta: dict[str, Any]) -> dict[str, Any]:
    """Ensure metadata values are ChromaDB-compatible primitives.

    ChromaDB rejects empty dicts, so we inject a sentinel key when empty.
    """
    clean: dict[str, Any] = {}
    for k, v in meta.items():
        if isinstance(v, (str, int, float, bool)):
            clean[k] = v
        elif v is None:
            clean[k] = ""
        else:
            clean[k] = str(v)
    if not clean:
        clean["_smp"] = "1"
    return clean


class ChromaVectorStore(VectorStore):
    """Vector store backed by an in-process ChromaDB instance."""

    def __init__(
        self,
        persist_directory: str | None = None,
        collection_name: str = _DEFAULT_COLLECTION,
    ) -> None:
        self._persist_dir = persist_directory
        self._collection_name = collection_name
        self._client: chromadb.ClientAPI | None = None
        self._collection: Collection | None = None

    # -- Lifecycle -----------------------------------------------------------

    async def connect(self) -> None:
        # ChromaDB's client is synchronous; wrap in thread if needed later.
        if self._persist_dir:
            Path(self._persist_dir).mkdir(parents=True, exist_ok=True)
            self._client = chromadb.PersistentClient(path=self._persist_dir)
        else:
            self._client = chromadb.EphemeralClient()

        self._collection = self._client.get_or_create_collection(
            name=self._collection_name,
            metadata={"hnsw:space": "cosine"},
        )
        log.info("chromadb_connected", collection=self._collection_name)

    async def close(self) -> None:
        # EphemeralClient discards data on GC; PersistentClient persists automatically.
        self._client = None
        self._collection = None
        log.info("chromadb_closed")

    async def clear(self) -> None:
        if not self._client:
            raise RuntimeError("ChromaVectorStore is not connected.")
        self._client.delete_collection(self._collection_name)
        self._collection = self._client.get_or_create_collection(
            name=self._collection_name,
            metadata={"hnsw:space": "cosine"},
        )
        log.warning("chromadb_cleared")

    # -- CRUD ----------------------------------------------------------------

    async def upsert(
        self,
        ids: Sequence[str],
        embeddings: Sequence[Sequence[float]],
        metadatas: Sequence[dict[str, Any]],
        documents: Sequence[str] | None = None,
    ) -> None:
        if not self._collection:
            raise RuntimeError("ChromaVectorStore is not connected.")
        if not ids:
            return

        clean_metas = [_sanitize_metadata(m) for m in metadatas]
        kwargs: dict[str, Any] = {
            "ids": list(ids),
            "embeddings": [list(e) for e in embeddings],
            "metadatas": clean_metas,
        }
        if documents:
            kwargs["documents"] = list(documents)

        self._collection.upsert(**kwargs)
        log.debug("vectors_upserted", count=len(ids))

    async def query(
        self,
        embedding: Sequence[float],
        top_k: int = 5,
        where: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        if not self._collection:
            raise RuntimeError("ChromaVectorStore is not connected.")

        results = self._collection.query(
            query_embeddings=[list(embedding)],
            n_results=top_k,
            where=where,
            include=["documents", "metadatas", "distances"],
        )

        out: list[dict[str, Any]] = []
        if not results or not results.get("ids") or not results["ids"][0]:
            return out

        for i, doc_id in enumerate(results["ids"][0]):
            out.append(
                {
                    "id": doc_id,
                    "score": 1.0 - results["distances"][0][i],  # cosine distance -> similarity
                    "metadata": results["metadatas"][0][i] if results.get("metadatas") else {},
                    "document": results["documents"][0][i] if results.get("documents") else "",
                }
            )
        return out

    async def get(self, ids: Sequence[str]) -> list[dict[str, Any] | None]:
        if not self._collection:
            raise RuntimeError("ChromaVectorStore is not connected.")

        results = self._collection.get(
            ids=list(ids),
            include=["documents", "metadatas", "embeddings"],
        )

        id_set = set(results["ids"])
        out: list[dict[str, Any] | None] = []
        for i, doc_id in enumerate(ids):
            if doc_id not in id_set:
                out.append(None)
            else:
                idx = results["ids"].index(doc_id)
                embeddings = results.get("embeddings")
                out.append(
                    {
                        "id": doc_id,
                        "metadata": results["metadatas"][idx] if results.get("metadatas") else {},
                        "document": results["documents"][idx] if results.get("documents") else "",
                        "embedding": embeddings[idx] if embeddings is not None else None,
                    }
                )
        return out

    async def delete(self, ids: Sequence[str]) -> int:
        if not self._collection:
            raise RuntimeError("ChromaVectorStore is not connected.")
        if not ids:
            return 0
        self._collection.delete(ids=list(ids))
        return len(ids)

    async def delete_by_file(self, file_path: str) -> int:
        if not self._collection:
            raise RuntimeError("ChromaVectorStore is not connected.")
        # Get all IDs matching the file_path metadata
        results = self._collection.get(where={"file_path": file_path})
        if not results or not results["ids"]:
            return 0
        self._collection.delete(ids=results["ids"])
        log.info("vectors_deleted_by_file", file_path=file_path, count=len(results["ids"]))
        return len(results["ids"])

    # -- Convenience ---------------------------------------------------------

    @property
    def collection(self) -> Collection | None:
        return self._collection
