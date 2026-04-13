"""Integration tests for MerkleTree and MerkleIndex."""

from __future__ import annotations

from smp.core.merkle import MerkleIndex, MerkleTree
from smp.core.models import GraphNode, NodeType, SemanticProperties, StructuralProperties


def make_file_node(
    node_id: str = "file_1",
    file_path: str = "src/app.py",
    source_hash: str = "abc123",
) -> GraphNode:
    """Create a FILE-type GraphNode for testing MerkleTree."""
    return GraphNode(
        id=node_id,
        type=NodeType.FILE,
        file_path=file_path,
        structural=StructuralProperties(name=file_path, file=file_path),
        semantic=SemanticProperties(source_hash=source_hash),
    )


class TestMerkleTree:
    """Tests for MerkleTree.build(), hash(), diff(), export(), import_data()."""

    def test_build_with_file_nodes(self) -> None:
        """Build tree from FILE nodes - no exceptions."""
        nodes = [
            make_file_node("file_1", "src/a.py", "hash1"),
            make_file_node("file_2", "src/b.py", "hash2"),
            make_file_node("file_3", "src/c.py", "hash3"),
        ]
        tree = MerkleTree()
        tree.build(nodes)
        assert tree.hash() != ""

    def test_build_with_mixed_node_types(self) -> None:
        """Build tree ignores non-FILE nodes."""
        nodes = [
            make_file_node("file_1", "src/a.py", "hash1"),
            GraphNode(
                id="func_1",
                type=NodeType.FUNCTION,
                file_path="src/a.py",
                structural=StructuralProperties(name="test_func"),
                semantic=SemanticProperties(),
            ),
        ]
        tree = MerkleTree()
        tree.build(nodes)
        assert tree.hash() != ""

    def test_build_empty(self) -> None:
        """Build with no FILE nodes results in empty _levels."""
        tree = MerkleTree()
        tree.build([])
        assert tree._levels == [[]]

    def test_hash_deterministic(self) -> None:
        """Same nodes produce same hash."""
        nodes = [
            make_file_node("file_1", "src/a.py", "hash1"),
            make_file_node("file_2", "src/b.py", "hash2"),
        ]
        tree1 = MerkleTree()
        tree1.build(nodes)
        tree2 = MerkleTree()
        tree2.build(nodes)
        assert tree1.hash() == tree2.hash()

    def test_hash_different_nodes_different_hash(self) -> None:
        """Different nodes produce different hashes."""
        tree1 = MerkleTree()
        tree1.build([make_file_node("file_1", "src/a.py", "hash1")])
        tree2 = MerkleTree()
        tree2.build([make_file_node("file_2", "src/b.py", "hash2")])
        assert tree1.hash() != tree2.hash()

    def test_diff_added(self) -> None:
        """Node added to remote appears in added set."""
        local_nodes = [make_file_node("file_1", "src/a.py", "hash1")]
        remote_nodes = [
            make_file_node("file_1", "src/a.py", "hash1"),
            make_file_node("file_2", "src/b.py", "hash2"),
        ]
        local = MerkleTree()
        local.build(local_nodes)
        remote = MerkleTree()
        remote.build(remote_nodes)
        diff = local.diff(remote)
        assert "file_2" in diff["added"]
        assert diff["removed"] == set()
        assert diff["modified"] == set()

    def test_diff_removed(self) -> None:
        """Node removed from remote appears in removed set."""
        local_nodes = [
            make_file_node("file_1", "src/a.py", "hash1"),
            make_file_node("file_2", "src/b.py", "hash2"),
        ]
        remote_nodes = [make_file_node("file_1", "src/a.py", "hash1")]
        local = MerkleTree()
        local.build(local_nodes)
        remote = MerkleTree()
        remote.build(remote_nodes)
        diff = local.diff(remote)
        assert diff["added"] == set()
        assert "file_2" in diff["removed"]
        assert diff["modified"] == set()

    def test_diff_modified(self) -> None:
        """Node with changed hash appears in modified set."""
        local_nodes = [make_file_node("file_1", "src/a.py", "hash1")]
        remote_nodes = [make_file_node("file_1", "src/a.py", "hash2")]
        local = MerkleTree()
        local.build(local_nodes)
        remote = MerkleTree()
        remote.build(remote_nodes)
        diff = local.diff(remote)
        assert diff["added"] == set()
        assert diff["removed"] == set()
        assert "file_1" in diff["modified"]

    def test_diff_no_changes(self) -> None:
        """Identical trees have no added/removed/modified."""
        nodes = [
            make_file_node("file_1", "src/a.py", "hash1"),
            make_file_node("file_2", "src/b.py", "hash2"),
        ]
        local = MerkleTree()
        local.build(nodes)
        remote = MerkleTree()
        remote.build(nodes)
        diff = local.diff(remote)
        assert diff["added"] == set()
        assert diff["removed"] == set()
        assert diff["modified"] == set()

    def test_export_returns_dict(self) -> None:
        """Export returns dict with expected keys."""
        tree = MerkleTree()
        tree.build([make_file_node("file_1", "src/a.py", "hash1")])
        exported = tree.export()
        assert "root" in exported
        assert "levels" in exported
        assert "leaf_hashes" in exported
        assert exported["root"] == tree.hash()

    def test_export_deterministic(self) -> None:
        """Same tree exports to same structure."""
        nodes = [make_file_node("file_1", "src/a.py", "hash1")]
        tree1 = MerkleTree()
        tree1.build(nodes)
        exp1 = tree1.export()
        tree2 = MerkleTree()
        tree2.build(nodes)
        exp2 = tree2.export()
        assert exp1["root"] == exp2["root"]

    def test_import_recreates_hash(self) -> None:
        """Import reconstructs tree with same hash."""
        nodes = [
            make_file_node("file_1", "src/a.py", "hash1"),
            make_file_node("file_2", "src/b.py", "hash2"),
        ]
        original = MerkleTree()
        original.build(nodes)
        exported = original.export()

        restored = MerkleTree()
        restored.import_data(exported)
        assert restored.hash() == original.hash()

    def test_roundtrip_lossless(self) -> None:
        """Round-trip export/import is lossless."""
        nodes = [
            make_file_node("file_1", "src/a.py", "hash1"),
            make_file_node("file_2", "src/b.py", "hash2"),
        ]
        original = MerkleTree()
        original.build(nodes)
        exported = original.export()

        restored = MerkleTree()
        restored.import_data(exported)
        restored_exp = restored.export()

        assert exported["root"] == restored_exp["root"]
        assert exported["leaf_hashes"] == restored_exp["leaf_hashes"]


class TestMerkleIndex:
    """Tests for MerkleIndex.sync() and apply_patch()."""

    def test_sync_in_sync(self) -> None:
        """When local_hash == remote_hash, sync returns None."""
        nodes = [make_file_node("file_1", "src/a.py", "hash1")]
        tree = MerkleTree()
        tree.build(nodes)
        index = MerkleIndex(tree)
        result = index.sync(tree.hash())
        assert result is None

    def test_sync_different_hash(self) -> None:
        """When different, sync returns None (triggers diff)."""
        tree = MerkleTree()
        tree.build([make_file_node("file_1", "src/a.py", "hash1")])
        index = MerkleIndex(tree)
        result = index.sync("different_hash")
        assert result is None

    def test_apply_patch_logs(self) -> None:
        """apply_patch executes without error."""
        tree = MerkleTree()
        tree.build([make_file_node("file_1", "src/a.py", "hash1")])
        index = MerkleIndex(tree)
        patch = {"added": ["file_2"], "removed": [], "modified": []}
        index.apply_patch(patch)
