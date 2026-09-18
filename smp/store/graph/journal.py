"""Append-only durable journal for graph mutations.

Records are written to the data region of an :class:`MMapFile` (after the
header and WAL).  Each record is length-prefixed, CRC-checked and tagged
with a small integer record type so we can replay the log on reopen and
rebuild the in-memory graph state.

This module is intentionally minimal: it knows how to serialise records,
write them to the underlying file, and walk them on replay.  Higher-level
semantics (node deletes overriding earlier upserts, transaction commit
boundaries, etc.) are the responsibility of the caller.

Record format::

    [type   : u8  ]  Record kind from :class:`RecordType`
    [flags  : u8  ]  Reserved (0) — used for compression / tx markers later
    [length : u32 ]  Payload length in bytes (little endian)
    [crc32  : u32 ]  CRC-32 of (type | flags | length | payload)
    [payload: ...  ] msgpack-encoded record body

Total fixed overhead per record: 10 bytes.
"""

from __future__ import annotations

import enum
import struct
import zlib
from collections.abc import Iterator
from typing import TYPE_CHECKING, Final

if TYPE_CHECKING:
    from smp.store.graph.mmap_file import MMapFile


RECORD_HEADER_SIZE: Final[int] = 10
RECORD_HEADER_FMT: Final[str] = "<BBII"


class RecordType(enum.IntEnum):
    """Tag identifying the meaning of a journal record."""

    NODE_UPSERT = 0x01
    NODE_DELETE = 0x02
    EDGE_UPSERT = 0x03
    FILE_DELETE = 0x04
    SESSION_UPSERT = 0x05
    SESSION_DELETE = 0x06
    LOCK_UPSERT = 0x07
    LOCK_RELEASE = 0x08
    LOCK_RELEASE_ALL = 0x09
    AUDIT_APPEND = 0x0A
    PARSE_STATUS = 0x0B
    BEGIN_TX = 0x0C
    COMMIT_TX = 0x0D
    ABORT_TX = 0x0E


class JournalCorruptionError(Exception):
    """Raised when a record cannot be decoded during replay."""

    def __init__(self, message: str, offset: int | None = None) -> None:
        super().__init__(message)
        self.offset = offset


class Journal:
    """Owns the data region of an :class:`MMapFile` and serialises records.

    The :class:`MMapFile` is responsible for tracking the data-region end
    pointer and growing the file when needed; ``Journal`` only encodes
    records and invokes :meth:`MMapFile.append_data`.
    """

    def __init__(self, mmap_file: MMapFile) -> None:
        self.file = mmap_file

    # -- writing ---------------------------------------------------------

    def append(self, rtype: RecordType, payload: bytes, *, fsync: bool = False) -> int:
        """Encode ``payload`` and append it to the data region.

        Returns the absolute byte offset of the record in the file.
        ``fsync=True`` requests a flush after the write.
        """
        return self.append_batch([(rtype, payload)], fsync=fsync)[0]

    def append_batch(self, records: list[tuple[RecordType, bytes]], *, fsync: bool = False) -> list[int]:
        """Encode multiple records and append them to the data region in one go.

        Returns a list of absolute byte offsets for each record.
        """
        if not records:
            return []

        encoded_records = [self._encode(rtype, payload) for rtype, payload in records]
        all_bytes = b"".join(encoded_records)

        start_offset = self.file.append_data(all_bytes)

        if fsync:
            self.file.flush()

        offsets: list[int] = []
        current_offset = start_offset
        for rec in encoded_records:
            offsets.append(current_offset)
            current_offset += len(rec)

        return offsets

    @staticmethod
    def _encode(rtype: RecordType, payload: bytes) -> bytes:
        length = len(payload)
        header_no_crc = struct.pack("<BBI", int(rtype), 0, length)
        crc = zlib.crc32(header_no_crc + payload) & 0xFFFFFFFF
        return header_no_crc + struct.pack("<I", crc) + payload

    # -- replay ----------------------------------------------------------

    def replay(self) -> Iterator[tuple[RecordType, bytes, int]]:
        """Yield ``(record_type, payload, offset)`` for every record in order.

        Stops at the first corrupted record (raises :class:`JournalCorruptionError`)
        unless the record sits exactly at the data-region end (which can
        happen for empty journals).
        """
        assert self.file.mmap is not None
        start = self.file.data_region_start
        end = self.file.data_region_end
        offset = start
        while offset < end:
            if offset + RECORD_HEADER_SIZE > end:
                raise JournalCorruptionError(f"Truncated record header at offset {offset} (data end={end})", offset)
            header = bytes(self.file.mmap[offset : offset + RECORD_HEADER_SIZE])
            rtype_int, flags, length, crc = struct.unpack(RECORD_HEADER_FMT, header)
            del flags
            payload_start = offset + RECORD_HEADER_SIZE
            payload_end = payload_start + length
            if payload_end > end:
                raise JournalCorruptionError(
                    f"Truncated record payload at offset {offset} (length={length}, data end={end})", offset
                )
            payload = bytes(self.file.mmap[payload_start:payload_end])
            expected = zlib.crc32(header[:6] + payload) & 0xFFFFFFFF
            if expected != crc:
                raise JournalCorruptionError(f"CRC mismatch at offset {offset}: got {crc}, expected {expected}", offset)
            try:
                rtype = RecordType(rtype_int)
            except ValueError as exc:
                raise JournalCorruptionError(f"Unknown record type {rtype_int} at offset {offset}", offset) from exc
            yield rtype, payload, offset
            offset = payload_end

    # -- maintenance -----------------------------------------------------

    def truncate(self) -> None:
        """Clear the journal (data region is reset to empty)."""
        self.file.reset_data_region()


__all__ = [
    "Journal",
    "JournalCorruptionError",
    "RECORD_HEADER_SIZE",
    "RecordType",
]
