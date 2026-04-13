"""Integration tests for Query Engine components — SMP(3).

Tests DefaultQueryEngine, SeedWalkEngine, and ChromaVectorStore.
"""

from __future__ import annotations

from typing import Any

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
from smp.engine.seed_walk import SeedWalkEngine, _simple_hash_embedding

try:
    from smp.store.chroma_store import ChromaVectorStore

    CHROMA_AVAILABLE = True
except Exception:
    CHROMA_AVAILABLE = False
    ChromaVectorStore = None


def make_node(
    id: str = "func_login",
    type: NodeType = NodeType.FUNCTION,
    name: str = "login",
    file_path: str = "src/auth/login.py",
    start_line: int = 10,
    end_line: int = 25,
    docstring: str = "",
    signature: str = "",
    tags: list[str] | None = None,
) -> GraphNode:
    if signature is None:
        signature = f"def {name}():"
    return GraphNode(
        id=id,
        type=type,
        file_path=file_path,
        structural=StructuralProperties(
            name=name,
            file=file_path,
            signature=signature or f"def {name}():",
            start_line=start_line,
            end_line=end_line,
            lines=end_line - start_line + 1,
        ),
        semantic=SemanticProperties(
            docstring=docstring,
            status="enriched" if docstring else "no_metadata",
            tags=tags or [],
        ),
    )


class MockGraphStore:
    """In-memory graph store for testing without Neo4j."""

    def __init__(self) -> None:
        self._nodes: dict[str, GraphNode] = {}
        self._edges: list[GraphEdge] = []

    async def connect(self) -> None:
        pass

    async def close(self) -> None:
        pass

    async def clear(self) -> None:
        self._nodes.clear()
        self._edges.clear()

    async def upsert_node(self, node: GraphNode) -> None:
        self._nodes[node.id] = node

    async def upsert_nodes(self, nodes: list[GraphNode]) -> None:
        for node in nodes:
            self._nodes[node.id] = node

    async def upsert_edge(self, edge: GraphEdge) -> None:
        self._edges.append(edge)

    async def upsert_edges(self, edges: list[GraphEdge]) -> None:
        self._edges.extend(edges)

    async def get_node(self, node_id: str) -> GraphNode | None:
        return self._nodes.get(node_id)

    async def delete_node(self, node_id: str) -> bool:
        if node_id in self._nodes:
            del self._nodes[node_id]
            self._edges = [e for e in self._edges if e.source_id != node_id and e.target_id != node_id]
            return True
        return False

    async def delete_nodes_by_file(self, file_path: str) -> int:
        nodes_to_delete = [nid for nid, n in self._nodes.items() if n.file_path == file_path]
        for nid in nodes_to_delete:
            await self.delete_node(nid)
        return len(nodes_to_delete)

    async def get_edges(
        self,
        node_id: str,
        edge_type: EdgeType | None = None,
        direction: str = "both",
    ) -> list[GraphEdge]:
        result: list[GraphEdge] = []
        for e in self._edges:
            if e.source_id == node_id and direction in ("outgoing", "both"):
                if edge_type is None or e.type == edge_type:
                    result.append(e)
            if e.target_id == node_id and direction in ("incoming", "both"):
                if edge_type is None or e.type == edge_type:
                    result.append(e)
        return result

    async def get_neighbors(
        self,
        node_id: str,
        edge_type: EdgeType | None = None,
        depth: int = 1,
    ) -> list[GraphNode]:
        visited: set[str] = set()
        queue: list[tuple[str, int]] = [(node_id, 0)]
        while queue:
            current, d = queue.pop(0)
            if d >= depth or current in visited:
                continue
            visited.add(current)
            edges = await self.get_edges(current, edge_type, "both")
            for e in edges:
                if e.source_id == current and e.target_id not in visited:
                    if e.target_id in self._nodes:
                        queue.append((e.target_id, d + 1))
                if e.target_id == current and e.source_id not in visited:
                    if e.source_id in self._nodes:
                        queue.append((e.source_id, d + 1))
        return [self._nodes[nid] for nid in visited if nid in self._nodes]

    async def traverse(
        self,
        start_id: str,
        edge_type: EdgeType,
        depth: int,
        max_nodes: int = 100,
        direction: str = "outgoing",
    ) -> list[GraphNode]:
        visited: dict[str, GraphNode] = {}
        queue: list[tuple[str, int]] = [(start_id, 0)]
        while queue and len(visited) < max_nodes:
            current, d = queue.pop(0)
            if d >= depth or current in visited:
                continue
            if current in self._nodes:
                visited[current] = self._nodes[current]
            edges = await self.get_edges(current, edge_type, direction)
            for e in edges:
                neighbor = e.target_id if e.source_id == current else e.source_id
                if neighbor not in visited and d + 1 <= depth:
                    queue.append((neighbor, d + 1))
        return list(visited.values())

    async def find_nodes(
        self,
        type: NodeType | None = None,
        file_path: str | None = None,
        name: str | None = None,
    ) -> list[GraphNode]:
        results = list(self._nodes.values())
        if type is not None:
            results = [n for n in results if n.type == type]
        if file_path is not None:
            results = [n for n in results if n.file_path == file_path]
        if name is not None:
            results = [n for n in results if name in n.id or n.structural.name == name or name in n.structural.name]
        return results

    async def count_nodes(self) -> int:
        return len(self._nodes)

    async def count_edges(self) -> int:
        return len(self._edges)

    async def search_nodes(
        self,
        query_terms: list[str],
        match: str = "any",
        node_types: list[str] | None = None,
        tags: list[str] | None = None,
        scope: str | None = None,
        top_k: int = 5,
    ) -> list[dict[str, Any]]:
        results: list[dict[str, Any]] = []
        for node in self._nodes.values():
            if node_types and node.type.value not in node_types:
                continue
            matched = False
            doc_lower = (node.semantic.docstring or "").lower()
            for term in query_terms:
                if term.lower() in doc_lower:
                    matched = True
                    break
            if matched:
                results.append(
                    {
                        "id": node.id,
                        "name": node.structural.name,
                        "file_path": node.file_path,
                        "type": node.type.value,
                        "docstring": node.semantic.docstring,
                    }
                )
        return results[:top_k]


class MockVectorStore:
    """In-memory vector store for testing."""

    def __init__(self) -> None:
        self._data: dict[str, dict[str, Any]] = {}

    async def connect(self) -> None:
        pass

    async def close(self) -> None:
        pass

    async def clear(self) -> None:
        self._data.clear()

    async def upsert(
        self,
        ids: list[str],
        embeddings: list[list[float]],
        metadatas: list[dict[str, Any]],
        documents: list[str] | None = None,
    ) -> None:
        for i, id_val in enumerate(ids):
            self._data[id_val] = {
                "embedding": embeddings[i] if i < len(embeddings) else [],
                "metadata": metadatas[i] if i < len(metadatas) else {},
                "document": documents[i] if documents and i < len(documents) else "",
            }

    async def query(
        self,
        embedding: list[float],
        top_k: int = 5,
        where: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        results: list[tuple[float, dict[str, Any]]] = []
        for id_val, data in self._data.items():
            if where:
                meta = data.get("metadata", {})
                match = all(meta.get(k) == v for k, v in where.items() if not isinstance(v, dict))
                if not match:
                    continue
            dist = sum((a - b) ** 2 for a, b in zip(embedding, data.get("embedding", []))) ** 0.5
            results.append(
                (
                    dist,
                    {
                        "id": id_val,
                        "score": dist,
                        "metadata": data.get("metadata", {}),
                        "document": data.get("document", ""),
                    },
                )
            )
        results.sort(key=lambda x: x[0])
        return [r[1] for r in results[:top_k]]

    async def get(self, ids: list[str]) -> list[dict[str, Any] | None]:
        return [self._data.get(id_val) for id_val in ids]

    async def delete(self, ids: list[str]) -> int:
        count = 0
        for id_val in ids:
            if id_val in self._data:
                del self._data[id_val]
                count += 1
        return count

    async def delete_by_file(self, file_path: str) -> int:
        to_delete = [
            id_val for id_val, data in self._data.items() if data.get("metadata", {}).get("file_path") == file_path
        ]
        for id_val in to_delete:
            del self._data[id_val]
        return len(to_delete)


async def seed_mock_graph(graph: MockGraphStore) -> None:
    """Seed a small graph for testing."""
    nodes = [
        make_node("file.py::File::file.py::1", NodeType.FILE, "file.py", "file.py", 1, 30),
        make_node("file.py::File::os::2", NodeType.FILE, "os", "file.py", 2, 2, signature="import os"),
        make_node("file.py::Function::func_a::4", NodeType.FUNCTION, "func_a", "file.py", 4, 8),
        make_node(
            "file.py::Function::func_b::10", NodeType.FUNCTION, "func_b", "file.py", 10, 14, docstring="Does B things."
        ),
        make_node("file.py::Function::func_c::16", NodeType.FUNCTION, "func_c", "file.py", 16, 20),
        make_node("file.py::Class::Service::22", NodeType.CLASS, "Service", "file.py", 22, 28),
        make_node("file.py::Function::method::23", NodeType.FUNCTION, "method", "file.py", 23, 25),
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
# DefaultQueryEngine Tests
# ---------------------------------------------------------------------------


class TestDefaultQueryEngineNavigate:
    """Tests for DefaultQueryEngine.navigate()."""

    @pytest.mark.asyncio
    async def test_navigate_returns_dict(self) -> None:
        graph = MockGraphStore()
        await seed_mock_graph(graph)
        engine = DefaultQueryEngine(graph)
        result = await engine.navigate("func_a")
        assert isinstance(result, dict)

    @pytest.mark.asyncio
    async def test_navigate_entity_structure(self) -> None:
        graph = MockGraphStore()
        await seed_mock_graph(graph)
        engine = DefaultQueryEngine(graph)
        result = await engine.navigate("func_a")
        assert "entity" in result
        entity = result["entity"]
        assert "id" in entity
        assert "type" in entity
        assert "name" in entity
        assert entity["name"] == "func_a"

    @pytest.mark.asyncio
    async def test_navigate_with_relationships(self) -> None:
        graph = MockGraphStore()
        await seed_mock_graph(graph)
        engine = DefaultQueryEngine(graph)
        result = await engine.navigate("func_a", include_relationships=True)
        assert "relationships" in result
        rels = result["relationships"]
        assert "calls" in rels
        assert "called_by" in rels
        assert "depends_on" in rels
        assert "imported_by" in rels

    @pytest.mark.asyncio
    async def test_navigate_missing_node(self) -> None:
        graph = MockGraphStore()
        await seed_mock_graph(graph)
        engine = DefaultQueryEngine(graph)
        result = await engine.navigate("nonexistent_node")
        assert "error" in result


class TestDefaultQueryEngineTrace:
    """Tests for DefaultQueryEngine.trace()."""

    @pytest.mark.asyncio
    async def test_trace_returns_list(self) -> None:
        graph = MockGraphStore()
        await seed_mock_graph(graph)
        engine = DefaultQueryEngine(graph)
        result = await engine.trace("func_a", "CALLS", depth=2)
        assert isinstance(result, list)

    @pytest.mark.asyncio
    async def test_trace_nodes_have_dict_structure(self) -> None:
        graph = MockGraphStore()
        await seed_mock_graph(graph)
        engine = DefaultQueryEngine(graph)
        result = await engine.trace("func_a", "CALLS", depth=2)
        for node in result:
            assert isinstance(node, dict)
            assert "id" in node
            assert "type" in node
            assert "name" in node

    @pytest.mark.asyncio
    async def test_trace_finds_call_chain(self) -> None:
        graph = MockGraphStore()
        await seed_mock_graph(graph)
        engine = DefaultQueryEngine(graph)
        result = await engine.trace("file.py::Function::func_a::4", "CALLS", depth=3)
        names = {n["name"] for n in result}
        assert "func_b" in names
        assert "func_c" in names


class TestDefaultQueryEngineGetContext:
    """Tests for DefaultQueryEngine.get_context()."""

    @pytest.mark.asyncio
    async def test_get_context_returns_rich_structure(self) -> None:
        graph = MockGraphStore()
        await seed_mock_graph(graph)
        engine = DefaultQueryEngine(graph)
        result = await engine.get_context("file.py")
        assert isinstance(result, dict)
        assert "self" in result
        assert "imports" in result
        assert "imported_by" in result
        assert "defines" in result
        assert "related_patterns" in result
        assert "entry_points" in result
        assert "data_flow_in" in result
        assert "data_flow_out" in result
        assert "summary" in result

    @pytest.mark.asyncio
    async def test_get_context_self_contains_node_info(self) -> None:
        graph = MockGraphStore()
        await seed_mock_graph(graph)
        engine = DefaultQueryEngine(graph)
        result = await engine.get_context("file.py")
        self_node = result["self"]
        assert "name" in self_node
        assert "file_path" in self_node

    @pytest.mark.asyncio
    async def test_get_context_summary_has_expected_fields(self) -> None:
        graph = MockGraphStore()
        await seed_mock_graph(graph)
        engine = DefaultQueryEngine(graph)
        result = await engine.get_context("file.py")
        summary = result["summary"]
        assert "role" in summary
        assert "blast_radius" in summary
        assert "avg_complexity" in summary
        assert "max_complexity" in summary
        assert "risk_level" in summary

    @pytest.mark.asyncio
    async def test_get_context_missing_file(self) -> None:
        graph = MockGraphStore()
        await seed_mock_graph(graph)
        engine = DefaultQueryEngine(graph)
        result = await engine.get_context("nonexistent.py")
        assert "error" in result


class TestDefaultQueryEngineAssessImpact:
    """Tests for DefaultQueryEngine.assess_impact()."""

    @pytest.mark.asyncio
    async def test_assess_impact_returns_dict(self) -> None:
        graph = MockGraphStore()
        await seed_mock_graph(graph)
        engine = DefaultQueryEngine(graph)
        result = await engine.assess_impact("func_b")
        assert isinstance(result, dict)

    @pytest.mark.asyncio
    async def test_assess_impact_has_expected_fields(self) -> None:
        graph = MockGraphStore()
        await seed_mock_graph(graph)
        engine = DefaultQueryEngine(graph)
        result = await engine.assess_impact("func_b")
        assert "affected_files" in result
        assert "affected_functions" in result
        assert "severity" in result
        assert "recommendations" in result

    @pytest.mark.asyncio
    async def test_assess_impact_severity_levels(self) -> None:
        graph = MockGraphStore()
        await seed_mock_graph(graph)
        engine = DefaultQueryEngine(graph)
        result = await engine.assess_impact("func_c")
        assert result["severity"] in ("low", "medium", "high")

    @pytest.mark.asyncio
    async def test_assess_impact_missing_node(self) -> None:
        graph = MockGraphStore()
        await seed_mock_graph(graph)
        engine = DefaultQueryEngine(graph)
        result = await engine.assess_impact("nonexistent_node")
        assert "error" in result


class TestDefaultQueryEngineFindFlow:
    """Tests for DefaultQueryEngine.find_flow()."""

    @pytest.mark.asyncio
    async def test_find_flow_returns_dict(self) -> None:
        graph = MockGraphStore()
        await seed_mock_graph(graph)
        engine = DefaultQueryEngine(graph)
        result = await engine.find_flow("func_a", "func_c")
        assert isinstance(result, dict)

    @pytest.mark.asyncio
    async def test_find_flow_has_expected_fields(self) -> None:
        graph = MockGraphStore()
        await seed_mock_graph(graph)
        engine = DefaultQueryEngine(graph)
        result = await engine.find_flow("func_a", "func_c")
        assert "path" in result
        assert "data_transformations" in result

    @pytest.mark.asyncio
    async def test_find_flow_same_node(self) -> None:
        graph = MockGraphStore()
        await seed_mock_graph(graph)
        engine = DefaultQueryEngine(graph)
        result = await engine.find_flow("func_a", "func_a")
        assert len(result["path"]) == 1
        assert result["path"][0]["node"] == "func_a"

    @pytest.mark.asyncio
    async def test_find_flow_direct_path(self) -> None:
        graph = MockGraphStore()
        await seed_mock_graph(graph)
        engine = DefaultQueryEngine(graph)
        result = await engine.find_flow("file.py::Function::func_a::4", "file.py::Function::func_b::10")
        path_names = [n["node"] for n in result["path"]]
        assert "func_a" in path_names
        assert "func_b" in path_names

    @pytest.mark.asyncio
    async def test_find_flow_no_path(self) -> None:
        graph = MockGraphStore()
        await seed_mock_graph(graph)
        engine = DefaultQueryEngine(graph)
        result = await engine.find_flow("func_c", "func_a")
        assert result["path"] == []


# ---------------------------------------------------------------------------
# SeedWalkEngine Tests
# ---------------------------------------------------------------------------


class TestSeedWalkEngineInit:
    """Tests for SeedWalkEngine initialization."""

    @pytest.mark.asyncio
    async def test_init_with_mock_stores(self) -> None:
        graph = MockGraphStore()
        vector = MockVectorStore()
        engine = SeedWalkEngine(graph, vector)
        assert engine._graph is graph
        assert engine._vector is vector
        assert engine._alpha == 0.50
        assert engine._beta == 0.30
        assert engine._gamma == 0.20

    @pytest.mark.asyncio
    async def test_init_with_custom_weights(self) -> None:
        graph = MockGraphStore()
        vector = MockVectorStore()
        engine = SeedWalkEngine(graph, vector, alpha=0.6, beta=0.3, gamma=0.1)
        assert engine._alpha == 0.6
        assert engine._beta == 0.3
        assert engine._gamma == 0.1


class TestSimpleHashEmbedding:
    """Tests for _simple_hash_embedding function."""

    def test_hash_embedding_returns_list(self) -> None:
        result = _simple_hash_embedding("test query")
        assert isinstance(result, list)

    def test_hash_embedding_dimensions(self) -> None:
        result = _simple_hash_embedding("test query", dim=256)
        assert len(result) == 256

    def test_hash_embedding_consistent(self) -> None:
        result1 = _simple_hash_embedding("test query")
        result2 = _simple_hash_embedding("test query")
        assert result1 == result2

    def test_hash_embedding_different_inputs_different_vectors(self) -> None:
        result1 = _simple_hash_embedding("query a")
        result2 = _simple_hash_embedding("query b")
        assert result1 != result2

    def test_hash_embedding_normalized(self) -> None:
        result = _simple_hash_embedding("test query")
        norm = sum(v * v for v in result) ** 0.5
        assert abs(norm - 1.0) < 0.0001 or norm == 0.0

    def test_hash_embedding_empty_string(self) -> None:
        result = _simple_hash_embedding("")
        assert len(result) == 128
        assert all(v == 0.0 for v in result)


class TestSeedWalkEngineLocate:
    """Tests for SeedWalkEngine.locate()."""

    @pytest.mark.asyncio
    async def test_locate_returns_list(self) -> None:
        graph = MockGraphStore()
        vector = MockVectorStore()
        await seed_mock_graph(graph)
        engine = SeedWalkEngine(graph, vector)
        result = await engine.locate("func_b")
        assert isinstance(result, list)

    @pytest.mark.asyncio
    async def test_locate_returns_correct_response_structure(self) -> None:
        graph = MockGraphStore()
        vector = MockVectorStore()
        await seed_mock_graph(graph)
        engine = SeedWalkEngine(graph, vector)
        result = await engine.locate("func")
        assert len(result) > 0
        response = result[0]
        assert "query" in response
        assert "routed_community" in response
        assert "seed_count" in response
        assert "total_walked" in response
        assert "results" in response
        assert "structural_map" in response

    @pytest.mark.asyncio
    async def test_locate_results_have_expected_fields(self) -> None:
        graph = MockGraphStore()
        vector = MockVectorStore()
        await seed_mock_graph(graph)
        engine = SeedWalkEngine(graph, vector)
        result = await engine.locate("func_b")
        assert len(result) > 0
        response = result[0]
        for item in response.get("results", []):
            assert hasattr(item, "node_id") or "node_id" in item
            assert hasattr(item, "node_type") or "node_type" in item
            assert hasattr(item, "name") or "name" in item
            assert hasattr(item, "file") or "file" in item
            assert hasattr(item, "final_score") or "final_score" in item

    @pytest.mark.asyncio
    async def test_locate_with_no_vector_store(self) -> None:
        graph = MockGraphStore()
        await seed_mock_graph(graph)
        engine = SeedWalkEngine(graph, None)
        result = await engine.locate("func_a")
        assert isinstance(result, list)
        assert len(result) > 0


# ---------------------------------------------------------------------------
# ChromaVectorStore Tests
# ---------------------------------------------------------------------------


@pytest.mark.skipif(not CHROMA_AVAILABLE, reason="ChromaDB not available (sqlite3 version)")
class TestChromaVectorStore:
    """Tests for ChromaVectorStore with in-memory ChromaDB."""

    @pytest.fixture
    async def chroma_store(self) -> ChromaVectorStore:
        store = ChromaVectorStore(collection_name="test_collection")
        await store.connect()
        yield store
        await store.clear()
        await store.close()

    @pytest.mark.asyncio
    async def test_upsert_and_query(self, chroma_store: ChromaVectorStore) -> None:
        await chroma_store.upsert(
            ids=["node1", "node2"],
            embeddings=[[0.1, 0.2, 0.3], [0.4, 0.5, 0.6]],
            metadatas=[{"file_path": "a.py", "type": "function"}, {"file_path": "b.py", "type": "class"}],
            documents=["doc1", "doc2"],
        )
        results = await chroma_store.query(embedding=[0.1, 0.2, 0.3], top_k=2)
        assert len(results) >= 1
        ids_found = {r["id"] for r in results}
        assert "node1" in ids_found

    @pytest.mark.asyncio
    async def test_query_with_filter(self, chroma_store: ChromaVectorStore) -> None:
        await chroma_store.upsert(
            ids=["node1", "node2"],
            embeddings=[[0.1, 0.2, 0.3], [0.4, 0.5, 0.6]],
            metadatas=[{"file_path": "a.py", "type": "function"}, {"file_path": "b.py", "type": "class"}],
            documents=["doc1", "doc2"],
        )
        results = await chroma_store.query(
            embedding=[0.1, 0.2, 0.3],
            top_k=5,
            where={"type": "function"},
        )
        assert len(results) >= 1
        assert results[0]["metadata"]["type"] == "function"

    @pytest.mark.asyncio
    async def test_delete(self, chroma_store: ChromaVectorStore) -> None:
        await chroma_store.upsert(
            ids=["node1", "node2"],
            embeddings=[[0.1, 0.2, 0.3], [0.4, 0.5, 0.6]],
            metadatas=[{"file_path": "a.py"}, {"file_path": "b.py"}],
        )
        deleted = await chroma_store.delete(ids=["node1"])
        assert deleted == 1
        results = await chroma_store.query(embedding=[0.1, 0.2, 0.3], top_k=5)
        ids_found = {r["id"] for r in results}
        assert "node1" not in ids_found

    @pytest.mark.asyncio
    async def test_get_by_ids(self, chroma_store: ChromaVectorStore) -> None:
        await chroma_store.upsert(
            ids=["node1", "node2"],
            embeddings=[[0.1, 0.2, 0.3], [0.4, 0.5, 0.6]],
            metadatas=[{"file_path": "a.py"}, {"file_path": "b.py"}],
        )
        results = await chroma_store.get(ids=["node1", "node2"])
        assert len(results) == 2
        assert results[0]["id"] == "node1"
        assert results[1]["id"] == "node2"

    @pytest.mark.asyncio
    async def test_clear(self, chroma_store: ChromaVectorStore) -> None:
        await chroma_store.upsert(
            ids=["node1"],
            embeddings=[[0.1, 0.2, 0.3]],
            metadatas=[{"file_path": "a.py"}],
        )
        await chroma_store.clear()
        results = await chroma_store.query(embedding=[0.1, 0.2, 0.3], top_k=5)
        assert len(results) == 0


# ---------------------------------------------------------------------------
# Integration Tests
# ---------------------------------------------------------------------------


class TestQueryEngineIntegration:
    """Integration tests combining QueryEngine with mock stores."""

    @pytest.mark.asyncio
    async def test_navigate_and_trace_work_together(self) -> None:
        graph = MockGraphStore()
        await seed_mock_graph(graph)
        engine = DefaultQueryEngine(graph)

        nav_result = await engine.navigate("file.py::Function::func_a::4")
        assert "entity" in nav_result

        trace_result = await engine.trace("file.py::Function::func_a::4", depth=3)
        assert len(trace_result) > 0

    @pytest.mark.asyncio
    async def test_locate_across_engines(self) -> None:
        graph = MockGraphStore()
        vector = MockVectorStore()
        await seed_mock_graph(graph)

        default_engine = DefaultQueryEngine(graph)
        seed_engine = SeedWalkEngine(graph, vector)

        default_result = await default_engine.locate("func_b")
        assert len(default_result) > 0

        seed_result = await seed_engine.locate("func_b")
        assert isinstance(seed_result, list)
