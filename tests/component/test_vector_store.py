from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from smp.vector.mmap_vector import MMapVectorStore


@pytest.mark.asyncio
class TestMMapVectorStore:
    """Component tests for MMapVectorStore."""

    async def test_connection_lifecycle(self, tmp_path: Path):
        path = tmp_path / "lifecycle.smpv"
        store = MMapVectorStore(path=str(path), dimension=128)

        with pytest.raises(RuntimeError, match="not connected"):
            await store.get(["id1"])

        await store.connect()
        assert store._connected is True
        assert store.dimension == 128

        await store.close()
        assert store._connected is False
        with pytest.raises(RuntimeError, match="not connected"):
            await store.get(["id1"])

    async def test_upsert_and_get_single(self, vector_store: MMapVectorStore, sample_embedding: list[float]):
        await vector_store.upsert(
            ids=["vec1"], embeddings=[sample_embedding], metadatas=[{"key": "val"}], documents=["doc1"]
        )

        results = await vector_store.get(["vec1"])
        assert len(results) == 1
        assert results[0]["id"] == "vec1"
        assert results[0]["metadata"] == {"key": "val"}
        assert results[0]["document"] == "doc1"

    async def test_upsert_and_get_multiple(self, vector_store: MMapVectorStore, sample_embeddings: list[list[float]]):
        ids = [f"vec{i}" for i in range(10)]
        metadatas = [{"i": i} for i in range(10)]
        documents = [f"doc{i}" for i in range(10)]

        await vector_store.upsert(ids, sample_embeddings, metadatas, documents)

        results = await vector_store.get(ids)
        assert len(results) == 10
        for i in range(10):
            assert results[i]["id"] == ids[i]
            assert results[i]["metadata"] == metadatas[i]
            assert results[i]["document"] == documents[i]

    async def test_get_non_existing(self, vector_store: MMapVectorStore):
        results = await vector_store.get(["non_existent"])
        assert results == [None]

    async def test_upsert_update(self, vector_store: MMapVectorStore, sample_embedding: list[float]):
        await vector_store.upsert(["vec1"], [sample_embedding], [{"v": 1}], ["doc1"])

        new_embedding = [x + 0.1 for x in sample_embedding]
        await vector_store.upsert(["vec1"], [new_embedding], [{"v": 2}], ["doc2"])

        results = await vector_store.get(["vec1"])
        assert len(results) == 1
        assert results[0]["metadata"] == {"v": 2}
        assert results[0]["document"] == "doc2"
        assert len(vector_store) == 1

    async def test_delete_single(self, vector_store: MMapVectorStore, sample_embedding: list[float]):
        await vector_store.upsert(["vec1"], [sample_embedding], [{}], ["doc1"])
        assert len(vector_store) == 1

        removed = await vector_store.delete(["vec1"])
        assert removed == 1
        assert len(vector_store) == 0

        results = await vector_store.get(["vec1"])
        assert results == [None]

    async def test_delete_multiple(self, vector_store: MMapVectorStore, sample_embeddings: list[list[float]]):
        ids = [f"vec{i}" for i in range(5)]
        await vector_store.upsert(ids, sample_embeddings[:5], [{}] * 5, [""] * 5)

        removed = await vector_store.delete(["vec0", "vec1", "vec2"])
        assert removed == 3
        assert len(vector_store) == 2

        results = await vector_store.get(["vec0", "vec3"])
        assert [r["id"] for r in results if r is not None] == ["vec3"]
        assert results[0] is None

    async def test_delete_non_existing(self, vector_store: MMapVectorStore):
        removed = await vector_store.delete(["non_existent"])
        assert removed == 0

    async def test_delete_by_file(self, vector_store: MMapVectorStore, sample_embeddings: list[list[float]]):
        ids = ["vec1", "vec2", "vec3"]
        metadatas = [
            {"file_path": "/test/a.py"},
            {"file_path": "/test/b.py"},
            {"file_path": "/test/a.py"},
        ]
        await vector_store.upsert(ids, sample_embeddings[:3], metadatas, [""] * 3)

        removed = await vector_store.delete_by_file("/test/a.py")
        assert removed == 2
        assert len(vector_store) == 1

        results = await vector_store.get(ids)
        assert [r["id"] for r in results if r is not None] == ["vec2"]

    async def test_query_basic_accuracy(self, vector_store: MMapVectorStore):
        # Use orthogonal vectors to test distance
        v1 = [1.0] + [0.0] * 127
        v2 = [0.0, 1.0] + [0.0] * 126
        v3 = [0.0, 0.0, 1.0] + [0.0] * 125

        await vector_store.upsert(["v1", "v2", "v3"], [v1, v2, v3], [{}] * 3, [""] * 3)

        # Query close to v1
        results = await vector_store.query([1.0, 0.1] + [0.0] * 126, top_k=1)
        assert len(results) == 1
        assert results[0]["id"] == "v1"
        assert results[0]["score"] < 0.1

        # Query exactly v2
        results = await vector_store.query(v2, top_k=1)
        assert results[0]["id"] == "v2"
        assert results[0]["score"] == pytest.approx(0.0, abs=1e-6)

    async def test_query_top_k(self, vector_store: MMapVectorStore):
        # Generate vectors with decreasing similarity to [1, 0, ...]
        embeddings = []
        for i in range(10):
            v = [0.0] * 128
            v[0] = 1.0
            v[i + 1] = 1.0 / (i + 1)
            embeddings.append(v)

        ids = [f"vec{i}" for i in range(10)]
        await vector_store.upsert(ids, embeddings, [{}] * 10, [""] * 10)

        results = await vector_store.query([1.0] + [0.0] * 127, top_k=3)
        assert len(results) == 3
        assert results[0]["id"] == "vec9"
        assert results[1]["id"] == "vec8"
        assert results[2]["id"] == "vec7"

    async def test_query_with_filters(self, vector_store: MMapVectorStore):
        v1 = [1.0] + [0.0] * 127
        v2 = [0.0, 1.0] + [0.0] * 126

        await vector_store.upsert(["v1", "v2"], [v1, v2], [{"type": "func"}, {"type": "class"}], [""] * 2)

        # Query closest to v2, but filter for "func" -> should return v1
        results = await vector_store.query([0.0, 1.0] + [0.0] * 126, top_k=1, where={"type": "func"})
        assert len(results) == 1
        assert results[0]["id"] == "v1"

    async def test_query_filter_none(self, vector_store: MMapVectorStore):
        await vector_store.upsert(["v1"], [[1.0] * 128], [{"type": "func"}], [""])
        results = await vector_store.query([1.0] * 128, where={"type": "class"})
        assert len(results) == 0

    async def test_query_edge_cases(self, vector_store: MMapVectorStore):
        # Top-k <= 0
        assert await vector_store.query([1.0] * 128, top_k=0) == []
        assert await vector_store.query([1.0] * 128, top_k=-1) == []

        # Empty store
        assert await vector_store.query([1.0] * 128) == []

        # Query dim mismatch
        with pytest.raises(ValueError, match="Query embedding dim mismatch"):
            await vector_store.query([1.0] * 64)

    async def test_dimension_validation_explicit(self, tmp_path: Path):
        path = tmp_path / "dim_test.smpv"
        store = MMapVectorStore(path=str(path), dimension=64)
        await store.connect()

        # Correct dim
        await store.upsert(["v1"], [[0.0] * 64], [{}], [""])

        # Incorrect dim
        with pytest.raises(ValueError, match="Embedding dimension mismatch"):
            await store.upsert(["v2"], [[0.0] * 128], [{}], [""])

        await store.close()

    async def test_dimension_validation_inferred(self, tmp_path: Path):
        path = tmp_path / "infer_test.smpv"
        store = MMapVectorStore(path=str(path))  # dim=None
        await store.connect()

        # First upsert sets dim to 64
        await store.upsert(["v1"], [[0.0] * 64], [{}], [""])
        assert store.dimension == 64

        # Second upsert must match
        with pytest.raises(ValueError, match="Embedding dimension mismatch"):
            await store.upsert(["v2"], [[0.0] * 128], [{}], [""])

        await store.close()

    async def test_persistence_reopen(self, tmp_path: Path, sample_embedding: list[float]):
        path = tmp_path / "persist.smpv"

        # Write data
        store1 = MMapVectorStore(path=str(path), dimension=128)
        await store1.connect()
        await store1.upsert(["p1"], [sample_embedding], [{"meta": "data"}], ["doc1"])
        await store1.close()

        # Reopen and verify
        store2 = MMapVectorStore(path=str(path), dimension=128)
        await store2.connect()
        results = await store2.get(["p1"])
        assert len(results) == 1
        assert results[0]["metadata"] == {"meta": "data"}
        assert len(store2) == 1
        await store2.close()

    async def test_persistence_dim_mismatch(self, tmp_path: Path, sample_embedding: list[float]):
        path = tmp_path / "mismatch.smpv"

        store1 = MMapVectorStore(path=str(path), dimension=128)
        await store1.connect()
        await store1.upsert(["p1"], [sample_embedding], [{}], [""])
        await store1.close()

        # Try to reopen with dim=64
        store2 = MMapVectorStore(path=str(path), dimension=64)
        with pytest.raises(ValueError, match="Dimension mismatch"):
            await store2.connect()

    async def test_persistence_corruption(self, tmp_path: Path):
        path = tmp_path / "corrupt.smpv"
        path.write_bytes(b"too small")

        store = MMapVectorStore(path=str(path))
        with pytest.raises(ValueError, match="Corrupt .smpv file"):
            await store.connect()

    async def test_persistence_invalid_magic(self, tmp_path: Path):
        path = tmp_path / "magic.smpv"
        # Create a file that looks like a store but has wrong magic
        store = MMapVectorStore(path=str(path), dimension=128)
        await store.connect()
        await store.close()

        # Overwrite magic
        with open(path, "r+b") as f:
            f.write(b"WRNG")

        store2 = MMapVectorStore(path=str(path))
        with pytest.raises(ValueError, match="Invalid .smpv magic"):
            await store2.connect()

    async def test_zero_vectors(self, vector_store: MMapVectorStore):
        v_zero = [0.0] * 128
        v_one = [1.0] * 128

        await vector_store.upsert(["zero", "one"], [v_zero, v_one], [{}] * 2, [""] * 2)

        # Query with zero vector should not crash
        results = await vector_store.query(v_zero, top_k=1)
        assert len(results) == 1

        # Query with one vector should find it
        results = await vector_store.query(v_one, top_k=1)
        assert results[0]["id"] == "one"

    async def test_index_staleness_and_rebuild(self, vector_store: MMapVectorStore, sample_embedding: list[float]):
        # 1. Initial upsert (builds FAISS)
        await vector_store.upsert(["v1"], [sample_embedding], [{}], [""])
        assert vector_store._index_stale is False

        # 2. Update existing ID (makes index stale)
        new_emb = [x + 0.1 for x in sample_embedding]
        await vector_store.upsert(["v1"], [new_emb], [{}], [""])
        assert vector_store._index_stale is True

        # 3. Query should now use linear scan (internally)
        # To verify, we can check that it still returns correct result
        results = await vector_store.query(new_emb, top_k=1)
        assert results[0]["id"] == "v1"

        # 4. Delete (makes index stale)
        await vector_store.delete(["v1"])
        assert vector_store._index_stale is True

        # 5. New upsert should mark stale=False if it's purely additive (since FAISS .add is called)
        # Wait, looking at code:
        # if has_updates: self._index_stale = True else: self._index.add(new_vectors)
        # So new vectors don't make it stale.
        await vector_store.upsert(["v2"], [sample_embedding], [{}], [""])
        assert vector_store._index_stale is False

    async def test_add_code_embedding_helper(self, vector_store: MMapVectorStore, sample_embedding: list[float]):
        await vector_store.add_code_embedding(
            node_id="node1", embedding=sample_embedding, metadata={"file": "test.py"}, document="def hello(): pass"
        )

        results = await vector_store.get(["node1"])
        assert len(results) == 1
        assert results[0]["id"] == "node1"
        assert results[0]["metadata"] == {"file": "test.py"}
        assert results[0]["document"] == "def hello(): pass"

    async def test_query_similar_helper(self, vector_store: MMapVectorStore, sample_embedding: list[float]):
        await vector_store.upsert(["v1"], [sample_embedding], [{}], ["doc1"])

        results = await vector_store.query_similar(sample_embedding, top_k=1)
        assert len(results) == 1
        assert results[0]["id"] == "v1"

    async def test_clear_store(self, vector_store: MMapVectorStore, sample_embedding: list[float]):
        await vector_store.upsert(["v1"], [sample_embedding], [{}], [""])
        assert len(vector_store) == 1

        await vector_store.clear()
        assert len(vector_store) == 0
        assert vector_store.dimension == 128  # Kept from initial_dim

        results = await vector_store.get(["v1"])
        assert results == [None]

    async def test_upsert_empty_lists(self, vector_store: MMapVectorStore):
        await vector_store.upsert([], [], [])
        assert len(vector_store) == 0

    async def test_upsert_mismatched_lengths(self, vector_store: MMapVectorStore):
        with pytest.raises(ValueError, match="must have equal length"):
            await vector_store.upsert(["id1"], [[0.0] * 128], [])

        with pytest.raises(ValueError, match="must match ids length"):
            await vector_store.upsert(["id1"], [[0.0] * 128], [{}], ["doc1", "doc2"])

    async def test_large_scale_query(self, vector_store: MMapVectorStore):
        # Test with 100 vectors to ensure FAISS is working well
        count = 100
        ids = [f"v{i}" for i in range(count)]
        embeddings = np.random.random((count, 128)).astype(np.float32).tolist()
        metadatas = [{} for _ in range(count)]
        documents = ["" for _ in range(count)]

        await vector_store.upsert(ids, embeddings, metadatas, documents)

        # Query with one of the actual vectors
        target_idx = 42
        results = await vector_store.query(embeddings[target_idx], top_k=1)
        assert results[0]["id"] == ids[target_idx]
        assert results[0]["score"] == pytest.approx(0.0, abs=1e-5)
