"""Integration tests for ChromaVectorStore."""

from __future__ import annotations

import sys

import pysqlite3

sys.modules["sqlite3"] = pysqlite3  # type: ignore[assignment]

import pytest

pytestmark = pytest.mark.asyncio

try:
    from smp.store.chroma_store import ChromaVectorStore

    CHROMA_AVAILABLE = True
except Exception as e:  # noqa: BLE001
    CHROMA_AVAILABLE = False
    _CHROMA_IMPORT_ERROR = str(e)

skip_if_no_chroma = pytest.mark.skipif(not CHROMA_AVAILABLE, reason="ChromaDB unavailable")

_DIM = 8
_VEC_A = [0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8]
_VEC_B = [0.8, 0.7, 0.6, 0.5, 0.4, 0.3, 0.2, 0.1]
_VEC_C = [0.5, 0.5, 0.5, 0.5, 0.5, 0.5, 0.5, 0.5]


@pytest.fixture()
async def store() -> ChromaVectorStore:
    """Provide a connected in-memory ChromaVectorStore."""
    s = ChromaVectorStore(collection_name="test_collection")
    await s.connect()
    yield s
    await s.close()


@skip_if_no_chroma
class TestInit:
    def test_defaults(self) -> None:
        s = ChromaVectorStore()
        assert s._collection_name == "smp_code_embeddings"
        assert s._persist_dir is None
        assert s._client is None
        assert s._collection is None

    def test_custom_params(self) -> None:
        s = ChromaVectorStore(collection_name="my_col", persist_dir="/tmp/chroma")
        assert s._collection_name == "my_col"
        assert s._persist_dir == "/tmp/chroma"


@skip_if_no_chroma
class TestConnect:
    async def test_connect_in_memory(self) -> None:
        s = ChromaVectorStore(collection_name="conn_test")
        await s.connect()
        assert s._client is not None
        assert s._collection is not None
        await s.close()

    async def test_close_resets_state(self) -> None:
        s = ChromaVectorStore(collection_name="close_test")
        await s.connect()
        await s.close()
        assert s._client is None
        assert s._collection is None


@skip_if_no_chroma
class TestUpsert:
    async def test_upsert_multiple(self, store: ChromaVectorStore) -> None:
        await store.upsert(
            ids=["id1", "id2"],
            embeddings=[_VEC_A, _VEC_B],
            metadatas=[{"file_path": "a.py"}, {"file_path": "b.py"}],
            documents=["doc a", "doc b"],
        )

    async def test_upsert_without_documents(self, store: ChromaVectorStore) -> None:
        await store.upsert(
            ids=["id3"],
            embeddings=[_VEC_C],
            metadatas=[{"file_path": "c.py"}],
        )

    async def test_upsert_raises_when_not_connected(self) -> None:
        s = ChromaVectorStore()
        with pytest.raises(RuntimeError, match="not connected"):
            await s.upsert(ids=["x"], embeddings=[_VEC_A], metadatas=[{}])

    async def test_upsert_overwrites_existing(self, store: ChromaVectorStore) -> None:
        await store.upsert(ids=["dup"], embeddings=[_VEC_A], metadatas=[{"v": "1"}], documents=["first"])
        await store.upsert(ids=["dup"], embeddings=[_VEC_B], metadatas=[{"v": "2"}], documents=["second"])
        results = await store.get(["dup"])
        assert len(results) == 1
        assert results[0] is not None
        assert results[0]["document"] == "second"


@skip_if_no_chroma
class TestQuery:
    async def test_query_returns_top_k(self, store: ChromaVectorStore) -> None:
        await store.upsert(
            ids=["q1", "q2", "q3"],
            embeddings=[_VEC_A, _VEC_B, _VEC_C],
            metadatas=[{"file_path": "f.py"}] * 3,
            documents=["d1", "d2", "d3"],
        )
        results = await store.query(embedding=_VEC_A, top_k=2)
        assert len(results) == 2

    async def test_query_result_structure(self, store: ChromaVectorStore) -> None:
        await store.upsert(
            ids=["struct1"],
            embeddings=[_VEC_A],
            metadatas=[{"file_path": "s.py", "kind": "function"}],
            documents=["source code"],
        )
        results = await store.query(embedding=_VEC_A, top_k=1)
        assert len(results) == 1
        r = results[0]
        assert "id" in r
        assert "score" in r
        assert "metadata" in r
        assert "document" in r

    async def test_query_raises_when_not_connected(self) -> None:
        s = ChromaVectorStore()
        with pytest.raises(RuntimeError, match="not connected"):
            await s.query(embedding=_VEC_A)

    async def test_query_with_where_filter(self, store: ChromaVectorStore) -> None:
        await store.upsert(
            ids=["f1", "f2"],
            embeddings=[_VEC_A, _VEC_B],
            metadatas=[{"file_path": "match.py"}, {"file_path": "other.py"}],
            documents=["m", "o"],
        )
        results = await store.query(embedding=_VEC_A, top_k=5, where={"file_path": "match.py"})
        assert all(r["metadata"]["file_path"] == "match.py" for r in results)


@skip_if_no_chroma
class TestGet:
    async def test_get_by_ids(self, store: ChromaVectorStore) -> None:
        await store.upsert(
            ids=["get1", "get2"],
            embeddings=[_VEC_A, _VEC_B],
            metadatas=[{"file_path": "g1.py"}, {"file_path": "g2.py"}],
            documents=["doc1", "doc2"],
        )
        results = await store.get(["get1", "get2"])
        assert len(results) == 2
        ids_returned = {r["id"] for r in results if r}
        assert "get1" in ids_returned
        assert "get2" in ids_returned

    async def test_get_result_structure(self, store: ChromaVectorStore) -> None:
        await store.upsert(ids=["gs1"], embeddings=[_VEC_A], metadatas=[{"x": "y"}], documents=["hello"])
        results = await store.get(["gs1"])
        assert len(results) == 1
        r = results[0]
        assert r is not None
        assert r["id"] == "gs1"
        assert r["metadata"] == {"x": "y"}
        assert r["document"] == "hello"

    async def test_get_raises_when_not_connected(self) -> None:
        s = ChromaVectorStore()
        with pytest.raises(RuntimeError, match="not connected"):
            await s.get(["x"])


@skip_if_no_chroma
class TestDelete:
    async def test_delete_by_ids(self, store: ChromaVectorStore) -> None:
        await store.upsert(
            ids=["del1", "del2", "del3"],
            embeddings=[_VEC_A, _VEC_B, _VEC_C],
            metadatas=[{"file_path": "d.py"}] * 3,
            documents=["a", "b", "c"],
        )
        count = await store.delete(["del1", "del2"])
        assert count == 2

    async def test_delete_removes_items(self, store: ChromaVectorStore) -> None:
        await store.upsert(ids=["rm1"], embeddings=[_VEC_A], metadatas=[{"file_path": "rm.py"}], documents=["x"])
        await store.delete(["rm1"])
        results = await store.get(["rm1"])
        assert results == []

    async def test_delete_raises_when_not_connected(self) -> None:
        s = ChromaVectorStore()
        with pytest.raises(RuntimeError, match="not connected"):
            await s.delete(["x"])


@skip_if_no_chroma
class TestDeleteByFile:
    async def test_delete_by_file(self, store: ChromaVectorStore) -> None:
        await store.upsert(
            ids=["dbf1", "dbf2", "dbf3"],
            embeddings=[_VEC_A, _VEC_B, _VEC_C],
            metadatas=[
                {"file_path": "target.py"},
                {"file_path": "target.py"},
                {"file_path": "keep.py"},
            ],
            documents=["a", "b", "c"],
        )
        await store.delete_by_file("target.py")
        results = await store.query(embedding=_VEC_A, top_k=10, where={"file_path": "target.py"})
        assert results == []

    async def test_delete_by_file_returns_minus_one(self, store: ChromaVectorStore) -> None:
        await store.upsert(ids=["dbf4"], embeddings=[_VEC_A], metadatas=[{"file_path": "z.py"}], documents=["z"])
        ret = await store.delete_by_file("z.py")
        assert ret == -1

    async def test_delete_by_file_raises_when_not_connected(self) -> None:
        s = ChromaVectorStore()
        with pytest.raises(RuntimeError, match="not connected"):
            await s.delete_by_file("x.py")


@skip_if_no_chroma
class TestAddCodeEmbedding:
    async def test_add_code_embedding(self, store: ChromaVectorStore) -> None:
        await store.add_code_embedding(
            node_id="node_func_foo",
            embedding=_VEC_A,
            metadata={"file_path": "foo.py", "kind": "function", "name": "foo"},
            document="def foo(): pass",
        )
        results = await store.get(["node_func_foo"])
        assert len(results) == 1
        r = results[0]
        assert r is not None
        assert r["id"] == "node_func_foo"
        assert r["document"] == "def foo(): pass"

    async def test_add_code_embedding_default_document(self, store: ChromaVectorStore) -> None:
        await store.add_code_embedding(
            node_id="node_no_doc",
            embedding=_VEC_B,
            metadata={"file_path": "bar.py"},
        )
        results = await store.get(["node_no_doc"])
        assert results[0] is not None
        assert results[0]["document"] == ""


@skip_if_no_chroma
class TestQuerySimilar:
    async def test_query_similar_returns_list(self, store: ChromaVectorStore) -> None:
        await store.upsert(
            ids=["qs1", "qs2"],
            embeddings=[_VEC_A, _VEC_B],
            metadatas=[{"file_path": "q.py"}] * 2,
            documents=["d1", "d2"],
        )
        results = await store.query_similar(embedding=_VEC_A, top_k=2)
        assert isinstance(results, list)
        assert len(results) == 2

    async def test_query_similar_result_keys(self, store: ChromaVectorStore) -> None:
        await store.upsert(ids=["qs3"], embeddings=[_VEC_C], metadatas=[{"file_path": "r.py"}], documents=["doc"])
        results = await store.query_similar(embedding=_VEC_C, top_k=1)
        assert len(results) >= 1
        r = results[0]
        for key in ("id", "score", "metadata", "document"):
            assert key in r

    async def test_query_similar_with_where(self, store: ChromaVectorStore) -> None:
        await store.upsert(
            ids=["wh1", "wh2"],
            embeddings=[_VEC_A, _VEC_B],
            metadatas=[{"file_path": "inc.py"}, {"file_path": "exc.py"}],
            documents=["i", "e"],
        )
        results = await store.query_similar(embedding=_VEC_A, top_k=5, where={"file_path": "inc.py"})
        assert all(r["metadata"]["file_path"] == "inc.py" for r in results)


@skip_if_no_chroma
class TestClear:
    async def test_clear_empties_collection(self, store: ChromaVectorStore) -> None:
        await store.upsert(
            ids=["c1", "c2"],
            embeddings=[_VEC_A, _VEC_B],
            metadatas=[{"file_path": "x.py"}] * 2,
            documents=["a", "b"],
        )
        await store.clear()
        results = await store.get(["c1", "c2"])
        assert results == []

    async def test_clear_allows_new_inserts(self, store: ChromaVectorStore) -> None:
        await store.upsert(ids=["old"], embeddings=[_VEC_A], metadatas=[{"file_path": "old.py"}], documents=["old"])
        await store.clear()
        await store.upsert(ids=["new"], embeddings=[_VEC_B], metadatas=[{"file_path": "new.py"}], documents=["new"])
        results = await store.get(["new"])
        assert len(results) == 1
        assert results[0]["document"] == "new"

    async def test_clear_raises_when_not_connected(self) -> None:
        s = ChromaVectorStore()
        with pytest.raises(RuntimeError, match="not connected"):
            await s.clear()
