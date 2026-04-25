"""Low-level memory-mapped file used as the SMP graph backing store.

Layout::

    [Header        : 4 KiB ]
        magic, version, flags, header CRC, data-region end pointer,
        WAL head/tail pointers, root pointers (reserved for future use)
    [WAL region    : 64 KiB]  reserved for the write-ahead log
    [Data region   : grows ]  append-only journal of mutation records

The header carries an absolute byte offset (``data_end``) marking the
position immediately past the last fully-written journal record.  The
file may be longer than ``data_end`` because we round growths up to a
page; only bytes ``[data_region_start, data_end)`` are considered valid
journal content.

The :class:`MMapFile` owns the file lifecycle (open/close/grow/flush) and
exposes :meth:`append_data` so :class:`smp.store.graph.journal.Journal`
can serialise records without managing geometry.
"""

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
WAL_SIZE: Final[int] = 64 * 1024  # 64KB WAL region
PAGE_SIZE: Final[int] = 4096
INITIAL_DATA_PAGES: Final[int] = 16  # 64 KiB initial data region
DATA_GROW_FACTOR: Final[float] = 1.5

DATA_REGION_START: Final[int] = HEADER_SIZE + WAL_SIZE

# -- Header offsets (within the 4 KiB header) ----------------------------------

OFF_MAGIC: Final[int] = 0
OFF_VERSION: Final[int] = 4
OFF_FLAGS: Final[int] = 6
OFF_CRC: Final[int] = 8
OFF_ROOTS: Final[int] = 12  # 4 reserved root pointers (16 bytes total)
OFF_WAL_HEAD: Final[int] = 64
OFF_WAL_TAIL: Final[int] = 68
OFF_DATA_END: Final[int] = 72  # u64 — absolute byte offset

# -- WAL record types (kept for backwards compat / phase 2) --------------------

WAL_TYPE_INSERT: Final[int] = 0x01
WAL_TYPE_DELETE: Final[int] = 0x02
WAL_TYPE_BEGIN: Final[int] = 0x05
WAL_TYPE_COMMIT: Final[int] = 0x06


class WALRecord:
    """A single record written to the WAL region (Phase 2 use)."""

    def __init__(self, rtype: int, payload: bytes) -> None:
        self.rtype = rtype
        self.payload = payload

    def serialize(self) -> bytes:
        size = len(self.payload)
        header = struct.pack("<BBBI", self.rtype, 0, 0, size)
        crc = zlib.crc32(header + self.payload) & 0xFFFFFFFF
        return header + struct.pack("<I", crc) + self.payload


class MMapFile:
    """Memory-mapped file with a tracked append-only data region.

    The class is *not* thread-safe; serialise writes externally if you
    have multiple producers.  Reads through the mmap buffer are safe
    because the OS handles page-level coherency on the same process.
    """

    def __init__(self, path: Path) -> None:
        self.path = path
        self.fd: int = -1
        self.mmap: mmap.mmap | None = None
        self._size: int = 0
        # Filled on open():
        self._data_end: int = DATA_REGION_START

    # -- properties -----------------------------------------------------

    @property
    def data_region_start(self) -> int:
        """Offset of the first byte of the data region."""
        return DATA_REGION_START

    @property
    def data_region_end(self) -> int:
        """Offset immediately past the last committed journal byte."""
        return self._data_end

    @property
    def size(self) -> int:
        """Current on-disk file size in bytes (may exceed ``data_region_end``)."""
        return self._size

    # -- lifecycle ------------------------------------------------------

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
            self._size = HEADER_SIZE + WAL_SIZE + INITIAL_DATA_PAGES * PAGE_SIZE
            os.ftruncate(self.fd, self._size)
            self.mmap = mmap.mmap(self.fd, self._size)
            self._init_header()
            self._data_end = DATA_REGION_START
            self._write_data_end(DATA_REGION_START)
            self.update_header_crc()
            self.flush()
        else:
            self._size = os.path.getsize(self.path)
            if self._size < HEADER_SIZE + WAL_SIZE:
                raise ValueError(f"File too small to be a valid SMPG file: {self.path}")
            self.mmap = mmap.mmap(self.fd, self._size)
            self._validate_header()
            self._data_end = self._read_data_end()
            if self._data_end < DATA_REGION_START or self._data_end > self._size:
                raise ValueError(
                    f"Corrupt data_end pointer: {self._data_end} "
                    f"(file size={self._size})"
                )
            self.replay_wal()

    def close(self) -> None:
        """Flush and close the file."""
        if self.mmap is not None:
            try:
                self.mmap.flush()
            except (ValueError, OSError):
                pass
            self.mmap.close()
            self.mmap = None
        if self.fd != -1:
            os.close(self.fd)
            self.fd = -1

    # -- data region append ---------------------------------------------

    def append_data(self, payload: bytes) -> int:
        """Append ``payload`` to the data region and return its offset.

        Grows the file if necessary so the entire payload plus subsequent
        journal records can be written without remapping every record.
        ``data_end`` in the header is updated atomically (single u64
        write) once the bytes have been copied.
        """
        assert self.mmap is not None
        size = len(payload)
        offset = self._data_end
        new_end = offset + size
        if new_end > self._size:
            target = max(int(self._size * DATA_GROW_FACTOR), new_end + PAGE_SIZE)
            self.grow(target)
            assert self.mmap is not None  # remapped
        self.mmap[offset:new_end] = payload
        self._data_end = new_end
        self._write_data_end(new_end)
        return offset

    def reset_data_region(self) -> None:
        """Drop all journal content (used by :meth:`Journal.truncate`)."""
        self._data_end = DATA_REGION_START
        self._write_data_end(DATA_REGION_START)
        self.update_header_crc()
        self.flush()

    def flush(self) -> None:
        """Flush dirty pages to disk."""
        if self.mmap is not None:
            self.mmap.flush()

    def fsync(self) -> None:
        """Force kernel-level fsync of the underlying fd."""
        self.flush()
        if self.fd != -1:
            try:
                os.fsync(self.fd)
            except OSError:
                pass

    # -- WAL -------------------------------------------------------------

    @property
    def _wal_start(self) -> int:
        return HEADER_SIZE

    @property
    def _wal_end(self) -> int:
        return HEADER_SIZE + WAL_SIZE

    def write_wal_record(self, rtype: int, payload: bytes) -> None:
        """Append a record to the WAL.  Auto-checkpoints when full."""
        assert self.mmap is not None
        record = WALRecord(rtype, payload).serialize()
        rec_size = len(record)
        head = struct.unpack("<I", self.mmap[OFF_WAL_HEAD : OFF_WAL_HEAD + 4])[0]
        if self._wal_start + head + rec_size > self._wal_end:
            self.checkpoint()
            head = 0
        pos = self._wal_start + head
        self.mmap[pos : pos + rec_size] = record
        new_head = head + rec_size
        self.mmap[OFF_WAL_HEAD : OFF_WAL_HEAD + 4] = struct.pack("<I", new_head)

    def read_wal_records(self) -> list[tuple[int, bytes]]:
        """Decode all WAL records currently in the buffer (FIFO order)."""
        assert self.mmap is not None
        head = struct.unpack("<I", self.mmap[OFF_WAL_HEAD : OFF_WAL_HEAD + 4])[0]
        records: list[tuple[int, bytes]] = []
        pos = 0
        while pos < head:
            if self._wal_start + pos + 7 > self._wal_end:
                break
            rtype = self.mmap[self._wal_start + pos]
            length = struct.unpack(
                "<I", self.mmap[self._wal_start + pos + 3 : self._wal_start + pos + 7]
            )[0]
            crc_pos = self._wal_start + pos + 7
            crc_stored = struct.unpack("<I", self.mmap[crc_pos : crc_pos + 4])[0]
            payload_pos = crc_pos + 4
            payload = bytes(self.mmap[payload_pos : payload_pos + length])
            header = bytes(self.mmap[self._wal_start + pos : self._wal_start + pos + 7])
            crc_actual = zlib.crc32(header + payload) & 0xFFFFFFFF
            if crc_actual != crc_stored:
                break
            records.append((rtype, payload))
            pos = (payload_pos - self._wal_start) + length
        return records

    def reset_wal(self) -> None:
        """Mark the WAL empty (used after checkpointing)."""
        assert self.mmap is not None
        self.mmap[OFF_WAL_HEAD : OFF_WAL_HEAD + 4] = struct.pack("<I", 0)
        self.mmap[OFF_WAL_TAIL : OFF_WAL_TAIL + 4] = struct.pack("<I", 0)

    def checkpoint(self) -> None:
        """Flush dirty pages and clear the WAL.

        After a checkpoint, every record previously written to the WAL
        is considered durable in the data region (it has either been
        applied to in-memory state and journaled, or is unrecoverable).
        """
        assert self.mmap is not None
        self.flush()
        self.reset_wal()
        self.update_header_crc()
        self.fsync()

    def replay_wal(self) -> list[tuple[int, bytes]]:
        """Return any WAL records present at open time.

        The store layer is responsible for re-applying the records (since
        only it knows how to interpret each payload).  This method does
        not modify the journal.
        """
        return self.read_wal_records()

    # -- header internals ----------------------------------------------

    def _init_header(self) -> None:
        assert self.mmap is not None
        self.mmap[OFF_MAGIC : OFF_MAGIC + 4] = MAGIC
        self.mmap[OFF_VERSION : OFF_VERSION + 2] = struct.pack("<H", VERSION)
        self.mmap[OFF_FLAGS : OFF_FLAGS + 2] = struct.pack("<H", 0)
        self.mmap[OFF_WAL_HEAD : OFF_WAL_HEAD + 4] = struct.pack("<I", 0)
        self.mmap[OFF_WAL_TAIL : OFF_WAL_TAIL + 4] = struct.pack("<I", 0)
        self.mmap[OFF_DATA_END : OFF_DATA_END + 8] = struct.pack("<Q", DATA_REGION_START)

    def _validate_header(self) -> None:
        assert self.mmap is not None
        if self.mmap[OFF_MAGIC : OFF_MAGIC + 4] != MAGIC:
            raise ValueError("Invalid magic bytes: not an SMPG file")
        version = struct.unpack("<H", self.mmap[OFF_VERSION : OFF_VERSION + 2])[0]
        if version > VERSION:
            raise ValueError(f"Unsupported version: {version}")
        stored_crc = struct.unpack("<I", self.mmap[OFF_CRC : OFF_CRC + 4])[0]
        header_data = self.mmap[OFF_ROOTS:HEADER_SIZE]
        actual_crc = zlib.crc32(header_data) & 0xFFFFFFFF
        if actual_crc != stored_crc:
            raise ValueError(
                f"Header CRC mismatch (stored=0x{stored_crc:08x}, "
                f"actual=0x{actual_crc:08x}); file may be corrupt"
            )

    def update_header_crc(self) -> None:
        assert self.mmap is not None
        header_data = self.mmap[OFF_ROOTS:HEADER_SIZE]
        crc = zlib.crc32(header_data) & 0xFFFFFFFF
        self.mmap[OFF_CRC : OFF_CRC + 4] = struct.pack("<I", crc)

    def _write_data_end(self, value: int) -> None:
        assert self.mmap is not None
        self.mmap[OFF_DATA_END : OFF_DATA_END + 8] = struct.pack("<Q", value)
        self.update_header_crc()

    def _read_data_end(self) -> int:
        assert self.mmap is not None
        return int(struct.unpack("<Q", self.mmap[OFF_DATA_END : OFF_DATA_END + 8])[0])

    # -- growth ---------------------------------------------------------

    def grow(self, new_size: int) -> None:
        """Resize the file (rounded up to a page) and re-mmap."""
        assert self.mmap is not None
        if new_size <= self._size:
            return
        new_size = (new_size + PAGE_SIZE - 1) // PAGE_SIZE * PAGE_SIZE
        self.mmap.flush()
        self.mmap.close()
        os.ftruncate(self.fd, new_size)
        self.mmap = mmap.mmap(self.fd, new_size)
        self._size = new_size

    # -- context manager ------------------------------------------------

    def __enter__(self) -> MMapFile:
        self.open()
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        self.close()
