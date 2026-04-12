"""Tests for the query engine — SMP(3)."""

from __future__ import annotations

import pytest

from smp.core.models import (
    EdgeType,
    GraphEdge,
    GraphNode,
    NodeType,
    SemanticProperties,
    StructuralProperties,
)
from smp.engine.enricher import StaticSemanticEnricher
from smp.engine.query import DefaultQueryEngine
from smp.store.graph.neo4j_store import Neo4jGraphStore

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
async def engine(graph: Neo4jGraphStore):
    enricher = StaticSemanticEnricher()
    return DefaultQueryEngine(graph, enricher)


def _make_node(
    id: str,
    type: NodeType,
    name: str,
    file_path: str,
    start_line: int = 1,
    end_line: int = 10,
    docstring: str = "",
    signature: str = "",
) -> GraphNode:
    return GraphNode(
        id=id,
        type=type,
        file_path=file_path,
        structural=StructuralProperties(
            name=name,
            file=file_path,
            signature=signature or f"{type.value.lower()} {name}",
            start_line=start_line,
            end_line=end_line,
            lines=end_line - start_line + 1,
        ),
        semantic=SemanticProperties(
            docstring=docstring,
            status="enriched" if docstring else "no_metadata",
        ),
    )


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
        _make_node("file.py::File::file.py::1", NodeType.FILE, "file.py", "file.py", 1, 30),
        _make_node("file.py::File::os::2", NodeType.FILE, "os", "file.py", 2, 2, signature="import os"),
        _make_node("file.py::Function::func_a::4", NodeType.FUNCTION, "func_a", "file.py", 4, 8),
        _make_node(
            "file.py::Function::func_b::10", NodeType.FUNCTION, "func_b", "file.py", 10, 14, docstring="Does B things."
        ),
        _make_node("file.py::Function::func_c::16", NodeType.FUNCTION, "func_c", "file.py", 16, 20),
        _make_node("file.py::Class::Service::22", NodeType.CLASS, "Service", "file.py", 22, 28),
        _make_node("file.py::Function::method::23", NodeType.FUNCTION, "method", "file.py", 23, 25),
    ]
    edges = [
        GraphEdge(source_id="file.py::File::file.py::1", target_id="file.py::File::os::2", type=EdgeType.IMPORTS),
        GraphEdge(
            source_id="file.py::File::file.py::1", target_id="file.py::Function::func_a::4", type=EdgeType.DEFINES
        ),
        GraphEdge(
            source_id="file.py::File::file.py::1", target_id="file.py::Function::func_b::10", type=EdgeType.DEFINES
        ),
        GraphEdge(
            source_id="file.py::File::file.py::1", target_id="file.py::Function::func_c::16", type=EdgeType.DEFINES
        ),
        GraphEdge(
            source_id="file.py::File::file.py::1", target_id="file.py::Class::Service::22", type=EdgeType.DEFINES
        ),
        GraphEdge(
            source_id="file.py::Function::func_a::4", target_id="file.py::Function::func_b::10", type=EdgeType.CALLS
        ),
        GraphEdge(
            source_id="file.py::Function::func_b::10", target_id="file.py::Function::func_c::16", type=EdgeType.CALLS
        ),
        GraphEdge(
            source_id="file.py::Class::Service::22", target_id="file.py::Function::method::23", type=EdgeType.DEFINES
        ),
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
        result = await engine.navigate("file.py::Function::func_a::4")
        assert "entity" in result
        assert result["entity"]["name"] == "func_a"

    @pytest.mark.asyncio
    async def test_navigate_missing(self, engine: DefaultQueryEngine, graph: Neo4jGraphStore) -> None:
        await _seed_graph(graph)
        result = await engine.navigate("nonexistent")
        assert "error" in result

    @pytest.mark.asyncio
    async def test_navigate_file(self, engine: DefaultQueryEngine, graph: Neo4jGraphStore) -> None:
        await _seed_graph(graph)
        result = await engine.navigate("file.py::File::file.py::1")
        assert result["entity"]["type"] == "File"


# ---------------------------------------------------------------------------
# trace
# ---------------------------------------------------------------------------


class TestTrace:
    @pytest.mark.asyncio
    async def test_trace_calls(self, engine: DefaultQueryEngine, graph: Neo4jGraphStore) -> None:
        await _seed_graph(graph)
        result = await engine.trace("file.py::Function::func_a::4", "CALLS", depth=2)
        names = {n["name"] for n in result}
        assert "func_b" in names
        assert "func_c" in names

    @pytest.mark.asyncio
    async def test_trace_depth_1(self, engine: DefaultQueryEngine, graph: Neo4jGraphStore) -> None:
        await _seed_graph(graph)
        result = await engine.trace("file.py::Function::func_a::4", "CALLS", depth=1)
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
        assert "self" in ctx
        assert len(ctx["functions_defined"]) >= 3

    @pytest.mark.asyncio
    async def test_context_empty_file(self, engine: DefaultQueryEngine, graph: Neo4jGraphStore) -> None:
        await _seed_graph(graph)
        ctx = await engine.get_context("nonexistent.py")
        assert "error" in ctx


# ---------------------------------------------------------------------------
# assess_impact
# ---------------------------------------------------------------------------


class TestAssessImpact:
    @pytest.mark.asyncio
    async def test_impact(self, engine: DefaultQueryEngine, graph: Neo4jGraphStore) -> None:
        await _seed_graph(graph)
        result = await engine.assess_impact("file.py::Function::func_b::10")
        assert "affected_files" in result or "severity" in result

    @pytest.mark.asyncio
    async def test_impact_missing(self, engine: DefaultQueryEngine, graph: Neo4jGraphStore) -> None:
        await _seed_graph(graph)
        result = await engine.assess_impact("nonexistent")
        assert "error" in result or result.get("severity") == "none"


# ---------------------------------------------------------------------------
# locate
# ---------------------------------------------------------------------------


class TestLocate:
    @pytest.mark.asyncio
    async def test_locate_by_name(self, engine: DefaultQueryEngine, graph: Neo4jGraphStore) -> None:
        await _seed_graph(graph)
        result = await engine.locate("func_b")
        assert len(result) > 0
        assert result[0]["entity"] == "func_b"

    @pytest.mark.asyncio
    async def test_locate_empty(self, engine: DefaultQueryEngine, graph: Neo4jGraphStore) -> None:
        await _seed_graph(graph)
        result = await engine.locate("")
        assert result == [] or isinstance(result, list)


# ---------------------------------------------------------------------------
# search
# ---------------------------------------------------------------------------


class TestSearch:
    @pytest.mark.asyncio
    async def test_search_docstring(self, engine: DefaultQueryEngine, graph: Neo4jGraphStore) -> None:
        await _seed_graph(graph)
        result = await engine.search("B things")
        assert result["total"] >= 1

    @pytest.mark.asyncio
    async def test_search_no_match(self, engine: DefaultQueryEngine, graph: Neo4jGraphStore) -> None:
        await _seed_graph(graph)
        result = await engine.search("xyz_nonexistent_term")
        assert result["total"] == 0
        assert "hint" in result


# ---------------------------------------------------------------------------
# find_flow
# ---------------------------------------------------------------------------


class TestFindFlow:
    @pytest.mark.asyncio
    async def test_direct_path(self, engine: DefaultQueryEngine, graph: Neo4jGraphStore) -> None:
        await _seed_graph(graph)
        result = await engine.find_flow(
            "file.py::Function::func_a::4",
            "file.py::Function::func_b::10",
        )
        assert len(result["path"]) >= 1
        assert result["path"][0]["node"] == "func_a"
        assert result["path"][-1]["node"] == "func_b"

    @pytest.mark.asyncio
    async def test_same_node(self, engine: DefaultQueryEngine, graph: Neo4jGraphStore) -> None:
        await _seed_graph(graph)
        result = await engine.find_flow(
            "file.py::Function::func_a::4",
            "file.py::Function::func_a::4",
        )
        assert len(result["path"]) == 1
        assert result["path"][0]["node"] == "func_a"

    @pytest.mark.asyncio
    async def test_missing_node(self, engine: DefaultQueryEngine, graph: Neo4jGraphStore) -> None:
        await _seed_graph(graph)
        result = await engine.find_flow("nonexistent", "also_nonexistent")
        assert result["path"] == []
