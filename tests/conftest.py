from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from smp.core.models import (
    EdgeType,
    GraphEdge,
    GraphNode,
    Language,
    NodeType,
)
from smp.store.graph.mmap_store import MMapGraphStore
from smp.vector.mmap_vector import MMapVectorStore


@dataclass
class StorePair:
    graph: MMapGraphStore
    vector: MMapVectorStore
    tmp_path: Path


@pytest.fixture
async def graph_store(tmp_path: Path) -> AsyncIterator[MMapGraphStore]:
    graph_path = tmp_path / "test.graph.smpg"
    store = MMapGraphStore(path=str(graph_path))
    await store.connect()
    try:
        yield store
    finally:
        await store.close()


@pytest.fixture
async def vector_store(tmp_path: Path) -> AsyncIterator[MMapVectorStore]:
    vector_path = tmp_path / "test.vector.smpv"
    store = MMapVectorStore(path=str(vector_path), dimension=128)
    await store.connect()
    try:
        yield store
    finally:
        await store.close()


@pytest.fixture
async def store_pair(tmp_path: Path) -> AsyncIterator[StorePair]:
    graph_path = tmp_path / "test.graph.smpg"
    vector_path = tmp_path / "test.vector.smpv"

    graph = MMapGraphStore(path=str(graph_path))
    vector = MMapVectorStore(path=str(vector_path), dimension=128)

    await graph.connect()
    await vector.connect()

    try:
        yield StorePair(graph=graph, vector=vector, tmp_path=tmp_path)
    finally:
        await graph.close()
        await vector.close()


@pytest.fixture
async def clean_graph(graph_store: MMapGraphStore) -> MMapGraphStore:
    await graph_store.clear()
    return graph_store


@pytest.fixture
def make_node() -> type[GraphNode]:
    from smp.core.models import StructuralProperties

    _counter = 0

    def _create_node(
        name: str = "test_function",
        node_type: NodeType = NodeType.FUNCTION,
        language: Language = Language.PYTHON,
        file_path: str = "/test/file.py",
        properties: dict[str, Any] | None = None,
    ) -> GraphNode:
        nonlocal _counter
        _counter += 1
        del language
        structural_kwargs: dict[str, Any] = {"name": name}
        if properties:
            for key in ("file", "signature", "start_line", "end_line", "complexity", "lines", "parameters"):
                if key in properties:
                    structural_kwargs[key] = properties[key]
        return GraphNode(
            id=f"node_{_counter}_{name}",
            type=node_type,
            file_path=file_path,
            structural=StructuralProperties(**structural_kwargs),
        )

    return _create_node


@pytest.fixture
def make_edge() -> type[GraphEdge]:
    _counter = 0

    def _create_edge(
        source_id: str = "source_node",
        target_id: str = "target_node",
        edge_type: EdgeType = EdgeType.CALLS,
        properties: dict[str, Any] | None = None,
    ) -> GraphEdge:
        nonlocal _counter
        _counter += 1
        del properties
        return GraphEdge(
            source_id=source_id,
            target_id=target_id,
            type=edge_type,
        )

    return _create_edge


@pytest.fixture
async def populated_graph_store(
    graph_store: MMapGraphStore, make_node: type[GraphNode], make_edge: type[GraphEdge]
) -> MMapGraphStore:
    """Graph store with a small realistic corpus for perf/benchmark tests."""
    from smp.core.models import StructuralProperties

    nodes = [
        GraphNode(
            id="class_User",
            type=NodeType.CLASS,
            file_path="src/auth/models.py",
            structural=StructuralProperties(name="User", file="src/auth/models.py", start_line=1, end_line=20),
        ),
        GraphNode(
            id="func_login",
            type=NodeType.FUNCTION,
            file_path="src/auth/login.py",
            structural=StructuralProperties(name="func_login", file="src/auth/login.py", start_line=1, end_line=30),
        ),
        GraphNode(
            id="func_auth",
            type=NodeType.FUNCTION,
            file_path="src/auth/session.py",
            structural=StructuralProperties(name="auth", file="src/auth/session.py", start_line=1, end_line=25),
        ),
    ]
    for i in range(17):
        nodes.append(make_node(name=f"perf_func_{i}", file_path=f"src/perf/mod_{i}.py"))
    for node in nodes:
        await graph_store.upsert_node(node)
    await graph_store.upsert_edge(make_edge(source_id="func_login", target_id="func_auth"))
    await graph_store.upsert_edge(make_edge(source_id="class_User", target_id="func_login"))
    return graph_store


@pytest.fixture
async def populated_vector_store(vector_store: MMapVectorStore) -> MMapVectorStore:
    """Vector store with sample embeddings for perf/benchmark tests."""
    import random

    random.seed(1234)
    ids = [f"perf_vec_{i}" for i in range(20)]
    embeddings = [[random.uniform(-1, 1) for _ in range(128)] for _ in range(20)]
    metadatas = [{"type": "code_chunk", "index": i} for i in range(20)]
    documents = [f"code snippet {i}" for i in range(20)]
    await vector_store.upsert(ids=ids, embeddings=embeddings, metadatas=metadatas, documents=documents)
    return vector_store


@pytest.fixture
async def populated_graph(
    graph_store: MMapGraphStore, make_node: type[GraphNode], make_edge: type[GraphEdge]
) -> MMapGraphStore:
    node_a = make_node(name="func_a", file_path="/test/a.py")
    node_b = make_node(name="func_b", file_path="/test/b.py")
    node_c = make_node(name="func_c", file_path="/test/c.py")

    await graph_store.upsert_node(node_a)
    await graph_store.upsert_node(node_b)
    await graph_store.upsert_node(node_c)

    edge_ab = make_edge(source_id=node_a.id, target_id=node_b.id)
    edge_bc = make_edge(source_id=node_b.id, target_id=node_c.id)

    await graph_store.upsert_edge(edge_ab)
    await graph_store.upsert_edge(edge_bc)

    return graph_store


@pytest.fixture
def mock_vector_store() -> MagicMock:
    store = MagicMock(spec=MMapVectorStore)
    store.upsert = AsyncMock(return_value=None)
    store.query = AsyncMock(return_value=[])
    store.delete = AsyncMock(return_value=0)
    store.get = AsyncMock(return_value=None)
    return store


@pytest.fixture
def mock_graph_store() -> MagicMock:
    store = MagicMock(spec=MMapGraphStore)
    store.upsert_node = AsyncMock(return_value=None)
    store.upsert_nodes = AsyncMock(return_value=None)
    store.upsert_edge = AsyncMock(return_value=None)
    store.upsert_edges = AsyncMock(return_value=None)
    store.get_node = AsyncMock(return_value=None)
    store.get_edges = AsyncMock(return_value=[])
    store.delete_node = AsyncMock(return_value=False)
    store.delete_nodes_by_file = AsyncMock(return_value=0)
    store.find_nodes = AsyncMock(return_value=[])
    store.query_nodes = AsyncMock(return_value=[])
    store.traverse = AsyncMock(return_value=[])
    store.get_neighbors = AsyncMock(return_value=[])
    store.count_nodes = AsyncMock(return_value=0)
    store.count_edges = AsyncMock(return_value=0)
    return store


@pytest.fixture
def sample_embedding() -> list[float]:
    import random

    random.seed(42)
    return [random.random() for _ in range(128)]


@pytest.fixture
def sample_embeddings() -> list[list[float]]:
    import random

    random.seed(42)
    return [[random.random() for _ in range(128)] for _ in range(10)]


@pytest.fixture
def api_key_valid() -> str:
    return "smp_test_key_12345"


@pytest.fixture
def api_key_expired() -> str:
    return "smp_expired_key_99999"


@pytest.fixture
def correlation_id() -> str:
    return "test_corr_id_12345"


@pytest.fixture
def http_client(mock_graph_store: MagicMock) -> MagicMock:
    return MagicMock()


@pytest.fixture
def in_memory_locks() -> dict[str, Any]:
    return {}


@pytest.fixture
def seeded_ctx(populated_graph: MMapGraphStore) -> dict[str, Any]:
    return {
        "graph": populated_graph,
        "nodes": {
            "func_a": populated_graph,
            "func_b": populated_graph,
            "func_c": populated_graph,
        },
    }


@pytest.fixture
def durable_ctx(graph_store: MMapGraphStore) -> dict[str, Any]:
    return {
        "graph": graph_store,
    }


@pytest.fixture
def secure_client(graph_store: MMapGraphStore, api_key_valid: str) -> MagicMock:
    return MagicMock()


@pytest.fixture
def open_client(graph_store: MMapGraphStore) -> MagicMock:
    return MagicMock()


@pytest.fixture
def git_repo(tmp_path: Path) -> Path:
    repo_dir = tmp_path / "test_repo"
    repo_dir.mkdir()
    (repo_dir / "test.txt").write_text("hello")
    return repo_dir


@pytest.fixture
def sample_project(tmp_path: Path) -> Path:
    project = tmp_path / "sample_project"
    src = project / "src"
    src.mkdir(parents=True)

    (src / "__init__.py").write_text("")
    (src / "main.py").write_text(
        """\
def main():
    print("hello")

def helper():
    pass
"""
    )
    (src / "utils.py").write_text(
        """\
def util_a():
    pass

def util_b():
    util_a()
"""
    )

    return project


@pytest.fixture
def runtime(tmp_path: Path) -> Path:
    sandbox_root = tmp_path / "sandbox"
    sandbox_root.mkdir()
    return sandbox_root


@pytest.fixture
def event_loop():
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()
