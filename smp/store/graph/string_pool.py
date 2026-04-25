from __future__ import annotations

import struct
import zlib
from typing import TYPE_CHECKING, Final

if TYPE_CHECKING:
    from smp.store.graph.mmap_file import MMapFile

STRING_BLOCK_SIZE: Final[int] = 1024 * 1024  # 1MB initial string pool


class StringPool:
    """Deduplicated string storage (atom table)."""

    def __init__(self, mmap_file: MMapFile, pool_ptr_offset: int) -> None:
        self.mmap = mmap_file
        self.pool_ptr_offset = pool_ptr_offset
        self._cache: dict[int, int] = {}

    def _get_pool_start(self) -> int:
        assert self.mmap.mmap is not None
        raw = self.mmap.mmap[self.pool_ptr_offset : self.pool_ptr_offset + 4]
        result: tuple[int, ...] = struct.unpack("<I", raw)
        return result[0]

    def get_or_insert(self, s: str) -> int:
        """Return offset of string in pool, inserting if new."""
        data = s.encode("utf-8")
        h = zlib.crc32(data) & 0xFFFFFFFF

        if h in self._cache:
            return self._cache[h]

        offset = self._append_string(data)
        self._cache[h] = offset
        return offset

    def _append_string(self, data: bytes) -> int:
        """Append raw bytes to the string pool region."""
        # Placeholder: just return an offset for now
        offset_val: int = 4096 + 65536 + 100
        return offset_val

    def get_string(self, offset: int, length: int) -> str:
        """Retrieve string from pool at given offset."""
        assert self.mmap.mmap is not None
        result = self.mmap.mmap[offset : offset + length]
        return result.decode("utf-8")
