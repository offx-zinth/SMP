"""Memory-mapped vector store (``.smpv`` format).

This module implements :class:`MMapVectorStore`, a self-contained
:class:`~smp.store.interfaces.VectorStore` backend that persists dense
``float32`` embeddings into a mmap'd file plus a JSON sidecar for
``id``/metadata/document bookkeeping.

File layout
-----------

The on-disk layout follows ``SPEC.md`` Phase 5:

``<path>.smpv`` — fixed 4096-byte header followed by an append-only
slot region of ``dim * 4`` bytes per vector::

    Offset  Field                                   Size
    ------  ----------------------------------      ----
    0       Magic ``SMPV``                          4 bytes
    4       Version (uint16 LE)                     2 bytes
    6       Flags  (uint16 LE)                      2 bytes
    8       Dimension (uint32 LE)                   4 bytes  (0 = uninitialised)
    12      Total slot count (uint32 LE)            4 bytes  (live + tombstoned)
    16      Live vector count (uint32 LE)           4 bytes
    20      Reserved                                8 bytes
    28      Header CRC32 (uint32 LE)                4 bytes
    32      Padding ...                             zero filled

``<path>.smpv.meta`` — JSON sidecar holding the (string) IDs, metadata,
documents, and tombstone flags for each slot.  This file is the source of
truth for the ``id -> slot`` mapping; the mmap holds dense embeddings only.

The implementation favours simplicity over absolute throughput:

* Inserts are append-only; updates re-use the existing slot when the ID is
  already known.
* Deletes are tombstoned; freed slots are not currently reclaimed.
* Similarity queries do a linear cosine scan over live slots.

Phase 5 only requires that we can persist embeddings and answer top-k
similarity queries; ANN indices and slot reclamation are deliberately left
for later milestones.
"""

from __future__ import annotations

import asyncio
import json
import mmap
import os
import struct
import zlib
from collections.abc import Sequence
from pathlib import Path
from typing import Any, Final

import numpy as np

from smp.logging import get_logger
from smp.store.interfaces import VectorStore

log = get_logger(__name__)

# -- File format constants -----------------------------------------------------

MAGIC: Final[bytes] = b"SMPV"
VERSION: Final[int] = 1
HEADER_SIZE: Final[int] = 4096
PAGE_SIZE: Final[int] = 4096
FLOAT_SIZE: Final[int] = 4

OFF_MAGIC: Final[int] = 0
OFF_VERSION: Final[int] = 4
OFF_FLAGS: Final[int] = 6
OFF_DIM: Final[int] = 8
OFF_SLOT_COUNT: Final[int] = 12
OFF_LIVE_COUNT: Final[int] = 16
OFF_RESERVED: Final[int] = 20
OFF_CRC: Final[int] = 28


def _meta_path_for(path: Path) -> Path:
    return path.with_suffix(path.suffix + ".meta")


class MMapVectorStore(VectorStore):
    """Memory-mapped vector store implementing :class:`VectorStore`.

    Args:
        path: Path to the ``.smpv`` file. The JSON sidecar is stored at
            ``<path>.meta``.
        dimension: Optional explicit embedding dimension. When provided and
            the file is being created, the dimension is locked at this value
            and subsequent upserts must match. When ``None``, the dimension
            is inferred from the first ``upsert`` call.
    """

    def __init__(
        self,
        path: str | os.PathLike[str],
        *,
        dimension: int | None = None,
    ) -> None:
        self._path = Path(path)
        self._meta_path = _meta_path_for(self._path)
        self._initial_dim = dimension
        self._dim: int = 0

        self._fd: int = -1
        self._mmap: mmap.mmap | None = None
        self._size: int = 0

        # In-memory sidecar (mirrors ``.smpv.meta``)
        self._ids: list[str] = []
        self._metadatas: list[dict[str, Any]] = []
        self._documents: list[str] = []
        self._tombstones: list[bool] = []
        self._id_to_slot: dict[str, int] = {}

        self._lock = asyncio.Lock()
        self._connected = False

    # -- Lifecycle -------------------------------------------------------------

    async def connect(self) -> None:
        await asyncio.get_running_loop().run_in_executor(None, self._open_blocking)
        self._connected = True
        log.info(
            "mmap_vector_connected",
            path=str(self._path),
            dim=self._dim,
            slots=len(self._ids),
            live=self._live_count(),
        )

    async def close(self) -> None:
        if not self._connected:
            return
        await asyncio.get_running_loop().run_in_executor(None, self._close_blocking)
        self._connected = False
        log.info("mmap_vector_closed", path=str(self._path))

    async def clear(self) -> None:
        self._require_connected()
        async with self._lock:
            await asyncio.get_running_loop().run_in_executor(None, self._clear_blocking)
        log.info("mmap_vector_cleared", path=str(self._path))

    # -- CRUD ------------------------------------------------------------------

    async def upsert(
        self,
        ids: Sequence[str],
        embeddings: Sequence[Sequence[float]],
        metadatas: Sequence[dict[str, Any]],
        documents: Sequence[str] | None = None,
    ) -> None:
        self._require_connected()
        if len(ids) != len(embeddings) or len(ids) != len(metadatas):
            raise ValueError("ids, embeddings, and metadatas must have equal length")
        if documents is not None and len(documents) != len(ids):
            raise ValueError("documents must match ids length when provided")
        if not ids:
            return

        async with self._lock:
            await asyncio.get_running_loop().run_in_executor(
                None,
                self._upsert_blocking,
                list(ids),
                [list(e) for e in embeddings],
                [dict(m) for m in metadatas],
                list(documents) if documents is not None else None,
            )
        log.info("mmap_vector_upserted", count=len(ids))

    async def query(
        self,
        embedding: Sequence[float],
        top_k: int = 5,
        where: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        self._require_connected()
        if top_k <= 0:
            return []
        return await asyncio.get_running_loop().run_in_executor(
            None,
            self._query_blocking,
            list(embedding),
            top_k,
            where,
        )

    async def get(self, ids: Sequence[str]) -> list[dict[str, Any] | None]:
        self._require_connected()
        results: list[dict[str, Any] | None] = []
        for entry_id in ids:
            slot = self._id_to_slot.get(entry_id)
            if slot is None or self._tombstones[slot]:
                continue
            results.append(
                {
                    "id": entry_id,
                    "metadata": dict(self._metadatas[slot]),
                    "document": self._documents[slot],
                }
            )
        return results

    async def delete(self, ids: Sequence[str]) -> int:
        self._require_connected()
        if not ids:
            return 0
        async with self._lock:
            removed = await asyncio.get_running_loop().run_in_executor(None, self._delete_blocking, list(ids))
        log.info("mmap_vector_deleted", count=removed)
        return removed

    async def delete_by_file(self, file_path: str) -> int:
        self._require_connected()
        async with self._lock:
            removed = await asyncio.get_running_loop().run_in_executor(None, self._delete_by_file_blocking, file_path)
        log.info("mmap_vector_deleted_by_file", file_path=file_path, count=removed)
        return removed

    # -- Convenience helpers (mirroring ChromaVectorStore) ---------------------

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

    # -- Introspection ---------------------------------------------------------

    @property
    def dimension(self) -> int:
        """Return the configured embedding dimension, or 0 if unset."""
        return self._dim

    @property
    def path(self) -> Path:
        return self._path

    def __len__(self) -> int:
        return self._live_count()

    # -- Internal: file open / close ------------------------------------------

    def _open_blocking(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        exists = self._path.exists()
        flags = os.O_RDWR
        if not exists:
            flags |= os.O_CREAT
        self._fd = os.open(self._path, flags, 0o644)

        if not exists:
            self._size = HEADER_SIZE
            os.ftruncate(self._fd, self._size)
            self._mmap = mmap.mmap(self._fd, self._size)
            self._dim = self._initial_dim or 0
            self._write_header()
            self._save_sidecar()
        else:
            self._size = os.path.getsize(self._path)
            if self._size < HEADER_SIZE:
                raise ValueError(f"Corrupt .smpv file (too small): {self._path}")
            self._mmap = mmap.mmap(self._fd, self._size)
            self._read_header()
            self._load_sidecar()
            if self._initial_dim is not None and self._dim and self._initial_dim != self._dim:
                raise ValueError(f"Dimension mismatch: file has dim={self._dim}, requested {self._initial_dim}")

    def _close_blocking(self) -> None:
        try:
            if self._mmap is not None:
                self._mmap.flush()
                self._mmap.close()
        finally:
            self._mmap = None
            if self._fd != -1:
                try:
                    os.close(self._fd)
                finally:
                    self._fd = -1
            self._save_sidecar()

    def _clear_blocking(self) -> None:
        if self._mmap is not None:
            self._mmap.flush()
            self._mmap.close()
            self._mmap = None
        if self._fd != -1:
            os.close(self._fd)
            self._fd = -1

        if self._path.exists():
            self._path.unlink()
        if self._meta_path.exists():
            self._meta_path.unlink()

        self._ids.clear()
        self._metadatas.clear()
        self._documents.clear()
        self._tombstones.clear()
        self._id_to_slot.clear()
        if self._initial_dim is None:
            self._dim = 0
        else:
            self._dim = self._initial_dim

        self._open_blocking()

    # -- Internal: header helpers ---------------------------------------------

    def _write_header(self) -> None:
        assert self._mmap is not None
        self._mmap[OFF_MAGIC : OFF_MAGIC + 4] = MAGIC
        self._mmap[OFF_VERSION : OFF_VERSION + 2] = struct.pack("<H", VERSION)
        self._mmap[OFF_FLAGS : OFF_FLAGS + 2] = struct.pack("<H", 0)
        self._mmap[OFF_DIM : OFF_DIM + 4] = struct.pack("<I", self._dim)
        self._mmap[OFF_SLOT_COUNT : OFF_SLOT_COUNT + 4] = struct.pack("<I", len(self._ids))
        self._mmap[OFF_LIVE_COUNT : OFF_LIVE_COUNT + 4] = struct.pack("<I", self._live_count())
        self._mmap[OFF_RESERVED : OFF_RESERVED + 8] = b"\x00" * 8
        self._update_header_crc()

    def _read_header(self) -> None:
        assert self._mmap is not None
        magic = bytes(self._mmap[OFF_MAGIC : OFF_MAGIC + 4])
        if magic != MAGIC:
            raise ValueError(f"Invalid .smpv magic: {magic!r}")
        version = struct.unpack("<H", self._mmap[OFF_VERSION : OFF_VERSION + 2])[0]
        if version > VERSION:
            raise ValueError(f"Unsupported .smpv version: {version}")
        self._dim = struct.unpack("<I", self._mmap[OFF_DIM : OFF_DIM + 4])[0]

    def _update_header_counts(self) -> None:
        assert self._mmap is not None
        self._mmap[OFF_DIM : OFF_DIM + 4] = struct.pack("<I", self._dim)
        self._mmap[OFF_SLOT_COUNT : OFF_SLOT_COUNT + 4] = struct.pack("<I", len(self._ids))
        self._mmap[OFF_LIVE_COUNT : OFF_LIVE_COUNT + 4] = struct.pack("<I", self._live_count())
        self._update_header_crc()

    def _update_header_crc(self) -> None:
        assert self._mmap is not None
        body = bytes(self._mmap[OFF_DIM:HEADER_SIZE])
        crc = zlib.crc32(body) & 0xFFFFFFFF
        self._mmap[OFF_CRC : OFF_CRC + 4] = struct.pack("<I", crc)

    # -- Internal: sidecar helpers --------------------------------------------

    def _save_sidecar(self) -> None:
        payload = {
            "version": VERSION,
            "dim": self._dim,
            "ids": self._ids,
            "metadata": self._metadatas,
            "documents": self._documents,
            "tombstones": self._tombstones,
        }
        tmp_path = self._meta_path.with_suffix(self._meta_path.suffix + ".tmp")
        tmp_path.write_text(json.dumps(payload), encoding="utf-8")
        os.replace(tmp_path, self._meta_path)

    def _load_sidecar(self) -> None:
        if not self._meta_path.exists():
            self._ids = []
            self._metadatas = []
            self._documents = []
            self._tombstones = []
            self._id_to_slot = {}
            return
        data = json.loads(self._meta_path.read_text(encoding="utf-8"))
        sidecar_dim = int(data.get("dim", 0))
        if self._dim and sidecar_dim and sidecar_dim != self._dim:
            raise ValueError(f"Sidecar dim ({sidecar_dim}) does not match header dim ({self._dim})")
        if not self._dim and sidecar_dim:
            self._dim = sidecar_dim
        self._ids = list(data.get("ids", []))
        self._metadatas = [dict(m) for m in data.get("metadata", [])]
        self._documents = list(data.get("documents", []))
        self._tombstones = list(data.get("tombstones", []))
        if not (len(self._ids) == len(self._metadatas) == len(self._documents) == len(self._tombstones)):
            raise ValueError(f"Sidecar slot lists out of sync: {self._meta_path}")
        self._id_to_slot = {entry_id: i for i, entry_id in enumerate(self._ids)}

    # -- Internal: vector slot helpers ----------------------------------------

    def _live_count(self) -> int:
        return sum(1 for t in self._tombstones if not t)

    def _slot_offset(self, slot: int) -> int:
        return HEADER_SIZE + slot * self._dim * FLOAT_SIZE

    def _ensure_capacity(self, slot_count: int) -> None:
        required = HEADER_SIZE + slot_count * self._dim * FLOAT_SIZE
        if required <= self._size:
            return
        new_size = ((required + PAGE_SIZE - 1) // PAGE_SIZE) * PAGE_SIZE
        assert self._mmap is not None
        self._mmap.flush()
        self._mmap.close()
        os.ftruncate(self._fd, new_size)
        self._mmap = mmap.mmap(self._fd, new_size)
        self._size = new_size

    def _write_vector(self, slot: int, vec: np.ndarray) -> None:
        assert self._mmap is not None
        off = self._slot_offset(slot)
        end = off + self._dim * FLOAT_SIZE
        self._mmap[off:end] = vec.tobytes()

    def _read_vector(self, slot: int) -> np.ndarray:
        assert self._mmap is not None
        off = self._slot_offset(slot)
        end = off + self._dim * FLOAT_SIZE
        return np.frombuffer(self._mmap[off:end], dtype=np.float32).copy()

    # -- Internal: blocking operations ----------------------------------------

    def _upsert_blocking(
        self,
        ids: list[str],
        embeddings: list[list[float]],
        metadatas: list[dict[str, Any]],
        documents: list[str] | None,
    ) -> None:
        if self._dim == 0:
            self._dim = len(embeddings[0])
            if self._dim <= 0:
                raise ValueError("Embedding dimension must be positive")
        for vec in embeddings:
            if len(vec) != self._dim:
                raise ValueError(f"Embedding dimension mismatch: expected {self._dim}, got {len(vec)}")

        new_slots = sum(1 for entry_id in ids if entry_id not in self._id_to_slot)
        if new_slots:
            self._ensure_capacity(len(self._ids) + new_slots)

        for i, entry_id in enumerate(ids):
            arr = np.asarray(embeddings[i], dtype=np.float32)
            metadata = metadatas[i]
            document = documents[i] if documents is not None else ""

            slot = self._id_to_slot.get(entry_id)
            if slot is None:
                slot = len(self._ids)
                self._ids.append(entry_id)
                self._metadatas.append(dict(metadata))
                self._documents.append(document)
                self._tombstones.append(False)
                self._id_to_slot[entry_id] = slot
            else:
                self._metadatas[slot] = dict(metadata)
                self._documents[slot] = document
                self._tombstones[slot] = False

            self._write_vector(slot, arr)

        self._update_header_counts()
        assert self._mmap is not None
        self._mmap.flush()
        self._save_sidecar()

    def _query_blocking(
        self,
        embedding: list[float],
        top_k: int,
        where: dict[str, Any] | None,
    ) -> list[dict[str, Any]]:
        if self._dim == 0 or not self._ids:
            return []
        if len(embedding) != self._dim:
            raise ValueError(f"Query embedding dim mismatch: expected {self._dim}, got {len(embedding)}")

        live_slots: list[int] = []
        for slot, tomb in enumerate(self._tombstones):
            if tomb:
                continue
            if where and not _matches_where(self._metadatas[slot], where):
                continue
            live_slots.append(slot)

        if not live_slots:
            return []

        query_vec = np.asarray(embedding, dtype=np.float32)
        q_norm = float(np.linalg.norm(query_vec)) or 1.0
        query_unit = query_vec / q_norm

        # Bulk read live vectors for efficient batched dot product.
        rows = np.empty((len(live_slots), self._dim), dtype=np.float32)
        for i, slot in enumerate(live_slots):
            rows[i] = self._read_vector(slot)
        norms = np.linalg.norm(rows, axis=1)
        norms = np.where(norms == 0, 1.0, norms)
        units = rows / norms[:, None]
        similarities = units @ query_unit
        distances = 1.0 - similarities

        k = min(top_k, len(live_slots))
        order = np.argsort(distances)[:k]

        results: list[dict[str, Any]] = []
        for idx in order:
            slot = live_slots[int(idx)]
            results.append(
                {
                    "id": self._ids[slot],
                    "score": float(distances[int(idx)]),
                    "metadata": dict(self._metadatas[slot]),
                    "document": self._documents[slot],
                }
            )
        return results

    def _delete_blocking(self, ids: list[str]) -> int:
        removed = 0
        for entry_id in ids:
            slot = self._id_to_slot.get(entry_id)
            if slot is None:
                continue
            if self._tombstones[slot]:
                continue
            self._tombstones[slot] = True
            removed += 1
        if removed:
            self._update_header_counts()
            assert self._mmap is not None
            self._mmap.flush()
            self._save_sidecar()
        return removed

    def _delete_by_file_blocking(self, file_path: str) -> int:
        removed = 0
        for slot, meta in enumerate(self._metadatas):
            if self._tombstones[slot]:
                continue
            if meta.get("file_path") == file_path:
                self._tombstones[slot] = True
                removed += 1
        if removed:
            self._update_header_counts()
            assert self._mmap is not None
            self._mmap.flush()
            self._save_sidecar()
        return removed

    # -- Internal: misc --------------------------------------------------------

    def _require_connected(self) -> None:
        if not self._connected or self._mmap is None:
            raise RuntimeError("MMapVectorStore is not connected")


def _matches_where(metadata: dict[str, Any], where: dict[str, Any]) -> bool:
    """Simple equality filter matching ChromaVectorStore's most common usage."""
    return all(metadata.get(key) == expected for key, expected in where.items())
