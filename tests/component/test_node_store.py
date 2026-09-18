from __future__ import annotations

from pathlib import Path

import pytest

from smp.core.models import GraphNode, NodeType, SemanticProperties, StructuralProperties
from smp.store.graph.mmap_file import MMapFile
from smp.store.graph.node_store import NodeStore


@pytest.fixture
def tmp_graph_file(tmp_path: Path) -> Path:
    return tmp_path / "test_nodes.smpg"


@pytest.fixture
def mmap_file(tmp_graph_file: Path) -> MMapFile:
    mmap_file = MMapFile(tmp_graph_file)
    mmap_file.open()
    yield mmap_file
    mmap_file.close()


@pytest.fixture
def node_store(mmap_file: MMapFile) -> NodeStore:
    # Use a pointer offset after the header and WAL region
    return NodeStore(mmap_file, store_ptr_offset=mmap_file.data_region_start)


@pytest.fixture
def make_node():
    def _make_node(
        node_id: str = "node_1",
        name: str = "test_node",
        node_type: NodeType = NodeType.FUNCTION,
        file_path: str = "/test/file.py",
        start_line: int = 10,
        end_line: int = 20,
        docstring: str = "Test docstring",
    ) -> GraphNode:
        return GraphNode(
            id=node_id,
            type=node_type,
            file_path=file_path,
            structural=StructuralProperties(
                name=name,
                file=file_path,
                start_line=start_line,
                end_line=end_line,
            ),
            semantic=SemanticProperties(
                docstring=docstring,
            ),
        )

    return _make_node


class TestNodeStoreBasic:
    """Test basic CRUD operations for NodeStore."""

    def test_upsert_and_get(self, node_store: NodeStore, make_node) -> None:
        node = make_node(node_id="n1", name="func1")
        offset = node_store.upsert(node)

        retrieved = node_store.get(offset)
        assert retrieved is not None
        assert retrieved.id == node.id
        assert retrieved.structural.name == "func1"

    def test_upsert_overwrite(self, node_store: NodeStore, make_node) -> None:
        node = make_node(node_id="n1", name="func1")
        offset = node_store.upsert(node)

        # Update the same node
        updated_node = make_node(node_id="n1", name="func1_updated")
        node_store.upsert(updated_node)

        retrieved = node_store.get(offset)
        assert retrieved.structural.name == "func1_updated"

    def test_delete_node(self, node_store: NodeStore, make_node) -> None:
        node = make_node(node_id="n1")
        offset = node_store.upsert(node)

        node_store.delete(offset)
        assert node_store.get(offset) is None

    def test_get_nonexistent(self, node_store: NodeStore) -> None:
        assert node_store.get(999999) is None


class TestNodeStoreIndexing:
    """Test indexing and retrieval by name and type."""

    def test_find_by_name(self, node_store: NodeStore, make_node) -> None:
        node1 = make_node(node_id="n1", name="shared_name")
        node2 = make_node(node_id="n2", name="shared_name")
        node3 = make_node(node_id="n3", name="other_name")

        off1 = node_store.upsert(node1)
        off2 = node_store.upsert(node2)
        off3 = node_store.upsert(node3)

        offsets = node_store.find_by_name("shared_name")
        assert len(offsets) == 2
        assert off1 in offsets
        assert off2 in offsets
        assert off3 not in offsets

    def test_find_by_type(self, node_store: NodeStore, make_node) -> None:
        node1 = make_node(node_id="n1", node_type=NodeType.FUNCTION)
        node2 = make_node(node_id="n2", node_type=NodeType.CLASS)
        node3 = make_node(node_id="n3", node_type=NodeType.FUNCTION)

        off1 = node_store.upsert(node1)
        off2 = node_store.upsert(node2)
        off3 = node_store.upsert(node3)

        offsets = node_store.find_by_type(NodeType.FUNCTION)
        assert len(offsets) == 2
        assert off1 in offsets
        assert off3 in offsets
        assert off2 not in offsets

    def test_find_by_name_empty(self, node_store: NodeStore) -> None:
        assert node_store.find_by_name("non_existent") == []


class TestNodeStoreStorage:
    """Test storage bounds, growth, and synchronization."""

    def test_storage_auto_growth(self, node_store: NodeStore, make_node) -> None:
        # Write enough nodes to force the MMapFile to grow
        # Assuming a reasonable inode size, 2000 nodes should trigger growth
        offsets = []
        for i in range(2000):
            node = make_node(node_id=f"n{i}")
            offsets.append(node_store.upsert(node))

        for off in offsets:
            assert node_store.get(off) is not None

    def test_mmap_synchronization(self, tmp_graph_file: Path, make_node) -> None:
        # Test that two NodeStore instances sharing the same file see the same data
        mmap1 = MMapFile(tmp_graph_file)
        mmap1.open()
        store1 = NodeStore(mmap1, mmap1.data_region_start)

        node = make_node(node_id="sync_node")
        offset = store1.upsert(node)
        mmap1.flush()
        mmap1.close()

        mmap2 = MMapFile(tmp_graph_file)
        mmap2.open()
        store2 = NodeStore(mmap2, mmap2.data_region_start)

        retrieved = store2.get(offset)
        assert retrieved is not None
        assert retrieved.id == "sync_node"
        mmap2.close()


class TestNodeStoreIntegrity:
    """Test corruption detection and robustness."""

    @pytest.mark.skip(reason="Requires mmap-level corruption detection")
    def test_corruption_detection(self, mmap_file: MMapFile, node_store: NodeStore, make_node) -> None:
        node = make_node(node_id="corrupt_me")
        offset = node_store.upsert(node)

        # Manually corrupt the data in the mmap
        # We'll flip some bits in the node data region
        mmap_file.mmap[offset] = mmap_file.mmap[offset] ^ 0xFF

        # Depending on implementation, this should either raise an error or return None
        # if it uses CRCs or magic bytes
        try:
            retrieved = node_store.get(offset)
            # If it didn't raise, it should at least not return the original node if it's corrupt
            if retrieved:
                assert retrieved.id != "corrupt_me"
        except (ValueError, RuntimeError):
            pass  # Corruption detected is a success

    def test_invalid_offset(self, node_store: NodeStore) -> None:
        with pytest.raises((ValueError, IndexError, RuntimeError)):
            node_store.get(-1)


class TestNodeStoreEdgeCases:
    """Test edge cases for NodeStore."""

    def test_empty_node_properties(self, node_store: NodeStore, make_node) -> None:
        node = make_node(name="", docstring="", file_path="")
        offset = node_store.upsert(node)
        retrieved = node_store.get(offset)
        assert retrieved.structural.name == ""
        assert retrieved.semantic.docstring == ""

    def test_large_properties(self, node_store: NodeStore, make_node) -> None:
        large_doc = "A" * 10_000  # 10KB docstring
        node = make_node(docstring=large_doc)
        offset = node_store.upsert(node)
        retrieved = node_store.get(offset)
        assert retrieved.semantic.docstring == large_doc

    def test_very_large_number_of_nodes(self, node_store: NodeStore, make_node) -> None:
        # Stress test
        offsets = [node_store.upsert(make_node(node_id=f"n{i}")) for i in range(5000)]
        assert len(offsets) == 5000
        assert node_store.get(offsets[-1]).id == "n4999"

    def test_collision_handling(self, node_store: NodeStore, make_node) -> None:
        # Test that multiple nodes with same name/type but different IDs are handled correctly
        node1 = make_node(node_id="n1", name="collision")
        node2 = make_node(node_id="n2", name="collision")

        off1 = node_store.upsert(node1)
        off2 = node_store.upsert(node2)

        assert off1 != off2
        assert len(node_store.find_by_name("collision")) == 2
