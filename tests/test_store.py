"""Tests for Neo4j graph store and ChromaDB vector store."""

from __future__ import annotations

import pytest

from smp.core.models import EdgeType, GraphEdge, GraphNode, NodeType, SemanticInfo
from smp.store.graph.neo4j_store import Neo4jGraphStore
from smp.store.vector.chroma_store import ChromaVectorStore
from tests.conftest import make_edge, make_node


# ===================================================================
# Neo4j Graph Store Tests
# ===================================================================

class TestNeo4jNodeCRUD:
    @pytest.mark.asyncio
    async def test_upsert_and_get(self, clean_graph: Neo4jGraphStore) -> None:
        node = make_node()
        await clean_graph.upsert_node(node)
        fetched = await clean_graph.get_node("func_login")
        assert fetched is not None
        assert fetched.id == "func_login"
        assert fetched.name == "login"
        assert fetched.type == NodeType.FUNCTION

    @pytest.mark.asyncio
    async def test_upsert_updates_existing(self, clean_graph: Neo4jGraphStore) -> None:
        node = make_node()
        await clean_graph.upsert_node(node)
        # Update signature
        updated = make_node(signature="def login(user: User, otp: str) -> Token:")
        await clean_graph.upsert_node(updated)
        fetched = await clean_graph.get_node("func_login")
        assert fetched is not None
        assert "otp" in fetched.signature

    @pytest.mark.asyncio
    async def test_upsert_batch(self, clean_graph: Neo4jGraphStore) -> None:
        nodes = [make_node(id=f"n{i}", name=f"n{i}") for i in range(10)]
        await clean_graph.upsert_nodes(nodes)
        assert await clean_graph.count_nodes() == 10

    @pytest.mark.asyncio
    async def test_get_missing_node(self, clean_graph: Neo4jGraphStore) -> None:
        result = await clean_graph.get_node("nonexistent")
        assert result is None

    @pytest.mark.asyncio
    async def test_delete_node(self, clean_graph: Neo4jGraphStore) -> None:
        await clean_graph.upsert_node(make_node())
        assert await clean_graph.delete_node("func_login") is True
        assert await clean_graph.get_node("func_login") is None

    @pytest.mark.asyncio
    async def test_delete_missing_returns_false(self, clean_graph: Neo4jGraphStore) -> None:
        assert await clean_graph.delete_node("nope") is False

    @pytest.mark.asyncio
    async def test_delete_by_file(self, clean_graph: Neo4jGraphStore) -> None:
        nodes = [
            make_node(id="a", file_path="f1.py"),
            make_node(id="b", file_path="f1.py"),
            make_node(id="c", file_path="f2.py"),
        ]
        await clean_graph.upsert_nodes(nodes)
        deleted = await clean_graph.delete_nodes_by_file("f1.py")
        assert deleted == 2
        assert await clean_graph.count_nodes() == 1


class TestNeo4jEdgeCRUD:
    @pytest.mark.asyncio
    async def test_upsert_edge(self, clean_graph: Neo4jGraphStore) -> None:
        await clean_graph.upsert_nodes([make_node(id="a"), make_node(id="b")])
        edge = make_edge(source="a", target="b", edge_type=EdgeType.CALLS)
        await clean_graph.upsert_edge(edge)
        edges = await clean_graph.get_edges("a", direction="outgoing")
        assert len(edges) == 1
        assert edges[0].target_id == "b"

    @pytest.mark.asyncio
    async def test_upsert_edges_batch(self, clean_graph: Neo4jGraphStore) -> None:
        nodes = [make_node(id=f"n{i}") for i in range(5)]
        await clean_graph.upsert_nodes(nodes)
        edges = [make_edge(source=f"n{i}", target=f"n{i+1}") for i in range(4)]
        await clean_graph.upsert_edges(edges)
        total = await clean_graph.count_edges()
        assert total == 4

    @pytest.mark.asyncio
    async def test_get_edges_by_type(self, clean_graph: Neo4jGraphStore) -> None:
        await clean_graph.upsert_nodes([make_node(id="x"), make_node(id="y"), make_node(id="z")])
        await clean_graph.upsert_edge(make_edge(source="x", target="y", edge_type=EdgeType.CALLS))
        await clean_graph.upsert_edge(make_edge(source="x", target="z", edge_type=EdgeType.IMPORTS))
        calls = await clean_graph.get_edges("x", edge_type=EdgeType.CALLS)
        assert len(calls) == 1

    @pytest.mark.asyncio
    async def test_incoming_edges(self, clean_graph: Neo4jGraphStore) -> None:
        await clean_graph.upsert_nodes([make_node(id="x"), make_node(id="y")])
        await clean_graph.upsert_edge(make_edge(source="x", target="y"))
        incoming = await clean_graph.get_edges("y", direction="incoming")
        assert len(incoming) == 1
        assert incoming[0].source_id == "x"


class TestNeo4jTraversal:
    @pytest.mark.asyncio
    async def test_neighbors(self, clean_graph: Neo4jGraphStore) -> None:
        nodes = [make_node(id=f"n{i}", name=f"n{i}") for i in range(4)]
        await clean_graph.upsert_nodes(nodes)
        edges = [
            make_edge(source="n0", target="n1"),
            make_edge(source="n0", target="n2"),
            make_edge(source="n1", target="n3"),
        ]
        await clean_graph.upsert_edges(edges)
        neighbors = await clean_graph.get_neighbors("n0", depth=1)
        ids = {n.id for n in neighbors}
        assert ids == {"n1", "n2"}

    @pytest.mark.asyncio
    async def test_traverse(self, clean_graph: Neo4jGraphStore) -> None:
        nodes = [make_node(id=f"n{i}", name=f"n{i}") for i in range(5)]
        await clean_graph.upsert_nodes(nodes)
        edges = [make_edge(source=f"n{i}", target=f"n{i+1}") for i in range(4)]
        await clean_graph.upsert_edges(edges)
        result = await clean_graph.traverse("n0", EdgeType.CALLS, depth=3)
        ids = {n.id for n in result}
        assert "n1" in ids
        assert "n3" in ids


class TestNeo4jSearch:
    @pytest.mark.asyncio
    async def test_find_by_type(self, clean_graph: Neo4jGraphStore) -> None:
        await clean_graph.upsert_nodes([
            make_node(id="f1", type=NodeType.FUNCTION, name="a"),
            make_node(id="c1", type=NodeType.CLASS, name="B"),
        ])
        funcs = await clean_graph.find_nodes(type=NodeType.FUNCTION)
        assert len(funcs) == 1
        assert funcs[0].id == "f1"

    @pytest.mark.asyncio
    async def test_find_by_file(self, clean_graph: Neo4jGraphStore) -> None:
        await clean_graph.upsert_nodes([
            make_node(id="a", file_path="x.py"),
            make_node(id="b", file_path="y.py"),
        ])
        result = await clean_graph.find_nodes(file_path="x.py")
        assert len(result) == 1

    @pytest.mark.asyncio
    async def test_find_by_name(self, clean_graph: Neo4jGraphStore) -> None:
        await clean_graph.upsert_nodes([
            make_node(id="a", name="login"),
            make_node(id="b", name="logout"),
        ])
        result = await clean_graph.find_nodes(name="login")
        assert len(result) == 1


class TestNeo4jCounts:
    @pytest.mark.asyncio
    async def test_empty_counts(self, clean_graph: Neo4jGraphStore) -> None:
        assert await clean_graph.count_nodes() == 0
        assert await clean_graph.count_edges() == 0

    @pytest.mark.asyncio
    async def test_counts_after_inserts(self, clean_graph: Neo4jGraphStore) -> None:
        await clean_graph.upsert_nodes([make_node(id="a"), make_node(id="b")])
        await clean_graph.upsert_edge(make_edge(source="a", target="b"))
        assert await clean_graph.count_nodes() == 2
        assert await clean_graph.count_edges() == 1


# ===================================================================
# ChromaDB Vector Store Tests
# ===================================================================

class TestChromaVectorStore:
    @pytest.mark.asyncio
    async def test_upsert_and_query(self, vector_store: ChromaVectorStore) -> None:
        emb = [1.0, 0.0, 0.0]
        await vector_store.upsert(
            ids=["n1"],
            embeddings=[emb],
            metadatas=[{"name": "login", "file_path": "auth.py"}],
            documents=["def login(): ..."],
        )
        results = await vector_store.query(emb, top_k=1)
        assert len(results) == 1
        assert results[0]["id"] == "n1"
        assert results[0]["score"] > 0.99  # identical vector → ~1.0 cosine similarity

    @pytest.mark.asyncio
    async def test_query_with_filter(self, vector_store: ChromaVectorStore) -> None:
        await vector_store.upsert(
            ids=["n1", "n2"],
            embeddings=[[1.0, 0.0], [0.0, 1.0]],
            metadatas=[{"file_path": "a.py"}, {"file_path": "b.py"}],
        )
        results = await vector_store.query([1.0, 0.0], top_k=5, where={"file_path": "a.py"})
        assert len(results) == 1
        assert results[0]["id"] == "n1"

    @pytest.mark.asyncio
    async def test_get_existing(self, vector_store: ChromaVectorStore) -> None:
        await vector_store.upsert(
            ids=["n1"],
            embeddings=[[1.0, 0.0]],
            metadatas=[{"name": "test"}],
            documents=["test doc"],
        )
        results = await vector_store.get(["n1", "n2"])
        assert results[0] is not None
        assert results[0]["id"] == "n1"
        assert results[1] is None

    @pytest.mark.asyncio
    async def test_delete(self, vector_store: ChromaVectorStore) -> None:
        await vector_store.upsert(
            ids=["n1", "n2"],
            embeddings=[[1.0], [2.0]],
            metadatas=[{}, {}],
        )
        deleted = await vector_store.delete(["n1"])
        assert deleted == 1
        results = await vector_store.get(["n1"])
        assert results[0] is None

    @pytest.mark.asyncio
    async def test_delete_by_file(self, vector_store: ChromaVectorStore) -> None:
        await vector_store.upsert(
            ids=["a1", "a2", "b1"],
            embeddings=[[1.0], [2.0], [3.0]],
            metadatas=[
                {"file_path": "a.py"},
                {"file_path": "a.py"},
                {"file_path": "b.py"},
            ],
        )
        deleted = await vector_store.delete_by_file("a.py")
        assert deleted == 2
        results = await vector_store.get(["a1", "a2", "b1"])
        assert results[0] is None
        assert results[1] is None
        assert results[2] is not None

    @pytest.mark.asyncio
    async def test_upsert_is_idempotent(self, vector_store: ChromaVectorStore) -> None:
        await vector_store.upsert(
            ids=["n1"],
            embeddings=[[1.0]],
            metadatas=[{"v": "first"}],
        )
        await vector_store.upsert(
            ids=["n1"],
            embeddings=[[2.0]],
            metadatas=[{"v": "second"}],
        )
        results = await vector_store.get(["n1"])
        assert results[0] is not None
        assert results[0]["metadata"]["v"] == "second"

    @pytest.mark.asyncio
    async def test_empty_upsert(self, vector_store: ChromaVectorStore) -> None:
        # Should not raise
        await vector_store.upsert(ids=[], embeddings=[], metadatas=[])
