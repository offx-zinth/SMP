"""Integration tests for CommunityDetector."""

from __future__ import annotations

from collections import defaultdict
from typing import Any

from smp.core.models import EdgeType, GraphEdge, GraphNode, NodeType, SemanticProperties, StructuralProperties
from smp.engine.community import CommunityDetector


class MockGraphStore:
    """Mock GraphStore for testing."""

    def __init__(self) -> None:
        self._nodes: dict[str, GraphNode] = {}
        self._edges: list[GraphEdge] = []
        self._edge_index: dict[str, list[GraphEdge]] = defaultdict(list)

    async def connect(self) -> None:
        pass

    async def close(self) -> None:
        pass

    async def clear(self) -> None:
        self._nodes.clear()
        self._edges.clear()
        self._edge_index.clear()

    async def upsert_node(self, node: GraphNode) -> None:
        self._nodes[node.id] = node

    async def upsert_nodes(self, nodes: list[GraphNode]) -> None:
        for node in nodes:
            self._nodes[node.id] = node

    async def get_node(self, node_id: str) -> GraphNode | None:
        return self._nodes.get(node_id)

    async def delete_node(self, node_id: str) -> bool:
        if node_id in self._nodes:
            del self._nodes[node_id]
            return True
        return False

    async def delete_nodes_by_file(self, file_path: str) -> int:
        nodes_to_delete = [nid for nid, n in self._nodes.items() if n.file_path == file_path]
        for nid in nodes_to_delete:
            del self._nodes[nid]
        return len(nodes_to_delete)

    async def upsert_edge(self, edge: GraphEdge) -> None:
        self._edges.append(edge)
        self._edge_index[edge.source_id].append(edge)

    async def upsert_edges(self, edges: list[GraphEdge]) -> None:
        for edge in edges:
            self._edges.append(edge)
            self._edge_index[edge.source_id].append(edge)

    async def get_edges(
        self,
        node_id: str,
        edge_type: EdgeType | None = None,
        direction: str = "both",
    ) -> list[GraphEdge]:
        result = []
        for edge in self._edge_index.get(node_id, []):
            if edge_type is None or edge.type == edge_type:
                result.append(edge)
        if direction == "incoming":
            incoming = [e for e in self._edges if e.target_id == node_id]
            result.extend(incoming)
        return result

    async def get_neighbors(
        self,
        node_id: str,
        edge_type: EdgeType | None = None,
        depth: int = 1,
    ) -> list[GraphNode]:
        neighbor_ids = set()
        current = {node_id}
        for _ in range(depth):
            next_current = set()
            for nid in current:
                for edge in self._edge_index.get(nid, []):
                    neighbor_ids.add(edge.target_id)
                    next_current.add(edge.target_id)
            current = next_current
        return [self._nodes[nid] for nid in neighbor_ids if nid in self._nodes]

    async def traverse(
        self,
        start_id: str,
        edge_type: EdgeType,
        depth: int,
        max_nodes: int = 100,
        direction: str = "outgoing",
    ) -> list[GraphNode]:
        return await self.get_neighbors(start_id, edge_type, depth)

    async def find_nodes(
        self,
        *,
        type: NodeType | None = None,
        file_path: str | None = None,
        name: str | None = None,
    ) -> list[GraphNode]:
        result = list(self._nodes.values())
        if type is not None:
            result = [n for n in result if n.type == type]
        if file_path is not None:
            result = [n for n in result if n.file_path == file_path]
        if name is not None:
            result = [n for n in result if n.structural.name == name]
        return result

    async def count_nodes(self) -> int:
        return len(self._nodes)

    async def count_edges(self) -> int:
        return len(self._edges)


class MockVectorStore:
    """Mock VectorStore for testing."""

    def __init__(self) -> None:
        self._embeddings: dict[str, list[float]] = {}
        self._metadata: dict[str, dict[str, Any]] = {}
        self._documents: dict[str, str] = {}

    async def connect(self) -> None:
        pass

    async def close(self) -> None:
        pass

    async def clear(self) -> None:
        self._embeddings.clear()
        self._metadata.clear()
        self._documents.clear()

    async def upsert(
        self,
        ids: list[str],
        embeddings: list[list[float]],
        metadatas: list[dict[str, Any]],
        documents: list[str] | None = None,
    ) -> None:
        for i, id_ in enumerate(ids):
            self._embeddings[id_] = embeddings[i]
            self._metadata[id_] = metadatas[i]
            if documents:
                self._documents[id_] = documents[i]

    async def add_code_embedding(
        self,
        node_id: str,
        embedding: list[float],
        metadata: dict[str, Any],
        document: str,
    ) -> None:
        self._embeddings[node_id] = embedding
        self._metadata[node_id] = metadata
        self._documents[node_id] = document

    async def query(
        self,
        embedding: list[float],
        top_k: int = 5,
        where: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        return []

    async def get(self, ids: list[str]) -> list[dict[str, Any] | None]:
        return [None] * len(ids)

    async def delete(self, ids: list[str]) -> int:
        count = 0
        for id_ in ids:
            if id_ in self._embeddings:
                del self._embeddings[id_]
                del self._metadata[id_]
                del self._documents[id_]
                count += 1
        return count

    async def delete_by_file(self, file_path: str) -> int:
        return 0


def make_community_node(
    id: str,
    type: NodeType = NodeType.FUNCTION,
    file_path: str = "src/module/file.py",
    name: str = "test_func",
    tags: list[str] | None = None,
) -> GraphNode:
    if tags is None:
        tags = []
    return GraphNode(
        id=id,
        type=type,
        file_path=file_path,
        structural=StructuralProperties(name=name, file=file_path),
        semantic=SemanticProperties(tags=tags),
    )


class TestCommunityDetectorInit:
    """Test CommunityDetector.__init__()."""

    async def test_init_with_graph_store_only(self) -> None:
        store = MockGraphStore()
        detector = CommunityDetector(graph_store=store)
        assert detector._graph is store
        assert detector._vector is None
        assert detector._min_size == 5
        assert detector._communities == {}

    async def test_init_with_graph_and_vector_store(self) -> None:
        graph_store = MockGraphStore()
        vector_store = MockVectorStore()
        detector = CommunityDetector(graph_store=graph_store, vector_store=vector_store, min_community_size=10)
        assert detector._graph is graph_store
        assert detector._vector is vector_store
        assert detector._min_size == 10


class TestLouvainAlgorithm:
    """Test CommunityDetector._louvain()."""

    async def test_louvain_three_cliques(self) -> None:
        store = MockGraphStore()
        await store.connect()

        clique_a_nodes = [
            make_community_node("a1", file_path="src/package_a/file1.py", name="func_a1", tags=["auth"]),
            make_community_node("a2", file_path="src/package_a/file1.py", name="func_a2", tags=["auth"]),
            make_community_node("a3", file_path="src/package_a/file2.py", name="func_a3", tags=["auth"]),
            make_community_node("a4", file_path="src/package_a/file2.py", name="func_a4", tags=["auth"]),
            make_community_node("a5", file_path="src/package_a/file3.py", name="func_a5", tags=["auth"]),
        ]
        clique_b_nodes = [
            make_community_node("b1", file_path="src/package_b/file1.py", name="func_b1", tags=["api"]),
            make_community_node("b2", file_path="src/package_b/file1.py", name="func_b2", tags=["api"]),
            make_community_node("b3", file_path="src/package_b/file2.py", name="func_b3", tags=["api"]),
            make_community_node("b4", file_path="src/package_b/file2.py", name="func_b4", tags=["api"]),
            make_community_node("b5", file_path="src/package_b/file3.py", name="func_b5", tags=["api"]),
        ]
        clique_c_nodes = [
            make_community_node("c1", file_path="src/package_c/file1.py", name="func_c1", tags=["core"]),
            make_community_node("c2", file_path="src/package_c/file1.py", name="func_c2", tags=["core"]),
            make_community_node("c3", file_path="src/package_c/file2.py", name="func_c3", tags=["core"]),
            make_community_node("c4", file_path="src/package_c/file2.py", name="func_c4", tags=["core"]),
            make_community_node("c5", file_path="src/package_c/file3.py", name="func_c5", tags=["core"]),
        ]

        all_nodes = clique_a_nodes + clique_b_nodes + clique_c_nodes
        await store.upsert_nodes(all_nodes)

        for n1, n2 in zip(clique_a_nodes, clique_a_nodes[1:], strict=False):
            await store.upsert_edge(GraphEdge(source_id=n1.id, target_id=n2.id, type=EdgeType.CALLS))
        for n1, n2 in zip(clique_b_nodes, clique_b_nodes[1:], strict=False):
            await store.upsert_edge(GraphEdge(source_id=n1.id, target_id=n2.id, type=EdgeType.CALLS))
        for n1, n2 in zip(clique_c_nodes, clique_c_nodes[1:], strict=False):
            await store.upsert_edge(GraphEdge(source_id=n1.id, target_id=n2.id, type=EdgeType.CALLS))

        await store.upsert_edge(GraphEdge(source_id="a1", target_id="b1", type=EdgeType.CALLS))
        await store.upsert_edge(GraphEdge(source_id="b3", target_id="c2", type=EdgeType.CALLS))

        detector = CommunityDetector(graph_store=store)
        nodes = await store.find_nodes()
        edge_types = [EdgeType.CALLS]
        adjacency = await detector._build_adjacency(nodes, edge_types)

        assignments = detector._louvain(nodes, adjacency, resolution=1.0)

        comm_groups: dict[str, list[str]] = defaultdict(list)
        for node_id, comm_id in assignments.items():
            comm_groups[comm_id].append(node_id)

        assert len(comm_groups) >= 3
        for group in comm_groups.values():
            assert len(group) >= 1

        for node_id in ["a1", "a2", "a3", "a4", "a5"]:
            assert node_id in assignments

        for node_id in ["b1", "b2", "b3", "b4", "b5"]:
            assert node_id in assignments

        for node_id in ["c1", "c2", "c3", "c4", "c5"]:
            assert node_id in assignments

    async def test_louvain_single_community(self) -> None:
        store = MockGraphStore()
        await store.connect()

        nodes = [
            make_community_node("n1", file_path="src/pkg/file.py", name="func1"),
            make_community_node("n2", file_path="src/pkg/file.py", name="func2"),
            make_community_node("n3", file_path="src/pkg/file.py", name="func3"),
        ]
        await store.upsert_nodes(nodes)

        await store.upsert_edge(GraphEdge(source_id="n1", target_id="n2", type=EdgeType.CALLS))
        await store.upsert_edge(GraphEdge(source_id="n2", target_id="n3", type=EdgeType.CALLS))
        await store.upsert_edge(GraphEdge(source_id="n3", target_id="n1", type=EdgeType.CALLS))

        detector = CommunityDetector(graph_store=store)
        all_nodes = await store.find_nodes()
        adjacency = await detector._build_adjacency(all_nodes, [EdgeType.CALLS])

        assignments = detector._louvain(all_nodes, adjacency, resolution=1.0)

        comm_ids = set(assignments.values())
        assert len(comm_ids) == 1

    async def test_louvain_empty_graph(self) -> None:
        store = MockGraphStore()
        detector = CommunityDetector(graph_store=store)

        assignments = detector._louvain([], {}, resolution=1.0)
        assert assignments == {}


class TestBuildCommunities:
    """Test CommunityDetector._build_communities()."""

    async def test_build_communities_labels_and_counts(self) -> None:
        store = MockGraphStore()
        await store.connect()

        nodes = [
            make_community_node("n1", file_path="src/auth/login.py", name="login", tags=["auth"]),
            make_community_node("n2", file_path="src/auth/login.py", name="validate", tags=["auth"]),
            make_community_node("n3", file_path="src/auth/logout.py", name="logout", tags=["auth"]),
        ]
        await store.upsert_nodes(nodes)

        await store.upsert_edge(GraphEdge(source_id="n1", target_id="n2", type=EdgeType.CALLS))
        await store.upsert_edge(GraphEdge(source_id="n2", target_id="n3", type=EdgeType.CALLS))
        await store.upsert_edge(GraphEdge(source_id="n3", target_id="n1", type=EdgeType.CALLS))

        detector = CommunityDetector(graph_store=store, min_community_size=1)
        all_nodes = await store.find_nodes()
        adjacency = await detector._build_adjacency(all_nodes, [EdgeType.CALLS])

        assignments = detector._louvain(all_nodes, adjacency, resolution=1.0)
        communities = detector._build_communities(assignments, all_nodes, adjacency, level=0, label="coarse")

        assert len(communities) >= 1
        for comm in communities.values():
            assert comm.label.startswith("coarse")
            assert comm.member_count >= 1
            assert comm.level == 0

    async def test_build_communities_file_count(self) -> None:
        store = MockGraphStore()
        await store.connect()

        nodes = [
            make_community_node("n1", file_path="src/auth/login.py", name="login"),
            make_community_node("n2", file_path="src/auth/login.py", name="validate"),
            make_community_node("n3", file_path="src/auth/logout.py", name="logout"),
            make_community_node("n4", file_path="src/core/util.py", name="helper"),
        ]
        await store.upsert_nodes(nodes)

        await store.upsert_edge(GraphEdge(source_id="n1", target_id="n2", type=EdgeType.CALLS))
        await store.upsert_edge(GraphEdge(source_id="n2", target_id="n3", type=EdgeType.CALLS))
        await store.upsert_edge(GraphEdge(source_id="n4", target_id="n1", type=EdgeType.CALLS))

        detector = CommunityDetector(graph_store=store, min_community_size=1)
        all_nodes = await store.find_nodes()
        adjacency = await detector._build_adjacency(all_nodes, [EdgeType.CALLS])

        assignments = detector._louvain(all_nodes, adjacency, resolution=1.0)
        communities = detector._build_communities(assignments, all_nodes, adjacency, level=0, label="test")

        for comm in communities.values():
            assert comm.file_count >= 1


class TestComputeModularity:
    """Test CommunityDetector._compute_modularity()."""

    async def test_good_partition_positive_modularity(self) -> None:
        store = MockGraphStore()
        await store.connect()

        nodes = [
            make_community_node("a1", file_path="src/pkg/file.py", name="a1"),
            make_community_node("a2", file_path="src/pkg/file.py", name="a2"),
            make_community_node("b1", file_path="src/pkg/file.py", name="b1"),
            make_community_node("b2", file_path="src/pkg/file.py", name="b2"),
        ]
        await store.upsert_nodes(nodes)

        await store.upsert_edge(GraphEdge(source_id="a1", target_id="a2", type=EdgeType.CALLS))
        await store.upsert_edge(GraphEdge(source_id="a2", target_id="a1", type=EdgeType.CALLS))
        await store.upsert_edge(GraphEdge(source_id="b1", target_id="b2", type=EdgeType.CALLS))
        await store.upsert_edge(GraphEdge(source_id="b2", target_id="b1", type=EdgeType.CALLS))

        detector = CommunityDetector(graph_store=store)
        all_nodes = await store.find_nodes()
        adjacency = await detector._build_adjacency(all_nodes, [EdgeType.CALLS])

        louvain_assignments = detector._louvain(all_nodes, adjacency, resolution=1.0)
        modularity = detector._compute_modularity(louvain_assignments, adjacency)

        assert modularity > 0

    async def test_random_partition_near_zero_modularity(self) -> None:
        store = MockGraphStore()
        await store.connect()

        nodes = [
            make_community_node("n1", file_path="src/pkg/file.py", name="n1"),
            make_community_node("n2", file_path="src/pkg/file.py", name="n2"),
            make_community_node("n3", file_path="src/pkg/file.py", name="n3"),
            make_community_node("n4", file_path="src/pkg/file.py", name="n4"),
        ]
        await store.upsert_nodes(nodes)

        await store.upsert_edge(GraphEdge(source_id="n1", target_id="n2", type=EdgeType.CALLS))
        await store.upsert_edge(GraphEdge(source_id="n2", target_id="n3", type=EdgeType.CALLS))
        await store.upsert_edge(GraphEdge(source_id="n3", target_id="n1", type=EdgeType.CALLS))
        await store.upsert_edge(GraphEdge(source_id="n4", target_id="n1", type=EdgeType.CALLS))

        detector = CommunityDetector(graph_store=store)
        all_nodes = await store.find_nodes()
        adjacency = await detector._build_adjacency(all_nodes, [EdgeType.CALLS])

        random_assignments = {node.id: f"comm_{i % 2}" for i, node in enumerate(all_nodes)}
        modularity = detector._compute_modularity(random_assignments, adjacency)

        assert modularity <= 1.0

    async def test_empty_adjacency_returns_zero(self) -> None:
        detector = CommunityDetector(graph_store=MockGraphStore())
        modularity = detector._compute_modularity({}, {})
        assert modularity == 0.0


class TestDetectBridges:
    """Test CommunityDetector._detect_bridges()."""

    async def test_bridges_detected_between_communities(self) -> None:
        store = MockGraphStore()
        await store.connect()

        nodes = [
            make_community_node("a1", file_path="src/pkg_a/file.py", name="func_a1"),
            make_community_node("a2", file_path="src/pkg_a/file.py", name="func_a2"),
            make_community_node("b1", file_path="src/pkg_b/file.py", name="func_b1"),
            make_community_node("b2", file_path="src/pkg_b/file.py", name="func_b2"),
        ]
        await store.upsert_nodes(nodes)

        await store.upsert_edge(GraphEdge(source_id="a1", target_id="a2", type=EdgeType.CALLS))
        await store.upsert_edge(GraphEdge(source_id="a2", target_id="a1", type=EdgeType.CALLS))
        await store.upsert_edge(GraphEdge(source_id="b1", target_id="b2", type=EdgeType.CALLS))
        await store.upsert_edge(GraphEdge(source_id="b2", target_id="b1", type=EdgeType.CALLS))
        await store.upsert_edge(GraphEdge(source_id="a1", target_id="b1", type=EdgeType.CALLS))

        detector = CommunityDetector(graph_store=store)
        all_nodes = await store.find_nodes()
        adjacency = await detector._build_adjacency(all_nodes, [EdgeType.CALLS])

        detector._node_communities_l0 = detector._louvain(all_nodes, adjacency, resolution=0.5)
        detector._node_communities_l1 = detector._node_communities_l0.copy()

        communities = detector._build_communities(
            detector._node_communities_l0, all_nodes, adjacency, level=0, label="coarse"
        )
        for cid, comm in communities.items():
            detector._communities[cid] = comm

        bridges = await detector._detect_bridges(all_nodes, adjacency)

        assert len(bridges) >= 0
        for bridge in bridges:
            assert "from_community" in bridge
            assert "to_community" in bridge
            assert bridge["from_community"] != bridge["to_community"]

    async def test_no_bridges_in_single_community(self) -> None:
        store = MockGraphStore()
        await store.connect()

        nodes = [
            make_community_node("n1", file_path="src/pkg/file.py", name="func1"),
            make_community_node("n2", file_path="src/pkg/file.py", name="func2"),
            make_community_node("n3", file_path="src/pkg/file.py", name="func3"),
        ]
        await store.upsert_nodes(nodes)

        await store.upsert_edge(GraphEdge(source_id="n1", target_id="n2", type=EdgeType.CALLS))
        await store.upsert_edge(GraphEdge(source_id="n2", target_id="n3", type=EdgeType.CALLS))
        await store.upsert_edge(GraphEdge(source_id="n3", target_id="n1", type=EdgeType.CALLS))

        detector = CommunityDetector(graph_store=store)
        all_nodes = await store.find_nodes()
        adjacency = await detector._build_adjacency(all_nodes, [EdgeType.CALLS])

        detector._node_communities_l0 = detector._louvain(all_nodes, adjacency, resolution=1.0)
        detector._node_communities_l1 = detector._node_communities_l0.copy()

        communities = detector._build_communities(
            detector._node_communities_l0, all_nodes, adjacency, level=0, label="test"
        )
        for cid, comm in communities.items():
            detector._communities[cid] = comm

        bridges = await detector._detect_bridges(all_nodes, adjacency)

        assert len(bridges) == 0


class TestListCommunities:
    """Test CommunityDetector.list_communities()."""

    async def test_list_empty_before_detection(self) -> None:
        store = MockGraphStore()
        await store.connect()
        detector = CommunityDetector(graph_store=store)

        result = await detector.list_communities()

        assert result["total"] == 0
        assert result["communities"] == []

    async def test_list_after_detection(self) -> None:
        store = MockGraphStore()
        await store.connect()

        nodes = [
            make_community_node("a1", file_path="src/auth/login.py", name="login", tags=["auth"]),
            make_community_node("a2", file_path="src/auth/login.py", name="validate", tags=["auth"]),
            make_community_node("a3", file_path="src/auth/logout.py", name="logout", tags=["auth"]),
        ]
        await store.upsert_nodes(nodes)

        await store.upsert_edge(GraphEdge(source_id="a1", target_id="a2", type=EdgeType.CALLS))
        await store.upsert_edge(GraphEdge(source_id="a2", target_id="a3", type=EdgeType.CALLS))

        detector = CommunityDetector(graph_store=store, min_community_size=1)
        await detector.detect()

        result = await detector.list_communities()

        assert result["total"] >= 1
        assert len(result["communities"]) >= 1

    async def test_list_filtered_by_level(self) -> None:
        store = MockGraphStore()
        await store.connect()

        nodes = [
            make_community_node("n1", file_path="src/pkg/file.py", name="func1", tags=["test"]),
            make_community_node("n2", file_path="src/pkg/file.py", name="func2", tags=["test"]),
        ]
        await store.upsert_nodes(nodes)

        await store.upsert_edge(GraphEdge(source_id="n1", target_id="n2", type=EdgeType.CALLS))

        detector = CommunityDetector(graph_store=store, min_community_size=1)
        await detector.detect()

        result_l0 = await detector.list_communities(level=0)
        result_l1 = await detector.list_communities(level=1)

        for comm in result_l0["communities"]:
            assert comm["level"] == 0
        for comm in result_l1["communities"]:
            assert comm["level"] == 1


class TestGetCommunity:
    """Test CommunityDetector.get_community()."""

    async def test_get_nonexistent_community(self) -> None:
        store = MockGraphStore()
        await store.connect()
        detector = CommunityDetector(graph_store=store)

        result = await detector.get_community("nonexistent_id")

        assert result is None

    async def test_get_existing_community(self) -> None:
        store = MockGraphStore()
        await store.connect()

        nodes = [
            make_community_node("n1", file_path="src/auth/login.py", name="login", tags=["auth"]),
            make_community_node("n2", file_path="src/auth/login.py", name="validate", tags=["auth"]),
        ]
        await store.upsert_nodes(nodes)

        await store.upsert_edge(GraphEdge(source_id="n1", target_id="n2", type=EdgeType.CALLS))

        detector = CommunityDetector(graph_store=store, min_community_size=1)
        await detector.detect()

        comm_ids = list(detector._communities.keys())
        assert len(comm_ids) >= 1

        result = await detector.get_community(comm_ids[0])

        assert result is not None
        assert "community_id" in result
        assert "members" in result

    async def test_get_community_with_node_type_filter(self) -> None:
        store = MockGraphStore()
        await store.connect()

        nodes = [
            make_community_node("n1", file_path="src/auth/login.py", name="login", tags=["auth"]),
            make_community_node("n2", file_path="src/auth/login.py", name="validate", tags=["auth"]),
        ]
        await store.upsert_nodes(nodes)

        await store.upsert_edge(GraphEdge(source_id="n1", target_id="n2", type=EdgeType.CALLS))

        detector = CommunityDetector(graph_store=store, min_community_size=1)
        await detector.detect()

        comm_ids = list(detector._communities.keys())
        result = await detector.get_community(comm_ids[0], node_types=["Function"])

        assert result is not None
        for member in result["members"]:
            assert member["type"] == "Function"


class TestGetBoundaries:
    """Test CommunityDetector.get_boundaries()."""

    async def test_get_boundaries_empty_before_detection(self) -> None:
        store = MockGraphStore()
        await store.connect()
        detector = CommunityDetector(graph_store=store)

        result = await detector.get_boundaries()

        assert result["level"] == 0
        assert result["boundaries"] == []

    async def test_get_boundaries_after_detection(self) -> None:
        store = MockGraphStore()
        await store.connect()

        nodes = [
            make_community_node("a1", file_path="src/pkg_a/file.py", name="func_a1"),
            make_community_node("a2", file_path="src/pkg_a/file.py", name="func_a2"),
            make_community_node("b1", file_path="src/pkg_b/file.py", name="func_b1"),
        ]
        await store.upsert_nodes(nodes)

        await store.upsert_edge(GraphEdge(source_id="a1", target_id="a2", type=EdgeType.CALLS))
        await store.upsert_edge(GraphEdge(source_id="a2", target_id="a1", type=EdgeType.CALLS))
        await store.upsert_edge(GraphEdge(source_id="a1", target_id="b1", type=EdgeType.CALLS))

        detector = CommunityDetector(graph_store=store, min_community_size=1)
        await detector.detect()

        result = await detector.get_boundaries()

        assert "level" in result
        assert "boundaries" in result

    async def test_get_boundaries_with_min_coupling(self) -> None:
        store = MockGraphStore()
        await store.connect()

        nodes = [
            make_community_node("a1", file_path="src/pkg_a/file.py", name="func_a1"),
            make_community_node("a2", file_path="src/pkg_a/file.py", name="func_a2"),
            make_community_node("b1", file_path="src/pkg_b/file.py", name="func_b1"),
        ]
        await store.upsert_nodes(nodes)

        await store.upsert_edge(GraphEdge(source_id="a1", target_id="a2", type=EdgeType.CALLS))
        await store.upsert_edge(GraphEdge(source_id="a1", target_id="b1", type=EdgeType.CALLS))

        detector = CommunityDetector(graph_store=store, min_community_size=1)
        await detector.detect()

        result = await detector.get_boundaries(level=0, min_coupling=0.5)

        assert "boundaries" in result