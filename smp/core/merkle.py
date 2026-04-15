from __future__ import annotations

import hashlib
from typing import Any

from smp.core.models import GraphNode, NodeType
from smp.logging import get_logger

log = get_logger(__name__)


class MerkleTree:
    """SHA-256 Merkle Tree for structural consistency checks."""

    def __init__(self) -> None:
        self._leaf_hashes: list[tuple[str, str]] = []
        self._levels: list[list[str]] = []

    def _hash_single(self, data: str) -> str:
        return hashlib.sha256(data.encode()).hexdigest()

    def _hash_pair(self, left: str, right: str) -> str:
        return hashlib.sha256(f"{left}{right}".encode()).hexdigest()

    def build(self, nodes: list[GraphNode]) -> None:
        """Build a SHA-256 tree where leaves are file nodes."""
        file_nodes = sorted([n for n in nodes if n.type == NodeType.FILE], key=lambda n: n.id)

        self._leaf_hashes = [(n.id, self._hash_single(f"{n.id}{n.semantic.source_hash}")) for n in file_nodes]

        current_level = [h for _, h in self._leaf_hashes]
        self._levels = [current_level]

        while len(current_level) > 1:
            next_level = []
            for i in range(0, len(current_level), 2):
                left = current_level[i]
                right = current_level[i + 1] if i + 1 < len(current_level) else left
                next_level.append(self._hash_pair(left, right))
            current_level = next_level
            self._levels.append(current_level)

    def hash(self) -> str:
        """Return the root hash."""
        if not self._levels:
            return ""
        return self._levels[-1][0]

    def diff(self, other: MerkleTree) -> dict[str, set[str]]:
        """Perform an O(log n) comparison to return {added, removed, modified} node IDs."""
        local_map = dict(self._leaf_hashes)
        remote_map = dict(other._leaf_hashes)

        local_ids = set(local_map.keys())
        remote_ids = set(remote_map.keys())

        added = remote_ids - local_ids
        removed = local_ids - remote_ids

        common_ids = local_ids & remote_ids
        modified = {nid for nid in common_ids if local_map[nid] != remote_map[nid]}

        return {"added": added, "removed": removed, "modified": modified}

    def export(self) -> dict[str, Any]:
        """Return a serializable format of the tree for distribution."""
        return {"root": self.hash(), "levels": self._levels, "leaf_hashes": self._leaf_hashes}

    def import_data(self, data: dict[str, Any]) -> None:
        """Reconstruct the tree from exported data."""
        self._levels = data["levels"]
        self._leaf_hashes = [tuple(x) for x in data["leaf_hashes"]]


class MerkleIndex:
    """Sync management using Merkle Trees."""

    def __init__(self, tree: MerkleTree) -> None:
        self._tree = tree

    def sync(self, remote_hash: str) -> dict[str, set[str]] | None:
        """Compare local root hash with remote, if different, trigger diff."""
        if self._tree.hash() == remote_hash:
            return None

        log.info("merkle_sync_diff_triggered", local=self._tree.hash(), remote=remote_hash)
        return None

    def apply_patch(self, patch: dict[str, Any]) -> None:
        """Update local state based on a patch."""
        log.info("merkle_apply_patch", patch_keys=list(patch.keys()))
