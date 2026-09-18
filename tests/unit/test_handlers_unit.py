from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import msgspec
import pytest

from smp.core.models import (
    EdgeType,
    GraphEdge,
    GraphNode,
    NodeType,
    SemanticProperties,
    StructuralProperties,
)
from smp.protocol.handlers import analysis, community, enrichment, memory, query, review, sandbox, session, sync, vector


def make_node(
    node_id: str = "n1",
    name: str = "test_func",
    complexity: int = 0,
    signature: str = "",
    start_line: int = 1,
    end_line: int = 10,
) -> GraphNode:
    return GraphNode(
        id=node_id,
        type=NodeType.FUNCTION,
        file_path="test.py",
        structural=StructuralProperties(
            name=name,
            complexity=complexity,
            signature=signature,
            start_line=start_line,
            end_line=end_line,
        ),
        semantic=SemanticProperties(status="no_metadata"),
    )


def make_edge(source_id: str = "n1", target_id: str = "n2") -> GraphEdge:
    return GraphEdge(source_id=source_id, target_id=target_id, type=EdgeType.CALLS)


class TestNavigateHandler:
    @pytest.fixture
    def mock_ctx(self):
        return {"engine": MagicMock()}

    @pytest.mark.asyncio
    async def test_navigate_valid_query(self, mock_ctx):
        engine = mock_ctx["engine"]
        engine.navigate = AsyncMock(return_value={"nodes": ["a", "b"], "edges": []})
        params = {"query": "find_main", "include_relationships": True}
        result = await query.navigate(params, mock_ctx)
        assert "nodes" in result
        engine.navigate.assert_called_once_with("find_main", True)

    @pytest.mark.asyncio
    async def test_navigate_without_relationships(self, mock_ctx):
        engine = mock_ctx["engine"]
        engine.navigate = AsyncMock(return_value={"nodes": ["a"]})
        params = {"query": "find_main", "include_relationships": False}
        await query.navigate(params, mock_ctx)
        engine.navigate.assert_called_once_with("find_main", False)

    @pytest.mark.asyncio
    async def test_navigate_missing_query(self, mock_ctx):
        with pytest.raises(msgspec.ValidationError):
            await query.navigate({}, mock_ctx)


class TestTraceHandler:
    @pytest.fixture
    def mock_ctx(self):
        return {"engine": MagicMock()}

    @pytest.mark.asyncio
    async def test_trace_valid_start(self, mock_ctx):
        engine = mock_ctx["engine"]
        engine.trace = AsyncMock(return_value=["node1", "node2", "node3"])
        params = {"start": "func_a", "relationship": "CALLS", "depth": 5, "direction": "outgoing"}
        result = await query.trace(params, mock_ctx)
        assert result["nodes"] == ["node1", "node2", "node3"]
        engine.trace.assert_called_once_with("func_a", "CALLS", 5, "outgoing")

    @pytest.mark.asyncio
    async def test_trace_default_depth(self, mock_ctx):
        engine = mock_ctx["engine"]
        engine.trace = AsyncMock(return_value=["node1"])
        params = {"start": "func_a"}
        await query.trace(params, mock_ctx)
        engine.trace.assert_called_once_with("func_a", "CALLS", 3, "outgoing")

    @pytest.mark.asyncio
    async def test_trace_incoming_direction(self, mock_ctx):
        engine = mock_ctx["engine"]
        engine.trace = AsyncMock(return_value=[])
        params = {"start": "func_a", "direction": "incoming"}
        await query.trace(params, mock_ctx)
        engine.trace.assert_called_once_with("func_a", "CALLS", 3, "incoming")


class TestContextHandler:
    @pytest.fixture
    def mock_ctx(self):
        return {"engine": MagicMock()}

    @pytest.mark.asyncio
    async def test_context_valid_file(self, mock_ctx):
        engine = mock_ctx["engine"]
        engine.get_context = AsyncMock(return_value={"context": "data", "symbols": []})
        params = {"file_path": "main.py", "scope": "file", "depth": 1}
        result = await query.context(params, mock_ctx)
        assert "context" in result
        engine.get_context.assert_called_once_with("main.py", "file", 1)

    @pytest.mark.asyncio
    async def test_context_default_scope(self, mock_ctx):
        engine = mock_ctx["engine"]
        engine.get_context = AsyncMock(return_value={})
        params = {"file_path": "main.py"}
        await query.context(params, mock_ctx)
        engine.get_context.assert_called_once_with("main.py", "edit", 2)


class TestImpactHandler:
    @pytest.fixture
    def mock_ctx(self):
        return {"engine": MagicMock()}

    @pytest.mark.asyncio
    async def test_impact_assessment_delete(self, mock_ctx):
        engine = mock_ctx["engine"]
        engine.assess_impact = AsyncMock(return_value={"impact_score": 8, "affected": ["n1", "n2"]})
        params = {"entity": "function_a", "change_type": "delete"}
        result = await query.impact(params, mock_ctx)
        assert result["impact_score"] == 8
        engine.assess_impact.assert_called_once_with("function_a", "delete")

    @pytest.mark.asyncio
    async def test_impact_modify_change(self, mock_ctx):
        engine = mock_ctx["engine"]
        engine.assess_impact = AsyncMock(return_value={"impact_score": 3})
        params = {"entity": "class_a", "change_type": "modify"}
        await query.impact(params, mock_ctx)
        engine.assess_impact.assert_called_once_with("class_a", "modify")


class TestLocateHandler:
    @pytest.fixture
    def mock_ctx(self):
        return {"engine": MagicMock()}

    @pytest.mark.asyncio
    async def test_locate_default_fields(self, mock_ctx):
        engine = mock_ctx["engine"]
        engine.locate = AsyncMock(return_value=["match1"])
        params = {"query": "parse"}
        result = await query.locate(params, mock_ctx)
        assert result["matches"] == ["match1"]
        engine.locate.assert_called_once()

    @pytest.mark.asyncio
    async def test_locate_with_node_types(self, mock_ctx):
        engine = mock_ctx["engine"]
        engine.locate = AsyncMock(return_value=[])
        params = {"query": "test", "node_types": ["Function", "Class"]}
        await query.locate(params, mock_ctx)
        engine.locate.assert_called_once()

    @pytest.mark.asyncio
    async def test_locate_custom_top_k(self, mock_ctx):
        engine = mock_ctx["engine"]
        engine.locate = AsyncMock(return_value=["m1", "m2"])
        params = {"query": "foo", "top_k": 2}
        result = await query.locate(params, mock_ctx)
        assert len(result["matches"]) == 2


class TestSearchHandler:
    @pytest.fixture
    def mock_ctx(self):
        return {"engine": MagicMock()}

    @pytest.mark.asyncio
    async def test_search_any_match(self, mock_ctx):
        engine = mock_ctx["engine"]
        engine.search = AsyncMock(return_value={"results": ["r1"]})
        params = {"query": "error handling", "match": "any"}
        await query.search(params, mock_ctx)
        engine.search.assert_called_once()

    @pytest.mark.asyncio
    async def test_search_all_match(self, mock_ctx):
        engine = mock_ctx["engine"]
        engine.search = AsyncMock(return_value={"results": []})
        params = {"query": "foo bar", "match": "all"}
        await query.search(params, mock_ctx)
        engine.search.assert_called_once()

    @pytest.mark.asyncio
    async def test_search_with_filter(self, mock_ctx):
        engine = mock_ctx["engine"]
        engine.search = AsyncMock(return_value={"results": []})
        params = {"query": "test", "filter": {"type": "Function"}}
        await query.search(params, mock_ctx)
        engine.search.assert_called_once()


class TestFlowHandler:
    @pytest.fixture
    def mock_ctx(self):
        return {"engine": MagicMock()}

    @pytest.mark.asyncio
    async def test_flow_data_flow(self, mock_ctx):
        engine = mock_ctx["engine"]
        engine.find_flow = AsyncMock(return_value=["start", "middle", "end"])
        params = {"start": "func_a", "end": "func_b", "flow_type": "data"}
        result = await query.flow(params, mock_ctx)
        assert len(result) == 3
        engine.find_flow.assert_called_once_with("func_a", "func_b", "data")

    @pytest.mark.asyncio
    async def test_flow_control_flow(self, mock_ctx):
        engine = mock_ctx["engine"]
        engine.find_flow = AsyncMock(return_value=[])
        params = {"start": "func_a", "end": "func_b", "flow_type": "control"}
        await query.flow(params, mock_ctx)
        engine.find_flow.assert_called_once_with("func_a", "func_b", "control")

    @pytest.mark.asyncio
    async def test_flow_empty_end(self, mock_ctx):
        engine = mock_ctx["engine"]
        engine.find_flow = AsyncMock(return_value=["n1", "n2"])
        params = {"start": "func_a", "flow_type": "data"}
        await query.flow(params, mock_ctx)
        engine.find_flow.assert_called_once()


class TestUpdateHandler:
    @pytest.fixture
    def mock_ctx(self):
        return {"graph": MagicMock()}

    @patch("smp.protocol.handlers.memory._is_path_allowed")
    @pytest.mark.asyncio
    async def test_update_path_forbidden(self, mock_allowed, mock_ctx):
        mock_allowed.return_value = False
        params = {"file_path": "/etc/passwd"}
        result = await memory.update(params, mock_ctx)
        assert result["error"] == "path_forbidden"
        assert result["nodes"] == 0

    @pytest.mark.asyncio
    async def test_update_ensure_parsed_success(self, mock_ctx):
        graph = mock_ctx["graph"]
        graph.invalidate_file = AsyncMock()
        graph.ensure_parsed = AsyncMock(return_value=[make_node("n1"), make_node("n2")])
        params = {"file_path": "main.py"}
        result = await memory.update(params, mock_ctx)
        assert result["nodes"] == 2
        assert result["errors"] == 0
        graph.ensure_parsed.assert_called_once_with("main.py")

    @pytest.mark.asyncio
    async def test_update_file_not_found(self, mock_ctx):
        graph = mock_ctx["graph"]
        graph.ensure_parsed = AsyncMock(side_effect=FileNotFoundError)
        params = {"file_path": "missing.py"}
        result = await memory.update(params, mock_ctx)
        assert result["error"] == "file_not_found"
        assert result["errors"] == 1

    @pytest.mark.asyncio
    async def test_update_generic_exception(self, mock_ctx):
        graph = mock_ctx["graph"]
        graph.ensure_parsed = AsyncMock(side_effect=RuntimeError("parse failed"))
        params = {"file_path": "broken.py"}
        result = await memory.update(params, mock_ctx)
        assert result["error"] == "parse failed"
        assert result["errors"] == 1

    @pytest.mark.asyncio
    async def test_update_parse_file_fallback(self, mock_ctx):
        graph = mock_ctx["graph"]
        del graph.ensure_parsed
        graph.parse_file = AsyncMock(return_value=[make_node("n1")])
        params = {"file_path": "main.py"}
        result = await memory.update(params, mock_ctx)
        assert result["nodes"] == 1

    @pytest.mark.asyncio
    async def test_update_no_graph_support(self, mock_ctx):
        graph = mock_ctx["graph"]
        del graph.ensure_parsed
        del graph.parse_file
        del graph.invalidate_file
        params = {"file_path": "main.py"}
        result = await memory.update(params, mock_ctx)
        assert "graph store does not support live parsing" in result["message"]


class TestBatchUpdateHandler:
    @pytest.fixture
    def mock_ctx(self):
        return {"graph": MagicMock()}

    @pytest.mark.asyncio
    async def test_batch_update_empty(self, mock_ctx):
        params = {"changes": []}
        result = await memory.batch_update(params, mock_ctx)
        assert result["updates"] == 0
        assert result["results"] == []

    @pytest.mark.asyncio
    async def test_batch_update_multiple_files(self, mock_ctx):
        with patch("smp.protocol.handlers.memory.update", new_callable=AsyncMock) as mock_update:
            mock_update.side_effect = [
                {"file_path": "a.py", "nodes": 1, "edges": 0, "errors": 0},
                {"file_path": "b.py", "nodes": 2, "edges": 0, "errors": 0},
            ]
            params = {"changes": [{"file_path": "a.py"}, {"file_path": "b.py"}]}
            result = await memory.batch_update(params, mock_ctx)
            assert result["updates"] == 2
            assert len(result["results"]) == 2


class TestReindexHandler:
    @pytest.fixture
    def mock_ctx(self):
        return {"graph": MagicMock()}

    @patch("smp.protocol.handlers.memory._is_path_allowed")
    @pytest.mark.asyncio
    async def test_reindex_path_forbidden(self, mock_allowed, mock_ctx):
        mock_allowed.return_value = False
        params = {"scope": "/forbidden"}
        result = await memory.reindex(params, mock_ctx)
        assert result["error"] == "path_forbidden"

    @patch("smp.protocol.handlers.memory._is_path_allowed")
    @patch("smp.protocol.handlers.memory.Path.is_dir")
    @pytest.mark.asyncio
    async def test_reindex_success(self, mock_is_dir, mock_allowed, mock_ctx):
        mock_allowed.return_value = True
        mock_is_dir.return_value = True
        graph = mock_ctx["graph"]
        graph.watch_directories = MagicMock()
        graph.pre_parse = AsyncMock(return_value=500)
        params = {"scope": "/project/src"}
        result = await memory.reindex(params, mock_ctx)
        assert result["status"] == "reindex_started"
        assert result["queued"] == 500

    @patch("smp.protocol.handlers.memory._is_path_allowed")
    @patch("smp.protocol.handlers.memory.Path.is_dir")
    @pytest.mark.asyncio
    async def test_reindex_not_a_directory(self, mock_is_dir, mock_allowed, mock_ctx):
        mock_allowed.return_value = True
        mock_is_dir.return_value = False
        params = {"scope": "/project/file.py"}
        result = await memory.reindex(params, mock_ctx)
        assert result["status"] == "reindex_requested"


class TestDiffHandler:
    @pytest.fixture
    def mock_ctx(self):
        return {"engine": MagicMock()}

    @pytest.mark.asyncio
    async def test_diff_valid_snapshots(self, mock_ctx):
        engine = mock_ctx["engine"]
        engine.diff = AsyncMock(return_value={"added": 2, "removed": 1, "changed": 3})
        params = {"from_snapshot": "v1", "to_snapshot": "v2", "scope": "full"}
        result = await analysis.diff(params, mock_ctx)
        assert "added" in result
        engine.diff.assert_called_once_with("v1", "v2", "full")

    @pytest.mark.asyncio
    async def test_diff_default_scope(self, mock_ctx):
        engine = mock_ctx["engine"]
        engine.diff = AsyncMock(return_value={})
        params = {"from_snapshot": "v1", "to_snapshot": "v2"}
        await analysis.diff(params, mock_ctx)
        engine.diff.assert_called_once_with("v1", "v2", "full")


class TestPlanHandler:
    @pytest.fixture
    def mock_ctx(self):
        return {"engine": MagicMock()}

    @pytest.mark.asyncio
    async def test_plan_valid_description(self, mock_ctx):
        engine = mock_ctx["engine"]
        engine.plan = AsyncMock(return_value={"steps": ["step1", "step2"]})
        params = {"change_description": "rename function", "target_file": "a.py", "change_type": "refactor"}
        result = await analysis.plan(params, mock_ctx)
        assert "steps" in result
        engine.plan.assert_called_once()

    @pytest.mark.asyncio
    async def test_plan_empty_description(self, mock_ctx):
        engine = mock_ctx["engine"]
        engine.plan = AsyncMock(return_value={"steps": []})
        params = {"change_description": ""}
        await analysis.plan(params, mock_ctx)
        engine.plan.assert_called_once()


class TestConflictHandler:
    @pytest.fixture
    def mock_ctx(self):
        return {"engine": MagicMock()}

    @pytest.mark.asyncio
    async def test_conflict_entity_proposed(self, mock_ctx):
        engine = mock_ctx["engine"]
        engine.conflict = AsyncMock(return_value={"has_conflict": True, "conflicts": ["n1"]})
        params = {"entity": "func_a", "proposed_change": "modify signature"}
        result = await analysis.conflict(params, mock_ctx)
        assert result["has_conflict"] is True
        engine.conflict.assert_called_once()

    @pytest.mark.asyncio
    async def test_conflict_with_context(self, mock_ctx):
        engine = mock_ctx["engine"]
        engine.conflict = AsyncMock(return_value={"has_conflict": False})
        params = {"entity": "class_a", "proposed_change": "delete method", "context": {"mode": "safe"}}
        await analysis.conflict(params, mock_ctx)
        engine.conflict.assert_called_once()


class TestWhyHandler:
    @pytest.fixture
    def mock_ctx(self):
        return {"engine": MagicMock()}

    @pytest.mark.asyncio
    async def test_why_existing_entity(self, mock_ctx):
        engine = mock_ctx["engine"]
        engine.why = AsyncMock(return_value={"reasons": ["reason1", "reason2"]})
        params = {"entity": "function_a", "relationship": "CALLS", "depth": 3}
        result = await analysis.why(params, mock_ctx)
        assert "reasons" in result
        engine.why.assert_called_once_with("function_a", "CALLS", 3)

    @pytest.mark.asyncio
    async def test_why_default_depth(self, mock_ctx):
        engine = mock_ctx["engine"]
        engine.why = AsyncMock(return_value={"reasons": []})
        params = {"entity": "function_a"}
        await analysis.why(params, mock_ctx)
        engine.why.assert_called_once_with("function_a", "", 3)


class TestTelemetryHandler:
    @pytest.fixture
    def mock_ctx(self):
        return {"graph": MagicMock()}

    @pytest.mark.asyncio
    async def test_telemetry_get_stats(self, mock_ctx):
        graph = mock_ctx["graph"]
        graph.count_nodes = AsyncMock(return_value=100)
        graph.count_edges = AsyncMock(return_value=250)
        graph.find_nodes = AsyncMock(return_value=[])
        params = {"action": "get_stats"}
        result = await analysis.telemetry(params, mock_ctx)
        assert result["nodes"] == 100
        assert result["edges"] == 250

    @pytest.mark.asyncio
    async def test_telemetry_hot_nodes_action(self, mock_ctx):
        graph = mock_ctx["graph"]
        graph.count_nodes = AsyncMock(return_value=50)
        graph.count_edges = AsyncMock(return_value=100)
        graph.find_nodes = AsyncMock(return_value=[])
        params = {"action": "hot_nodes"}
        result = await analysis.telemetry(params, mock_ctx)
        assert result["action"] == "hot_nodes"

    @pytest.mark.asyncio
    async def test_telemetry_with_threshold(self, mock_ctx):
        graph = mock_ctx["graph"]
        graph.count_nodes = AsyncMock(return_value=10)
        graph.count_edges = AsyncMock(return_value=20)
        graph.find_nodes = AsyncMock(return_value=[])
        params = {"action": "stats", "threshold": 3}
        result = await analysis.telemetry(params, mock_ctx)
        assert result["nodes"] == 10


class TestTelemetryHotHandler:
    @pytest.fixture
    def mock_ctx(self):
        return {"graph": MagicMock()}

    @pytest.mark.asyncio
    async def test_telemetry_hot_node_found(self, mock_ctx):
        graph = mock_ctx["graph"]
        node = make_node("n1", "hot_func", complexity=15)
        graph.get_node = AsyncMock(return_value=node)
        graph.get_node_degree = AsyncMock(return_value=(10, 5))
        params = {"node_id": "n1"}
        result = await analysis.telemetry_hot(params, mock_ctx)
        assert result["is_hot"] is True
        assert result["degree"] == 15

    @pytest.mark.asyncio
    async def test_telemetry_hot_node_not_found(self, mock_ctx):
        graph = mock_ctx["graph"]
        graph.get_node = AsyncMock(return_value=None)
        params = {"node_id": "nonexistent"}
        result = await analysis.telemetry_hot(params, mock_ctx)
        assert result["error"] == "node_not_found"
        assert result["is_hot"] is False


class TestTelemetryNodeHandler:
    @pytest.fixture
    def mock_ctx(self):
        return {"graph": MagicMock()}

    @pytest.mark.asyncio
    async def test_telemetry_node_valid(self, mock_ctx):
        graph = mock_ctx["graph"]
        node = make_node("n1")
        node.semantic.tags = ["tag1", "tag2"]
        graph.get_node = AsyncMock(return_value=node)
        graph.get_edges = AsyncMock(
            side_effect=[
                [make_edge("n1", "n2"), make_edge("n1", "n3")],
                [make_edge("n0", "n1")],
            ]
        )
        params = {"node_id": "n1"}
        result = await analysis.telemetry_node(params, mock_ctx)
        assert result["node_id"] == "n1"
        assert result["out_degree"] == 2
        assert result["in_degree"] == 1

    @pytest.mark.asyncio
    async def test_telemetry_node_not_found(self, mock_ctx):
        graph = mock_ctx["graph"]
        graph.get_node = AsyncMock(return_value=None)
        params = {"node_id": "ghost"}
        result = await analysis.telemetry_node(params, mock_ctx)
        assert result["error"] == "node_not_found"


class TestEnrichHandler:
    @pytest.fixture
    def mock_ctx(self):
        return {"graph": MagicMock()}

    @pytest.mark.asyncio
    async def test_enrich_node_found_not_enriched(self, mock_ctx):
        graph = mock_ctx["graph"]
        node = make_node("n1")
        node.semantic.status = "no_metadata"
        graph.get_node = AsyncMock(return_value=node)
        graph.upsert_node = AsyncMock()
        params = {"node_id": "n1"}
        result = await enrichment.enrich(params, mock_ctx)
        assert result["enriched"] is True
        graph.upsert_node.assert_called_once()

    @pytest.mark.asyncio
    async def test_enrich_node_not_found(self, mock_ctx):
        graph = mock_ctx["graph"]
        graph.get_node = AsyncMock(return_value=None)
        params = {"node_id": "ghost"}
        result = await enrichment.enrich(params, mock_ctx)
        assert result["enriched"] is False
        assert result["error"] == "node_not_found"

    @pytest.mark.asyncio
    async def test_enrich_already_enriched(self, mock_ctx):
        graph = mock_ctx["graph"]
        node = make_node("n1")
        node.semantic.status = "enriched"
        graph.get_node = AsyncMock(return_value=node)
        params = {"node_id": "n1", "force": False}
        result = await enrichment.enrich(params, mock_ctx)
        assert result["enriched"] is False
        assert result["skipped"] is True

    @pytest.mark.asyncio
    async def test_enrich_force_overwrite(self, mock_ctx):
        graph = mock_ctx["graph"]
        node = make_node("n1")
        node.semantic.status = "enriched"
        graph.get_node = AsyncMock(return_value=node)
        graph.upsert_node = AsyncMock()
        params = {"node_id": "n1", "force": True}
        result = await enrichment.enrich(params, mock_ctx)
        assert result["enriched"] is True


class TestEnrichBatchHandler:
    @pytest.fixture
    def mock_ctx(self):
        return {"graph": MagicMock()}

    @pytest.mark.asyncio
    async def test_enrich_batch_full_scope(self, mock_ctx):
        graph = mock_ctx["graph"]
        nodes = [make_node("n1"), make_node("n2")]
        graph.find_nodes = AsyncMock(return_value=nodes)
        graph.upsert_node = AsyncMock()
        params = {"scope": "full"}
        result = await enrichment.enrich_batch(params, mock_ctx)
        assert result["enriched"] == 2

    @pytest.mark.asyncio
    async def test_enrich_batch_with_scope(self, mock_ctx):
        graph = mock_ctx["graph"]
        graph.find_nodes_by_scope = AsyncMock(return_value=[make_node("n1")])
        graph.upsert_node = AsyncMock()
        params = {"scope": "module_a"}
        result = await enrichment.enrich_batch(params, mock_ctx)
        assert result["enriched"] == 1


class TestEnrichStaleHandler:
    @pytest.fixture
    def mock_ctx(self):
        return {"graph": MagicMock()}

    @pytest.mark.asyncio
    async def test_enrich_stale_nodes(self, mock_ctx):
        graph = mock_ctx["graph"]
        node1 = make_node("n1")
        node1.semantic.status = "stale"
        node2 = make_node("n2")
        node2.semantic.status = "enriched"
        graph.find_nodes = AsyncMock(return_value=[node1, node2])
        graph.upsert_node = AsyncMock()
        params = {"scope": "full"}
        result = await enrichment.enrich_stale(params, mock_ctx)
        assert result["enriched"] == 1


class TestEnrichStatusHandler:
    @pytest.fixture
    def mock_ctx(self):
        return {"graph": MagicMock()}

    @pytest.mark.asyncio
    async def test_enrich_status_counts(self, mock_ctx):
        graph = mock_ctx["graph"]
        node1 = make_node("n1")
        node1.semantic.status = "enriched"
        node2 = make_node("n2")
        node2.semantic.status = "enriched"
        node3 = make_node("n3")
        node3.semantic.status = "stale"
        graph.find_nodes = AsyncMock(return_value=[node1, node2, node3])
        params = {"scope": "full"}
        result = await enrichment.enrich_status(params, mock_ctx)
        assert result["total"] == 3
        assert result["by_status"]["enriched"] == 2
        assert result["by_status"]["stale"] == 1


class TestAnnotateHandler:
    @pytest.fixture
    def mock_ctx(self):
        return {"graph": MagicMock()}

    @pytest.mark.asyncio
    async def test_annotate_success(self, mock_ctx):
        graph = mock_ctx["graph"]
        node = make_node("n1")
        graph.get_node = AsyncMock(return_value=node)
        graph.upsert_node = AsyncMock()
        params = {"node_id": "n1", "description": "new description", "tags": ["tag1"]}
        result = await enrichment.annotate(params, mock_ctx)
        assert result["annotated"] is True
        assert "tag1" in result["tags"]

    @pytest.mark.asyncio
    async def test_annotate_node_not_found(self, mock_ctx):
        graph = mock_ctx["graph"]
        graph.get_node = AsyncMock(return_value=None)
        params = {"node_id": "ghost", "description": "desc"}
        result = await enrichment.annotate(params, mock_ctx)
        assert result["annotated"] is False
        assert result["error"] == "node_not_found"

    @pytest.mark.asyncio
    async def test_annotate_manually_set_skip(self, mock_ctx):
        graph = mock_ctx["graph"]
        node = make_node("n1")
        node.semantic.manually_set = True
        graph.get_node = AsyncMock(return_value=node)
        params = {"node_id": "n1", "force": False}
        result = await enrichment.annotate(params, mock_ctx)
        assert result["skipped"] is True


class TestAnnotateBulkHandler:
    @pytest.fixture
    def mock_ctx(self):
        return {"graph": MagicMock()}

    @pytest.mark.asyncio
    async def test_annotate_bulk_success(self, mock_ctx):
        graph = mock_ctx["graph"]
        graph.get_node = AsyncMock(
            side_effect=[
                make_node("n1"),
                make_node("n2"),
                None,
            ]
        )
        graph.upsert_node = AsyncMock()
        from smp.core.models import AnnotateBulkItem

        params = {
            "annotations": [
                AnnotateBulkItem(node_id="n1", description="desc1"),
                AnnotateBulkItem(node_id="n2", tags=["t1"]),
                AnnotateBulkItem(node_id="n3"),
            ]
        }
        result = await enrichment.annotate_bulk(params, mock_ctx)
        assert result["annotated"] == 2
        assert "n3" in result["missing"]


class TestTagHandler:
    @pytest.fixture
    def mock_ctx(self):
        return {"graph": MagicMock()}

    @pytest.mark.asyncio
    async def test_tag_add_action(self, mock_ctx):
        graph = mock_ctx["graph"]
        node = make_node("n1")
        node.semantic.tags = ["existing"]
        graph.find_nodes = AsyncMock(return_value=[node])
        graph.upsert_node = AsyncMock()
        params = {"scope": "full", "tags": ["new_tag"], "action": "add"}
        result = await enrichment.tag(params, mock_ctx)
        assert result["action"] == "add"
        assert result["updated"] == 1

    @pytest.mark.asyncio
    async def test_tag_remove_action(self, mock_ctx):
        graph = mock_ctx["graph"]
        node = make_node("n1")
        node.semantic.tags = ["to_remove", "keep"]
        graph.find_nodes = AsyncMock(return_value=[node])
        graph.upsert_node = AsyncMock()
        params = {"scope": "full", "tags": ["to_remove"], "action": "remove"}
        result = await enrichment.tag(params, mock_ctx)
        assert result["action"] == "remove"
        assert result["updated"] == 1

    @pytest.mark.asyncio
    async def test_tag_set_action(self, mock_ctx):
        graph = mock_ctx["graph"]
        node = make_node("n1")
        node.semantic.tags = ["old"]
        graph.find_nodes = AsyncMock(return_value=[node])
        graph.upsert_node = AsyncMock()
        params = {"scope": "full", "tags": ["new_set"], "action": "set"}
        result = await enrichment.tag(params, mock_ctx)
        assert result["action"] == "set"


class TestSessionOpenHandler:
    @pytest.fixture
    def mock_ctx(self):
        return {"graph": MagicMock()}

    @pytest.mark.asyncio
    async def test_session_open_valid(self, mock_ctx):
        graph = mock_ctx["graph"]
        graph.upsert_session = AsyncMock()
        graph.append_audit = AsyncMock()
        params = {"agent_id": "agent_1", "task": "refactor", "mode": "write"}
        result = await session.session_open(params, mock_ctx)
        assert "session_id" in result
        assert result["status"] == "open"
        graph.upsert_session.assert_called_once()

    @pytest.mark.asyncio
    async def test_session_open_default_mode(self, mock_ctx):
        graph = mock_ctx["graph"]
        graph.upsert_session = AsyncMock()
        graph.append_audit = AsyncMock()
        params = {"agent_id": "agent_1"}
        result = await session.session_open(params, mock_ctx)
        assert result["status"] == "open"


class TestSessionCloseHandler:
    @pytest.fixture
    def mock_ctx(self):
        return {"graph": MagicMock()}

    @pytest.mark.asyncio
    async def test_session_close_not_found(self, mock_ctx):
        graph = mock_ctx["graph"]
        graph.get_session = AsyncMock(return_value=None)
        params = {"session_id": "nonexistent"}
        result = await session.session_close(params, mock_ctx)
        assert result["closed"] is False
        assert result["error"] == "session_not_found"

    @pytest.mark.asyncio
    async def test_session_close_success(self, mock_ctx):
        graph = mock_ctx["graph"]
        graph.get_session = AsyncMock(return_value={"session_id": "s1", "status": "open", "locked_files": []})
        graph.release_all_locks = AsyncMock(return_value=3)
        graph.delete_session = AsyncMock()
        graph.append_audit = AsyncMock()
        params = {"session_id": "s1", "status": "completed"}
        result = await session.session_close(params, mock_ctx)
        assert result["closed"] is True
        assert result["released_locks"] == 3


class TestSessionRecoverHandler:
    @pytest.fixture
    def mock_ctx(self):
        return {"graph": MagicMock()}

    @pytest.mark.asyncio
    async def test_session_recover_not_found(self, mock_ctx):
        graph = mock_ctx["graph"]
        graph.get_session = AsyncMock(return_value=None)
        params = {"session_id": "ghost"}
        result = await session.session_recover(params, mock_ctx)
        assert result["recovered"] is False
        assert result["error"] == "session_not_found"

    @pytest.mark.asyncio
    async def test_session_recover_success(self, mock_ctx):
        graph = mock_ctx["graph"]
        session_data = {"session_id": "s1", "agent_id": "a1", "task": "test"}
        graph.get_session = AsyncMock(return_value=session_data)
        params = {"session_id": "s1"}
        result = await session.session_recover(params, mock_ctx)
        assert result["recovered"] is True
        assert result["session"] == session_data


class TestCheckpointHandler:
    @pytest.fixture
    def mock_ctx(self):
        return {"graph": MagicMock()}

    @pytest.mark.asyncio
    async def test_checkpoint_session_not_found(self, mock_ctx):
        graph = mock_ctx["graph"]
        graph.get_session = AsyncMock(return_value=None)
        params = {"session_id": "ghost", "files": ["a.py"]}
        result = await session.checkpoint(params, mock_ctx)
        assert result["created"] is False
        assert result["error"] == "session_not_found"

    @pytest.mark.asyncio
    async def test_checkpoint_success(self, mock_ctx):
        graph = mock_ctx["graph"]
        graph.get_session = AsyncMock(return_value={"session_id": "s1", "checkpoints": []})
        graph.find_nodes = AsyncMock(return_value=[make_node("n1")])
        graph.upsert_session = AsyncMock()
        graph.append_audit = AsyncMock()
        params = {"session_id": "s1", "files": ["a.py"]}
        result = await session.checkpoint(params, mock_ctx)
        assert result["created"] is True
        assert "checkpoint_id" in result


class TestRollbackHandler:
    @pytest.fixture
    def mock_ctx(self):
        return {"graph": MagicMock()}

    @pytest.mark.asyncio
    async def test_rollback_session_not_found(self, mock_ctx):
        graph = mock_ctx["graph"]
        graph.get_session = AsyncMock(return_value=None)
        params = {"session_id": "ghost", "checkpoint_id": "c1"}
        result = await session.rollback(params, mock_ctx)
        assert result["rolled_back"] is False

    @pytest.mark.asyncio
    async def test_rollback_checkpoint_not_found(self, mock_ctx):
        graph = mock_ctx["graph"]
        graph.get_session = AsyncMock(return_value={"session_id": "s1", "checkpoints": []})
        params = {"session_id": "s1", "checkpoint_id": "nonexistent"}
        result = await session.rollback(params, mock_ctx)
        assert result["rolled_back"] is False
        assert result["error"] == "checkpoint_not_found"

    @pytest.mark.asyncio
    async def test_rollback_success(self, mock_ctx):
        graph = mock_ctx["graph"]
        checkpoint = {"checkpoint_id": "c1", "files": ["a.py"], "fingerprints": {"n1": "f1"}}
        graph.get_session = AsyncMock(return_value={"session_id": "s1", "checkpoints": [checkpoint]})
        graph.append_audit = AsyncMock()
        params = {"session_id": "s1", "checkpoint_id": "c1"}
        result = await session.rollback(params, mock_ctx)
        assert result["rolled_back"] is True


class TestLockHandler:
    @pytest.fixture
    def mock_ctx(self):
        return {"graph": MagicMock()}

    @pytest.mark.asyncio
    async def test_lock_acquire_success(self, mock_ctx):
        graph = mock_ctx["graph"]
        graph.get_lock = AsyncMock(return_value=None)
        graph.upsert_lock = AsyncMock()
        graph.append_audit = AsyncMock()
        graph.get_session = AsyncMock(return_value={"session_id": "s1", "locked_files": []})
        graph.upsert_session = AsyncMock()
        params = {"session_id": "s1", "files": ["a.py"], "ttl_seconds": 300}
        result = await session.lock(params, mock_ctx)
        assert "a.py" in result["locked"]

    @pytest.mark.asyncio
    async def test_lock_conflict_active(self, mock_ctx):
        graph = mock_ctx["graph"]
        graph.get_lock = AsyncMock(
            return_value={
                "session_id": "s2",
                "expires_at": (datetime.now(UTC) + timedelta(hours=1)).isoformat(),
            }
        )
        graph.get_session = AsyncMock(return_value={"session_id": "s1", "locked_files": []})
        graph.upsert_lock = AsyncMock()
        graph.append_audit = AsyncMock()
        graph.upsert_session = AsyncMock()
        params = {"session_id": "s1", "files": ["a.py"]}
        result = await session.lock(params, mock_ctx)
        assert len(result["conflicts"]) == 1

    @pytest.mark.asyncio
    async def test_lock_force_steal(self, mock_ctx):
        graph = mock_ctx["graph"]
        graph.get_lock = AsyncMock(
            return_value={
                "session_id": "s2",
                "expires_at": (datetime.now(UTC) + timedelta(hours=1)).isoformat(),
            }
        )
        graph.release_lock = AsyncMock(return_value=True)
        graph.upsert_lock = AsyncMock()
        graph.append_audit = AsyncMock()
        graph.get_session = AsyncMock(return_value={"session_id": "s1", "locked_files": []})
        graph.upsert_session = AsyncMock()
        params = {"session_id": "s1", "files": ["a.py"], "force": True}
        result = await session.lock(params, mock_ctx)
        assert "a.py" in result["locked"]


class TestUnlockHandler:
    @pytest.fixture
    def mock_ctx(self):
        return {"graph": MagicMock()}

    @pytest.mark.asyncio
    async def test_unlock_success(self, mock_ctx):
        graph = mock_ctx["graph"]
        graph.release_lock = AsyncMock(return_value=True)
        graph.get_session = AsyncMock(return_value={"session_id": "s1", "locked_files": ["a.py"]})
        graph.upsert_session = AsyncMock()
        graph.append_audit = AsyncMock()
        params = {"session_id": "s1", "files": ["a.py"]}
        result = await session.unlock(params, mock_ctx)
        assert "a.py" in result["released"]

    @pytest.mark.asyncio
    async def test_unlock_not_held(self, mock_ctx):
        graph = mock_ctx["graph"]
        graph.release_lock = AsyncMock(return_value=False)
        graph.get_session = AsyncMock(return_value={"session_id": "s1", "locked_files": ["a.py"]})
        graph.upsert_session = AsyncMock()
        graph.append_audit = AsyncMock()
        params = {"session_id": "s1", "files": ["a.py"]}
        result = await session.unlock(params, mock_ctx)
        assert "a.py" not in result["released"]


class TestAuditGetHandler:
    @pytest.fixture
    def mock_ctx(self):
        return {"graph": MagicMock(), "_audit_log": []}

    @pytest.mark.asyncio
    async def test_audit_get_from_graph(self, mock_ctx):
        graph = mock_ctx["graph"]
        graph.list_audit = AsyncMock(
            return_value=[
                {"event": "session_open", "session_id": "s1"},
                {"event": "lock_acquired", "session_id": "s1"},
            ]
        )
        params = {"audit_log_id": "s1"}
        result = await session.audit_get(params, mock_ctx)
        assert result["count"] == 2

    @pytest.mark.asyncio
    async def test_audit_get_empty(self, mock_ctx):
        graph = mock_ctx["graph"]
        graph.list_audit = AsyncMock(return_value=[])
        params = {}
        result = await session.audit_get(params, mock_ctx)
        assert result["count"] == 0


class TestReviewCreateHandler:
    @pytest.fixture
    def mock_ctx(self):
        return {"graph": MagicMock()}

    @pytest.mark.asyncio
    async def test_review_create_success(self, mock_ctx):
        graph = mock_ctx["graph"]
        graph.upsert_session = AsyncMock()
        params = {
            "session_id": "s1",
            "files_changed": ["a.py", "b.py"],
            "diff_summary": "refactored",
            "reviewers": ["reviewer1"],
        }
        result = await review.review_create(params, mock_ctx)
        assert "review_id" in result
        assert result["status"] == "pending"


class TestReviewApproveHandler:
    @pytest.fixture
    def mock_ctx(self):
        return {"graph": MagicMock(), "_reviews": {}}

    @pytest.mark.asyncio
    async def test_review_approve_not_found(self, mock_ctx):
        params = {"review_id": "nonexistent", "reviewer": "r1"}
        result = await review.review_approve(params, mock_ctx)
        assert result["approved"] is False
        assert result["error"] == "review_not_found"

    @pytest.mark.asyncio
    async def test_review_approve_success(self, mock_ctx):
        mock_ctx["_reviews"]["rev1"] = {"review_id": "rev1", "approvals": [], "rejections": [], "status": "pending"}
        graph = mock_ctx["graph"]
        graph.upsert_session = AsyncMock()
        params = {"review_id": "rev1", "reviewer": "reviewer1"}
        result = await review.review_approve(params, mock_ctx)
        assert result["approved"] is True
        assert result["status"] == "approved"


class TestReviewRejectHandler:
    @pytest.fixture
    def mock_ctx(self):
        return {"graph": MagicMock(), "_reviews": {}}

    @pytest.mark.asyncio
    async def test_review_reject_not_found(self, mock_ctx):
        params = {"review_id": "nonexistent", "reviewer": "r1", "reason": "bad"}
        result = await review.review_reject(params, mock_ctx)
        assert result["rejected"] is False

    @pytest.mark.asyncio
    async def test_review_reject_success(self, mock_ctx):
        mock_ctx["_reviews"]["rev1"] = {"review_id": "rev1", "approvals": [], "rejections": [], "status": "pending"}
        graph = mock_ctx["graph"]
        graph.upsert_session = AsyncMock()
        params = {"review_id": "rev1", "reviewer": "reviewer1", "reason": "code style violation"}
        result = await review.review_reject(params, mock_ctx)
        assert result["rejected"] is True
        assert result["status"] == "rejected"


class TestReviewCommentHandler:
    @pytest.fixture
    def mock_ctx(self):
        return {"graph": MagicMock(), "_reviews": {}}

    @pytest.mark.asyncio
    async def test_review_comment_not_found(self, mock_ctx):
        params = {"review_id": "nonexistent", "author": "dev1", "comment": "looks good"}
        result = await review.review_comment(params, mock_ctx)
        assert result["added"] is False

    @pytest.mark.asyncio
    async def test_review_comment_success(self, mock_ctx):
        mock_ctx["_reviews"]["rev1"] = {"review_id": "rev1", "comments": [], "status": "pending"}
        graph = mock_ctx["graph"]
        graph.upsert_session = AsyncMock()
        params = {"review_id": "rev1", "author": "dev1", "comment": "nice fix", "file_path": "a.py", "line": 10}
        result = await review.review_comment(params, mock_ctx)
        assert result["added"] is True
        assert result["total_comments"] == 1


class TestPrCreateHandler:
    @pytest.fixture
    def mock_ctx(self):
        return {"graph": MagicMock(), "_reviews": {}, "_pull_requests": {}}

    @pytest.mark.asyncio
    async def test_pr_create_review_not_found(self, mock_ctx):
        params = {"review_id": "nonexistent", "title": "PR Title"}
        result = await review.pr_create(params, mock_ctx)
        assert result["created"] is False
        assert result["error"] == "review_not_found"

    @patch("smp.protocol.handlers.review.get_provider")
    @pytest.mark.asyncio
    async def test_pr_create_success(self, mock_get_provider, mock_ctx):
        mock_ctx["_reviews"]["rev1"] = {"review_id": "rev1"}
        graph = mock_ctx["graph"]
        graph.upsert_session = AsyncMock()
        mock_provider = MagicMock()
        mock_provider.create_pull_request = AsyncMock(
            return_value=MagicMock(
                pr_id="pr123",
                title="My PR",
                body="PR body",
                branch="feature",
                base_branch="main",
                provider="github",
                url="https://github.com/pr/123",
                number=123,
                created_at="2024-01-01T00:00:00Z",
            )
        )
        mock_get_provider.return_value = mock_provider
        params = {"review_id": "rev1", "title": "My PR", "body": "PR body", "branch": "feature"}
        result = await review.pr_create(params, mock_ctx)
        assert result["created"] is True
        assert result["pr_id"] == "pr123"


class TestSandboxSpawnHandler:
    @pytest.fixture
    def mock_ctx(self):
        return {}

    @patch("smp.protocol.handlers.sandbox.get_runtime")
    @pytest.mark.asyncio
    async def test_sandbox_spawn_success(self, mock_get_runtime, mock_ctx):
        mock_runtime = MagicMock()
        mock_runtime.spawn = AsyncMock(
            return_value=MagicMock(
                sandbox_id="sb_abc123",
                name="test_sandbox",
                template="python",
                files=["main.py"],
                root="/tmp/sandbox",
                created_at="2024-01-01T00:00:00Z",
            )
        )
        mock_get_runtime.return_value = mock_runtime
        params = {"name": "test_sandbox", "template": "python", "files": {"main.py": "print('hello')"}}
        result = await sandbox.sandbox_spawn(params, mock_ctx)
        assert result["sandbox_id"] == "sb_abc123"
        assert result["status"] == "ready"


class TestSandboxExecuteHandler:
    @pytest.fixture
    def mock_ctx(self):
        return {}

    @patch("smp.protocol.handlers.sandbox.get_runtime")
    @pytest.mark.asyncio
    async def test_sandbox_execute_not_found(self, mock_get_runtime, mock_ctx):
        mock_runtime = MagicMock()
        mock_runtime.get.return_value = None
        mock_get_runtime.return_value = mock_runtime
        params = {"sandbox_id": "nonexistent", "command": ["echo", "hello"]}
        result = await sandbox.sandbox_execute(params, mock_ctx)
        assert result["started"] is False
        assert result["error"] == "sandbox_not_found"

    @patch("smp.protocol.handlers.sandbox.get_runtime")
    @pytest.mark.asyncio
    async def test_sandbox_execute_empty_command(self, mock_get_runtime, mock_ctx):
        mock_runtime = MagicMock()
        mock_runtime.get.return_value = MagicMock()
        mock_get_runtime.return_value = mock_runtime
        params = {"sandbox_id": "sb1", "command": []}
        result = await sandbox.sandbox_execute(params, mock_ctx)
        assert result["error"] == "empty_command"

    @patch("smp.protocol.handlers.sandbox.get_runtime")
    @pytest.mark.asyncio
    async def test_sandbox_execute_success(self, mock_get_runtime, mock_ctx):
        mock_runtime = MagicMock()
        mock_runtime.get.return_value = MagicMock()
        mock_runtime.execute = AsyncMock(
            return_value=MagicMock(
                execution_id="ex1",
                status="completed",
                exit_code=0,
                stdout="hello",
                stderr="",
                started_at="2024-01-01T00:00:00Z",
                ended_at="2024-01-01T00:00:01Z",
                duration_ms=1000,
                timed_out=False,
                truncated=False,
            )
        )
        mock_get_runtime.return_value = mock_runtime
        params = {"sandbox_id": "sb1", "command": ["echo", "hello"]}
        result = await sandbox.sandbox_execute(params, mock_ctx)
        assert result["started"] is True
        assert result["exit_code"] == 0


class TestSandboxKillHandler:
    @pytest.fixture
    def mock_ctx(self):
        return {}

    @patch("smp.protocol.handlers.sandbox.get_runtime")
    @pytest.mark.asyncio
    async def test_sandbox_kill_success(self, mock_get_runtime, mock_ctx):
        mock_runtime = MagicMock()
        mock_runtime.kill = AsyncMock(return_value=True)
        mock_get_runtime.return_value = mock_runtime
        params = {"execution_id": "ex1"}
        result = await sandbox.sandbox_kill(params, mock_ctx)
        assert result["killed"] is True

    @patch("smp.protocol.handlers.sandbox.get_runtime")
    @pytest.mark.asyncio
    async def test_sandbox_kill_not_found(self, mock_get_runtime, mock_ctx):
        mock_runtime = MagicMock()
        mock_runtime.kill = AsyncMock(return_value=False)
        mock_get_runtime.return_value = mock_runtime
        params = {"execution_id": "nonexistent"}
        result = await sandbox.sandbox_kill(params, mock_ctx)
        assert result["killed"] is False
        assert result["error"] == "execution_not_found"


class TestCommunityDetectHandler:
    @pytest.fixture
    def mock_ctx(self):
        return {"graph": MagicMock(), "_communities": {"by_id": {}, "node_to_id": {}, "level": 0}}

    @pytest.mark.asyncio
    async def test_community_detect_success(self, mock_ctx):
        graph = mock_ctx["graph"]
        graph.find_nodes = AsyncMock(return_value=[make_node("n1"), make_node("n2")])
        graph.get_edges = AsyncMock(return_value=[make_edge("n1", "n2")])
        params = {"relationship_types": ["CALLS"]}
        result = await community.community_detect(params, mock_ctx)
        assert "communities" in result
        assert result["total"] >= 1


class TestCommunityListHandler:
    @pytest.fixture
    def mock_ctx(self):
        return {"graph": MagicMock(), "_communities": {"by_id": {}, "node_to_id": {}, "level": 0}}

    @pytest.mark.asyncio
    async def test_community_list_empty(self, mock_ctx):
        graph = mock_ctx["graph"]
        graph.find_nodes = AsyncMock(return_value=[])
        params = {}
        result = await community.community_list(params, mock_ctx)
        assert result["total"] == 0

    @pytest.mark.asyncio
    async def test_community_list_with_data(self, mock_ctx):
        mock_ctx["_communities"]["by_id"] = {"com1": ["n1", "n2"], "com2": ["n3"]}
        mock_ctx["_communities"]["node_to_id"] = {"n1": "com1", "n2": "com1", "n3": "com2"}
        params = {"level": 0}
        result = await community.community_list(params, mock_ctx)
        assert result["total"] == 2


class TestCommunityGetHandler:
    @pytest.fixture
    def mock_ctx(self):
        return {"graph": MagicMock(), "_communities": {"by_id": {}, "node_to_id": {}, "level": 0}}

    @pytest.mark.asyncio
    async def test_community_get_not_found(self, mock_ctx):
        graph = mock_ctx["graph"]
        graph.find_nodes = AsyncMock(return_value=[])
        mock_ctx["_communities"]["by_id"] = {}
        params = {"community_id": "nonexistent"}
        result = await community.community_get(params, mock_ctx)
        assert result["size"] == 0
        assert result["nodes"] == []

    @pytest.mark.asyncio
    async def test_community_get_with_nodes(self, mock_ctx):
        mock_ctx["_communities"]["by_id"] = {"com1": ["n1"]}
        mock_ctx["_communities"]["node_to_id"] = {"n1": "com1"}
        graph = mock_ctx["graph"]
        graph.get_node = AsyncMock(return_value=make_node("n1"))
        graph.get_edges = AsyncMock(return_value=[])
        params = {"community_id": "com1"}
        result = await community.community_get(params, mock_ctx)
        assert result["community_id"] == "com1"
        assert len(result["nodes"]) == 1


class TestSyncHandler:
    @pytest.fixture
    def mock_ctx(self):
        return {"graph": MagicMock()}

    @pytest.mark.asyncio
    async def test_sync_in_sync(self, mock_ctx):
        graph = mock_ctx["graph"]
        node = make_node("n1", name="func", signature="()", start_line=1, end_line=10)
        graph.find_nodes = AsyncMock(return_value=[node])
        params = {"remote_data": {"nodes": [{"id": "n1", "signature": "test.py::Function::func::1", "hash": "abc123"}]}}
        result = await sync.sync(params, mock_ctx)
        assert "in_sync" in result

    @pytest.mark.asyncio
    async def test_sync_missing_locally(self, mock_ctx):
        graph = mock_ctx["graph"]
        graph.find_nodes = AsyncMock(return_value=[])
        params = {"remote_data": {"nodes": [{"id": "n1", "signature": "s1", "hash": "h1"}]}}
        result = await sync.sync(params, mock_ctx)
        assert "n1" in result["missing_locally"]


class TestIndexImportHandler:
    @pytest.fixture
    def mock_ctx(self):
        return {"graph": MagicMock()}

    @pytest.mark.asyncio
    async def test_index_import_empty_payload(self, mock_ctx):
        graph = mock_ctx["graph"]
        graph.upsert_nodes = AsyncMock()
        graph.upsert_edges = AsyncMock()
        params = {"data": {"nodes": [], "edges": []}}
        result = await sync.index_import(params, mock_ctx)
        assert result["imported_nodes"] == 0
        assert result["imported_edges"] == 0

    @pytest.mark.asyncio
    async def test_index_import_with_nodes(self, mock_ctx):
        graph = mock_ctx["graph"]
        graph.upsert_nodes = AsyncMock()
        graph.upsert_edges = AsyncMock()
        params = {
            "data": {
                "nodes": [{"id": "n1", "type": "Function", "file_path": "test.py", "structural": {"name": "f1"}}],
                "edges": [],
            }
        }
        result = await sync.index_import(params, mock_ctx)
        assert result["imported_nodes"] == 1
        assert result["skipped_nodes"] == 0


class TestIntegrityCheckHandler:
    @pytest.fixture
    def mock_ctx(self):
        return {"graph": MagicMock()}

    @pytest.mark.asyncio
    async def test_integrity_check_store_level(self, mock_ctx):
        graph = mock_ctx["graph"]
        graph.integrity_report = AsyncMock(return_value={"ok": True, "warnings": [], "errors": []})
        params = {"node_id": ""}
        result = await sync.integrity_check(params, mock_ctx)
        assert result["scope"] == "store"

    @pytest.mark.asyncio
    async def test_integrity_check_node_not_found(self, mock_ctx):
        graph = mock_ctx["graph"]
        graph.get_node = AsyncMock(return_value=None)
        params = {"node_id": "nonexistent"}
        result = await sync.integrity_check(params, mock_ctx)
        assert result["matches"] is False
        assert result["error"] == "node_not_found"

    @pytest.mark.asyncio
    async def test_integrity_check_node_match(self, mock_ctx):
        graph = mock_ctx["graph"]
        node = make_node("n1", name="func", signature="()", start_line=1, end_line=10)
        graph.get_node = AsyncMock(return_value=node)
        params = {"node_id": "n1", "current_state": {"signature": "abc123"}}
        result = await sync.integrity_check(params, mock_ctx)
        assert "matches" in result


class TestIntegrityBaselineHandler:
    @pytest.fixture
    def mock_ctx(self):
        return {"graph": MagicMock()}

    @pytest.mark.asyncio
    async def test_integrity_baseline_node_not_found(self, mock_ctx):
        graph = mock_ctx["graph"]
        graph.get_node = AsyncMock(return_value=None)
        params = {"node_id": "nonexistent"}
        result = await sync.integrity_baseline(params, mock_ctx)
        assert result["baseline_set"] is False
        assert result["error"] == "node_not_found"

    @pytest.mark.asyncio
    async def test_integrity_baseline_success(self, mock_ctx):
        graph = mock_ctx["graph"]
        node = make_node("n1")
        graph.get_node = AsyncMock(return_value=node)
        graph.upsert_node = AsyncMock()
        params = {"node_id": "n1", "state": {"signature": "new_sig"}}
        result = await sync.integrity_baseline(params, mock_ctx)
        assert result["baseline_set"] is True


class TestVectorSearchHandler:
    @pytest.fixture
    def mock_ctx(self):
        return {"vector_store": MagicMock()}

    @pytest.mark.asyncio
    async def test_vector_search_success(self, mock_ctx):
        vector_store = mock_ctx["vector_store"]
        vector_store.query = AsyncMock(return_value=[{"id": "n1", "score": 0.9}])
        params = {"embedding": [0.1] * 128, "top_k": 5}
        result = await vector.vector_search(params, mock_ctx)
        assert result["count"] == 1
        vector_store.query.assert_called_once()

    @pytest.mark.asyncio
    async def test_vector_search_with_filter(self, mock_ctx):
        vector_store = mock_ctx["vector_store"]
        vector_store.query = AsyncMock(return_value=[])
        params = {"embedding": [0.1] * 128, "top_k": 10, "where": {"type": "Function"}}
        await vector.vector_search(params, mock_ctx)
        vector_store.query.assert_called_once()


class TestVectorUpsertHandler:
    @pytest.fixture
    def mock_ctx(self):
        return {"vector_store": MagicMock()}

    @pytest.mark.asyncio
    async def test_vector_upsert_success(self, mock_ctx):
        vector_store = mock_ctx["vector_store"]
        vector_store.upsert = AsyncMock()
        params = {"ids": ["n1", "n2"], "embeddings": [[0.1] * 128, [0.2] * 128]}
        result = await vector.vector_upsert(params, mock_ctx)
        assert result["upserted"] == 2


class TestVectorDeleteHandler:
    @pytest.fixture
    def mock_ctx(self):
        return {"vector_store": MagicMock()}

    @pytest.mark.asyncio
    async def test_vector_delete_success(self, mock_ctx):
        vector_store = mock_ctx["vector_store"]
        vector_store.delete = AsyncMock(return_value=2)
        params = {"ids": ["n1", "n2"]}
        result = await vector.vector_delete(params, mock_ctx)
        assert result["deleted"] == 2


class TestDryRunHandler:
    @pytest.fixture
    def mock_ctx(self):
        return {"engine": MagicMock()}

    @pytest.mark.asyncio
    async def test_dryrun_success(self, mock_ctx):
        engine = mock_ctx["engine"]
        engine.diff_file = AsyncMock(return_value={"lines_added": 5, "lines_removed": 2})
        params = {"session_id": "s1", "file_path": "a.py", "proposed_content": "new content"}
        result = await session.dryrun(params, mock_ctx)
        assert "diff" in result
        engine.diff_file.assert_called_once_with("a.py", "new content")
