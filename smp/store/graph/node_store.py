from __future__ import annotations

from typing import TYPE_CHECKING, Final

from smp.core.models import GraphNode, NodeType

if TYPE_CHECKING:
    from smp.store.graph.mmap_file import MMapFile

INODE_SIZE: Final[int] = 32


class NodeStore:
    """Manages Inode storage and retrieval."""

    def __init__(self, mmap_file: MMapFile, store_ptr_offset: int) -> None:
        self.mmap = mmap_file
        self.store_ptr_offset = store_ptr_offset
        # In-memory indices for quick lookups
        self._offset_to_node: dict[int, GraphNode] = {}
        self._name_to_offsets: dict[str, list[int]] = {}
        self._type_to_offsets: dict[str, list[int]] = {}
        self._id_to_offset: dict[str, int] = {}

    def upsert(self, node: GraphNode) -> int:
        """Serialize GraphNode to an Inode and return its offset."""
        # Check if node already exists
        if node.id in self._id_to_offset:
            offset = self._id_to_offset[node.id]
            # Remove from old indices
            old_node = self._offset_to_node.get(offset)
            if old_node:
                if old_node.structural.name in self._name_to_offsets:
                    self._name_to_offsets[old_node.structural.name].remove(offset)
                if old_node.type.value in self._type_to_offsets:
                    self._type_to_offsets[old_node.type.value].remove(offset)
        else:
            # Allocate new offset
            offset = self.store_ptr_offset + len(self._offset_to_node) * INODE_SIZE

        # Store in memory indices
        self._offset_to_node[offset] = node
        self._id_to_offset[node.id] = offset

        # Index by name
        if node.structural.name not in self._name_to_offsets:
            self._name_to_offsets[node.structural.name] = []
        self._name_to_offsets[node.structural.name].append(offset)

        # Index by type
        if node.type.value not in self._type_to_offsets:
            self._type_to_offsets[node.type.value] = []
        self._type_to_offsets[node.type.value].append(offset)

        return offset

    def get(self, offset: int) -> GraphNode | None:
        """Read Inode data from offset."""
        return self._offset_to_node.get(offset)

    def delete(self, offset: int) -> None:
        """Delete a node from storage."""
        node = self._offset_to_node.pop(offset, None)
        if node:
            if node.id in self._id_to_offset:
                del self._id_to_offset[node.id]
            if node.structural.name in self._name_to_offsets:
                self._name_to_offsets[node.structural.name].remove(offset)
                if not self._name_to_offsets[node.structural.name]:
                    del self._name_to_offsets[node.structural.name]
            if node.type.value in self._type_to_offsets:
                self._type_to_offsets[node.type.value].remove(offset)
                if not self._type_to_offsets[node.type.value]:
                    del self._type_to_offsets[node.type.value]

    def find_by_name(self, name: str) -> list[int]:
        """Find all node offsets with given name."""
        offsets = self._name_to_offsets.get(name, [])
        return [offset for offset in offsets if offset in self._offset_to_node]

    def find_by_type(self, node_type: NodeType) -> list[int]:
        """Find all node offsets with given type."""
        type_key = node_type.value if isinstance(node_type, NodeType) else str(node_type)
        offsets = self._type_to_offsets.get(type_key, [])
        return [offset for offset in offsets if offset in self._offset_to_node]

    def read_node(self, offset: int) -> dict[str, int]:
        """Read Inode data from offset (legacy method)."""
        node = self._offset_to_node.get(offset)
        if not node:
            return {}
        return {
            "flags": 1,
            "name_hash": hash(node.structural.name) & 0xFFFFFFFF,
            "sig_hash": hash(node.structural.signature) & 0xFFFFFFFF,
            "file_hash": hash(node.file_path) & 0xFFFFFFFF,
            "start_line": node.structural.start_line,
            "end_line": node.structural.end_line or 0,
            "id_hash": hash(node.id) & 0xFFFFFFFF,
        }
