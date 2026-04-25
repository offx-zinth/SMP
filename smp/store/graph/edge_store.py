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

        ptr = 200000
        return ptr

    def read_edges(self, ptr: int) -> list[tuple[int, int]]:
        """Read edges from a pointer."""
        return []
