from __future__ import annotations

import os
import random
import time

import pytest

from smp.core.models import EdgeType, GraphEdge, GraphNode, NodeType, StructuralProperties
from smp.engine.query import DefaultQueryEngine
from smp.store.graph.mmap_store import MMapGraphStore
from smp.vector.mmap_vector import MMapVectorStore

# Scale tests ingest ~1M nodes / 10M edges / 1M vectors. They are opt-in
# via SMP_RUN_SCALE_TESTS=1 and never run in normal CI.
pytestmark = pytest.mark.skipif(
    os.environ.get("SMP_RUN_SCALE_TESTS") != "1",
    reason="scale tests require SMP_RUN_SCALE_TESTS=1",
)


@pytest.fixture(scope="module")
def scale_paths(tmp_path_factory):
    """Provide paths for scale testing datasets."""
    tmp_dir = tmp_path_factory.mktemp("scale_data")
    return {
        "graph": str(tmp_dir / "scale_graph.smpg"),
        "vector": str(tmp_dir / "scale_vector.smpv"),
    }


@pytest.fixture(scope="module", autouse=True)
async def setup_scale_data(scale_paths):
    """Pre-populate scale datasets once for the module."""
    # 1M Nodes
    graph = MMapGraphStore(path=scale_paths["graph"])
    await graph.connect()

    node_count = 1_000_000
    batch_size = 20_000
    for i in range(0, node_count, batch_size):
        nodes = [
            GraphNode(
                id=f"node_{j}",
                type=NodeType.FUNCTION,
                file_path=f"src/file_{j // 1000}.py",
                structural=StructuralProperties(
                    name=f"func_{j}",
                    file=f"src/file_{j // 1000}.py",
                    start_line=1,
                    end_line=10,
                    lines=10,
                ),
            )
            for j in range(i, min(i + batch_size, node_count))
        ]
        for node in nodes:
            await graph.upsert_node(node)

    # 10M Edges
    edge_count = 10_000_000
    for i in range(0, edge_count, batch_size):
        edges = [
            GraphEdge(
                source_id=f"node_{random.randint(0, node_count - 1)}",
                target_id=f"node_{random.randint(0, node_count - 1)}",
                type=EdgeType.CALLS,
            )
            for _ in range(min(batch_size, edge_count - i))
        ]
        for edge in edges:
            await graph.upsert_edge(edge)

    await graph.close()

    # 1M Vectors
    vector_store = MMapVectorStore(path=scale_paths["vector"], dimension=128)
    await vector_store.connect()

    vec_count = 1_000_000
    for i in range(0, vec_count, batch_size):
        ids = [f"vec_{j}" for j in range(i, min(i + batch_size, vec_count))]
        embeddings = [[random.uniform(-1, 1) for _ in range(128)] for _ in range(len(ids))]
        metadatas = [{"type": "code_chunk"} for _ in range(len(ids))]
        documents = [f"Document {j}" for j in range(i, min(i + batch_size, vec_count))]
        await vector_store.upsert(ids=ids, embeddings=embeddings, metadatas=metadatas, documents=documents)

    await vector_store.close()


@pytest.mark.asyncio
async def test_p012_node_scale_query(scale_paths):
    """P-012: Measure query performance with 1M nodes."""
    graph = MMapGraphStore(path=scale_paths["graph"])
    await graph.connect()
    engine = DefaultQueryEngine(graph_store=graph)

    start_time = time.perf_counter()
    result = await engine.locate("func_500000", fields=["name"], node_types=[NodeType.FUNCTION], top_k=1)
    duration = time.perf_counter() - start_time

    await graph.close()
    assert len(result) > 0
    assert duration < 0.1  # Expect sub-100ms for indexed lookup


@pytest.mark.asyncio
async def test_p013_edge_scale_query(scale_paths):
    """P-013: Measure query performance with 10M edges."""
    graph = MMapGraphStore(path=scale_paths["graph"])
    await graph.connect()
    engine = DefaultQueryEngine(graph_store=graph)

    start_time = time.perf_counter()
    # Trace from a random node
    result = await engine.trace("node_123", "calls", depth=2, direction="out")
    duration = time.perf_counter() - start_time

    await graph.close()
    assert isinstance(result, list)
    assert duration < 0.2  # Expect sub-200ms for small depth trace


@pytest.mark.asyncio
async def test_p014_vector_scale_search(scale_paths):
    """P-014: Measure search performance with 1M vectors."""
    vector_store = MMapVectorStore(path=scale_paths["vector"], dimension=128)
    await vector_store.connect()

    embedding = [random.uniform(-1, 1) for _ in range(128)]
    start_time = time.perf_counter()
    result = await vector_store.query(embedding=embedding, top_k=10)
    duration = time.perf_counter() - start_time

    await vector_store.close()
    assert len(result) == 10
    assert duration < 0.1  # Expect sub-100ms for vector search


@pytest.mark.asyncio
async def test_p015_mixed_scale_performance(scale_paths):
    """P-015: Measure mixed scale performance."""
    graph = MMapGraphStore(path=scale_paths["graph"])
    await graph.connect()
    vector_store = MMapVectorStore(path=scale_paths["vector"], dimension=128)
    await vector_store.connect()
    engine = DefaultQueryEngine(graph_store=graph)

    start_time = time.perf_counter()
    # Simulate a complex operation: Vector search -> Navigate result
    embedding = [random.uniform(-1, 1) for _ in range(128)]
    vec_results = await vector_store.query(embedding=embedding, top_k=1)
    if vec_results:
        node_id = vec_results[0]["id"]
        await engine.navigate(node_id, include_relationships=True)

    duration = time.perf_counter() - start_time

    await graph.close()
    await vector_store.close()
    assert duration < 0.3
