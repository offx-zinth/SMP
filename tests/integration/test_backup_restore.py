from __future__ import annotations

import asyncio
import os
import shutil
import tarfile
import tempfile
from pathlib import Path
from typing import Any

import pytest

from smp.core.models import (
    EdgeType,
    GraphEdge,
    GraphNode,
    Language,
    NodeType,
    SemanticProperties,
    StructuralProperties,
)
from smp.observability.backup import backup, compact, restore
from smp.store.graph.mmap_store import MMapGraphStore


@pytest.fixture
async def test_store(tmp_path: Path) -> MMapGraphStore:
    graph_path = tmp_path / "backup_test.graph.smpg"
    store = MMapGraphStore(path=str(graph_path))
    await store.connect()
    try:
        yield store
    finally:
        await store.close()


@pytest.fixture
async def test_store_empty(tmp_path: Path) -> MMapGraphStore:
    graph_path = tmp_path / "backup_clean.graph.smpg"
    store = MMapGraphStore(path=str(graph_path))
    await store.connect()
    await store.clear()
    try:
        yield store
    finally:
        await store.close()


class TestBackupRestoreIntegration:
    """Integration tests for Backup/Restore operations across graph stores."""

    @pytest.mark.asyncio
    async def test_backup_creates_consistent_snapshot(self, test_store):
        """Test backup creates a consistent snapshot of the graph store."""
        nodes = [
            GraphNode(
                id=f"node_{i}",
                type=NodeType.FUNCTION,
                file_path=f"f{i}.py",
                structural=StructuralProperties(name=f"func_{i}"),
            )
            for i in range(10)
        ]
        for node in nodes:
            await test_store.upsert_node(node)

        backup_path = Path(str(test_store.path).replace(".smpg", "_backup.smpg"))
        await backup(test_store, backup_path)

        assert backup_path.exists()
        restored = MMapGraphStore(path=str(backup_path))
        await restored.connect()
        try:
            for node in nodes:
                retrieved = await restored.get_node(node.id)
                assert retrieved is not None
                assert retrieved.id == node.id
        finally:
            await restored.close()

    @pytest.mark.asyncio
    async def test_restore_replaces_graph_file(self, tmp_path):
        """Test restore atomically replaces the graph file."""
        original_path = tmp_path / "original.smpg"
        original = MMapGraphStore(path=str(original_path))
        await original.connect()
        node = GraphNode(
            id="original_node",
            type=NodeType.FUNCTION,
            file_path="orig.py",
            structural=StructuralProperties(name="original"),
        )
        await original.upsert_node(node)
        await original.flush()
        await original.close()

        backup_path = tmp_path / "backup.smpg"
        store2 = MMapGraphStore(path=str(original_path))
        await store2.connect()
        await backup(store2, backup_path)
        await store2.close()

        new_path = tmp_path / "restored.smpg"
        await restore(new_path, backup_path)

        assert new_path.exists()
        restored = MMapGraphStore(path=str(new_path))
        await restored.connect()
        try:
            node = await restored.get_node("original_node")
            assert node is not None
        finally:
            await restored.close()

    @pytest.mark.asyncio
    async def test_backup_preserves_node_data(self, test_store):
        """Test backup preserves all node data including properties."""
        node = GraphNode(
            id="full_node",
            type=NodeType.FUNCTION,
            file_path="full.py",
            structural=StructuralProperties(name="full_func"),
            semantic=SemanticProperties(tags=["api", "test"]),
        )
        await test_store.upsert_node(node)

        backup_path = Path(str(test_store.path).replace(".smpg", "_full.smpg"))
        await backup(test_store, backup_path)

        restored = MMapGraphStore(path=backup_path)
        await restored.connect()
        try:
            retrieved = await restored.get_node(node.id)
            assert retrieved is not None
            assert retrieved.semantic.tags == ["api", "test"]
        finally:
            await restored.close()

    @pytest.mark.asyncio
    async def test_backup_preserves_edges(self, test_store):
        """Test backup preserves edges between nodes."""
        node_a = GraphNode(
            id="edge_a",
            type=NodeType.FUNCTION,
            file_path="a.py",
            structural=StructuralProperties(name="a"),
        )
        node_b = GraphNode(
            id="edge_b",
            type=NodeType.FUNCTION,
            file_path="b.py",
            structural=StructuralProperties(name="b"),
        )
        edge = GraphEdge(
            source_id="edge_a",
            target_id="edge_b",
            type=EdgeType.CALLS,
        )

        await test_store.upsert_node(node_a)
        await test_store.upsert_node(node_b)
        await test_store.upsert_edge(edge)

        backup_path = Path(str(test_store.path).replace(".smpg", "_edges.smpg"))
        await backup(test_store, backup_path)

        restored = MMapGraphStore(path=backup_path)
        await restored.connect()
        try:
            edges_result = await restored.get_edges(node_a.id)
            assert len(edges_result) > 0
            assert len(edges_result) > 0
            retrieved_edge = edges_result[0]
            assert retrieved_edge.source_id == edge.source_id
            assert retrieved_edge.target_id == edge.target_id
        finally:
            await restored.close()

    @pytest.mark.asyncio
    async def test_backup_with_large_dataset(self, test_store):
        """Test backup handles a large number of nodes."""
        for i in range(100):
            node = GraphNode(
                id=f"large_{i}",
                type=NodeType.FUNCTION,
                file_path=f"l{i}.py",
                structural=StructuralProperties(name=f"large_{i}"),
            )
            await test_store.upsert_node(node)

        backup_path = Path(str(test_store.path).replace(".smpg", "_large.smpg"))
        await backup(test_store, backup_path)

        restored = MMapGraphStore(path=str(backup_path))
        await restored.connect()
        try:
            count = await restored.count_nodes()
            assert count == 100
        finally:
            await restored.close()

    @pytest.mark.asyncio
    async def test_restore_creates_sidecar_backup(self, tmp_path):
        """Test restore creates a sidecar backup of existing file."""
        original_path = tmp_path / "existing.smpg"
        store = MMapGraphStore(path=str(original_path))
        await store.connect()
        node = GraphNode(
            id="existing",
            type=NodeType.FUNCTION,
            file_path="e.py",
            structural=StructuralProperties(name="existing"),
        )
        await store.upsert_node(node)
        await store.flush()
        await store.close()

        backup_path = tmp_path / "backup.smpg"
        store2 = MMapGraphStore(path=str(original_path))
        await store2.connect()
        await backup(store2, backup_path)
        await store2.close()

        restored_path = tmp_path / "restored.smpg"
        await restore(restored_path, backup_path)

        sidecars = list(tmp_path.glob("existing.smpg.bak.*"))
        assert len(sidecars) > 0

    @pytest.mark.asyncio
    async def test_backup_after_multiple_upserts(self, test_store):
        """Test backup after multiple upsert cycles."""
        for cycle in range(3):
            for i in range(5):
                node = GraphNode(
                    id=f"cycle_{cycle}_node_{i}",
                    type=NodeType.FUNCTION,
                    file_path=f"c{cycle}_{i}.py",
                    structural=StructuralProperties(name=f"cycle_{cycle}_{i}"),
                )
                await test_store.upsert_node(node)

        backup_path = Path(str(test_store.path).replace(".smpg", "_cycles.smpg"))
        backup_path = Path(backup_path)
        await backup(test_store, backup_path)

        restored = MMapGraphStore(path=backup_path)
        await restored.connect()
        try:
            for cycle in range(3):
                for i in range(5):
                    node = await restored.get_node(f"cycle_{cycle}_node_{i}")
                    assert node is not None
        finally:
            await restored.close()

    @pytest.mark.asyncio
    async def test_restore_fails_for_missing_source(self, tmp_path):
        """Test restore raises error for missing source file."""
        with pytest.raises(FileNotFoundError):
            await restore(tmp_path / "target.smpg", tmp_path / "nonexistent.smpg")

    @pytest.mark.asyncio
    async def test_backup_empty_store(self, test_store_empty):
        """Test backup works with an empty graph store."""
        backup_path = Path(str(test_store_empty.path).replace(".smpg", "_empty.smpg"))
        await backup(test_store_empty, backup_path)

        assert backup_path.exists()

    @pytest.mark.asyncio
    async def test_compact_reduces_file_size(self, test_store):
        """Test compaction reduces works on the store."""
        for i in range(50):
            node = GraphNode(
                id=f"compact_{i}",
                type=NodeType.FUNCTION,
                file_path=f"c{i}.py",
                structural=StructuralProperties(name=f"compact_{i}"),
            )
            await test_store.upsert_node(node)

        for i in range(25):
            await test_store.delete_node(f"compact_{i}")

        result = await compact(test_store)
        after_size = result["after_bytes"]

        assert after_size > 0
        count = await test_store.count_nodes()
        assert count == 25

    @pytest.mark.asyncio
    async def test_compact_preserves_remaining_nodes(self, test_store):
        """Test compaction preserves remaining nodes."""
        for i in range(20):
            node = GraphNode(
                id=f"compact_preserve_{i}",
                type=NodeType.FUNCTION,
                file_path=f"cp{i}.py",
                structural=StructuralProperties(name=f"compact_preserve_{i}"),
            )
            await test_store.upsert_node(node)

        for i in range(10):
            await test_store.delete_node(f"compact_preserve_{i}")

        await compact(test_store)

        for i in range(10, 20):
            node = await test_store.get_node(f"compact_preserve_{i}")
            assert node is not None

    @pytest.mark.asyncio
    async def test_compact_preserves_edges(self, test_store):
        """Test compaction preserves edges."""
        node_a = GraphNode(
            id="compact_edge_a",
            type=NodeType.FUNCTION,
            file_path="cea.py",
            structural=StructuralProperties(name="cea"),
        )
        node_b = GraphNode(
            id="compact_edge_b",
            type=NodeType.FUNCTION,
            file_path="ceb.py",
            structural=StructuralProperties(name="ceb"),
        )
        edge = GraphEdge(
            source_id="compact_edge_a",
            target_id="compact_edge_b",
            type=EdgeType.CALLS,
        )

        await test_store.upsert_node(node_a)
        await test_store.upsert_node(node_b)
        await test_store.upsert_edge(edge)

        await compact(test_store)

        retrieved = (await test_store.get_edges(source_id))[0]
        assert retrieved is not None

    @pytest.mark.asyncio
    async def test_backup_and_restore_roundtrip(self, test_store):
        """Test complete backup and restore roundtrip."""
        nodes = [
            GraphNode(
                id=f"roundtrip_{i}",
                type=NodeType.FUNCTION,
                file_path=f"r{i}.py",
                structural=StructuralProperties(name=f"roundtrip_{i}"),
            )
            for i in range(15)
        ]
        for node in nodes:
            await test_store.upsert_node(node)

        edge = GraphEdge("roundtrip_edge",
            source_id="roundtrip_0",
            target_id="roundtrip_1",
            type=EdgeType.CALLS,
        )
        await test_store.upsert_edge(edge)

        await test_store.flush()
        backup_path = Path(str(test_store.path).replace(".smpg", "_roundtrip.smpg"))
        backup_path = Path(backup_path)
        await backup(test_store, backup_path)

        await test_store.close()

        new_path_str = Path(str(test_store.path).replace("_roundtrip.smpg", "_restored.smpg"))
        new_path = Path(new_path_str)
        await restore(new_path, backup_path)

        restored = MMapGraphStore(path=new_path_str)
        await restored.connect()
        try:
            for i in range(15):
                node = await restored.get_node(f"roundtrip_{i}")
                assert node is not None
            retrieved_edge = (await restored.get_edges(source_id=edge.source_id))[0]
            assert retrieved_edge is not None
        finally:
            await restored.close()

    @pytest.mark.asyncio
    async def test_backup_with_different_node_types(self, test_store):
        """Test backup preserves different node types."""
        node_types = [
            GraphNode(id="func_node", type=NodeType.FUNCTION, file_path="f.py"),
            GraphNode(id="class_node", type=NodeType.CLASS, file_path="c.py"),
            GraphNode(id="var_node", type=NodeType.VARIABLE, file_path="v.py"),
            GraphNode(id="file_node", type=NodeType.FILE, file_path="test.py"),
        ]
        for node in node_types:
            await test_store.upsert_node(node)

        backup_path = Path(str(test_store.path).replace(".smpg", "_types.smpg"))
        backup_path = Path(backup_path)
        await backup(test_store, backup_path)

        restored = MMapGraphStore(path=backup_path)
        await restored.connect()
        try:
            for node in node_types:
                retrieved = await restored.get_node(node.id)
                assert retrieved is not None
                assert retrieved.type == node.type
        finally:
            await restored.close()

    @pytest.mark.asyncio
    async def test_backup_with_semantic_properties(self, test_store):
        """Test backup preserves semantic properties."""
        node = GraphNode(
            id="semantic_node",
            type=NodeType.FUNCTION,
            file_path="s.py",
            semantic=SemanticProperties(
                docstring="Test docstring",
                tags=["tag1", "tag2"],
            ),
        )
        await test_store.upsert_node(node)

        backup_path = Path(str(test_store.path).replace(".smpg", "_semantic.smpg"))
        backup_path = Path(backup_path)
        await backup(test_store, backup_path)

        restored = MMapGraphStore(path=backup_path)
        await restored.connect()
        try:
            retrieved = await restored.get_node("semantic_node")
            assert retrieved is not None
            assert retrieved.semantic.docstring == "Test docstring"
            assert retrieved.semantic.tags == ["tag1", "tag2"]
        finally:
            await restored.close()

    @pytest.mark.asyncio
    async def test_backup_with_structural_properties(self, test_store):
        """Test backup preserves structural properties."""
        node = GraphNode(
            id="structural_node",
            type=NodeType.FUNCTION,
            file_path="st.py",
            structural=StructuralProperties(
                name="test_func",
                file="st.py",
                signature="def test_func():",
                start_line=1,
                end_line=10,
            ),
        )
        await test_store.upsert_node(node)

        backup_path = Path(str(test_store.path).replace(".smpg", "_structural.smpg"))
        backup_path = Path(backup_path)
        await backup(test_store, backup_path)

        restored = MMapGraphStore(path=backup_path)
        await restored.connect()
        try:
            retrieved = await restored.get_node("structural_node")
            assert retrieved is not None
            assert retrieved.structural.name == "test_func"
            assert retrieved.structural.start_line == 1
            assert retrieved.structural.end_line == 10
        finally:
            await restored.close()

    @pytest.mark.asyncio
    async def test_backup_with_different_languages(self, test_store):
        """Test backup preserves language metadata."""
        node_python = GraphNode(
            id="py_node", type=NodeType.FUNCTION, file_path="p.py", language=Language.PYTHON
        )
        node_javascript = GraphNode(
            id="js_node", type=NodeType.FUNCTION, file_path="j.js", language=Language.JAVASCRIPT
        )
        node_rust = GraphNode(
            id="rs_node", type=NodeType.FUNCTION, file_path="r.rs", language=Language.RUST
        )

        await test_store.upsert_node(node_python)
        await test_store.upsert_node(node_javascript)
        await test_store.upsert_node(node_rust)

        backup_path = Path(str(test_store.path).replace(".smpg", "_lang.smpg"))
        backup_path = Path(backup_path)
        await backup(test_store, backup_path)

        restored = MMapGraphStore(path=backup_path)
        await restored.connect()
        try:
            py = await restored.get_node("py_node")
            js = await restored.get_node("js_node")
            rs = await restored.get_node("rs_node")
            assert py.language == Language.PYTHON
            assert js.language == Language.JAVASCRIPT
            assert rs.language == Language.RUST
        finally:
            await restored.close()

    @pytest.mark.asyncio
    async def test_backup_after_delete_operations(self, test_store):
        """Test backup after delete operations."""
        for i in range(10):
            node = GraphNode(
                id=f"del_{i}",
                type=NodeType.FUNCTION,
                file_path=f"d{i}.py",
                structural=StructuralProperties(name=f"delete_{i}"),
            )
            await test_store.upsert_node(node)

        await test_store.delete_node("del_0")
        await test_store.delete_node("del_1")
        await test_store.delete_node("del_2")

        backup_path = Path(str(test_store.path).replace(".smpg", "_after_del.smpg"))
        backup_path = Path(backup_path)
        await backup(test_store, backup_path)

        restored = MMapGraphStore(path=backup_path)
        await restored.connect()
        try:
            assert await restored.get_node("del_0") is None
            assert await restored.get_node("del_3") is not None
        finally:
            await restored.close()

    @pytest.mark.asyncio
    async def test_compact_after_delete_operations(self, test_store):
        """Test compaction after delete operations."""
        for i in range(10):
            node = GraphNode(
                id=f"compact_del_{i}",
                type=NodeType.FUNCTION,
                file_path=f"cd{i}.py",
                structural=StructuralProperties(name=f"compact_del_{i}"),
            )
            await test_store.upsert_node(node)

        await test_store.delete_node("compact_del_0")
        await test_store.delete_node("compact_del_1")

        await compact(test_store)

        for i in range(2, 10):
            node = await test_store.get_node(f"compact_del_{i}")
            assert node is not None

    @pytest.mark.asyncio
    async def test_backup_multiple_times(self, test_store):
        """Test creating multiple backups."""
        node1 = GraphNode(
            id="multi_backup",
            type=NodeType.FUNCTION,
            file_path="m.py",
            structural=StructuralProperties(name="multi_backup"),
        )
        await test_store.upsert_node(node1)

        backup_path = Path(str(test_store.path).replace(".smpg", "_backup1.smpg"))
        backup_path = Path(backup_path)
        await backup(test_store, backup_path)

        node2 = GraphNode(
            id="multi_backup_2",
            type=NodeType.FUNCTION,
            file_path="m2.py",
            structural=StructuralProperties(name="multi_backup_2"),
        )
        await test_store.upsert_node(node2)

        backup_path2 = Path(str(test_store.path).replace(".smpg", "_backup2.smpg"))
        await backup(test_store, backup_path2)

        assert backup_path.exists()
        assert backup_path2.exists()

    @pytest.mark.asyncio
    async def test_restore_overwrites_existing(self, tmp_path):
        """Test restore overwrites existing file."""
        target_path = tmp_path / "target.smpg"

        store1 = MMapGraphStore(path=str(target_path))
        await store1.connect()
        node_old = GraphNode(
            id="old_node",
            type=NodeType.FUNCTION,
            file_path="old.py",
            structural=StructuralProperties(name="old_node"),
        )
        await store1.upsert_node(node_old)
        await store1.flush()
        await store1.close()

        backup_path = tmp_path / "backup.smpg"
        store2 = MMapGraphStore(path=str(target_path))
        await store2.connect()
        node_new = GraphNode(
            id="new_node",
            type=NodeType.FUNCTION,
            file_path="new.py",
            structural=StructuralProperties(name="new_node"),
        )
        await store2.upsert_node(node_new)
        await store2.flush()
        await backup(store2, backup_path)
        await store2.close()

        await restore(target_path, backup_path)

        restored = MMapGraphStore(path=str(target_path))
        await restored.connect()
        try:
            node = await restored.get_node("new_node")
            assert node is not None
        finally:
            await restored.close()

    @pytest.mark.asyncio
    async def test_backup_edge_metadata_preserved(self, test_store):
        """Test backup preserves edge metadata."""
        node_src = GraphNode(
            id="src",
            type=NodeType.FUNCTION,
            file_path="src.py",
            structural=StructuralProperties(name="src"),
        )
        node_tgt = GraphNode(
            id="tgt",
            type=NodeType.FUNCTION,
            file_path="tgt.py",
            structural=StructuralProperties(name="tgt"),
        )
        edge = GraphEdge(
            source_id="src",
            target_id="tgt",
            type=EdgeType.CALLS,
            metadata={"weight": "1.5", "label": "test"},
        )

        await test_store.upsert_node(node_src)
        await test_store.upsert_node(node_tgt)
        await test_store.upsert_edge(edge)

        backup_path = Path(str(test_store.path).replace(".smpg", "_edge_meta.smpg"))
        await backup(test_store, backup_path)

        restored = MMapGraphStore(path=str(backup_path))
        await restored.connect()
        try:
            retrieved_edges = await restored.get_edges(source_id="src")
            assert len(retrieved_edges) > 0
            retrieved = retrieved_edges[0]
            assert retrieved.metadata["weight"] == "1.5"
            assert retrieved.metadata["label"] == "test"
        finally:
            await restored.close()

    @pytest.mark.asyncio
    async def test_backup_traverse_traversal_data(self, test_store):
        """Test backup preserves data needed for traversal."""
        node_a = GraphNode(
            id="traverse_a",
            type=NodeType.FUNCTION,
            file_path="ta.py",
            structural=StructuralProperties(name="traverse_a"),
        )
        node_b = GraphNode(
            id="traverse_b",
            type=NodeType.FUNCTION,
            file_path="tb.py",
            structural=StructuralProperties(name="traverse_b"),
        )
        node_c = GraphNode(
            id="traverse_c",
            type=NodeType.FUNCTION,
            file_path="tc.py",
            structural=StructuralProperties(name="traverse_c"),
        )
        edge_ab = GraphEdge(
            source_id="traverse_a",
            target_id="traverse_b",
            type=EdgeType.CALLS,
        )
        edge_bc = GraphEdge(
            source_id="traverse_b",
            target_id="traverse_c",
            type=EdgeType.CALLS,
        )

        await test_store.upsert_node(node_a)
        await test_store.upsert_node(node_b)
        await test_store.upsert_node(node_c)
        await test_store.upsert_edge(edge_ab)
        await test_store.upsert_edge(edge_bc)

        backup_path = Path(str(test_store.path).replace(".smpg", "_traverse.smpg"))
        await backup(test_store, backup_path)

        restored = MMapGraphStore(path=str(backup_path))
        await restored.connect()
        try:
            neighbors = await restored.traverse("traverse_a", relationship=EdgeType.CALLS)
            assert "traverse_b" in neighbors
        finally:
            await restored.close()

    @pytest.mark.asyncio
    async def test_backup_query_results_preserved(self, test_store):
        """Test backup preserves data for query operations."""
        nodes = [
            GraphNode(
                id=f"query_{i}",
                type=NodeType.FUNCTION,
                file_path=f"q{i}.py",
                structural=StructuralProperties(name=f"query_name_{i}"),
            )
            for i in range(5)
        ]
        for node in nodes:
            await test_store.upsert_node(node)

        backup_path = Path(str(test_store.path).replace(".smpg", "_query.smpg"))
        await backup(test_store, backup_path)

        restored = MMapGraphStore(path=str(backup_path))
        await restored.connect()
        try:
            results = await restored.find_nodes(name="query_name_0")
            assert len(results) > 0
        finally:
            await restored.close()