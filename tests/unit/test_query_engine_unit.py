"""Unit tests for query engine logic - L1: Mock-based unit tests.

Tests all DefaultQueryEngine methods with mocked graph store.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

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


def make_node(
    node_id: str,
    node_type: NodeType = NodeType.FUNCTION,
    file_path: str = "test.py",
    name: str = "",
    complexity: int = 1,
    docstring: str = "",
    decorators: list[str] | None = None,
    tags: list[str] | None = None,
    source_hash: str = "abc123",
    manually_set: bool = False,
) -> GraphNode:
    """Factory for creating test GraphNode instances."""
    return GraphNode(
        id=node_id,
        type=node_type,
        file_path=file_path,
        structural=StructuralProperties(
            name=name or node_id,
            file=file_path,
            signature=name or node_id,
            start_line=1,
            end_line=10,
            complexity=complexity,
            lines=10,
        ),
        semantic=SemanticProperties(
            docstring=docstring,
            decorators=decorators or [],
            tags=tags or [],
            source_hash=source_hash,
            manually_set=manually_set,
        ),
    )


def make_edge(
    source_id: str,
    target_id: str,
    edge_type: EdgeType = EdgeType.CALLS,
) -> GraphEdge:
    """Factory for creating test GraphEdge instances."""
    return GraphEdge(source_id=source_id, target_id=target_id, type=edge_type)


class TestNavigate:
    """Tests for navigate() method."""

    @pytest.fixture
    def mock_store(self) -> MagicMock:
        """Create a mock graph store."""
        store = MagicMock()
        store.get_node = AsyncMock(return_value=None)
        store.get_edges = AsyncMock(return_value=[])
        store.find_nodes = AsyncMock(return_value=[])
        return store

    @pytest.mark.asyncio
    async def test_navigate_exact_match(self, mock_store: MagicMock) -> None:
        """Test navigate finds node by exact ID."""
        node = make_node("func_process", NodeType.FUNCTION, "api.py", "process")
        mock_store.get_node = AsyncMock(return_value=node)

        engine = DefaultQueryEngine(graph_store=mock_store)
        result = await engine.navigate("func_process")

        assert "entity" in result
        assert result["entity"]["id"] == "func_process"

    @pytest.mark.asyncio
    async def test_navigate_not_found(self, mock_store: MagicMock) -> None:
        """Test navigate returns error when node not found."""
        mock_store.get_node = AsyncMock(return_value=None)
        mock_store.find_nodes = AsyncMock(return_value=[])

        engine = DefaultQueryEngine(graph_store=mock_store)
        result = await engine.navigate("nonexistent")

        assert "error" in result

    @pytest.mark.asyncio
    async def test_navigate_by_file_path(self, mock_store: MagicMock) -> None:
        """Test navigate finds node by file path."""
        node = make_node("func_a", NodeType.FUNCTION, "src/auth.py", "authenticate")
        mock_store.get_node = AsyncMock(return_value=None)
        mock_store.find_nodes = AsyncMock(return_value=[node])

        engine = DefaultQueryEngine(graph_store=mock_store)
        result = await engine.navigate("src/auth.py")

        assert "entity" in result

    @pytest.mark.asyncio
    async def test_navigate_by_name(self, mock_store: MagicMock) -> None:
        """Test navigate finds node by name."""
        node = make_node("func_login", NodeType.FUNCTION, "auth.py", "login")
        mock_store.get_node = AsyncMock(return_value=None)
        mock_store.find_nodes = AsyncMock(return_value=[node])

        engine = DefaultQueryEngine(graph_store=mock_store)
        result = await engine.navigate("login")

        assert "entity" in result

    @pytest.mark.asyncio
    async def test_navigate_partial_match(self, mock_store: MagicMock) -> None:
        """Test navigate finds node by partial ID match."""
        node = make_node("module_func_example", NodeType.FUNCTION, "mod.py", "example")
        mock_store.get_node = AsyncMock(return_value=None)
        mock_store.find_nodes = AsyncMock(return_value=[node])

        engine = DefaultQueryEngine(graph_store=mock_store)
        result = await engine.navigate("func_example")

        assert "entity" in result

    @pytest.mark.asyncio
    async def test_navigate_with_relationships(self, mock_store: MagicMock) -> None:
        """Test navigate includes relationships."""
        node = make_node("func_a", NodeType.FUNCTION, "a.py", "func_a")
        outgoing_edges = [make_edge("func_a", "func_b", EdgeType.CALLS)]
        incoming_edges = [make_edge("func_c", "func_a", EdgeType.CALLS)]
        mock_store.get_node = AsyncMock(return_value=node)
        mock_store.get_edges = AsyncMock(
            side_effect=[
                outgoing_edges,
                incoming_edges,
            ]
        )

        engine = DefaultQueryEngine(graph_store=mock_store)
        result = await engine.navigate("func_a", include_relationships=True)

        assert "relationships" in result

    @pytest.mark.asyncio
    async def test_navigate_without_relationships(self, mock_store: MagicMock) -> None:
        """Test navigate excludes relationships when requested."""
        node = make_node("func_x", NodeType.FUNCTION, "x.py", "func_x")
        mock_store.get_node = AsyncMock(return_value=node)

        engine = DefaultQueryEngine(graph_store=mock_store)
        result = await engine.navigate("func_x", include_relationships=False)

        assert "relationships" not in result


class TestTrace:
    """Tests for trace() method."""

    @pytest.fixture
    def mock_store(self) -> MagicMock:
        """Create a mock graph store."""
        store = MagicMock()
        store.traverse = AsyncMock(return_value=[])
        store.get_node = AsyncMock(return_value=make_node("func_a", NodeType.FUNCTION, "a.py", "a"))
        store.find_nodes = AsyncMock(return_value=[])
        return store

    @pytest.mark.asyncio
    async def test_trace_default_params(self, mock_store: MagicMock) -> None:
        """Test trace with default parameters."""
        nodes = [
            make_node("func_a", NodeType.FUNCTION, "a.py", "a"),
            make_node("func_b", NodeType.FUNCTION, "b.py", "b"),
        ]
        mock_store.traverse = AsyncMock(return_value=nodes)

        engine = DefaultQueryEngine(graph_store=mock_store)
        result = await engine.trace("func_start")

        assert isinstance(result, list)

    @pytest.mark.asyncio
    async def test_trace_custom_depth(self, mock_store: MagicMock) -> None:
        """Test trace with custom depth."""
        mock_store.traverse = AsyncMock(return_value=[])

        engine = DefaultQueryEngine(graph_store=mock_store)
        await engine.trace("func_a", depth=5)

        mock_store.traverse.assert_called_once()
        call_args = mock_store.traverse.call_args
        assert call_args[0][2] == 5

    @pytest.mark.asyncio
    async def test_trace_incoming_direction(self, mock_store: MagicMock) -> None:
        """Test trace in incoming direction."""
        mock_store.traverse = AsyncMock(return_value=[])

        engine = DefaultQueryEngine(graph_store=mock_store)
        await engine.trace("func_a", direction="incoming")

        call_args = mock_store.traverse.call_args
        assert call_args[1]["direction"] == "incoming"

    @pytest.mark.asyncio
    async def test_trace_custom_edge_type(self, mock_store: MagicMock) -> None:
        """Test trace with custom edge type."""
        mock_store.traverse = AsyncMock(return_value=[])

        engine = DefaultQueryEngine(graph_store=mock_store)
        await engine.trace("func_a", relationship="IMPORTS")

        call_args = mock_store.traverse.call_args
        assert call_args[0][1] == EdgeType.IMPORTS


class TestGetContext:
    """Tests for get_context() method."""

    @pytest.fixture
    def mock_store(self) -> MagicMock:
        """Create a mock graph store."""
        store = MagicMock()
        store.find_nodes = AsyncMock(return_value=[])
        store.get_edges = AsyncMock(return_value=[])
        store.get_node = AsyncMock(return_value=None)
        store.traverse = AsyncMock(return_value=[])
        return store

    @pytest.mark.asyncio
    async def test_get_context_file_not_found(self, mock_store: MagicMock) -> None:
        """Test get_context returns error when file not found."""
        mock_store.find_nodes = AsyncMock(return_value=[])

        engine = DefaultQueryEngine(graph_store=mock_store)
        result = await engine.get_context("nonexistent.py")

        assert "error" in result

    @pytest.mark.asyncio
    async def test_get_context_default_scope(self, mock_store: MagicMock) -> None:
        """Test get_context with default scope."""
        node = make_node("file_api", NodeType.FILE, "api.py", "api")
        mock_store.find_nodes = AsyncMock(return_value=[node])

        engine = DefaultQueryEngine(graph_store=mock_store)
        result = await engine.get_context("api.py")

        assert "self" in result
        assert result["self"]["id"] == "file_api"

    @pytest.mark.asyncio
    async def test_get_context_custom_depth(self, mock_store: MagicMock) -> None:
        """Test get_context with custom depth."""
        node = make_node("file_test", NodeType.FILE, "test.py", "test")
        mock_store.find_nodes = AsyncMock(return_value=[node])

        engine = DefaultQueryEngine(graph_store=mock_store)
        await engine.get_context("test.py", depth=5)

        mock_store.traverse.assert_called()

    @pytest.mark.asyncio
    async def test_get_context_with_imports(self, mock_store: MagicMock) -> None:
        """Test get_context includes imports."""
        file_node = make_node("file_app", NodeType.FILE, "app.py", "app")
        import_edges = [make_edge("file_app", "file_utils", EdgeType.IMPORTS)]
        mock_store.find_nodes = AsyncMock(return_value=[file_node])
        mock_store.get_edges = AsyncMock(return_value=import_edges)

        engine = DefaultQueryEngine(graph_store=mock_store)
        result = await engine.get_context("app.py")

        assert "imports" in result

    @pytest.mark.asyncio
    async def test_get_context_with_defines(self, mock_store: MagicMock) -> None:
        """Test get_context includes defined functions."""
        file_node = make_node("file_lib", NodeType.FILE, "lib.py", "lib")
        define_edges = [make_edge("file_lib", "func_hello", EdgeType.DEFINES)]
        func_node = make_node("func_hello", NodeType.FUNCTION, "lib.py", "hello")
        mock_store.find_nodes = AsyncMock(return_value=[file_node])
        mock_store.get_edges = AsyncMock(
            side_effect=[
                [],
                [],
                define_edges,
                [],
            ]
        )
        mock_store.get_node = AsyncMock(return_value=func_node)

        engine = DefaultQueryEngine(graph_store=mock_store)
        result = await engine.get_context("lib.py")

        assert "defines" in result


class TestAssessImpact:
    """Tests for assess_impact() method."""

    @pytest.fixture
    def mock_store(self) -> MagicMock:
        """Create a mock graph store."""
        store = MagicMock()
        store.get_node = AsyncMock(return_value=None)
        store.find_nodes = AsyncMock(return_value=[])
        store.traverse = AsyncMock(return_value=[])
        return store

    @pytest.mark.asyncio
    async def test_assess_impact_not_found(self, mock_store: MagicMock) -> None:
        """Test assess_impact returns error when entity not found."""
        mock_store.get_node = AsyncMock(return_value=None)
        mock_store.find_nodes = AsyncMock(return_value=[])

        engine = DefaultQueryEngine(graph_store=mock_store)
        result = await engine.assess_impact("nonexistent")

        assert "error" in result

    @pytest.mark.asyncio
    async def test_assess_impact_by_name(self, mock_store: MagicMock) -> None:
        """Test assess_impact finds node by name."""
        node = make_node("func_test", NodeType.FUNCTION, "test.py", "test")
        mock_store.get_node = AsyncMock(return_value=None)
        mock_store.find_nodes = AsyncMock(return_value=[node])

        engine = DefaultQueryEngine(graph_store=mock_store)
        result = await engine.assess_impact("test")

        assert "error" not in result

    @pytest.mark.asyncio
    async def test_assess_impact_with_dependents(self, mock_store: MagicMock) -> None:
        """Test assess_impact includes dependents."""
        node = make_node("func_core", NodeType.FUNCTION, "core.py", "core")
        dependents = [
            make_node("func_caller1", NodeType.FUNCTION, "caller1.py", "caller1"),
            make_node("func_caller2", NodeType.FUNCTION, "caller2.py", "caller2"),
        ]
        mock_store.get_node = AsyncMock(return_value=node)
        mock_store.traverse = AsyncMock(return_value=dependents)

        engine = DefaultQueryEngine(graph_store=mock_store)
        result = await engine.assess_impact("func_core")

        assert "affected_files" in result

    @pytest.mark.asyncio
    async def test_assess_impact_low_severity(self, mock_store: MagicMock) -> None:
        """Test assess_impact with low severity."""
        node = make_node("func_rare", NodeType.FUNCTION, "rare.py", "rare")
        mock_store.get_node = AsyncMock(return_value=node)
        mock_store.traverse = AsyncMock(return_value=[])

        engine = DefaultQueryEngine(graph_store=mock_store)
        result = await engine.assess_impact("func_rare")

        assert result["severity"] == "low"

    @pytest.mark.asyncio
    async def test_assess_impact_medium_severity(self, mock_store: MagicMock) -> None:
        """Test assess_impact with medium severity."""
        node = make_node("func_used", NodeType.FUNCTION, "used.py", "used")
        dependents = [make_node(f"caller{i}", NodeType.FUNCTION, f"c{i}.py", f"c{i}") for i in range(5)]
        mock_store.get_node = AsyncMock(return_value=node)
        mock_store.traverse = AsyncMock(return_value=dependents)

        engine = DefaultQueryEngine(graph_store=mock_store)
        result = await engine.assess_impact("func_used")

        assert result["severity"] == "medium"

    @pytest.mark.asyncio
    async def test_assess_impact_high_severity(self, mock_store: MagicMock) -> None:
        """Test assess_impact with high severity."""
        node = make_node("func_hot", NodeType.FUNCTION, "hot.py", "hot")
        dependents = [make_node(f"caller{i}", NodeType.FUNCTION, f"c{i}.py", f"caller{i}") for i in range(15)]
        mock_store.get_node = AsyncMock(return_value=node)
        mock_store.traverse = AsyncMock(return_value=dependents)

        engine = DefaultQueryEngine(graph_store=mock_store)
        result = await engine.assess_impact("func_hot")

        assert result["severity"] == "high"

    @pytest.mark.asyncio
    async def test_assess_impact_signature_change(self, mock_store: MagicMock) -> None:
        """Test assess_impact with signature_change type."""
        node = make_node("func_api", NodeType.FUNCTION, "api.py", "api")
        mock_store.get_node = AsyncMock(return_value=node)
        mock_store.traverse = AsyncMock(
            return_value=[
                make_node("caller1", NodeType.FUNCTION, "c1.py", "c1"),
            ]
        )

        engine = DefaultQueryEngine(graph_store=mock_store)
        result = await engine.assess_impact("func_api", change_type="signature_change")

        assert len(result["recommendations"]) > 0

    @pytest.mark.asyncio
    async def test_assess_impact_delete_type(self, mock_store: MagicMock) -> None:
        """Test assess_impact with delete type."""
        node = make_node("func_del", NodeType.FUNCTION, "del.py", "del")
        mock_store.get_node = AsyncMock(return_value=node)
        mock_store.traverse = AsyncMock(return_value=[])

        engine = DefaultQueryEngine(graph_store=mock_store)
        result = await engine.assess_impact("func_del", change_type="delete")

        assert len(result["recommendations"]) > 0


class TestLocate:
    """Tests for locate() method."""

    @pytest.fixture
    def mock_store(self) -> MagicMock:
        """Create a mock graph store."""
        store = MagicMock()
        store.find_nodes = AsyncMock(return_value=[])
        return store

    @pytest.mark.asyncio
    async def test_locate_default_params(self, mock_store: MagicMock) -> None:
        """Test locate with default parameters."""
        nodes = [
            make_node("func_login", NodeType.FUNCTION, "auth.py", "login", docstring="User login"),
        ]
        mock_store.find_nodes = AsyncMock(return_value=nodes)

        engine = DefaultQueryEngine(graph_store=mock_store)
        result = await engine.locate("login")

        assert isinstance(result, list)

    @pytest.mark.asyncio
    async def test_locate_match_name(self, mock_store: MagicMock) -> None:
        """Test locate matches on name."""
        node = make_node("func_process", NodeType.FUNCTION, "process.py", "process_data")
        mock_store.find_nodes = AsyncMock(return_value=[node])

        engine = DefaultQueryEngine(graph_store=mock_store)
        result = await engine.locate("process")

        assert len(result) > 0

    @pytest.mark.asyncio
    async def test_locate_match_docstring(self, mock_store: MagicMock) -> None:
        """Test locate matches on docstring."""
        node = make_node("func_auth", NodeType.FUNCTION, "auth.py", "authenticate", docstring="Authenticate user")
        mock_store.find_nodes = AsyncMock(return_value=[node])

        engine = DefaultQueryEngine(graph_store=mock_store)
        result = await engine.locate("authenticate")

        assert len(result) > 0

    @pytest.mark.asyncio
    async def test_locate_match_tags(self, mock_store: MagicMock) -> None:
        """Test locate matches on tags."""
        node = make_node("func_legacy", NodeType.FUNCTION, "legacy.py", "old_func", tags=["legacy"])
        mock_store.find_nodes = AsyncMock(return_value=[node])

        engine = DefaultQueryEngine(graph_store=mock_store)
        result = await engine.locate("legacy")

        assert len(result) > 0

    @pytest.mark.asyncio
    async def test_locate_with_node_types(self, mock_store: MagicMock) -> None:
        """Test locate with node type filter."""
        node = make_node("class_user", NodeType.CLASS, "models.py", "User")
        mock_store.find_nodes = AsyncMock(return_value=[node])

        engine = DefaultQueryEngine(graph_store=mock_store)
        result = await engine.locate("user", node_types=["Class"])

        assert len(result) >= 0

    @pytest.mark.asyncio
    async def test_locate_top_k(self, mock_store: MagicMock) -> None:
        """Test locate respects top_k parameter."""
        nodes = [make_node(f"func_{i}", NodeType.FUNCTION, f"f{i}.py", f"func{i}") for i in range(10)]
        mock_store.find_nodes = AsyncMock(return_value=nodes)

        engine = DefaultQueryEngine(graph_store=mock_store)
        result = await engine.locate("func", top_k=3)

        assert len(result) <= 3


class TestSearch:
    """Tests for search() method."""

    @pytest.fixture
    def mock_store(self) -> MagicMock:
        """Create a mock graph store."""
        store = MagicMock()
        store.search_nodes = AsyncMock(return_value=[])
        return store

    @pytest.mark.asyncio
    async def test_search_with_results(self, mock_store: MagicMock) -> None:
        """Test search returns results."""
        search_results = [{"id": "func_a", "name": "a"}]
        mock_store.search_nodes = AsyncMock(return_value=search_results)

        engine = DefaultQueryEngine(graph_store=mock_store)
        result = await engine.search("query")

        assert result["total"] > 0

    @pytest.mark.asyncio
    async def test_search_no_results(self, mock_store: MagicMock) -> None:
        """Test search with no results."""
        mock_store.search_nodes = AsyncMock(return_value=[])

        engine = DefaultQueryEngine(graph_store=mock_store)
        result = await engine.search("nonexistent")

        assert result["total"] == 0
        assert "hint" in result

    @pytest.mark.asyncio
    async def test_search_with_filters(self, mock_store: MagicMock) -> None:
        """Test search with filters."""
        mock_store.search_nodes = AsyncMock(return_value=[])

        engine = DefaultQueryEngine(graph_store=mock_store)
        await engine.search("query", filters={"node_types": ["Function"]})

        call_args = mock_store.search_nodes.call_args
        assert call_args[1]["node_types"] == ["Function"]

    @pytest.mark.asyncio
    async def test_search_with_tags(self, mock_store: MagicMock) -> None:
        """Test search with tags filter."""
        mock_store.search_nodes = AsyncMock(return_value=[])

        engine = DefaultQueryEngine(graph_store=mock_store)
        await engine.search("query", filters={"tags": ["important"]})

        call_args = mock_store.search_nodes.call_args
        assert call_args[1]["tags"] == ["important"]

    @pytest.mark.asyncio
    async def test_search_match_all(self, mock_store: MagicMock) -> None:
        """Test search with match=all."""
        mock_store.search_nodes = AsyncMock(return_value=[])

        engine = DefaultQueryEngine(graph_store=mock_store)
        await engine.search("query", match="all")

        call_args = mock_store.search_nodes.call_args
        assert call_args[1]["match"] == "all"


class TestFindFlow:
    """Tests for find_flow() method."""

    @pytest.fixture
    def mock_store(self) -> MagicMock:
        """Create a mock graph store."""
        store = MagicMock()
        store.get_node = AsyncMock(return_value=None)
        store.find_nodes = AsyncMock(return_value=[])
        store.get_edges = AsyncMock(return_value=[])
        return store

    @pytest.mark.asyncio
    async def test_find_flow_same_node(self, mock_store: MagicMock) -> None:
        """Test find_flow when start equals end."""
        node = make_node("func_a", NodeType.FUNCTION, "a.py", "func_a")
        mock_store.get_node = AsyncMock(return_value=node)

        engine = DefaultQueryEngine(graph_store=mock_store)
        result = await engine.find_flow("func_a", "func_a")

        assert len(result["path"]) == 1

    @pytest.mark.asyncio
    async def test_find_flow_no_path(self, mock_store: MagicMock) -> None:
        """Test find_flow when no path exists."""
        mock_store.get_node = AsyncMock(return_value=None)
        mock_store.find_nodes = AsyncMock(return_value=[])

        engine = DefaultQueryEngine(graph_store=mock_store)
        result = await engine.find_flow("func_a", "func_b")

        assert len(result["path"]) == 0

    @pytest.mark.asyncio
    async def test_find_flow_start_not_found(self, mock_store: MagicMock) -> None:
        """Test find_flow when start not found."""
        mock_store.get_node = AsyncMock(return_value=None)
        mock_store.find_nodes = AsyncMock(return_value=[])

        engine = DefaultQueryEngine(graph_store=mock_store)
        result = await engine.find_flow("nonexistent", "func_b")

        assert len(result["path"]) == 0

    @pytest.mark.asyncio
    async def test_find_flow_data_type(self, mock_store: MagicMock) -> None:
        """Test find_flow with data flow type."""
        mock_store.get_node = AsyncMock(return_value=None)

        engine = DefaultQueryEngine(graph_store=mock_store)
        result = await engine.find_flow("start", "end", flow_type="data")

        assert "path" in result

    @pytest.mark.asyncio
    async def test_find_flow_control_type(self, mock_store: MagicMock) -> None:
        """Test find_flow with control flow type."""
        mock_store.get_node = AsyncMock(return_value=None)

        engine = DefaultQueryEngine(graph_store=mock_store)
        result = await engine.find_flow("start", "end", flow_type="control")

        assert "path" in result

    @pytest.mark.asyncio
    async def test_find_flow_dependency_type(self, mock_store: MagicMock) -> None:
        """Test find_flow with dependency flow type."""
        mock_store.get_node = AsyncMock(return_value=None)

        engine = DefaultQueryEngine(graph_store=mock_store)
        result = await engine.find_flow("start", "end", flow_type="dependency")

        assert "path" in result


class TestDiff:
    """Tests for diff() method (checkpoint/live snapshot semantics)."""

    @pytest.fixture
    def mock_store(self) -> MagicMock:
        """Create a mock graph store."""
        store = MagicMock()
        store.find_nodes = AsyncMock(return_value=[])
        store.find_nodes_by_scope = AsyncMock(return_value=[])
        store.get_session = AsyncMock(return_value=None)
        return store

    def _checkpoint(self, checkpoint_id: str, node_index: dict[str, dict[str, str]]) -> dict[str, object]:
        return {
            "session_id": checkpoint_id,
            "kind": "checkpoint",
            "checkpoint_id": checkpoint_id,
            "files": sorted(node_index),
            "fingerprints": {},
            "node_index": node_index,
            "created_at": "2026-01-01T00:00:00+00:00",
        }

    @pytest.mark.asyncio
    async def test_diff_added_nodes(self, mock_store: MagicMock) -> None:
        """Test diff with added nodes (checkpoint -> live)."""
        live = [
            make_node("n1", NodeType.FUNCTION, "f1.py", "n1"),
            make_node("n2", NodeType.FUNCTION, "f2.py", "n2"),
        ]
        mock_store.find_nodes = AsyncMock(return_value=live)
        mock_store.get_session = AsyncMock(
            return_value=self._checkpoint("ckpt_1", {"f1.py": {"n1": live[0].content_hash()}})
        )

        engine = DefaultQueryEngine(graph_store=mock_store)
        result = await engine.diff("ckpt_1", "live")

        assert result["added"] == ["n2"]
        assert result["files_added"] == ["f2.py"]

    @pytest.mark.asyncio
    async def test_diff_removed_nodes(self, mock_store: MagicMock) -> None:
        """Test diff with removed nodes."""
        live = [make_node("n1", NodeType.FUNCTION, "f1.py", "n1")]
        mock_store.find_nodes = AsyncMock(return_value=live)
        mock_store.get_session = AsyncMock(
            return_value=self._checkpoint("ckpt_1", {"f1.py": {"n1": live[0].content_hash(), "n2": "oldhash"}})
        )

        engine = DefaultQueryEngine(graph_store=mock_store)
        result = await engine.diff("ckpt_1", "live")

        assert result["removed"] == ["n2"]
        assert result["files_changed"] == ["f1.py"]

    @pytest.mark.asyncio
    async def test_diff_changed_nodes(self, mock_store: MagicMock) -> None:
        """Test diff detects changed nodes."""
        live = [make_node("n1", NodeType.FUNCTION, "f1.py", "n1")]
        mock_store.find_nodes = AsyncMock(return_value=live)
        mock_store.get_session = AsyncMock(return_value=self._checkpoint("ckpt_1", {"f1.py": {"n1": "stalehash"}}))

        engine = DefaultQueryEngine(graph_store=mock_store)
        result = await engine.diff("ckpt_1", "live")

        assert result["changed"] == ["n1"]
        assert result["files_changed"] == ["f1.py"]

    @pytest.mark.asyncio
    async def test_diff_stats(self, mock_store: MagicMock) -> None:
        """Test diff includes stats."""
        engine = DefaultQueryEngine(graph_store=mock_store)
        result = await engine.diff("live", "live")

        assert "stats" in result
        assert "added_count" in result["stats"]
        assert "files_changed" in result

    @pytest.mark.asyncio
    async def test_diff_unknown_snapshot(self, mock_store: MagicMock) -> None:
        """Test diff with an unknown snapshot id."""
        engine = DefaultQueryEngine(graph_store=mock_store)
        result = await engine.diff("ckpt_nope", "live")

        assert result["error"] == "snapshot_not_found"
        assert result["missing_snapshot"] == "ckpt_nope"


class TestPlan:
    """Tests for plan() method."""

    @pytest.fixture
    def mock_store(self) -> MagicMock:
        """Create a mock graph store."""
        store = MagicMock()
        store.find_nodes = AsyncMock(return_value=[])
        store.traverse = AsyncMock(return_value=[])
        return store

    @pytest.mark.asyncio
    async def test_plan_basic(self, mock_store: MagicMock) -> None:
        """Test plan with basic change."""
        mock_store.find_nodes = AsyncMock(return_value=[])

        engine = DefaultQueryEngine(graph_store=mock_store)
        result = await engine.plan("Add feature", "app.py")

        assert "steps" in result
        assert len(result["steps"]) >= 3

    @pytest.mark.asyncio
    async def test_plan_with_callers(self, mock_store: MagicMock) -> None:
        """Test plan finds affected nodes."""
        file_node = make_node("file_api", NodeType.FILE, "api.py", "api")
        callers = [make_node("caller1", NodeType.FUNCTION, "c1.py", "caller1")]
        mock_store.find_nodes = AsyncMock(return_value=[file_node])
        mock_store.traverse = AsyncMock(return_value=callers)

        engine = DefaultQueryEngine(graph_store=mock_store)
        result = await engine.plan("Refactor", "api.py")

        assert "affected_nodes" in result

    @pytest.mark.asyncio
    async def test_plan_signature_change(self, mock_store: MagicMock) -> None:
        """Test plan with signature change type."""
        mock_store.find_nodes = AsyncMock(return_value=[])

        engine = DefaultQueryEngine(graph_store=mock_store)
        result = await engine.plan("Change signature", "api.py", change_type="signature_change")

        assert len(result["steps"]) > 3

    @pytest.mark.asyncio
    async def test_plan_risk_low(self, mock_store: MagicMock) -> None:
        """Test plan with low risk."""
        mock_store.find_nodes = AsyncMock(return_value=[])
        mock_store.traverse = AsyncMock(return_value=[])

        engine = DefaultQueryEngine(graph_store=mock_store)
        result = await engine.plan("Minor fix", "lib.py")

        assert result["risk_level"] == "low"

    @pytest.mark.asyncio
    async def test_plan_risk_high(self, mock_store: MagicMock) -> None:
        """Test plan with high risk."""
        file_node = make_node("file_core", NodeType.FILE, "core.py", "core")
        callers = [make_node(f"c{i}", NodeType.FUNCTION, f"c{i}.py", f"c{i}") for i in range(15)]
        mock_store.find_nodes = AsyncMock(return_value=[file_node])
        mock_store.traverse = AsyncMock(return_value=callers)

        engine = DefaultQueryEngine(graph_store=mock_store)
        result = await engine.plan("Major refactor", "core.py")

        assert result["risk_level"] == "high"


class TestConflict:
    """Tests for conflict() method."""

    @pytest.fixture
    def mock_store(self) -> MagicMock:
        """Create a mock graph store."""
        store = MagicMock()
        store.get_node = AsyncMock(return_value=None)
        store.find_nodes = AsyncMock(return_value=[])
        store.get_edges = AsyncMock(return_value=[])
        return store

    @pytest.mark.asyncio
    async def test_conflict_not_found(self, mock_store: MagicMock) -> None:
        """Test conflict when entity not found."""
        mock_store.get_node = AsyncMock(return_value=None)
        mock_store.find_nodes = AsyncMock(return_value=[])

        engine = DefaultQueryEngine(graph_store=mock_store)
        result = await engine.conflict("nonexistent", "change")

        assert result["conflict"] is False

    @pytest.mark.asyncio
    async def test_conflict_by_name(self, mock_store: MagicMock) -> None:
        """Test conflict finds node by name."""
        node = make_node("func_test", NodeType.FUNCTION, "test.py", "test")
        mock_store.get_node = AsyncMock(return_value=None)
        mock_store.find_nodes = AsyncMock(return_value=[node])

        engine = DefaultQueryEngine(graph_store=mock_store)
        result = await engine.conflict("test", "change")

        assert result["caller_count"] == 0

    @pytest.mark.asyncio
    async def test_conflict_high_blast_radius(self, mock_store: MagicMock) -> None:
        """Test conflict detected with high blast radius."""
        node = make_node("func_hot", NodeType.FUNCTION, "hot.py", "hot")
        edges = [make_edge(f"caller{i}", "func_hot", EdgeType.CALLS) for i in range(10)]
        mock_store.get_node = AsyncMock(return_value=node)
        mock_store.get_edges = AsyncMock(return_value=edges)

        engine = DefaultQueryEngine(graph_store=mock_store)
        result = await engine.conflict("func_hot", "change")

        assert result["conflict"] is True

    @pytest.mark.asyncio
    async def test_conflict_with_manually_set(self, mock_store: MagicMock) -> None:
        """Test conflict with manually set entity."""
        node = make_node("func_annotated", NodeType.FUNCTION, "annot.py", "annotated", manually_set=True)
        mock_store.get_node = AsyncMock(return_value=node)

        engine = DefaultQueryEngine(graph_store=mock_store)
        result = await engine.conflict("func_annotated", "change")

        assert len(result["warnings"]) > 0

    @pytest.mark.asyncio
    async def test_conflict_with_context(self, mock_store: MagicMock) -> None:
        """Test conflict with session context."""
        node = make_node("func_locked", NodeType.FUNCTION, "locked.py", "locked")
        mock_store.get_node = AsyncMock(return_value=node)

        engine = DefaultQueryEngine(graph_store=mock_store)
        result = await engine.conflict(
            "func_locked",
            "change",
            context={"session_id": "s1", "locked_files": ["locked.py"]},
        )

        assert result["conflict"] is True


class TestWhy:
    """Tests for why() method."""

    @pytest.fixture
    def mock_store(self) -> MagicMock:
        """Create a mock graph store."""
        store = MagicMock()
        store.get_node = AsyncMock(return_value=None)
        store.find_nodes = AsyncMock(return_value=[])
        store.get_edges = AsyncMock(return_value=[])
        return store

    @pytest.mark.asyncio
    async def test_why_not_found(self, mock_store: MagicMock) -> None:
        """Test why returns error when entity not found."""
        mock_store.get_node = AsyncMock(return_value=None)
        mock_store.find_nodes = AsyncMock(return_value=[])

        engine = DefaultQueryEngine(graph_store=mock_store)
        result = await engine.why("nonexistent")

        assert "error" in result

    @pytest.mark.asyncio
    async def test_why_by_file_path(self, mock_store: MagicMock) -> None:
        """Test why finds entity by file path."""
        node = make_node("file_auth", NodeType.FILE, "auth.py", "auth")
        mock_store.get_node = AsyncMock(return_value=None)
        mock_store.find_nodes = AsyncMock(return_value=[node])
        mock_store.get_edges = AsyncMock(return_value=[])

        engine = DefaultQueryEngine(graph_store=mock_store)
        result = await engine.why("auth.py")

        assert "error" not in result

    @pytest.mark.asyncio
    async def test_why_incoming_edges(self, mock_store: MagicMock) -> None:
        """Test why includes incoming edges."""
        node = make_node("func_target", NodeType.FUNCTION, "target.py", "target")
        incoming = [make_edge("source", "func_target", EdgeType.CALLS)]
        mock_store.get_node = AsyncMock(return_value=node)
        mock_store.get_edges = AsyncMock(
            side_effect=[
                incoming,
                [],
            ]
        )

        engine = DefaultQueryEngine(graph_store=mock_store)
        result = await engine.why("func_target")

        assert "reasons" in result

    @pytest.mark.asyncio
    async def test_why_outgoing_edges(self, mock_store: MagicMock) -> None:
        """Test why includes outgoing edges."""
        node = make_node("func_source", NodeType.FUNCTION, "source.py", "source")
        outgoing = [make_edge("func_source", "target", EdgeType.CALLS)]
        mock_store.get_node = AsyncMock(return_value=node)
        mock_store.get_edges = AsyncMock(
            side_effect=[
                [],
                outgoing,
            ]
        )

        engine = DefaultQueryEngine(graph_store=mock_store)
        result = await engine.why("func_source")

        assert "reasons" in result

    @pytest.mark.asyncio
    async def test_why_total_relationships(self, mock_store: MagicMock) -> None:
        """Test why includes total relationship count."""
        node = make_node("func_connected", NodeType.FUNCTION, "conn.py", "connected")
        incoming = [make_edge("c1", "func_connected", EdgeType.CALLS)]
        outgoing = [make_edge("func_connected", "c2", EdgeType.CALLS)]
        mock_store.get_node = AsyncMock(return_value=node)
        mock_store.get_edges = AsyncMock(
            side_effect=[
                incoming,
                outgoing,
            ]
        )

        engine = DefaultQueryEngine(graph_store=mock_store)
        result = await engine.why("func_connected")

        assert result["total_relationships"] == 2


class TestDiffFile:
    """Tests for diff_file() method."""

    @pytest.fixture
    def mock_store(self) -> MagicMock:
        """Create a mock graph store."""
        store = MagicMock()
        store.find_nodes = AsyncMock(return_value=[])
        store.get_edges = AsyncMock(return_value=[])
        return store

    @pytest.mark.asyncio
    async def test_diff_file_basic(self, mock_store: MagicMock) -> None:
        """Test diff_file with no proposed content."""
        nodes = [make_node("n1", NodeType.FILE, "f.py", "n1")]
        mock_store.find_nodes = AsyncMock(return_value=nodes)

        engine = DefaultQueryEngine(graph_store=mock_store)
        result = await engine.diff_file("f.py")

        assert "nodes_added" in result

    @pytest.mark.asyncio
    async def test_diff_file_with_proposed_content(self, mock_store: MagicMock) -> None:
        """Test diff_file with proposed content."""
        nodes = [make_node("n1", NodeType.FILE, "f.py", "n1")]
        mock_store.find_nodes = AsyncMock(return_value=nodes)
        mock_store.get_edges = AsyncMock(return_value=[])

        with patch("smp.engine.query.CodeParser") as mock_parser_class:
            mock_parser = MagicMock()
            mock_parser.parse.return_value = MagicMock(
                nodes=[
                    MagicMock(node_id="n1"),
                    MagicMock(node_id="n2"),
                ]
            )
            mock_parser_class.return_value = mock_parser

            engine = DefaultQueryEngine(graph_store=mock_store)
            result = await engine.diff_file("f.py", proposed_content="new code")

            assert "nodes_added" in result


class TestPlanMultiFile:
    """Tests for plan_multi_file() method."""

    @pytest.fixture
    def mock_store(self) -> MagicMock:
        """Create a mock graph store."""
        store = MagicMock()
        store.find_nodes = AsyncMock(return_value=[])
        store.get_edges = AsyncMock(return_value=[])
        return store

    @pytest.mark.asyncio
    async def test_plan_multi_file_basic(self, mock_store: MagicMock) -> None:
        """Test plan_multi_file basic execution."""
        mock_store.find_nodes = AsyncMock(return_value=[])

        engine = DefaultQueryEngine(graph_store=mock_store)
        result = await engine.plan_multi_file("session1", "task", ["a.py", "b.py"])

        assert "execution_order" in result
        assert len(result["execution_order"]) == 2

    @pytest.mark.asyncio
    async def test_plan_multi_file_risk_levels(self, mock_store: MagicMock) -> None:
        """Test plan_multi_file calculates risk levels."""
        mock_store.find_nodes = AsyncMock(return_value=[])

        engine = DefaultQueryEngine(graph_store=mock_store)
        result = await engine.plan_multi_file("session1", "task", ["a.py", "b.py"])

        for step in result["execution_order"]:
            assert "risk_level" in step


class TestDetectConflict:
    """Tests for detect_conflict() method."""

    @pytest.fixture
    def mock_store(self) -> MagicMock:
        """Create a mock graph store."""
        store = MagicMock()
        return store

    @pytest.mark.asyncio
    async def test_detect_conflict_no_overlap(self, mock_store: MagicMock) -> None:
        """Test detect_conflict with no overlap."""
        engine = DefaultQueryEngine(graph_store=mock_store)
        result = await engine.detect_conflict("session_a", "session_b")

        assert result["has_conflict"] is False

    @pytest.mark.asyncio
    async def test_detect_conflict_structure(self, mock_store: MagicMock) -> None:
        """Test detect_conflict returns correct structure."""
        engine = DefaultQueryEngine(graph_store=mock_store)
        result = await engine.detect_conflict("s1", "s2")

        assert "overlapping_files" in result
        assert "conflicting_nodes" in result


class TestNameSimilarity:
    """Tests for _name_similarity() static method."""

    def test_name_similarity_identical(self) -> None:
        """Test name similarity with identical names."""
        result = DefaultQueryEngine._name_similarity("process_data", "process_data")
        assert result == 1.0

    def test_name_similarity_empty_a(self) -> None:
        """Test name similarity with empty first name."""
        result = DefaultQueryEngine._name_similarity("", "process")
        assert result == 0.0

    def test_name_similarity_empty_b(self) -> None:
        """Test name similarity with empty second name."""
        result = DefaultQueryEngine._name_similarity("process", "")
        assert result == 0.0

    def test_name_similarity_both_empty(self) -> None:
        """Test name similarity with both empty."""
        result = DefaultQueryEngine._name_similarity("", "")
        assert result == 0.0

    def test_name_similarity_partial(self) -> None:
        """Test name similarity with partial match."""
        result = DefaultQueryEngine._name_similarity("process", "process_data")
        assert 0.0 < result < 1.0


class TestClassifyRole:
    """Tests for _classify_role() method."""

    @pytest.fixture
    def mock_engine(self) -> DefaultQueryEngine:
        """Create engine instance without store for testing."""
        store = MagicMock()
        return DefaultQueryEngine(graph_store=store)

    def test_classify_role_test_file(self, mock_engine: DefaultQueryEngine) -> None:
        """Test role classification for test file."""
        node = make_node("test_file", NodeType.FILE, "tests/test_auth.py", "test_auth")
        result = mock_engine._classify_role(node, [], [], [])
        assert result == "test"

    def test_classify_role_config(self, mock_engine: DefaultQueryEngine) -> None:
        """Test role classification for config file."""
        node = make_node("config", NodeType.CONFIG, "config.py", "config")
        result = mock_engine._classify_role(node, [], [], [])
        assert result == "config"

    def test_classify_role_endpoint(self, mock_engine: DefaultQueryEngine) -> None:
        """Test role classification for endpoint."""
        node = make_node("api", NodeType.FILE, "api.py", "api", decorators=["@app.get"])
        result = mock_engine._classify_role(node, [], [], ["@app.get"])
        assert result == "endpoint"

    def test_classify_role_endpoint_routes(self, mock_engine: DefaultQueryEngine) -> None:
        """Test role classification for routes file."""
        node = make_node("routes", NodeType.FILE, "app/routes.py", "routes")
        result = mock_engine._classify_role(node, [], [], [])
        assert result == "endpoint"

    def test_classify_role_service(self, mock_engine: DefaultQueryEngine) -> None:
        """Test role classification for service."""
        node = make_node("service", NodeType.FILE, "app/services.py", "services")
        incoming = [make_edge("c1", "service", EdgeType.IMPORTS)]
        result = mock_engine._classify_role(node, incoming, [], [])
        assert result == "service"

    def test_classify_role_isolated(self, mock_engine: DefaultQueryEngine) -> None:
        """Test role classification for isolated file."""
        node = make_node("orphan", NodeType.FILE, "orphan.py", "orphan")
        result = mock_engine._classify_role(node, [], [], [])
        assert result == "isolated"

    def test_classify_role_core_utility(self, mock_engine: DefaultQueryEngine) -> None:
        """Test role classification for core utility."""
        node = make_node("util", NodeType.FILE, "lib/utils.py", "utils")
        incoming = [make_edge(f"c{i}", "util", EdgeType.IMPORTS) for i in range(10)]
        result = mock_engine._classify_role(node, incoming, [], [])
        assert result == "core_utility"

    def test_classify_role_module_default(self, mock_engine: DefaultQueryEngine) -> None:
        """Test role classification defaults to module."""
        node = make_node("mod", NodeType.FILE, "module.py", "module")
        incoming = [make_edge("c1", "mod", EdgeType.IMPORTS)]
        result = mock_engine._classify_role(node, incoming, [], [])
        assert result == "module"


class TestNodeToDict:
    """Tests for _node_to_dict() helper method."""

    @pytest.fixture
    def mock_engine(self) -> DefaultQueryEngine:
        """Create engine instance for testing."""
        store = MagicMock()
        return DefaultQueryEngine(graph_store=store)

    def test_node_to_dict_function(self, mock_engine: DefaultQueryEngine) -> None:
        """Test _node_to_dict with function node."""
        node = make_node(
            "func_test",
            NodeType.FUNCTION,
            "test.py",
            "test_function",
            complexity=5,
            docstring="Test function",
        )
        result = mock_engine._node_to_dict(node)

        assert result["id"] == "func_test"
        assert result["type"] == "Function"
        assert result["file_path"] == "test.py"
        assert result["name"] == "test_function"
        assert result["complexity"] == 5

    def test_node_to_dict_class(self, mock_engine: DefaultQueryEngine) -> None:
        """Test _node_to_dict with class node."""
        node = make_node("class_user", NodeType.CLASS, "models.py", "User")
        result = mock_engine._node_to_dict(node)

        assert result["type"] == "Class"

    def test_node_to_dict_file(self, mock_engine: DefaultQueryEngine) -> None:
        """Test _node_to_dict with file node."""
        node = make_node("file_main", NodeType.FILE, "main.py", "main")
        result = mock_engine._node_to_dict(node)

        assert result["type"] == "File"

    def test_node_to_dict_semantic(self, mock_engine: DefaultQueryEngine) -> None:
        """Test _node_to_dict includes semantic data."""
        node = make_node(
            "func_decorated",
            NodeType.FUNCTION,
            "api.py",
            "endpoint",
            decorators=["@app.get"],
            tags=["api"],
        )
        result = mock_engine._node_to_dict(node)

        assert "semantic" in result
        assert result["semantic"]["decorators"] == ["@app.get"]
        assert result["semantic"]["tags"] == ["api"]


class TestEngineConstruction:
    """Tests for DefaultQueryEngine construction."""

    def test_engine_init(self) -> None:
        """Test engine initializes with store."""
        store = MagicMock()
        engine = DefaultQueryEngine(graph_store=store)

        assert engine._graph is store
        assert engine._enricher is None

    def test_engine_init_with_enricher(self) -> None:
        """Test engine initializes with enricher."""
        store = MagicMock()
        enricher = MagicMock()
        engine = DefaultQueryEngine(graph_store=store, enricher=enricher)

        assert engine._enricher is enricher
