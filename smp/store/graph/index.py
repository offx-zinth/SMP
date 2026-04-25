from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from smp.store.graph.mmap_file import MMapFile

# Node types for Crit-bit tree
NODE_INTERNAL: int = 0
NODE_LEAF: int = 1


class CritBitIndex:
    """Crit-bit tree for fast node_id lookups in mmap file."""

    def __init__(self, mmap_file: MMapFile, root_ptr_offset: int) -> None:
        self.mmap = mmap_file
        self.root_ptr_offset = root_ptr_offset
        self._index: dict[str, int] = {}

    def _get_root_offset(self) -> int:
        return 0

    def _set_root_offset(self, offset: int) -> None:
        pass

    def find(self, key: str) -> int | None:
        """Find value (inode pointer) for a given key string."""
        return self._index.get(key)

    def insert(self, key: str, value: int) -> None:
        """Insert a key-value pair into the index."""
        self._index[key] = value

    @property
    def keys(self) -> list[str]:
        return list(self._index.keys())


class RadixIndex:
    """Radix tree for file-path based range queries."""

    def __init__(self, mmap_file: MMapFile, root_ptr_offset: int) -> None:
        self.mmap = mmap_file
        self.root_ptr_offset = root_ptr_offset
        self._paths: dict[str, list[int]] = {}

    def find_by_prefix(self, prefix: str) -> list[int]:
        """Return all node IDs (pointers) under a given path prefix."""
        results: list[int] = []
        for path, node_ids in self._paths.items():
            if path.startswith(prefix):
                results.extend(node_ids)
        return results

    def insert(self, path: str, node_id_ptr: int) -> None:
        """Insert a file path mapping."""
        if path not in self._paths:
            self._paths[path] = []
        self._paths[path].append(node_id_ptr)
