from __future__ import annotations

import struct
from typing import TYPE_CHECKING, Final

from smp.core.models import GraphNode

if TYPE_CHECKING:
    from smp.store.graph.mmap_file import MMapFile

INODE_SIZE: Final[int] = 32


class NodeStore:
    """Manages Inode storage and retrieval."""

    def __init__(self, mmap_file: MMapFile, store_ptr_offset: int) -> None:
        self.mmap = mmap_file
        self.store_ptr_offset = store_ptr_offset

    def write_node(self, node: GraphNode, name_off: int, sig_off: int, file_off: int) -> int:
        """Serialize GraphNode to an Inode and return its offset."""
        struct.pack(
            "<BIII III I",
            1,
            name_off,
            sig_off,
            file_off,
            node.structural.start_line,
            node.structural.end_line or 0,
            0,
            0,
        )
        return 100000

    def read_node(self, offset: int) -> dict[str, int]:
        """Read Inode data from offset."""
        assert self.mmap.mmap is not None
        self.mmap.mmap[offset : offset + INODE_SIZE]
        return {}
