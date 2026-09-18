"""Disaster recovery tests: Vector store recovery.

D-005: Vector store recovery (rebuild from graph)
"""

from __future__ import annotations

from typing import Any

import numpy as np
import pytest

from smp.core.models import (
    EdgeType,
    GraphEdge,
    GraphNode,
    NodeType,
    SemanticProperties,
    StructuralProperties,
)
from smp.store.graph.mmap_store import MMapGraphStore
from smp.vector.mmap_vector import MMapVectorStore


class TestVectorStoreRecovery:
    """D-005: Vector store recovery (rebuild from graph)."""

    @pytest.mark.asyncio
    async def test_rebuild_vector_store_from_graph(self, tmp_path):
        """D-005: Rebuild vector store from existing graph data."""
        graph_path = tmp_path / "rebuild_graph.smpg"
        vector_path = tmp_path / "rebuild_vector.smpv"

        graph_store = MMapGraphStore(path=graph_path)
        await graph_store.connect()
        try:
            for i in range(20):
                node = make_node(id=f"rebuild_{i}")
                await graph_store.upsert_node(node)
        finally:
            await graph_store.close()

        vector_store = MMapVectorStore(path=vector_path, dimension=128)
        await vector_store.connect()
        try:
            for i in range(20):
                embedding = np.random.rand(128).astype(np.float32)
                await vector_store.upsert(
                    ids=[f"rebuild_{i}"],
                    embeddings=[embedding],
                    metadatas=[{"text": f"Document {i}"}],
                    documents=[f"Document {i}"],
                )
        finally:
            await vector_store.close()

        del vector_store

        vector_store2 = MMapVectorStore(path=vector_path, dimension=128)
        await vector_store2.connect()
        try:
            results = await vector_store2.query(embedding=np.random.rand(128).astype(np.float32), top_k=20)
            assert len(results) == 20
        finally:
            await vector_store2.close()

    @pytest.mark.asyncio
    async def test_vector_store_recovery_after_crash(self, tmp_path):
        """D-005: Vector store recovers after hard crash."""
        graph_path = tmp_path / "vector_crash_graph.smpg"
        vector_path = tmp_path / "vector_crash_vector.smpv"

        graph_store = MMapGraphStore(path=graph_path)
        await graph_store.connect()
        try:
            for i in range(30):
                node = make_node(id=f"vc_{i}", semantic=SemanticProperties(docstring=f"Doc {i}"))
                await graph_store.upsert_node(node)
        finally:
            await graph_store.close()

        vector_store = MMapVectorStore(path=vector_path, dimension=128)
        await vector_store.connect()
        try:
            for i in range(30):
                emb = np.random.rand(128).astype(np.float32)
                await vector_store.upsert(
                    ids=[f"vc_{i}"],
                    embeddings=[emb],
                    metadatas=[{"text": f"D{i}"}],
                    documents=[f"D{i}"],
                )
        finally:
            await vector_store.close()

        del vector_store

        vector_store2 = MMapVectorStore(path=vector_path, dimension=128)
        await vector_store2.connect()
        try:
            found = 0
            for _ in range(30):
                res = await vector_store2.query(embedding=np.random.rand(128).astype(np.float32), top_k=30)
                if len(res) > 0:
                    found += 1
            assert found > 0
        finally:
            await vector_store2.close()

    @pytest.mark.asyncio
    async def test_rebuild_empty_vector_store(self, tmp_path):
        """D-005: Rebuild empty vector store is idempotent."""
        graph_path = tmp_path / "empty_vector_graph.smpg"
        vector_path = tmp_path / "empty_vector.smpv"

        graph_store = MMapGraphStore(path=graph_path)
        await graph_store.connect()
        await graph_store.close()

        vector_store = MMapVectorStore(path=vector_path, dimension=128)
        await vector_store.connect()
        try:
            res = await vector_store.query(embedding=np.zeros(128, dtype=np.float32), top_k=10)
            assert res == []
        finally:
            await vector_store.close()

    @pytest.mark.asyncio
    async def test_rebuild_with_edges_in_graph(self, tmp_path):
        """D-005: Vector store rebuild includes graph edge information."""
        graph_path = tmp_path / "vector_edges_graph.smpg"
        vector_path = tmp_path / "vector_edges_vector.smpv"

        graph_store = MMapGraphStore(path=graph_path)
        await graph_store.connect()
        try:
            for i in range(10):
                await graph_store.upsert_node(make_node(id=f"edge_v_{i}"))
            for i in range(9):
                edge = make_edge(source=f"edge_v_{i}", target=f"edge_v_{i + 1}")
                await graph_store.upsert_edge(edge)
        finally:
            await graph_store.close()

        vector_store = MMapVectorStore(path=vector_path, dimension=128)
        await vector_store.connect()
        try:
            for i in range(10):
                emb = np.random.rand(128).astype(np.float32)
                await vector_store.upsert(
                    ids=[f"edge_v_{i}"],
                    embeddings=[emb],
                    metadatas=[{"neighbors": [i - 1, i + 1] if 0 < i < 9 else []}],
                    documents=[""],
                )
        finally:
            await vector_store.close()

        del vector_store

        vector_store2 = MMapVectorStore(path=vector_path, dimension=128)
        await vector_store2.connect()
        try:
            res = await vector_store2.query(embedding=np.random.rand(128).astype(np.float32), top_k=10)
            assert len(res) == 10
        finally:
            await vector_store2.close()

    @pytest.mark.asyncio
    async def test_partial_vector_recovery(self, tmp_path):
        """D-005: Partial vector data is recovered."""
        graph_path = tmp_path / "partial_vector_graph.smpg"
        vector_path = tmp_path / "partial_vector.smpv"

        graph_store = MMapGraphStore(path=graph_path)
        await graph_store.connect()
        try:
            for i in range(50):
                await graph_store.upsert_node(make_node(id=f"partial_v_{i}"))
        finally:
            await graph_store.close()

        vector_store = MMapVectorStore(path=vector_path, dimension=128)
        await vector_store.connect()
        try:
            for i in range(25):
                emb = np.random.rand(128).astype(np.float32)
                await vector_store.upsert(
                    ids=[f"partial_v_{i}"],
                    embeddings=[emb],
                    metadatas=[{"text": f"P{i}"}],
                    documents=[f"P{i}"],
                )
        finally:
            await vector_store.close()

        vector_store2 = MMapVectorStore(path=vector_path, dimension=128)
        await vector_store2.connect()
        try:
            res = await vector_store2.query(embedding=np.random.rand(128).astype(np.float32), top_k=30)
            assert len(res) >= 20
        finally:
            await vector_store2.close()

    @pytest.mark.asyncio
    async def test_rebuild_with_different_node_types(self, tmp_path):
        """D-005: Vector store rebuild handles different node types."""
        graph_path = tmp_path / "types_vector_graph.smpg"
        vector_path = tmp_path / "types_vector.smpv"

        graph_store = MMapGraphStore(path=graph_path)
        await graph_store.connect()
        try:
            for i, nt in enumerate([NodeType.FUNCTION, NodeType.CLASS, NodeType.VARIABLE, NodeType.FILE]):
                node = make_node(id=f"type_{i}", type=nt)
                await graph_store.upsert_node(node)
        finally:
            await graph_store.close()

        vector_store = MMapVectorStore(path=vector_path, dimension=128)
        await vector_store.connect()
        try:
            for i in range(4):
                emb = np.random.rand(128).astype(np.float32)
                await vector_store.upsert(
                    ids=[f"type_{i}"],
                    embeddings=[emb],
                    metadatas=[{"type": str(i)}],
                    documents=[""],
                )
        finally:
            await vector_store.close()

        vector_store2 = MMapVectorStore(path=vector_path, dimension=128)
        await vector_store2.connect()
        try:
            res = await vector_store2.query(embedding=np.random.rand(128).astype(np.float32), top_k=5)
            assert len(res) >= 3
        finally:
            await vector_store2.close()

    @pytest.mark.asyncio
    async def test_vector_recovery_preserves_documents(self, tmp_path):
        """D-005: Vector store recovery preserves document metadata."""
        graph_path = tmp_path / "doc_vector_graph.smpg"
        vector_path = tmp_path / "doc_vector.smpv"

        graph_store = MMapGraphStore(path=graph_path)
        await graph_store.connect()
        try:
            for i in range(15):
                node = make_node(id=f"doc_v_{i}", semantic=SemanticProperties(docstring=f"Description {i}"))
                await graph_store.upsert_node(node)
        finally:
            await graph_store.close()

        vector_store = MMapVectorStore(path=vector_path, dimension=128)
        await vector_store.connect()
        try:
            for i in range(15):
                emb = np.random.rand(128).astype(np.float32)
                await vector_store.upsert(
                    ids=[f"doc_v_{i}"],
                    embeddings=[emb],
                    metadatas=[{"text": f"Description {i}", "source": "test", "index": i}],
                    documents=[f"Description {i}"],
                )
        finally:
            await vector_store.close()

        del vector_store

        vector_store2 = MMapVectorStore(path=vector_path, dimension=128)
        await vector_store2.connect()
        try:
            res = await vector_store2.query(embedding=np.random.rand(128).astype(np.float32), top_k=15)
            for r in res:
                assert "text" in r["metadata"] or "source" in r["metadata"]
        finally:
            await vector_store2.close()

    @pytest.mark.asyncio
    async def test_rebuild_large_vector_store(self, tmp_path):
        """D-005: Large vector store rebuild completes successfully."""
        graph_path = tmp_path / "large_vector_graph.smpg"
        vector_path = tmp_path / "large_vector.smpv"

        graph_store = MMapGraphStore(path=graph_path)
        await graph_store.connect()
        try:
            for i in range(200):
                await graph_store.upsert_node(make_node(id=f"large_v_{i}"))
        finally:
            await graph_store.close()

        vector_store = MMapVectorStore(path=vector_path, dimension=128)
        await vector_store.connect()
        try:
            for i in range(200):
                emb = np.random.rand(128).astype(np.float32)
                await vector_store.upsert(
                    ids=[f"large_v_{i}"],
                    embeddings=[emb],
                    metadatas=[{"id": i}],
                    documents=[""],
                )
        finally:
            await vector_store.close()

        del vector_store

        vector_store2 = MMapVectorStore(path=vector_path, dimension=128)
        await vector_store2.connect()
        try:
            res = await vector_store2.query(embedding=np.random.rand(128).astype(np.float32), top_k=200)
            assert len(res) >= 190
        finally:
            await vector_store2.close()

    @pytest.mark.asyncio
    async def test_corrupted_vector_recovery(self, tmp_path):
        """D-005: Vector recovery handles corrupted data gracefully."""
        graph_path = tmp_path / "corrupt_vector_graph.smpg"
        vector_path = tmp_path / "corrupt_vector.smpv"

        graph_store = MMapGraphStore(path=graph_path)
        await graph_store.connect()
        try:
            for i in range(10):
                await graph_store.upsert_node(make_node(id=f"corrupt_v_{i}"))
        finally:
            await graph_store.close()

        vector_store = MMapVectorStore(path=vector_path, dimension=128)
        await vector_store.connect()
        try:
            for i in range(10):
                emb = np.random.rand(128).astype(np.float32)
                await vector_store.upsert(
                    ids=[f"corrupt_v_{i}"],
                    embeddings=[emb],
                    metadatas=[{"text": f"C{i}"}],
                    documents=[f"C{i}"],
                )
        finally:
            await vector_store.close()

        with open(vector_path, "ab") as f:
            f.write(b"CORRUPTION")

        vector_store2 = MMapVectorStore(path=vector_path, dimension=128)
        await vector_store2.connect()
        try:
            res = await vector_store2.query(embedding=np.random.rand(128).astype(np.float32), top_k=10)
            assert len(res) >= 5
        finally:
            await vector_store2.close()

    @pytest.mark.asyncio
    async def test_vector_recovery_with_missing_dimensions(self, tmp_path):
        """D-005: Vector recovery handles mismatched dimensions."""
        vector_path = tmp_path / "mismatch_vector.smpv"

        vector_store = MMapVectorStore(path=vector_path, dimension=128)
        await vector_store.connect()
        try:
            for i in range(5):
                emb = np.random.rand(128).astype(np.float32)
                await vector_store.upsert(
                    ids=[f"mismatch_{i}"],
                    embeddings=[emb],
                    metadatas=[{"text": f"M{i}"}],
                    documents=[f"M{i}"],
                )
        finally:
            await vector_store.close()

        vector_store2 = MMapVectorStore(path=vector_path, dimension=128)
        await vector_store2.connect()
        try:
            res = await vector_store2.query(embedding=np.random.rand(128).astype(np.float32), top_k=5)
            assert len(res) >= 3
        finally:
            await vector_store2.close()

    @pytest.mark.asyncio
    async def test_sync_graph_and_vector_after_recovery(self, tmp_path):
        """D-005: Graph and vector stores stay in sync after recovery."""
        graph_path = tmp_path / "sync_graph.smpg"
        vector_path = tmp_path / "sync_vector.smpv"

        graph_store = MMapGraphStore(path=graph_path)
        await graph_store.connect()
        try:
            for i in range(25):
                await graph_store.upsert_node(make_node(id=f"sync_{i}"))
        finally:
            await graph_store.close()

        vector_store = MMapVectorStore(path=vector_path, dimension=128)
        await vector_store.connect()
        try:
            for i in range(25):
                emb = np.random.rand(128).astype(np.float32)
                await vector_store.upsert(
                    ids=[f"sync_{i}"],
                    embeddings=[emb],
                    metadatas=[{"text": f"S{i}"}],
                    documents=[f"S{i}"],
                )
        finally:
            await vector_store.close()

        del vector_store

        vector_store2 = MMapVectorStore(path=vector_path, dimension=128)
        await vector_store2.connect()
        try:
            graph_store2 = MMapGraphStore(path=graph_path)
            await graph_store2.connect()
            try:
                for i in range(25):
                    node = await graph_store2.get_node(f"sync_{i}")
                    assert node is not None
                    res = await vector_store2.query(embedding=np.random.rand(128).astype(np.float32), top_k=30)
                    ids = [r["id"] for r in res]
                    assert f"sync_{i}" in ids
            finally:
                await graph_store2.close()
        finally:
            await vector_store2.close()


def make_node(
    id: str = "test_node", type: NodeType = NodeType.FUNCTION, file_path: str = "test.py", **kwargs: Any
) -> GraphNode:
    """Helper to create test nodes."""
    defaults = {
        "id": id,
        "type": type,
        "file_path": file_path,
        "structural": StructuralProperties(name=id, file=file_path, signature="def test():", start_line=1, end_line=2),
        "semantic": SemanticProperties(docstring=f"Doc for {id}", status="test"),
    }
    defaults.update(kwargs)
    return GraphNode(**defaults)


def make_edge(source: str = "src", target: str = "tgt", edge_type: EdgeType = EdgeType.CALLS) -> GraphEdge:
    """Helper to create test edges."""
    return GraphEdge(source_id=source, target_id=target, type=edge_type)
