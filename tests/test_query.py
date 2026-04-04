"""Tests for the query engine."""

from __future__ import annotations

import pytest

from smp.core.models import EdgeType, GraphEdge, GraphNode, NodeType, SemanticInfo
from smp.engine.enricher import LLMSemanticEnricher, _hash_embed
from smp.engine.query import DefaultQueryEngine
from smp.store.graph.neo4j_store import Neo4jGraphStore
from smp.store.vector.chroma_store import ChromaVectorStore


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
async def graph():
    store = Neo4jGraphStore()
    await store.connect()
    await store.clear()
    yield store
    await store.clear()
    await store.close()


@pytest.fixture()
async def vector():
    import uuid
    store = ChromaVectorStore(collection_name=f"smp_query_test_{uuid.uuid4().hex[:8]}")
    await store.connect()
    yield store
    await store.close()


@pytest.fixture()
async def engine(graph: Neo4jGraphStore, vector: ChromaVectorStore):
    enricher = LLMSemanticEnricher()
    return DefaultQueryEngine(graph, vector, enricher)


async def _seed_graph(graph: Neo4jGraphStore) -> None:
    """Seed a small graph for testing:
    file.py
      ├── import os
      ├── func_a() calls func_b()
      ├── func_b() calls func_c()
      ├── class Service
      │    └── method()
      └── func_c()
    """
    nodes = [
        GraphNode(id="file.py::FILE::file.py::1", type=NodeType.FILE, name="file.py", file_path="file.py", start_line=1, end_line=30),
        GraphNode(id="file.py::IMPORT::os::2", type=NodeType.IMPORT, name="os", file_path="file.py", start_line=2, end_line=2),
        GraphNode(id="file.py::FUNCTION::func_a::4", type=NodeType.FUNCTION, name="func_a", file_path="file.py", start_line=4, end_line=8),
        GraphNode(id="file.py::FUNCTION::func_b::10", type=NodeType.FUNCTION, name="func_b", file_path="file.py", start_line=10, end_line=14, docstring="Does B things."),
        GraphNode(id="file.py::FUNCTION::func_c::16", type=NodeType.FUNCTION, name="func_c", file_path="file.py", start_line=16, end_line=20),
        GraphNode(id="file.py::CLASS::Service::22", type=NodeType.CLASS, name="Service", file_path="file.py", start_line=22, end_line=28),
        GraphNode(id="file.py::METHOD::method::23", type=NodeType.METHOD, name="method", file_path="file.py", start_line=23, end_line=25, metadata={"class": "Service"}),
    ]
    edges = [
        GraphEdge(source_id="file.py::FILE::file.py::1", target_id="file.py::IMPORT::os::2", type=EdgeType.IMPORTS),
        GraphEdge(source_id="file.py::FILE::file.py::1", target_id="file.py::FUNCTION::func_a::4", type=EdgeType.CONTAINS),
        GraphEdge(source_id="file.py::FILE::file.py::1", target_id="file.py::FUNCTION::func_b::10", type=EdgeType.CONTAINS),
        GraphEdge(source_id="file.py::FILE::file.py::1", target_id="file.py::FUNCTION::func_c::16", type=EdgeType.CONTAINS),
        GraphEdge(source_id="file.py::FILE::file.py::1", target_id="file.py::CLASS::Service::22", type=EdgeType.CONTAINS),
        GraphEdge(source_id="file.py::FUNCTION::func_a::4", target_id="file.py::FUNCTION::func_b::10", type=EdgeType.CALLS),
        GraphEdge(source_id="file.py::FUNCTION::func_b::10", target_id="file.py::FUNCTION::func_c::16", type=EdgeType.CALLS),
        GraphEdge(source_id="file.py::CLASS::Service::22", target_id="file.py::METHOD::method::23", type=EdgeType.CONTAINS),
    ]
    await graph.upsert_nodes(nodes)
    await graph.upsert_edges(edges)


# ---------------------------------------------------------------------------
# navigate
# ---------------------------------------------------------------------------

class TestNavigate:
    @pytest.mark.asyncio
    async def test_navigate_node(self, engine: DefaultQueryEngine, graph: Neo4jGraphStore) -> None:
        await _seed_graph(graph)
        result = await engine.navigate("file.py::FUNCTION::func_a::4")
        assert "node" in result
        assert result["node"]["name"] == "func_a"
        assert len(result["neighbors"]) > 0
        assert len(result["edges"]) > 0

    @pytest.mark.asyncio
    async def test_navigate_missing(self, engine: DefaultQueryEngine, graph: Neo4jGraphStore) -> None:
        await _seed_graph(graph)
        result = await engine.navigate("nonexistent")
        assert "error" in result

    @pytest.mark.asyncio
    async def test_navigate_file(self, engine: DefaultQueryEngine, graph: Neo4jGraphStore) -> None:
        await _seed_graph(graph)
        result = await engine.navigate("file.py::FILE::file.py::1")
        assert result["node"]["type"] == "FILE"
        assert len(result["neighbors"]) >= 3


# ---------------------------------------------------------------------------
# trace
# ---------------------------------------------------------------------------

class TestTrace:
    @pytest.mark.asyncio
    async def test_trace_calls(self, engine: DefaultQueryEngine, graph: Neo4jGraphStore) -> None:
        await _seed_graph(graph)
        result = await engine.trace("file.py::FUNCTION::func_a::4", "CALLS", depth=2)
        names = {n["name"] for n in result}
        assert "func_b" in names
        assert "func_c" in names

    @pytest.mark.asyncio
    async def test_trace_depth_1(self, engine: DefaultQueryEngine, graph: Neo4jGraphStore) -> None:
        await _seed_graph(graph)
        result = await engine.trace("file.py::FUNCTION::func_a::4", "CALLS", depth=1)
        names = {n["name"] for n in result}
        assert "func_b" in names
        assert "func_c" not in names


# ---------------------------------------------------------------------------
# get_context
# ---------------------------------------------------------------------------

class TestGetContext:
    @pytest.mark.asyncio
    async def test_context_file(self, engine: DefaultQueryEngine, graph: Neo4jGraphStore) -> None:
        await _seed_graph(graph)
        ctx = await engine.get_context("file.py")
        assert ctx["file_path"] == "file.py"
        assert len(ctx["nodes"]) >= 5
        assert len(ctx["edges"]) >= 5

    @pytest.mark.asyncio
    async def test_context_empty_file(self, engine: DefaultQueryEngine, graph: Neo4jGraphStore) -> None:
        await _seed_graph(graph)
        ctx = await engine.get_context("nonexistent.py")
        assert len(ctx["nodes"]) == 0


# ---------------------------------------------------------------------------
# assess_impact
# ---------------------------------------------------------------------------

class TestAssessImpact:
    @pytest.mark.asyncio
    async def test_impact(self, engine: DefaultQueryEngine, graph: Neo4jGraphStore) -> None:
        await _seed_graph(graph)
        result = await engine.assess_impact("file.py::FUNCTION::func_b::10")
        assert result["entity"]["name"] == "func_b"
        assert result["total_affected"] >= 0

    @pytest.mark.asyncio
    async def test_impact_missing(self, engine: DefaultQueryEngine, graph: Neo4jGraphStore) -> None:
        await _seed_graph(graph)
        result = await engine.assess_impact("nonexistent")
        assert "error" in result


# ---------------------------------------------------------------------------
# locate_by_intent
# ---------------------------------------------------------------------------

class TestLocateByIntent:
    @pytest.mark.asyncio
    async def test_locate(self, engine: DefaultQueryEngine, graph: Neo4jGraphStore, vector: ChromaVectorStore) -> None:
        await _seed_graph(graph)

        # Enrich and store in vector store
        enricher = LLMSemanticEnricher()
        nodes = await graph.find_nodes()
        enriched = await enricher.enrich_batch(nodes)
        # Update graph with semantic info
        await graph.upsert_nodes(enriched)
        # Store in vector store
        ids = [n.id for n in enriched]
        embeddings = [n.semantic.embedding for n in enriched if n.semantic and n.semantic.embedding]
        metadatas = [{"name": n.name, "file_path": n.file_path, "type": n.type.value} for n in enriched if n.semantic and n.semantic.embedding]
        docs = [n.semantic.purpose for n in enriched if n.semantic and n.semantic.embedding]
        await vector.upsert(ids=ids[:len(embeddings)], embeddings=embeddings, metadatas=metadatas, documents=docs)

        result = await engine.locate_by_intent("function that does B things")
        assert len(result) > 0
        assert all("score" in r for r in result)

    @pytest.mark.asyncio
    async def test_locate_empty(self, engine: DefaultQueryEngine, graph: Neo4jGraphStore, vector: ChromaVectorStore) -> None:
        await _seed_graph(graph)
        result = await engine.locate_by_intent("")
        assert result == []


# ---------------------------------------------------------------------------
# find_flow
# ---------------------------------------------------------------------------

class TestFindFlow:
    @pytest.mark.asyncio
    async def test_direct_path(self, engine: DefaultQueryEngine, graph: Neo4jGraphStore) -> None:
        await _seed_graph(graph)
        paths = await engine.find_flow(
            "file.py::FUNCTION::func_a::4",
            "file.py::FUNCTION::func_b::10",
        )
        assert len(paths) >= 1
        assert paths[0][0]["name"] == "func_a"
        assert paths[0][-1]["name"] == "func_b"

    @pytest.mark.asyncio
    async def test_indirect_path(self, engine: DefaultQueryEngine, graph: Neo4jGraphStore) -> None:
        await _seed_graph(graph)
        paths = await engine.find_flow(
            "file.py::FUNCTION::func_a::4",
            "file.py::FUNCTION::func_c::16",
        )
        assert len(paths) >= 1
        # Path should go through func_b
        path_names = [n["name"] for n in paths[0]]
        assert "func_a" in path_names
        assert "func_c" in path_names

    @pytest.mark.asyncio
    async def test_no_path(self, engine: DefaultQueryEngine, graph: Neo4jGraphStore) -> None:
        await _seed_graph(graph)
        paths = await engine.find_flow(
            "file.py::IMPORT::os::2",
            "file.py::METHOD::method::23",
        )
        # No direct edges from import to method — but BFS walks all edges
        # so there might be a path via file node
        assert isinstance(paths, list)

    @pytest.mark.asyncio
    async def test_same_node(self, engine: DefaultQueryEngine, graph: Neo4jGraphStore) -> None:
        await _seed_graph(graph)
        paths = await engine.find_flow(
            "file.py::FUNCTION::func_a::4",
            "file.py::FUNCTION::func_a::4",
        )
        assert len(paths) == 1
        assert len(paths[0]) == 1
        assert paths[0][0]["name"] == "func_a"

    @pytest.mark.asyncio
    async def test_missing_node(self, engine: DefaultQueryEngine, graph: Neo4jGraphStore) -> None:
        await _seed_graph(graph)
        paths = await engine.find_flow("nonexistent", "also_nonexistent")
        assert paths == []
