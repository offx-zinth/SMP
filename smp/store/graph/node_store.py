from __future__ import annotations

import json
import struct
from typing import TYPE_CHECKING, Final

from smp.core.models import GraphNode, NodeType

if TYPE_CHECKING:
    from smp.store.graph.mmap_file import MMapFile

INODE_SIZE: Final[int] = 32
INDEX_MAGIC = b"SMPN"


class NodeStore:
    """Manages Inode storage and retrieval with mmap persistence."""

    def __init__(self, mmap_file: MMapFile, store_ptr_offset: int) -> None:
        self.mmap = mmap_file
        self.store_ptr_offset = store_ptr_offset
        self._offset_to_node: dict[int, GraphNode] = {}
        self._name_to_offsets: dict[str, list[int]] = {}
        self._type_to_offsets: dict[str, list[int]] = {}
        self._id_to_offset: dict[str, int] = {}
        self._next_data_offset = store_ptr_offset
        self._load_from_mmap()

    def _load_from_mmap(self) -> None:
        """Load node data from mmap file."""
        if not self.mmap.mmap:
            return
        try:
            data_end = self.mmap._data_end
            if data_end <= self.store_ptr_offset:
                return
            pos = self.store_ptr_offset
            while pos + 4 < data_end:
                magic = self.mmap.mmap[pos : pos + 4]
                if magic != INDEX_MAGIC:
                    break
                pos += 4
                size_bytes = self.mmap.mmap[pos : pos + 4]
                if len(size_bytes) < 4:
                    break
                size = struct.unpack("<I", size_bytes)[0]
                pos += 4
                if pos + size > data_end:
                    break
                record = self.mmap.mmap[pos : pos + size]
                pos += size
                try:
                    data = json.loads(record.decode("utf-8"))
                    node = GraphNode(
                        id=data["id"],
                        type=NodeType(data["type"]),
                        file_path=data["file_path"],
                        structural=data["structural"],
                        semantic=data["semantic"],
                    )
                    offset = data["offset"]
                    self._offset_to_node[offset] = node
                    self._id_to_offset[node.id] = offset
                    name = node.structural.name
                    if name not in self._name_to_offsets:
                        self._name_to_offsets[name] = []
                    self._name_to_offsets[name].append(offset)
                    type_key = node.type.value
                    if type_key not in self._type_to_offsets:
                        self._type_to_offsets[type_key] = []
                    self._type_to_offsets[type_key].append(offset)
                    self._next_data_offset = offset + INODE_SIZE
                except (json.JSONDecodeError, KeyError, ValueError):
                    break
        except Exception:
            pass

    def upsert(self, node: GraphNode) -> int:
        """Serialize GraphNode to mmap and return its offset."""
        if node.id in self._id_to_offset:
            offset = self._id_to_offset[node.id]
            old_node = self._offset_to_node.get(offset)
            if old_node:
                old_name = old_node.structural.name
                if old_name in self._name_to_offsets and offset in self._name_to_offsets[old_name]:
                    self._name_to_offsets[old_name].remove(offset)
                old_type = old_node.type.value
                if old_type in self._type_to_offsets and offset in self._type_to_offsets[old_type]:
                    self._type_to_offsets[old_type].remove(offset)
        else:
            offset = self._next_data_offset
            self._next_data_offset += INODE_SIZE

        data = {
            "id": node.id,
            "type": node.type.value,
            "file_path": node.file_path,
            "structural": {
                "name": node.structural.name,
                "file": node.structural.file,
                "signature": node.structural.signature,
                "start_line": node.structural.start_line,
                "end_line": node.structural.end_line,
                "complexity": node.structural.complexity,
                "lines": node.structural.lines,
                "parameters": node.structural.parameters,
            },
            "semantic": {
                "status": node.semantic.status,
                "docstring": node.semantic.docstring,
                "description": node.semantic.description,
                "inline_comments": node.semantic.inline_comments,
                "decorators": node.semantic.decorators,
                "annotations": node.semantic.annotations,
                "tags": node.semantic.tags,
                "score": node.semantic.score,
                "manually_set": node.semantic.manually_set,
                "source_hash": node.semantic.source_hash,
                "enriched_at": node.semantic.enriched_at,
            },
            "offset": offset,
        }
        payload = json.dumps(data).encode("utf-8")
        header = INDEX_MAGIC + struct.pack("<I", len(payload))
        self.mmap.append_data(header + payload)

        self._offset_to_node[offset] = node
        self._id_to_offset[node.id] = offset

        if node.structural.name not in self._name_to_offsets:
            self._name_to_offsets[node.structural.name] = []
        self._name_to_offsets[node.structural.name].append(offset)

        type_key = node.type.value
        if type_key not in self._type_to_offsets:
            self._type_to_offsets[type_key] = []
        self._type_to_offsets[type_key].append(offset)

        return offset

    def get(self, offset: int) -> GraphNode | None:
        """Read Inode data from offset."""
        if offset < 0:
            raise ValueError(f"Invalid offset: {offset}")
        return self._offset_to_node.get(offset)

    def delete(self, offset: int) -> None:
        """Delete a node from storage."""
        node = self._offset_to_node.pop(offset, None)
        if node:
            if node.id in self._id_to_offset:
                del self._id_to_offset[node.id]
            if node.structural.name in self._name_to_offsets:
                if offset in self._name_to_offsets[node.structural.name]:
                    self._name_to_offsets[node.structural.name].remove(offset)
                if not self._name_to_offsets[node.structural.name]:
                    del self._name_to_offsets[node.structural.name]
            if node.type.value in self._type_to_offsets:
                if offset in self._type_to_offsets[node.type.value]:
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
