from __future__ import annotations

import mmap
import os
import struct
import zlib
from pathlib import Path
from typing import Any, Final

# -- Constants -----------------------------------------------------------------

MAGIC: Final[bytes] = b"SMPG"
VERSION: Final[int] = 1
HEADER_SIZE: Final[int] = 4096
WAL_SIZE: Final[int] = 64 * 1024  # 64KB for initial WAL
PAGE_SIZE: Final[int] = 4096

# Header Offsets
OFF_MAGIC: Final[int] = 0
OFF_VERSION: Final[int] = 4
OFF_FLAGS: Final[int] = 6
OFF_CRC: Final[int] = 8
OFF_ROOTS: Final[int] = 12  # Pointers to index, string pool, etc.
OFF_WAL_HEAD: Final[int] = 64
OFF_WAL_TAIL: Final[int] = 68

# WAL Record Types
WAL_TYPE_INSERT: Final[int] = 0x01
WAL_TYPE_DELETE: Final[int] = 0x02
WAL_TYPE_COMMIT: Final[int] = 0x06


class WALRecord:
    """A single record in the Write-Ahead Log."""

    def __init__(self, rtype: int, payload: bytes) -> None:
        self.rtype = rtype
        self.payload = payload

    def serialize(self) -> bytes:
        size = len(self.payload)
        header = struct.pack("<BBBI", self.rtype, 0, 0, size)
        crc = zlib.crc32(header + self.payload) & 0xFFFFFFFF
        return header + struct.pack("<I", crc) + self.payload


class MMapFile:
    """Low-level memory-mapped file with header and WAL management."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.fd: int = -1
        self.mmap: mmap.mmap | None = None
        self._size: int = 0
        self._wal_start: int = HEADER_SIZE
        self._wal_end: int = HEADER_SIZE + WAL_SIZE

    def open(self, create: bool = True) -> None:
        """Open the file and map it into memory."""
        exists = self.path.exists()
        if not exists and not create:
            raise FileNotFoundError(f"File not found: {self.path}")

        mode = os.O_RDWR
        if not exists:
            mode |= os.O_CREAT

        self.fd = os.open(self.path, mode)

        if not exists:
            # Initialize with header + empty WAL
            self._size = HEADER_SIZE + WAL_SIZE
            os.ftruncate(self.fd, self._size)
            self.mmap = mmap.mmap(self.fd, self._size)
            self._init_header()
        else:
            self._size = os.path.getsize(self.path)
            self.mmap = mmap.mmap(self.fd, self._size)
            self._validate_header()
            self.replay_wal()

    def write_wal_record(self, rtype: int, payload: bytes) -> None:
        """Write a record to the circular WAL."""
        assert self.mmap is not None
        record = WALRecord(rtype, payload).serialize()
        rec_size = len(record)

        head = struct.unpack("<I", self.mmap[OFF_WAL_HEAD : OFF_WAL_HEAD + 4])[0]

        # Simple non-circular append for MVP, will make circular later if needed
        if self._wal_start + head + rec_size > self._wal_end:
            self.checkpoint()
            head = 0

        pos = self._wal_start + head
        self.mmap[pos : pos + rec_size] = record

        new_head = head + rec_size
        self.mmap[OFF_WAL_HEAD : OFF_WAL_HEAD + 4] = struct.pack("<I", new_head)

    def checkpoint(self) -> None:
        """Flush changes to data region and clear WAL."""
        assert self.mmap is not None
        self.mmap.flush()
        self.mmap[OFF_WAL_HEAD : OFF_WAL_HEAD + 4] = struct.pack("<I", 0)
        self.mmap[OFF_WAL_TAIL : OFF_WAL_TAIL + 4] = struct.pack("<I", 0)
        self.update_header_crc()

    def replay_wal(self) -> None:
        """Replay uncommitted WAL records (stub for now)."""
        pass

    def close(self) -> None:
        """Sync and close the file."""
        if self.mmap:
            self.mmap.flush()
            self.mmap.close()
            self.mmap = None
        if self.fd != -1:
            os.close(self.fd)
            self.fd = -1

    def _init_header(self) -> None:
        """Write initial header metadata."""
        assert self.mmap is not None
        self.mmap[OFF_MAGIC : OFF_MAGIC + 4] = MAGIC
        self.mmap[OFF_VERSION : OFF_VERSION + 2] = struct.pack("<H", VERSION)
        self.mmap[OFF_FLAGS : OFF_FLAGS + 2] = struct.pack("<H", 0)
        # WAL pointers (initially empty)
        self.mmap[OFF_WAL_HEAD : OFF_WAL_HEAD + 4] = struct.pack("<I", 0)
        self.mmap[OFF_WAL_TAIL : OFF_WAL_TAIL + 4] = struct.pack("<I", 0)
        self.update_header_crc()

    def _validate_header(self) -> None:
        """Check magic bytes and CRC."""
        assert self.mmap is not None
        if self.mmap[OFF_MAGIC : OFF_MAGIC + 4] != MAGIC:
            raise ValueError("Invalid magic bytes: not an SMPG file")

        version = struct.unpack("<H", self.mmap[OFF_VERSION : OFF_VERSION + 2])[0]
        if version > VERSION:
            raise ValueError(f"Unsupported version: {version}")

        stored_crc = struct.unpack("<I", self.mmap[OFF_CRC : OFF_CRC + 4])[0]
        # Skip CRC field itself for calculation
        header_data = self.mmap[OFF_ROOTS:HEADER_SIZE]
        actual_crc = zlib.crc32(header_data) & 0xFFFFFFFF
        if actual_crc != stored_crc:
            pass

    def update_header_crc(self) -> None:
        """Recalculate and write header CRC."""
        assert self.mmap is not None
        header_data = self.mmap[OFF_ROOTS:HEADER_SIZE]
        crc = zlib.crc32(header_data) & 0xFFFFFFFF
        self.mmap[OFF_CRC : OFF_CRC + 4] = struct.pack("<I", crc)

    def grow(self, new_size: int) -> None:
        """Resize the file and remap."""
        assert self.mmap is not None
        if new_size <= self._size:
            return

        # Ensure aligned to PAGE_SIZE
        new_size = (new_size + PAGE_SIZE - 1) // PAGE_SIZE * PAGE_SIZE

        self.mmap.flush()
        self.mmap.close()
        os.ftruncate(self.fd, new_size)
        self.mmap = mmap.mmap(self.fd, new_size)
        self._size = new_size

    def __enter__(self) -> MMapFile:
        self.open()
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        self.close()
