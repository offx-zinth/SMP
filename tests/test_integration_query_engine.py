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
        result = await seeded_engine.navigate("file.py::Function::func_a::4", include_relationships=True)
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

    async def test_nodes_have_dict_structure(self, seeded_engine: DefaultQueryEngine) -> None:
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

    async def test_reach_labels_callers_and_callees(self, seeded_engine: DefaultQueryEngine) -> None:
        result = await seeded_engine.trace("file.py::Function::func_b::10", "CALLS", depth=1, direction="both")
        by_name = {n["name"]: n["reach"] for n in result}
        assert by_name["func_b"] == "self"
        assert by_name["func_a"] == "caller"
        assert by_name["func_c"] == "callee"

    async def test_both_excludes_callee_siblings(self, clean_graph: MMapGraphStore) -> None:
        # sib_a and sib_b share helper h. Tracing sib_a with direction=both
        # must report h as a callee and must NOT report sib_b (a mixed
        # out-then-in walk is neither a caller nor a callee).
        helper = _node("sib.py::Function::h::1", NodeType.FUNCTION, "h", "sib.py", 1, 3)
        sib_a = _node("sib.py::Function::sib_a::5", NodeType.FUNCTION, "sib_a", "sib.py", 5, 7)
        sib_b = _node("sib.py::Function::sib_b::9", NodeType.FUNCTION, "sib_b", "sib.py", 9, 11)
        await clean_graph.upsert_nodes([helper, sib_a, sib_b])
        await clean_graph.upsert_edges(
            [
                GraphEdge(source_id=sib_a.id, target_id=helper.id, type=EdgeType.CALLS),
                GraphEdge(source_id=sib_b.id, target_id=helper.id, type=EdgeType.CALLS),
            ]
        )
        engine = DefaultQueryEngine(clean_graph)
        result = await engine.trace("sib_a", "CALLS", depth=3, direction="both")
        names = {n["name"] for n in result}
        assert "h" in names
        assert "sib_b" not in names
        by_name = {n["name"]: n["reach"] for n in result}
        assert by_name["h"] == "callee"
        assert by_name["sib_a"] == "self"


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
        result = await seeded_engine.find_flow("file.py::Function::func_a::4", "file.py::Function::func_c::16")
        assert isinstance(result, dict)

    async def test_has_expected_fields(self, seeded_engine: DefaultQueryEngine) -> None:
        result = await seeded_engine.find_flow("file.py::Function::func_a::4", "file.py::Function::func_c::16")
        assert "path" in result
        assert "data_transformations" in result

    async def test_same_node(self, seeded_engine: DefaultQueryEngine) -> None:
        result = await seeded_engine.find_flow("file.py::Function::func_a::4", "file.py::Function::func_a::4")
        assert len(result["path"]) == 1

    async def test_direct_path(self, seeded_engine: DefaultQueryEngine) -> None:
        result = await seeded_engine.find_flow("file.py::Function::func_a::4", "file.py::Function::func_b::10")
        path_names = [n["node"] for n in result["path"]]
        assert "func_a" in path_names or "file.py::Function::func_a::4" in path_names

    async def test_forward_hops_follow_edge_direction(self, seeded_engine: DefaultQueryEngine) -> None:
        result = await seeded_engine.find_flow("file.py::Function::func_a::4", "file.py::Function::func_c::16")
        assert result["direction"] == "outgoing"
        assert len(result["hops"]) == 2
        assert all(h["orientation"] == "forward" for h in result["hops"])
        assert result["hops"][0] == {
            "from": "func_a",
            "to": "func_b",
            "edge_type": "CALLS",
            "orientation": "forward",
        }
        assert result["data_transformations"] == ["func_a → func_b", "func_b → func_c"]

    async def test_reverse_hops_marked_not_flipped(self, seeded_engine: DefaultQueryEngine) -> None:
        # Stored edges run func_a → func_b → func_c; asking callee → caller
        # must report reverse orientation, never a fake forward path.
        result = await seeded_engine.find_flow("file.py::Function::func_c::16", "file.py::Function::func_a::4")
        assert result["direction"] == "incoming"
        assert len(result["hops"]) == 2
        assert all(h["orientation"] == "reverse" for h in result["hops"])
        assert result["hops"][0]["from"] == "func_c"
        assert result["hops"][0]["to"] == "func_b"
        assert any("←" in t and "reverse CALLS" in t for t in result["data_transformations"])
        assert "traversal_note" in result


# ---------------------------------------------------------------------------
# dead_code()
# ---------------------------------------------------------------------------


class TestDeadCode:
    async def test_skips_subclassed_and_flags_unused(self, clean_graph: MMapGraphStore) -> None:
        sub = _node(
            "d.py::Class::Sub::1",
            NodeType.CLASS,
            "Sub",
            "d.py",
            1,
            10,
            signature="class Sub(Base)",
        )
        plain = _node("d.py::Class::Plain::12", NodeType.CLASS, "Plain", "d.py", 12, 15, signature="class Plain")
        unused = _node("d.py::Function::unused::20", NodeType.FUNCTION, "unused", "d.py", 20, 22)
        used = _node("d.py::Function::used::25", NodeType.FUNCTION, "used", "d.py", 25, 27)
        caller = _node("d.py::Function::caller::30", NodeType.FUNCTION, "caller", "d.py", 30, 32)
        method = _node("d.py::Function::helper::5", NodeType.FUNCTION, "helper", "d.py", 5, 7)
        await clean_graph.upsert_nodes([sub, plain, unused, used, caller, method])
        await clean_graph.upsert_edges(
            [
                GraphEdge(source_id=caller.id, target_id=used.id, type=EdgeType.CALLS),
                GraphEdge(source_id=sub.id, target_id=method.id, type=EdgeType.CONTAINS),
            ]
        )
        engine = DefaultQueryEngine(clean_graph)
        result = await engine.dead_code(top_k=50)
        names = {n["name"] for n in result["nodes"]}
        # Declared bases = polymorphic use -> skipped.
        assert "Sub" not in names
        # CONTAINS (containment) is not usage -> still flagged.
        assert "helper" in names
        assert "unused" in names
        assert "Plain" in names
        assert "used" not in names
        assert "caller" not in names


# ---------------------------------------------------------------------------
# Combined / smoke
# ---------------------------------------------------------------------------


class TestQueryEngineSmoke:
    async def test_navigate_and_trace_work_together(self, seeded_engine: DefaultQueryEngine) -> None:
        nav = await seeded_engine.navigate("file.py::Function::func_a::4")
        assert "entity" in nav

        traced = await seeded_engine.trace("file.py::Function::func_a::4", depth=3)
        assert len(traced) > 0


# ---------------------------------------------------------------------------
# diff()
# ---------------------------------------------------------------------------


class TestDiff:
    async def test_live_vs_live_is_empty(self, seeded_engine: DefaultQueryEngine) -> None:
        result = await seeded_engine.diff("", "live", scope="full")
        assert result["added"] == []
        assert result["removed"] == []
        assert result["changed"] == []
        assert result["files_changed"] == []
        assert "error" not in result

    async def test_unknown_snapshot_errors(self, seeded_engine: DefaultQueryEngine) -> None:
        result = await seeded_engine.diff("ckpt_nope", "live")
        assert result["error"] == "snapshot_not_found"
        assert result["missing_snapshot"] == "ckpt_nope"

    async def test_checkpoint_vs_live_reports_nodes(
        self, seeded_engine: DefaultQueryEngine, clean_graph: MMapGraphStore
    ) -> None:
        nodes = await clean_graph.find_nodes()
        index = {n.id: n.content_hash() for n in nodes if n.file_path == "file.py"}
        added_id = "file.py::Function::func_c::16"
        changed_id = "file.py::Function::func_b::10"
        del index[added_id]
        index[changed_id] = "deadbeef"
        await clean_graph.upsert_session(
            {
                "session_id": "ckpt_t1",
                "kind": "checkpoint",
                "checkpoint_id": "ckpt_t1",
                "files": ["file.py"],
                "fingerprints": {},
                "node_index": {"file.py": index},
                "created_at": "2026-01-01T00:00:00+00:00",
            }
        )
        result = await seeded_engine.diff("ckpt_t1", "live", scope="full")
        assert result["files_changed"] == ["file.py"]
        assert result["added"] == [added_id]
        assert result["changed"] == [changed_id]
        assert result["removed"] == []
        assert result["node_detail"] == "full"
        assert result["stats"]["added_count"] == 1
        assert result["stats"]["changed_count"] == 1

    async def test_legacy_checkpoint_is_file_level_only(
        self, seeded_engine: DefaultQueryEngine, clean_graph: MMapGraphStore
    ) -> None:
        nodes = await clean_graph.find_nodes()
        fps = [n.fingerprint() for n in nodes if n.file_path == "file.py"]
        await clean_graph.upsert_session(
            {
                "session_id": "ckpt_legacy",
                "kind": "checkpoint",
                "checkpoint_id": "ckpt_legacy",
                "files": ["file.py"],
                "fingerprints": {"file.py": fps[:-1]},
                "created_at": "2026-01-01T00:00:00+00:00",
            }
        )
        result = await seeded_engine.diff("ckpt_legacy", "live", scope="full")
        assert result["files_changed"] == ["file.py"]
        assert result["node_detail"] == "files_only"
        assert result["added"] == []
        assert result["removed"] == []
        assert result["changed"] == []

    async def test_scope_filters_files(self, seeded_engine: DefaultQueryEngine, clean_graph: MMapGraphStore) -> None:
        nodes = await clean_graph.find_nodes()
        index = {n.id: n.content_hash() for n in nodes if n.file_path == "file.py"}
        del index["file.py::Function::func_c::16"]
        await clean_graph.upsert_session(
            {
                "session_id": "ckpt_scope",
                "kind": "checkpoint",
                "checkpoint_id": "ckpt_scope",
                "files": ["file.py"],
                "fingerprints": {},
                "node_index": {"file.py": index},
                "created_at": "2026-01-01T00:00:00+00:00",
            }
        )
        result = await seeded_engine.diff("ckpt_scope", "live", scope="nomatch/")
        assert result["files_changed"] == []
        assert result["removed"] == []
        assert "error" not in result
