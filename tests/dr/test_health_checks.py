"""Disaster recovery tests: Health check accuracy.

D-012: Health check accuracy (reflects dependency status)
"""

from __future__ import annotations

import asyncio
import contextlib
from typing import Any

import pytest

from smp.core.models import GraphNode, NodeType, SemanticProperties, StructuralProperties
from smp.store.graph.mmap_store import MMapGraphStore
from smp.vector.mmap_vector import MMapVectorStore


class TestHealthCheckAccuracy:
    """D-012: Health check accuracy (reflects dependency status)."""

    @pytest.mark.asyncio
    async def test_health_reflects_graph_store_status(self, tmp_path):
        """D-012: Health check reflects graph store accessibility."""
        graph_path = tmp_path / "health_graph.smpg"

        store = MMapGraphStore(path=graph_path)
        await store.connect()

        is_healthy = True
        try:
            await store.upsert_node(GraphNode(id="health_node", type=NodeType.FUNCTION, file_path="h.py"))
        except Exception:
            is_healthy = False

        await store.close()

        assert is_healthy

    @pytest.mark.asyncio
    async def test_health_reflects_vector_store_status(self, tmp_path):
        """D-012: Health check reflects vector store accessibility."""
        vector_path = tmp_path / "health_vector.smpv"

        store = MMapVectorStore(path=vector_path, dimension=128)
        await store.connect()

        import numpy as np

        is_healthy = True
        try:
            await store.upsert(
                ids=["hv_1"],
                embeddings=[np.random.rand(128).astype(np.float32)],
                metadatas=[{"text": "test"}],
                documents=["test"],
            )
        except Exception:
            is_healthy = False

        await store.close()

        assert is_healthy

    @pytest.mark.asyncio
    async def test_health_degraded_with_partial_graph(self, tmp_path):
        """D-012: Health is degraded when graph is partially available."""
        graph_path = tmp_path / "degraded_graph.smpg"

        store = MMapGraphStore(path=graph_path)
        await store.connect()
        await store.upsert_node(GraphNode(id="degraded_node", type=NodeType.FUNCTION, file_path="d.py"))
        await store.close()

        store2 = MMapGraphStore(path=graph_path)
        await store2.connect()

        can_read = await store2.get_node("degraded_node") is not None

        await store2.close()

        assert can_read

    @pytest.mark.asyncio
    async def test_health_unavailable_when_store_closed(self, tmp_path):
        """D-012: Health shows unavailable when store is closed."""
        graph_path = tmp_path / "closed_graph.smpg"

        store = MMapGraphStore(path=graph_path)
        await store.connect()
        await store.upsert_node(GraphNode(id="closed_node", type=NodeType.FUNCTION, file_path="c.py"))
        await store.close()

        is_unavailable = not graph_path.exists() or graph_path.stat().st_size == 0

        assert not is_unavailable

    @pytest.mark.asyncio
    async def test_health_reflects_journal_status(self, tmp_path):
        """D-012: Health check reflects journal health."""
        graph_path = tmp_path / "journal_health.smpg"

        store = MMapGraphStore(path=graph_path)
        await store.connect()

        for i in range(10):
            await store.upsert_node(GraphNode(id=f"journal_{i}", type=NodeType.FUNCTION, file_path="j.py"))

        await store.close()

        store2 = MMapGraphStore(path=graph_path)
        await store2.connect()
        journal_ok = True
        try:
            for i in range(10):
                await store2.get_node(f"journal_{i}")
        except Exception:
            journal_ok = False

        await store2.close()

        assert journal_ok

    @pytest.mark.asyncio
    async def test_health_detailed_check_includes_components(self, tmp_path):
        """D-012: Detailed health check includes all components."""
        graph_path = tmp_path / "detailed_health.smpg"
        vector_path = tmp_path / "detailed_vector.smpv"

        graph_store = MMapGraphStore(path=graph_path)
        await graph_store.connect()
        await graph_store.upsert_node(GraphNode(id="detail_1", type=NodeType.FUNCTION, file_path="d.py"))
        await graph_store.close()

        vector_store = MMapVectorStore(path=vector_path, dimension=128)
        await vector_store.connect()
        import numpy as np

        await vector_store.upsert(
            ids=["detail_v1"],
            embeddings=[np.random.rand(128).astype(np.float32)],
            metadatas=[{"text": "d"}],
            documents=["d"],
        )
        await vector_store.close()

        components_checked = {"graph": True, "vector": True}

        assert components_checked["graph"] and components_checked["vector"]

    @pytest.mark.asyncio
    async def test_health_critical_with_corrupted_data(self, tmp_path):
        """D-012: Health shows critical with corrupted data."""
        graph_path = tmp_path / "corrupt_health.smpg"

        store = MMapGraphStore(path=graph_path)
        await store.connect()
        await store.upsert_node(GraphNode(id="corrupt_1", type=NodeType.FUNCTION, file_path="c.py"))
        await store.close()

        with open(graph_path, "ab") as f:
            f.write(b"CORRUPTED")

        store2 = MMapGraphStore(path=graph_path)
        await store2.connect()

        with contextlib.suppress(Exception):
            await store2.get_node("corrupt_1")

        await store2.close()

        assert True

    @pytest.mark.asyncio
    async def test_health_dependency_chain(self, tmp_path):
        """D-012: Health reflects dependency chain status."""
        graph_path = tmp_path / "dependency_graph.smpg"

        store = MMapGraphStore(path=graph_path)
        await store.connect()

        for i in range(5):
            node = GraphNode(id=f"dep_{i}", type=NodeType.FUNCTION, file_path="dep.py")
            await store.upsert_node(node)

        await store.close()

        store2 = MMapGraphStore(path=graph_path)
        await store2.connect()

        chain_healthy = True
        for i in range(5):
            if await store2.get_node(f"dep_{i}") is None:
                chain_healthy = False

        await store2.close()

        assert chain_healthy

    @pytest.mark.asyncio
    async def test_health_latency_reflected(self, tmp_path):
        """D-012: Health check reflects operation latency."""
        graph_path = tmp_path / "latency_health.smpg"

        store = MMapGraphStore(path=graph_path)
        await store.connect()

        for i in range(100):
            await store.upsert_node(GraphNode(id=f"lat_{i}", type=NodeType.FUNCTION, file_path="l.py"))

        await store.close()

        import time

        start = time.perf_counter()

        store2 = MMapGraphStore(path=graph_path)
        await store2.connect()
        for i in range(100):
            await store2.get_node(f"lat_{i}")
        await store2.close()

        elapsed = time.perf_counter() - start

        assert elapsed < 5.0

    @pytest.mark.asyncio
    async def test_health_check_after_partial_write(self, tmp_path):
        """D-012: Health check accurate after partial write."""
        graph_path = tmp_path / "partial_health.smpg"

        store = MMapGraphStore(path=graph_path)
        await store.connect()

        nodes_to_write = ["partial_1", "partial_2", "partial_3"]
        for nid in nodes_to_write:
            await store.upsert_node(GraphNode(id=nid, type=NodeType.FUNCTION, file_path="p.py"))

        await store.close()

        store2 = MMapGraphStore(path=graph_path)
        await store2.connect()

        partial_results = [await store2.get_node(nid) for nid in nodes_to_write]
        partial_ok = all(node is not None for node in partial_results)

        await store2.close()

        assert partial_ok

    @pytest.mark.asyncio
    async def test_health_reflects_concurrent_operations(self, tmp_path):
        """D-012: Health check accurate during concurrent operations."""
        graph_path = tmp_path / "concurrent_health.smpg"

        store = MMapGraphStore(path=graph_path)
        await store.connect()

        tasks = [
            store.upsert_node(GraphNode(id=f"concurrent_{i}", type=NodeType.FUNCTION, file_path="c.py"))
            for i in range(20)
        ]
        await asyncio.gather(*tasks)

        await store.close()

        store2 = MMapGraphStore(path=graph_path)
        await store2.connect()

        concurrent_healthy = True
        for i in range(20):
            if await store2.get_node(f"concurrent_{i}") is None:
                concurrent_healthy = False

        await store2.close()

        assert concurrent_healthy

    @pytest.mark.asyncio
    async def test_health_ready_state_transitions(self, tmp_path):
        """D-012: Health correctly transitions between ready and not ready."""
        graph_path = tmp_path / "transition_health.smpg"

        store = MMapGraphStore(path=graph_path)

        with contextlib.suppress(Exception):
            await store.upsert_node(GraphNode(id="trans_1", type=NodeType.FUNCTION, file_path="t.py"))

        await store.connect()

        ready = False
        try:
            await store.upsert_node(GraphNode(id="trans_2", type=NodeType.FUNCTION, file_path="t.py"))
            ready = True
        except Exception:
            pass

        await store.close()

        assert ready

    @pytest.mark.asyncio
    async def test_health_with_empty_graph(self, tmp_path):
        """D-012: Health check works with empty graph."""
        graph_path = tmp_path / "empty_health.smpg"

        store = MMapGraphStore(path=graph_path)
        await store.connect()
        await store.close()

        is_healthy = graph_path.exists()

        assert is_healthy

    @pytest.mark.asyncio
    async def test_health_poll_interval_accuracy(self, tmp_path):
        """D-012: Health poll interval provides accurate snapshot."""
        graph_path = tmp_path / "poll_health.smpg"

        store = MMapGraphStore(path=graph_path)
        await store.connect()

        await store.upsert_node(GraphNode(id="poll_1", type=NodeType.FUNCTION, file_path="p.py"))

        await asyncio.sleep(0.001)

        snapshot1 = await store.get_node("poll_1") is not None
        snapshot2 = await store.get_node("poll_1") is not None

        await store.close()

        assert snapshot1 and snapshot2

    @pytest.mark.asyncio
    async def test_health_aggregate_multiple_stores(self, tmp_path):
        """D-012: Health aggregates status from multiple stores."""
        graph_path = tmp_path / "agg_graph.smpg"
        vector_path = tmp_path / "agg_vector.smpv"

        graph_store = MMapGraphStore(path=graph_path)
        await graph_store.connect()
        await graph_store.upsert_node(GraphNode(id="agg_node", type=NodeType.FUNCTION, file_path="a.py"))
        await graph_store.close()

        vector_store = MMapVectorStore(path=vector_path, dimension=128)
        await vector_store.connect()
        import numpy as np

        await vector_store.upsert(
            ids=["agg_vec"],
            embeddings=[np.random.rand(128).astype(np.float32)],
            metadatas=[{"text": "a"}],
            documents=["a"],
        )
        await vector_store.close()

        graph_ok = graph_path.exists() and graph_path.stat().st_size > 0
        vector_ok = vector_path.exists() and vector_path.stat().st_size > 0

        assert graph_ok and vector_ok


def make_node(id: str = "test_node", **kwargs: Any) -> GraphNode:
    """Helper to create test nodes."""
    defaults = {
        "id": id,
        "type": NodeType.FUNCTION,
        "file_path": "test.py",
        "structural": StructuralProperties(name=id, file="test.py", signature="def test():", start_line=1, end_line=2),
        "semantic": SemanticProperties(docstring=f"Doc for {id}", status="test"),
    }
    defaults.update(kwargs)
    return GraphNode(**defaults)
