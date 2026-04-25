"""Integration tests for :class:`~smp.engine.query.DefaultQueryEngine`.

The engine is exercised against a real :class:`~smp.store.graph.mmap_store.MMapGraphStore`
seeded with a small graph (``file.py`` containing ``func_a``, ``func_b``,
``func_c`` and a ``Service`` class with one method).
"""

from __future__ import annotations

from collections.abc import AsyncIterator

import pytest

from smp.core.models import (
    EdgeType,
    GraphEdge,
    GraphNode,
    NodeType,
    SemanticProperties,
    StructuralProperties,
)
from smp.engine.query import DefaultQueryEngine
from smp.store.graph.mmap_store import MMapGraphStore


# ---------------------------------------------------------------------------
# Test fixture: a small, hand-built graph
# ---------------------------------------------------------------------------


def _node(
    node_id: str,
    node_type: NodeType,
    name: str,
    file_path: str = "file.py",
    start_line: int = 1,
    end_line: int = 1,
    docstring: str = "",
    signature: str | None = None,
) -> GraphNode:
    return GraphNode(
        id=node_id,
        type=node_type,
        file_path=file_path,
        structural=StructuralProperties(
            name=name,
            file=file_path,
            signature=signature or f"def {name}():",
            start_line=start_line,
            end_line=end_line,
            lines=max(end_line - start_line + 1, 1),
        ),
        semantic=SemanticProperties(
            docstring=docstring,
            status="enriched" if docstring else "no_metadata",
        ),
    )


@pytest.fixture()
async def seeded_engine(clean_graph: MMapGraphStore) -> AsyncIterator[DefaultQueryEngine]:
    """Yield a ``DefaultQueryEngine`` over a small, fully-seeded graph."""
    nodes = [
        _node("file.py::File::file.py::1", NodeType.FILE, "file.py", "file.py", 1, 30),
        _node(
            "file.py::File::os::2",
            NodeType.FILE,
            "os",
            "file.py",
            2,
            2,
            signature="import os",
        ),
        _node("file.py::Function::func_a::4", NodeType.FUNCTION, "func_a", "file.py", 4, 8),
        _node(
            "file.py::Function::func_b::10",
            NodeType.FUNCTION,
            "func_b",
            "file.py",
            10,
            14,
            docstring="Does B things.",
        ),
        _node("file.py::Function::func_c::16", NodeType.FUNCTION, "func_c", "file.py", 16, 20),
        _node("file.py::Class::Service::22", NodeType.CLASS, "Service", "file.py", 22, 28),
        _node("file.py::Function::method::23", NodeType.FUNCTION, "method", "file.py", 23, 25),
    ]
    edges = [
        GraphEdge(
            source_id="file.py::File::file.py::1",
            target_id="file.py::File::os::2",
            type=EdgeType.IMPORTS,
        ),
        GraphEdge(
            source_id="file.py::File::file.py::1",
            target_id="file.py::Function::func_a::4",
            type=EdgeType.DEFINES,
        ),
        GraphEdge(
            source_id="file.py::File::file.py::1",
            target_id="file.py::Function::func_b::10",
            type=EdgeType.DEFINES,
        ),
        GraphEdge(
            source_id="file.py::File::file.py::1",
            target_id="file.py::Function::func_c::16",
            type=EdgeType.DEFINES,
        ),
        GraphEdge(
            source_id="file.py::File::file.py::1",
            target_id="file.py::Class::Service::22",
            type=EdgeType.DEFINES,
        ),
        GraphEdge(
            source_id="file.py::Function::func_a::4",
            target_id="file.py::Function::func_b::10",
            type=EdgeType.CALLS,
        ),
        GraphEdge(
            source_id="file.py::Function::func_b::10",
            target_id="file.py::Function::func_c::16",
            type=EdgeType.CALLS,
        ),
        GraphEdge(
            source_id="file.py::Class::Service::22",
            target_id="file.py::Function::method::23",
            type=EdgeType.DEFINES,
        ),
    ]
    await clean_graph.upsert_nodes(nodes)
    await clean_graph.upsert_edges(edges)

    yield DefaultQueryEngine(clean_graph)


# ---------------------------------------------------------------------------
# navigate()
# ---------------------------------------------------------------------------


class TestNavigate:
    async def test_returns_dict(self, seeded_engine: DefaultQueryEngine) -> None:
        result = await seeded_engine.navigate("file.py::Function::func_a::4")
        assert isinstance(result, dict)

    async def test_entity_structure(self, seeded_engine: DefaultQueryEngine) -> None:
        result = await seeded_engine.navigate("file.py::Function::func_a::4")
        entity = result["entity"]
        assert "id" in entity
        assert "type" in entity
        assert entity.get("name") == "func_a"

    async def test_with_relationships(self, seeded_engine: DefaultQueryEngine) -> None:
        result = await seeded_engine.navigate(
            "file.py::Function::func_a::4", include_relationships=True
        )
        rels = result["relationships"]
        for key in ("calls", "called_by", "depends_on", "imported_by"):
            assert key in rels

    async def test_missing_node(self, seeded_engine: DefaultQueryEngine) -> None:
        result = await seeded_engine.navigate("nonexistent_node")
        assert "error" in result


# ---------------------------------------------------------------------------
# trace()
# ---------------------------------------------------------------------------


class TestTrace:
    async def test_returns_list(self, seeded_engine: DefaultQueryEngine) -> None:
        result = await seeded_engine.trace("file.py::Function::func_a::4", "CALLS", depth=2)
        assert isinstance(result, list)

    async def test_nodes_have_dict_structure(
        self, seeded_engine: DefaultQueryEngine
    ) -> None:
        result = await seeded_engine.trace("file.py::Function::func_a::4", "CALLS", depth=2)
        for node in result:
            assert isinstance(node, dict)
            for key in ("id", "type", "name"):
                assert key in node

    async def test_finds_call_chain(self, seeded_engine: DefaultQueryEngine) -> None:
        result = await seeded_engine.trace("file.py::Function::func_a::4", "CALLS", depth=3)
        names = {n["name"] for n in result}
        assert "func_b" in names
        assert "func_c" in names


# ---------------------------------------------------------------------------
# get_context()
# ---------------------------------------------------------------------------


class TestGetContext:
    async def test_returns_rich_structure(self, seeded_engine: DefaultQueryEngine) -> None:
        result = await seeded_engine.get_context("file.py")
        assert isinstance(result, dict)
        for key in (
            "self",
            "imports",
            "imported_by",
            "defines",
            "related_patterns",
            "entry_points",
            "data_flow_in",
            "data_flow_out",
            "summary",
        ):
            assert key in result

    async def test_self_contains_node_info(self, seeded_engine: DefaultQueryEngine) -> None:
        result = await seeded_engine.get_context("file.py")
        self_node = result["self"]
        assert "name" in self_node
        assert "file_path" in self_node

    async def test_summary_has_expected_fields(self, seeded_engine: DefaultQueryEngine) -> None:
        result = await seeded_engine.get_context("file.py")
        summary = result["summary"]
        for key in ("role", "blast_radius", "avg_complexity", "max_complexity", "risk_level"):
            assert key in summary

    async def test_missing_file(self, seeded_engine: DefaultQueryEngine) -> None:
        result = await seeded_engine.get_context("nonexistent.py")
        assert "error" in result


# ---------------------------------------------------------------------------
# assess_impact()
# ---------------------------------------------------------------------------


class TestAssessImpact:
    async def test_returns_dict(self, seeded_engine: DefaultQueryEngine) -> None:
        result = await seeded_engine.assess_impact("file.py::Function::func_b::10")
        assert isinstance(result, dict)

    async def test_has_expected_fields(self, seeded_engine: DefaultQueryEngine) -> None:
        result = await seeded_engine.assess_impact("file.py::Function::func_b::10")
        for key in ("affected_files", "affected_functions", "severity", "recommendations"):
            assert key in result

    async def test_severity_levels(self, seeded_engine: DefaultQueryEngine) -> None:
        result = await seeded_engine.assess_impact("file.py::Function::func_c::16")
        assert result["severity"] in ("low", "medium", "high")

    async def test_missing_node(self, seeded_engine: DefaultQueryEngine) -> None:
        result = await seeded_engine.assess_impact("nonexistent_node")
        assert "error" in result


# ---------------------------------------------------------------------------
# find_flow()
# ---------------------------------------------------------------------------


class TestFindFlow:
    async def test_returns_dict(self, seeded_engine: DefaultQueryEngine) -> None:
        result = await seeded_engine.find_flow(
            "file.py::Function::func_a::4", "file.py::Function::func_c::16"
        )
        assert isinstance(result, dict)

    async def test_has_expected_fields(self, seeded_engine: DefaultQueryEngine) -> None:
        result = await seeded_engine.find_flow(
            "file.py::Function::func_a::4", "file.py::Function::func_c::16"
        )
        assert "path" in result
        assert "data_transformations" in result

    async def test_same_node(self, seeded_engine: DefaultQueryEngine) -> None:
        result = await seeded_engine.find_flow(
            "file.py::Function::func_a::4", "file.py::Function::func_a::4"
        )
        assert len(result["path"]) == 1

    async def test_direct_path(self, seeded_engine: DefaultQueryEngine) -> None:
        result = await seeded_engine.find_flow(
            "file.py::Function::func_a::4", "file.py::Function::func_b::10"
        )
        path_names = [n["node"] for n in result["path"]]
        assert "func_a" in path_names or "file.py::Function::func_a::4" in path_names


# ---------------------------------------------------------------------------
# Combined / smoke
# ---------------------------------------------------------------------------


class TestQueryEngineSmoke:
    async def test_navigate_and_trace_work_together(
        self, seeded_engine: DefaultQueryEngine
    ) -> None:
        nav = await seeded_engine.navigate("file.py::Function::func_a::4")
        assert "entity" in nav

        traced = await seeded_engine.trace("file.py::Function::func_a::4", depth=3)
        assert len(traced) > 0
