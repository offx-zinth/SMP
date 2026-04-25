"""Unit tests for :class:`MMapVectorStore`.

Covers Phase 5 milestone (`SPEC.md`): the ``.smpv`` file format, dimension
inference and locking, lifecycle, CRUD, similarity search, ``where``
filtering, deletion (including ``delete_by_file``), and persistence across
reopen cycles.
"""

from __future__ import annotations

import math
import struct
from pathlib import Path

import pytest

from smp.vector.mmap_vector import (
    HEADER_SIZE,
    MAGIC,
    OFF_DIM,
    OFF_LIVE_COUNT,
    OFF_SLOT_COUNT,
    MMapVectorStore,
)

pytestmark = pytest.mark.asyncio

_DIM = 4
_VEC_A = [1.0, 0.0, 0.0, 0.0]
_VEC_B = [0.0, 1.0, 0.0, 0.0]
_VEC_C = [1.0, 1.0, 0.0, 0.0]


@pytest.fixture()
async def store(tmp_path: Path) -> MMapVectorStore:
    s = MMapVectorStore(tmp_path / "vectors.smpv")
    await s.connect()
    yield s
    await s.close()


class TestLifecycle:
    async def test_creates_file_on_connect(self, tmp_path: Path) -> None:
        path = tmp_path / "vectors.smpv"
        s = MMapVectorStore(path)
        await s.connect()
        try:
            assert path.exists()
            assert path.stat().st_size >= HEADER_SIZE
        finally:
            await s.close()

    async def test_header_magic_and_zero_dim_on_create(self, tmp_path: Path) -> None:
        path = tmp_path / "vectors.smpv"
        s = MMapVectorStore(path)
        await s.connect()
        await s.close()
        with path.open("rb") as f:
            header = f.read(HEADER_SIZE)
        assert header[:4] == MAGIC
        dim = struct.unpack("<I", header[OFF_DIM : OFF_DIM + 4])[0]
        assert dim == 0

    async def test_explicit_dimension_locks_at_create(self, tmp_path: Path) -> None:
        path = tmp_path / "vectors.smpv"
        s = MMapVectorStore(path, dimension=_DIM)
        await s.connect()
        await s.close()
        with path.open("rb") as f:
            header = f.read(HEADER_SIZE)
        assert struct.unpack("<I", header[OFF_DIM : OFF_DIM + 4])[0] == _DIM

    async def test_reopen_with_mismatched_dim_raises(self, tmp_path: Path) -> None:
        path = tmp_path / "vectors.smpv"
        s = MMapVectorStore(path, dimension=_DIM)
        await s.connect()
        await s.upsert(ids=["a"], embeddings=[_VEC_A], metadatas=[{}])
        await s.close()

        bad = MMapVectorStore(path, dimension=_DIM + 1)
        with pytest.raises(ValueError, match="Dimension mismatch"):
            await bad.connect()

    async def test_double_close_safe(self, tmp_path: Path) -> None:
        s = MMapVectorStore(tmp_path / "vectors.smpv")
        await s.connect()
        await s.close()
        await s.close()


class TestUpsert:
    async def test_upsert_infers_dimension(self, store: MMapVectorStore) -> None:
        await store.upsert(
            ids=["a"],
            embeddings=[_VEC_A],
            metadatas=[{"file_path": "a.py"}],
        )
        assert store.dimension == _DIM
        assert len(store) == 1

    async def test_upsert_rejects_mismatched_dim(self, store: MMapVectorStore) -> None:
        await store.upsert(ids=["a"], embeddings=[_VEC_A], metadatas=[{}])
        with pytest.raises(ValueError, match="Embedding dimension mismatch"):
            await store.upsert(ids=["b"], embeddings=[[1.0, 2.0]], metadatas=[{}])

    async def test_upsert_overwrites_existing_id(self, store: MMapVectorStore) -> None:
        await store.upsert(ids=["dup"], embeddings=[_VEC_A], metadatas=[{"v": "1"}], documents=["first"])
        await store.upsert(ids=["dup"], embeddings=[_VEC_B], metadatas=[{"v": "2"}], documents=["second"])
        results = await store.get(["dup"])
        assert len(results) == 1
        assert results[0]["document"] == "second"
        assert results[0]["metadata"]["v"] == "2"
        assert len(store) == 1

    async def test_upsert_validates_lengths(self, store: MMapVectorStore) -> None:
        with pytest.raises(ValueError, match="equal length"):
            await store.upsert(ids=["a", "b"], embeddings=[_VEC_A], metadatas=[{}])
        with pytest.raises(ValueError, match="documents"):
            await store.upsert(ids=["a"], embeddings=[_VEC_A], metadatas=[{}], documents=["x", "y"])

    async def test_upsert_requires_connection(self, tmp_path: Path) -> None:
        s = MMapVectorStore(tmp_path / "vectors.smpv")
        with pytest.raises(RuntimeError, match="not connected"):
            await s.upsert(ids=["a"], embeddings=[_VEC_A], metadatas=[{}])


class TestGet:
    async def test_get_returns_metadata_and_document(self, store: MMapVectorStore) -> None:
        await store.upsert(
            ids=["a"],
            embeddings=[_VEC_A],
            metadatas=[{"file_path": "a.py"}],
            documents=["doc-a"],
        )
        results = await store.get(["a"])
        assert len(results) == 1
        assert results[0]["id"] == "a"
        assert results[0]["metadata"] == {"file_path": "a.py"}
        assert results[0]["document"] == "doc-a"

    async def test_get_skips_missing_ids(self, store: MMapVectorStore) -> None:
        await store.upsert(ids=["a"], embeddings=[_VEC_A], metadatas=[{}])
        results = await store.get(["a", "ghost"])
        assert [r["id"] for r in results] == ["a"]


class TestQuery:
    async def test_returns_top_k_in_distance_order(self, store: MMapVectorStore) -> None:
        await store.upsert(
            ids=["a", "b", "c"],
            embeddings=[_VEC_A, _VEC_B, _VEC_C],
            metadatas=[{"file_path": "f.py"}] * 3,
            documents=["d1", "d2", "d3"],
        )
        results = await store.query(embedding=_VEC_A, top_k=2)
        assert len(results) == 2
        assert results[0]["id"] == "a"
        assert results[0]["score"] == pytest.approx(0.0, abs=1e-6)
        assert results[1]["score"] >= results[0]["score"]

    async def test_distance_is_one_minus_cosine(self, store: MMapVectorStore) -> None:
        await store.upsert(
            ids=["a", "b"],
            embeddings=[_VEC_A, _VEC_B],
            metadatas=[{}] * 2,
        )
        results = await store.query(embedding=_VEC_A, top_k=2)
        scores = {r["id"]: r["score"] for r in results}
        assert scores["a"] == pytest.approx(0.0, abs=1e-6)
        assert scores["b"] == pytest.approx(1.0, abs=1e-6)

    async def test_query_empty_store_returns_empty_list(self, store: MMapVectorStore) -> None:
        # Establish dimension by inserting and tombstoning all vectors.
        await store.upsert(ids=["a"], embeddings=[_VEC_A], metadatas=[{}])
        await store.delete(["a"])
        assert await store.query(embedding=_VEC_A, top_k=5) == []

    async def test_query_dim_mismatch_raises(self, store: MMapVectorStore) -> None:
        await store.upsert(ids=["a"], embeddings=[_VEC_A], metadatas=[{}])
        with pytest.raises(ValueError, match="dim mismatch"):
            await store.query(embedding=[1.0, 0.0], top_k=1)

    async def test_query_top_k_zero_returns_empty(self, store: MMapVectorStore) -> None:
        await store.upsert(ids=["a"], embeddings=[_VEC_A], metadatas=[{}])
        assert await store.query(embedding=_VEC_A, top_k=0) == []

    async def test_query_handles_zero_vector(self, store: MMapVectorStore) -> None:
        await store.upsert(
            ids=["zero"],
            embeddings=[[0.0, 0.0, 0.0, 0.0]],
            metadatas=[{}],
        )
        results = await store.query(embedding=_VEC_A, top_k=1)
        assert len(results) == 1
        assert math.isfinite(results[0]["score"])

    async def test_query_where_filter_equality(self, store: MMapVectorStore) -> None:
        await store.upsert(
            ids=["match", "other"],
            embeddings=[_VEC_A, _VEC_B],
            metadatas=[{"file_path": "match.py"}, {"file_path": "other.py"}],
        )
        results = await store.query(embedding=_VEC_A, top_k=5, where={"file_path": "match.py"})
        assert len(results) == 1
        assert results[0]["id"] == "match"


class TestDelete:
    async def test_delete_returns_count(self, store: MMapVectorStore) -> None:
        await store.upsert(
            ids=["a", "b", "c"],
            embeddings=[_VEC_A, _VEC_B, _VEC_C],
            metadatas=[{}] * 3,
        )
        removed = await store.delete(["a", "b", "ghost"])
        assert removed == 2
        assert len(store) == 1

    async def test_delete_idempotent_on_repeated_id(self, store: MMapVectorStore) -> None:
        await store.upsert(ids=["a"], embeddings=[_VEC_A], metadatas=[{}])
        assert await store.delete(["a"]) == 1
        assert await store.delete(["a"]) == 0

    async def test_get_after_delete_returns_empty(self, store: MMapVectorStore) -> None:
        await store.upsert(ids=["rm"], embeddings=[_VEC_A], metadatas=[{}])
        await store.delete(["rm"])
        assert await store.get(["rm"]) == []

    async def test_query_skips_tombstoned(self, store: MMapVectorStore) -> None:
        await store.upsert(
            ids=["a", "b"],
            embeddings=[_VEC_A, _VEC_B],
            metadatas=[{}] * 2,
        )
        await store.delete(["a"])
        results = await store.query(embedding=_VEC_A, top_k=5)
        assert {r["id"] for r in results} == {"b"}


class TestDeleteByFile:
    async def test_returns_count_of_removed_vectors(self, store: MMapVectorStore) -> None:
        await store.upsert(
            ids=["a", "b", "c"],
            embeddings=[_VEC_A, _VEC_B, _VEC_C],
            metadatas=[
                {"file_path": "target.py"},
                {"file_path": "target.py"},
                {"file_path": "keep.py"},
            ],
        )
        count = await store.delete_by_file("target.py")
        assert count == 2
        results = await store.query(embedding=_VEC_A, top_k=5)
        assert {r["id"] for r in results} == {"c"}

    async def test_returns_zero_for_unknown_file(self, store: MMapVectorStore) -> None:
        await store.upsert(
            ids=["a"],
            embeddings=[_VEC_A],
            metadatas=[{"file_path": "x.py"}],
        )
        assert await store.delete_by_file("unknown.py") == 0


class TestPersistence:
    async def test_data_survives_reopen(self, tmp_path: Path) -> None:
        path = tmp_path / "persist.smpv"
        s1 = MMapVectorStore(path)
        await s1.connect()
        await s1.upsert(
            ids=["a", "b"],
            embeddings=[_VEC_A, _VEC_B],
            metadatas=[{"file_path": "a.py"}, {"file_path": "b.py"}],
            documents=["doc-a", "doc-b"],
        )
        await s1.delete(["b"])
        await s1.close()

        s2 = MMapVectorStore(path)
        await s2.connect()
        try:
            assert s2.dimension == _DIM
            assert len(s2) == 1
            results = await s2.get(["a", "b"])
            assert [r["id"] for r in results] == ["a"]
            top = await s2.query(embedding=_VEC_A, top_k=5)
            assert {r["id"] for r in top} == {"a"}
        finally:
            await s2.close()

    async def test_header_counts_updated_on_close(self, tmp_path: Path) -> None:
        path = tmp_path / "counts.smpv"
        s = MMapVectorStore(path)
        await s.connect()
        await s.upsert(
            ids=["a", "b", "c"],
            embeddings=[_VEC_A, _VEC_B, _VEC_C],
            metadatas=[{}] * 3,
        )
        await s.delete(["b"])
        await s.close()

        with path.open("rb") as f:
            header = f.read(HEADER_SIZE)
        slots = struct.unpack("<I", header[OFF_SLOT_COUNT : OFF_SLOT_COUNT + 4])[0]
        live = struct.unpack("<I", header[OFF_LIVE_COUNT : OFF_LIVE_COUNT + 4])[0]
        assert slots == 3
        assert live == 2


class TestClear:
    async def test_clear_removes_all_data(self, store: MMapVectorStore) -> None:
        await store.upsert(
            ids=["a", "b"],
            embeddings=[_VEC_A, _VEC_B],
            metadatas=[{"file_path": "a.py"}, {"file_path": "b.py"}],
        )
        await store.clear()
        assert len(store) == 0
        assert await store.get(["a", "b"]) == []

    async def test_clear_allows_reuse(self, store: MMapVectorStore) -> None:
        await store.upsert(ids=["a"], embeddings=[_VEC_A], metadatas=[{}])
        await store.clear()
        await store.upsert(ids=["c"], embeddings=[_VEC_C], metadatas=[{}])
        results = await store.query(embedding=_VEC_C, top_k=1)
        assert results[0]["id"] == "c"


class TestHelpers:
    async def test_add_code_embedding(self, store: MMapVectorStore) -> None:
        await store.add_code_embedding(
            node_id="func_foo",
            embedding=_VEC_A,
            metadata={"file_path": "foo.py", "kind": "function"},
            document="def foo(): ...",
        )
        results = await store.get(["func_foo"])
        assert len(results) == 1
        assert results[0]["document"] == "def foo(): ..."

    async def test_query_similar_matches_query(self, store: MMapVectorStore) -> None:
        await store.upsert(
            ids=["a", "b"],
            embeddings=[_VEC_A, _VEC_B],
            metadatas=[{}] * 2,
        )
        a = await store.query(embedding=_VEC_A, top_k=1)
        b = await store.query_similar(embedding=_VEC_A, top_k=1)
        assert [r["id"] for r in a] == [r["id"] for r in b]
