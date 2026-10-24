"""Tests for SMP gap-fill parity with codebase-memory-mcp.

Covers the three read paths SMP missed plus observability upgrades:
``smp/query`` (query_graph), ``smp/code_snippet`` (get_code_snippet),
``smp/detect_changes`` (detect_changes), search_code observability
(elapsed_ms/dedup/directories), trace envelope (function/direction),
and per-path coverage metadata.
"""

from __future__ import annotations

from collections.abc import AsyncIterator

import pytest

from smp.core.models import EdgeType, GraphEdge, GraphNode, NodeType, StructuralProperties
from smp.engine.query import DefaultQueryEngine
from smp.protocol.handlers import query as query_handlers
from smp.protocol.handlers import sync as sync_handlers
from smp.protocol.server import _dispatch
from smp.store.graph.mmap_store import MMapGraphStore


def _node(node_id: str, name: str, file_path: str = "src/a.py", start: int = 1, end: int = 10) -> GraphNode:
    return GraphNode(
        id=node_id,
        type=NodeType.FUNCTION,
        file_path=file_path,
        structural=StructuralProperties(name=name, file=file_path, start_line=start, end_line=end),
    )


@pytest.fixture()
async def gap_engine(clean_graph: MMapGraphStore) -> AsyncIterator[DefaultQueryEngine]:
    nodes = [
        _node("src/a.py::Function::login::1", "login", "src/a.py", 1, 10),
        _node("src/b.py::Function::validate::1", "validate", "src/b.py", 1, 8),
    ]
    await clean_graph.upsert_nodes(nodes)
    await clean_graph.upsert_edge(GraphEdge(source_id=nodes[0].id, target_id=nodes[1].id, type=EdgeType.CALLS))
    yield DefaultQueryEngine(clean_graph)


class TestQueryGraph:
    async def test_cypher_subset_returns_rows(self, gap_engine: DefaultQueryEngine) -> None:
        res = await gap_engine.query_graph("MATCH (n:Function {name: 'login'}) RETURN n.qn LIMIT 5")
        assert res["columns"] == ["qn"]
        assert res["total"] == 1
        assert len(res["rows"][0]) == 1
        assert res["rows"][0][0].endswith("login::1") or "login" in res["rows"][0][0]
        assert res["total_relation"] == "eq"
        assert "elapsed_ms" in res
        assert res["warnings"] == []

    async def test_where_contains_filters(self, gap_engine: DefaultQueryEngine) -> None:
        res = await gap_engine.query_graph(
            "MATCH (n:Function) WHERE n.name CONTAINS 'log' RETURN n.name, n.file_path LIMIT 10"
        )
        assert res["columns"] == ["name", "file_path"]
        assert res["total"] == 1
        assert res["rows"] == [["login", "src/a.py"]]
        assert res["warnings"] == []

    async def test_where_equality_and_unsupported_warn(self, gap_engine: DefaultQueryEngine) -> None:
        res = await gap_engine.query_graph(
            "MATCH (n:Function) WHERE n.name = 'validate' OR n.name = 'login' RETURN n.name LIMIT 10"
        )
        # OR is unsupported: the unparseable atom is reported, never silently
        # applied; the supported remainder (nothing here) still executes.
        assert any("OR" in u for u in res["unsupported"])
        assert len(res["warnings"]) >= 1
        assert res["total"] == 2

    async def test_default_projection_unchanged(self, gap_engine: DefaultQueryEngine) -> None:
        res = await gap_engine.query_graph("MATCH (n:Function {name: 'login'}) LIMIT 5")
        assert res["columns"] == ["qn", "file"]
        assert res["total"] == 1
        assert len(res["rows"][0]) == 2

    async def test_plain_text_fallback(self, gap_engine: DefaultQueryEngine) -> None:
        res = await gap_engine.query_graph("validate")
        assert res["total"] >= 1

    async def test_pagination(self, gap_engine: DefaultQueryEngine) -> None:
        res = await gap_engine.query_graph("MATCH (n:Function) RETURN n LIMIT 1", max_rows=1, offset=1)
        assert res["returned"] == 1
        assert res["total"] == 2


class TestCodeSnippet:
    async def test_full_returns_callers(self, gap_engine: DefaultQueryEngine) -> None:
        res = await gap_engine.get_code_snippet("src/b.py::Function::validate::1", source_mode="full")
        assert res["name"] == "validate"
        assert res["callers"] == 1
        assert res["callees"] == 0
        assert "coverage_note" in res

    async def test_missing_returns_hint(self, gap_engine: DefaultQueryEngine) -> None:
        res = await gap_engine.get_code_snippet("nope_missing")
        assert res["error"] == "function not found"
        assert "hint" in res


class TestDetectChanges:
    async def test_clean_tree_shape(self, gap_engine: DefaultQueryEngine) -> None:
        res = await gap_engine.detect_changes(base_branch="main", depth=1)
        for key in (
            "base",
            "changed_total",
            "changed_files",
            "seed_symbols",
            "impacted_total",
            "impacted",
            "truncated",
        ):
            assert key in res
        assert res["impacted_total_relation"] == "eq"


class TestObservability:
    async def test_search_code_has_metrics(self, gap_engine: DefaultQueryEngine) -> None:
        res = await gap_engine.search_code("login", mode="compact", top_k=5)
        for key in ("elapsed_ms", "dedup_ratio", "directories", "total_relation", "total_grep_matches"):
            assert key in res

    async def test_trace_handler_envelope(self, gap_engine: DefaultQueryEngine) -> None:
        ctx: dict[str, object] = {"engine": gap_engine}
        res = await query_handlers.trace({"start": "login", "depth": 1}, ctx)  # type: ignore[dict-item]
        assert res["function"] == "login"
        assert res["direction"] == "outgoing"
        assert "callers_total" in res
        assert "callees_total" in res
        assert "nodes" in res
        assert all("reach" in n for n in res["nodes"])
        both = await query_handlers.trace({"start": "login", "depth": 1, "direction": "both"}, ctx)  # type: ignore[dict-item]
        assert "note" in both

    async def test_coverage_has_metadata(self, gap_engine: DefaultQueryEngine, clean_graph: MMapGraphStore) -> None:
        ctx: dict[str, object] = {"graph": clean_graph, "engine": gap_engine}
        res = await sync_handlers.coverage({"paths": ["src/a.py", "nope/missing.py"]}, ctx)  # type: ignore[dict-item]
        assert res["signal"] == "best_effort"
        assert "metadata" in res
        assert res["metadata"]["hash_records_complete"] is True
        assert res["path_total"] == 2
        by_path = {p["requested_path"]: p for p in res["paths"]}
        assert by_path["src/a.py"]["status"] == "no_recorded_issue"
        assert by_path["src/a.py"]["freshness"] == "metadata_match"
        assert by_path["nope/missing.py"]["status"] == "not_indexed"


class TestDispatch:
    async def test_new_methods_dispatched(self, gap_engine: DefaultQueryEngine, clean_graph: MMapGraphStore) -> None:
        ctx: dict[str, object] = {"engine": gap_engine, "graph": clean_graph}
        for method, params in [
            ("smp/query", {"query": "login"}),
            ("smp/code_snippet", {"qualified_name": "login"}),
            ("smp/detect_changes", {"base_branch": "main"}),
        ]:
            res = await _dispatch(method, params, ctx)  # type: ignore[arg-type]
            assert isinstance(res, dict)
