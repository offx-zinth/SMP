from __future__ import annotations

import struct
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from smp.store.graph.mmap_file import MMapFile


class EdgeStore:
    """Manages variable-length adjacency lists."""

    def __init__(self, mmap_file: MMapFile) -> None:
        self.mmap = mmap_file

    def write_edges(self, source_offset: int, targets: list[tuple[int, int]]) -> int:
        """Write edge list for a node and return its pointer."""
        count = len(targets)
        payload = struct.pack("<I", count)
        for target_off, etype in targets:
            payload += struct.pack("<II", target_off, etype)

        ptr = self.mmap.append_data(payload)
        return ptr

    def read_edges(self, ptr: int) -> list[tuple[int, int]]:
        """Read edges from a pointer."""
        assert self.mmap.mmap is not None
        count_data = self.mmap.mmap[ptr : ptr + 4]
        if len(count_data) < 4:
            return []

        count = struct.unpack("<I", count_data)[0]
        edges: list[tuple[int, int]] = []

        for i in range(count):
            offset = ptr + 4 + (i * 8)
            edge_data = self.mmap.mmap[offset : offset + 8]
            if len(edge_data) < 8:
                break
            target_off, etype = struct.unpack("<II", edge_data)
            edges.append((target_off, etype))

        return edges
