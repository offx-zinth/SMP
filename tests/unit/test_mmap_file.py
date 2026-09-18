from __future__ import annotations

import os
import struct
import tempfile
import zlib
from collections.abc import Generator
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from smp.store.graph.mmap_file import (
    DATA_REGION_START,
    HEADER_SIZE,
    INITIAL_DATA_PAGES,
    MAGIC,
    OFF_CRC,
    OFF_DATA_END,
    OFF_FLAGS,
    OFF_MAGIC,
    OFF_VERSION,
    OFF_WAL_HEAD,
    OFF_WAL_TAIL,
    PAGE_SIZE,
    VERSION,
    WAL_SIZE,
    WAL_TYPE_COMMIT,
    WAL_TYPE_INSERT,
    MMapFile,
)


@pytest.fixture
def temp_dir() -> Generator[Path, None, None]:
    with tempfile.TemporaryDirectory() as td:
        yield Path(td)


class TestMMapFileConstants:
    def test_magic_bytes(self) -> None:
        assert MAGIC == b"SMPG"

    def test_version(self) -> None:
        assert VERSION == 1

    def test_header_size(self) -> None:
        assert HEADER_SIZE == 4096

    def test_wal_size(self) -> None:
        assert WAL_SIZE == 65536

    def test_page_size(self) -> None:
        assert PAGE_SIZE == 4096

    def test_initial_data_pages(self) -> None:
        assert INITIAL_DATA_PAGES == 16

    def test_data_region_start(self) -> None:
        assert DATA_REGION_START == HEADER_SIZE + WAL_SIZE


class TestMMapFileInit:
    def test_init_stores_path(self, temp_dir: Path) -> None:
        file_path = temp_dir / "test.mmap"
        mmap_file = MMapFile(file_path)
        assert mmap_file.path == file_path

    def test_init_sets_fd_to_minus_one(self, temp_dir: Path) -> None:
        mmap_file = MMapFile(temp_dir / "test.mmap")
        assert mmap_file.fd == -1

    def test_init_sets_mmap_to_none(self, temp_dir: Path) -> None:
        mmap_file = MMapFile(temp_dir / "test.mmap")
        assert mmap_file.mmap is None

    def test_init_sets_size_to_zero(self, temp_dir: Path) -> None:
        mmap_file = MMapFile(temp_dir / "test.mmap")
        assert mmap_file._size == 0

    def test_init_sets_data_end_to_data_region_start(self, temp_dir: Path) -> None:
        mmap_file = MMapFile(temp_dir / "test.mmap")
        assert mmap_file._data_end == DATA_REGION_START

    def test_init_data_region_start_property(self, temp_dir: Path) -> None:
        mmap_file = MMapFile(temp_dir / "test.mmap")
        assert mmap_file.data_region_start == DATA_REGION_START

    def test_init_data_region_end_property(self, temp_dir: Path) -> None:
        mmap_file = MMapFile(temp_dir / "test.mmap")
        assert mmap_file.data_region_end == DATA_REGION_START

    def test_init_size_property(self, temp_dir: Path) -> None:
        mmap_file = MMapFile(temp_dir / "test.mmap")
        assert mmap_file.size == 0


class TestMagicBytesVerification:
    def test_valid_magic_bytes(self, temp_dir: Path) -> None:
        file_path = temp_dir / "test.mmap"
        with MMapFile(file_path) as f:
            assert f.mmap is not None
            assert f.mmap[OFF_MAGIC : OFF_MAGIC + 4] == MAGIC

    def test_invalid_magic_bytes_raises(self, temp_dir: Path) -> None:
        file_path = temp_dir / "test.mmap"
        file_path.write_bytes(b"XXXX" + b"\x00" * (HEADER_SIZE + WAL_SIZE - 4))
        with pytest.raises(ValueError, match="Invalid magic bytes"), MMapFile(file_path):  # noqa: F841
            pass

    def test_corrupted_magic_detected(self, temp_dir: Path) -> None:
        file_path = temp_dir / "test.mmap"
        with MMapFile(file_path):
            pass
        corrupted = bytearray(file_path.read_bytes())
        corrupted[OFF_MAGIC : OFF_MAGIC + 4] = b"JUNK"
        file_path.write_bytes(corrupted)
        with pytest.raises(ValueError, match="Invalid magic bytes"), MMapFile(file_path):
            pass


class TestVersionChecking:
    def test_version_written(self, temp_dir: Path) -> None:
        file_path = temp_dir / "test.mmap"
        with MMapFile(file_path) as f:
            version = struct.unpack("<H", f.mmap[OFF_VERSION : OFF_VERSION + 2])[0]
            assert version == VERSION

    def test_future_version_raises(self, temp_dir: Path) -> None:
        file_path = temp_dir / "test.mmap"
        with MMapFile(file_path):
            pass
        modified = bytearray(file_path.read_bytes())
        modified[OFF_VERSION : OFF_VERSION + 2] = struct.pack("<H", VERSION + 1)
        file_path.write_bytes(modified)
        with pytest.raises(ValueError, match="Unsupported version"), MMapFile(file_path):
            pass


class TestHeaderCRC:
    def test_header_crc_written(self, temp_dir: Path) -> None:
        file_path = temp_dir / "test.mmap"
        with MMapFile(file_path) as f:
            stored_crc = struct.unpack("<I", f.mmap[OFF_CRC : OFF_CRC + 4])[0]
            header_data = f.mmap[12:HEADER_SIZE]
            actual_crc = zlib.crc32(header_data) & 0xFFFFFFFF
            assert stored_crc == actual_crc

    def test_corrupted_header_raises(self, temp_dir: Path) -> None:
        file_path = temp_dir / "test.mmap"
        with MMapFile(file_path):
            pass
        corrupted = bytearray(file_path.read_bytes())
        corrupted[OFF_CRC + 1] ^= 0xFF
        file_path.write_bytes(corrupted)
        with pytest.raises(ValueError, match="Header CRC mismatch"), MMapFile(file_path):
            pass


class TestFileHeader:
    def test_flags_initialized_to_zero(self, temp_dir: Path) -> None:
        file_path = temp_dir / "test.mmap"
        with MMapFile(file_path) as f:
            flags = struct.unpack("<H", f.mmap[OFF_FLAGS : OFF_FLAGS + 2])[0]
            assert flags == 0

    def test_wal_head_initialized(self, temp_dir: Path) -> None:
        file_path = temp_dir / "test.mmap"
        with MMapFile(file_path) as f:
            wal_head = struct.unpack("<I", f.mmap[OFF_WAL_HEAD : OFF_WAL_HEAD + 4])[0]
            assert wal_head == 0

    def test_wal_tail_initialized(self, temp_dir: Path) -> None:
        file_path = temp_dir / "test.mmap"
        with MMapFile(file_path) as f:
            wal_tail = struct.unpack("<I", f.mmap[OFF_WAL_TAIL : OFF_WAL_TAIL + 4])[0]
            assert wal_tail == 0

    def test_data_end_pointing_to_data_region_start(self, temp_dir: Path) -> None:
        file_path = temp_dir / "test.mmap"
        with MMapFile(file_path) as f:
            data_end = f._read_data_end()
            assert data_end == DATA_REGION_START


class TestOpenCreate:
    def test_open_creates_file_when_not_exists(self, temp_dir: Path) -> None:
        file_path = temp_dir / "new.mmap"
        assert not file_path.exists()
        with MMapFile(file_path):
            pass
        assert file_path.exists()

    def test_open_sets_correct_size(self, temp_dir: Path) -> None:
        file_path = temp_dir / "test.mmap"
        with MMapFile(file_path) as f:
            expected = HEADER_SIZE + WAL_SIZE + INITIAL_DATA_PAGES * PAGE_SIZE
            assert f._size == expected
            assert f.size == expected

    def test_open_mmaps_file(self, temp_dir: Path) -> None:
        file_path = temp_dir / "test.mmap"
        with MMapFile(file_path) as f:
            assert f.mmap is not None

    def test_open_no_create_raises_when_not_exists(self, temp_dir: Path) -> None:
        file_path = temp_dir / "nonexistent.mmap"
        with pytest.raises(FileNotFoundError):
            MMapFile(file_path).open(create=False)

    def test_open_file_too_small_raises(self, temp_dir: Path) -> None:
        file_path = temp_dir / "tiny.mmap"
        file_path.write_bytes(b"\x00" * 100)
        with pytest.raises(ValueError, match="File too small"):
            MMapFile(file_path).open()


class TestOpenExisting:
    def test_open_existing_file(self, temp_dir: Path) -> None:
        file_path = temp_dir / "existing.mmap"
        with MMapFile(file_path) as f1:
            pass
        with MMapFile(file_path) as f2:
            assert f2._size == f1._size
            assert f2._data_end == f1._data_end

    def test_open_loads_data_end(self, temp_dir: Path) -> None:
        file_path = temp_dir / "test.mmap"
        with MMapFile(file_path) as f:
            f.append_data(b"test data")
            f.flush()
        with MMapFile(file_path) as f:
            assert f._data_end > DATA_REGION_START

    def test_open_validates_header(self, temp_dir: Path) -> None:
        file_path = temp_dir / "test.mmap"
        with MMapFile(file_path):
            pass
        content = bytearray(file_path.read_bytes())
        content[OFF_MAGIC : OFF_MAGIC + 4] = b"XXXX"
        file_path.write_bytes(content)
        with pytest.raises(ValueError, match="Invalid magic bytes"), MMapFile(file_path):
            pass


class TestClose:
    def test_close_sets_mmap_to_none(self, temp_dir: Path) -> None:
        file_path = temp_dir / "test.mmap"
        with MMapFile(file_path) as f:
            pass
        assert f.mmap is None

    def test_close_closes_fd(self, temp_dir: Path) -> None:
        file_path = temp_dir / "test.mmap"
        mmap_file = MMapFile(file_path)
        mmap_file.open()
        mmap_file.close()
        assert mmap_file.fd == -1


class TestFlush:
    def test_flush_calls_mmap_flush(self, temp_dir: Path) -> None:
        file_path = temp_dir / "test.mmap"
        mmap_file = MMapFile(file_path)
        mmap_file.open()
        mmap_file.mmap = MagicMock()
        mmap_file.flush()
        mmap_file.mmap.flush.assert_called_once()


class TestFsync:
    def test_fsync_flushes_and_calls_fsync(self, temp_dir: Path) -> None:
        file_path = temp_dir / "test.mmap"
        mmap_file = MMapFile(file_path)
        mmap_file.open()
        mmap_file.fd = 5
        with patch.object(os, "fsync") as mock_fsync:
            mmap_file.fsync()
            mock_fsync.assert_called_once_with(5)

    def test_fsync_handles_oserror(self, temp_dir: Path) -> None:
        file_path = temp_dir / "test.mmap"
        mmap_file = MMapFile(file_path)
        mmap_file.open()
        mmap_file.fd = 999
        mmap_file.fsync()


class TestAppendData:
    def test_append_returns_offset(self, temp_dir: Path) -> None:
        file_path = temp_dir / "test.mmap"
        with MMapFile(file_path) as f:
            offset = f.append_data(b"test")
            assert offset == DATA_REGION_START

    def test_append_writes_data(self, temp_dir: Path) -> None:
        file_path = temp_dir / "test.mmap"
        with MMapFile(file_path) as f:
            payload = b"test data"
            offset = f.append_data(payload)
            assert f.mmap[offset : offset + len(payload)] == payload

    def test_append_updates_data_end(self, temp_dir: Path) -> None:
        file_path = temp_dir / "test.mmap"
        with MMapFile(file_path) as f:
            f.append_data(b"test")
            assert f._data_end == DATA_REGION_START + 4

    def test_append_multiple_records(self, temp_dir: Path) -> None:
        file_path = temp_dir / "test.mmap"
        with MMapFile(file_path) as f:
            f.append_data(b"first")
            f.append_data(b"second")
            assert f._data_end == DATA_REGION_START + 5 + 6

    def test_append_grows_file(self, temp_dir: Path) -> None:
        file_path = temp_dir / "test.mmap"
        with MMapFile(file_path) as f:
            initial_size = f._size
            large_payload = b"x" * (initial_size + 1)
            f.append_data(large_payload)
            assert f._size > initial_size


class TestResetDataRegion:
    def test_reset_clears_data_end(self, temp_dir: Path) -> None:
        file_path = temp_dir / "test.mmap"
        with MMapFile(file_path) as f:
            f.append_data(b"some data")
            f.reset_data_region()
            assert f._data_end == DATA_REGION_START

    def test_reset_updates_crc(self, temp_dir: Path) -> None:
        file_path = temp_dir / "test.mmap"
        with MMapFile(file_path) as f:
            f.append_data(b"data")
            f.reset_data_region()
            stored_crc = struct.unpack("<I", f.mmap[OFF_CRC : OFF_CRC + 4])[0]
            header_data = f.mmap[12:HEADER_SIZE]
            actual_crc = zlib.crc32(header_data) & 0xFFFFFFFF
            assert stored_crc == actual_crc


class TestGrow:
    def test_grow_increases_size(self, temp_dir: Path) -> None:
        file_path = temp_dir / "test.mmap"
        with MMapFile(file_path) as f:
            initial = f._size
            f.grow(initial + PAGE_SIZE * 2)
            assert f._size > initial

    def test_grow_rounds_to_page(self, temp_dir: Path) -> None:
        file_path = temp_dir / "test.mmap"
        with MMapFile(file_path) as f:
            f.grow(f._size + 1)
            assert f._size % PAGE_SIZE == 0

    def test_grow_does_nothing_if_smaller(self, temp_dir: Path) -> None:
        file_path = temp_dir / "test.mmap"
        with MMapFile(file_path) as f:
            initial = f._size
            f.grow(initial - 1)
            assert f._size == initial


class TestCorruptDataEnd:
    def test_corrupt_data_end_below_start_raises(self, temp_dir: Path) -> None:
        file_path = temp_dir / "test.mmap"
        with MMapFile(file_path):  # noqa: F841
            pass
        content = bytearray(file_path.read_bytes())
        content[OFF_DATA_END : OFF_DATA_END + 8] = struct.pack("<Q", 100)
        header_data = content[12:HEADER_SIZE]
        new_crc = zlib.crc32(header_data) & 0xFFFFFFFF
        content[OFF_CRC : OFF_CRC + 4] = struct.pack("<I", new_crc)
        file_path.write_bytes(content)
        with pytest.raises(ValueError, match="Corrupt data_end pointer"), MMapFile(file_path):
            pass

    def test_corrupt_data_end_exceeds_size_raises(self, temp_dir: Path) -> None:
        file_path = temp_dir / "test.mmap"
        with MMapFile(file_path):
            pass
        content = bytearray(file_path.read_bytes())
        content[OFF_DATA_END : OFF_DATA_END + 8] = struct.pack("<Q", 1000)
        header_data = content[12:HEADER_SIZE]
        new_crc = zlib.crc32(header_data) & 0xFFFFFFFF
        content[OFF_CRC : OFF_CRC + 4] = struct.pack("<I", new_crc)
        file_path.write_bytes(content)
        with pytest.raises(ValueError, match="Corrupt data_end pointer"), MMapFile(file_path):
            pass


class TestContextManager:
    def test_context_manager_opens_and_closes(self, temp_dir: Path) -> None:
        file_path = temp_dir / "test.mmap"
        with MMapFile(file_path) as f:
            assert f.mmap is not None
        assert f.mmap is None

    def test_context_manager_returns_self(self, temp_dir: Path) -> None:
        file_path = temp_dir / "test.mmap"
        with MMapFile(file_path) as f:
            assert isinstance(f, MMapFile)


class TestWalOperations:
    def test_write_wal_record(self, temp_dir: Path) -> None:
        file_path = temp_dir / "test.mmap"
        with MMapFile(file_path) as f:
            f.write_wal_record(WAL_TYPE_INSERT, b"payload")
            head = struct.unpack("<I", f.mmap[OFF_WAL_HEAD : OFF_WAL_HEAD + 4])[0]
            assert head > 0

    def test_read_wal_records(self, temp_dir: Path) -> None:
        file_path = temp_dir / "test.mmap"
        with MMapFile(file_path) as f:
            f.write_wal_record(WAL_TYPE_INSERT, b"test data")
            records = f.read_wal_records()
            assert len(records) == 1
            assert records[0][0] == WAL_TYPE_INSERT
            assert records[0][1] == b"test data"

    def test_reset_wal(self, temp_dir: Path) -> None:
        file_path = temp_dir / "test.mmap"
        with MMapFile(file_path) as f:
            f.write_wal_record(WAL_TYPE_INSERT, b"data")
            f.reset_wal()
            head = struct.unpack("<I", f.mmap[OFF_WAL_HEAD : OFF_WAL_HEAD + 4])[0]
            assert head == 0

    def test_checkpoint(self, temp_dir: Path) -> None:
        file_path = temp_dir / "test.mmap"
        with MMapFile(file_path) as f:
            f.write_wal_record(WAL_TYPE_COMMIT, b"data")
            f.checkpoint()
            head = struct.unpack("<I", f.mmap[OFF_WAL_HEAD : OFF_WAL_HEAD + 4])[0]
            assert head == 0


class TestEdgeCases:
    def test_write_empty_payload(self, temp_dir: Path) -> None:
        file_path = temp_dir / "test.mmap"
        with MMapFile(file_path) as f:
            offset = f.append_data(b"")
            assert offset == DATA_REGION_START
            assert f._data_end == DATA_REGION_START

    def test_multiple_empty_appends(self, temp_dir: Path) -> None:
        file_path = temp_dir / "test.mmap"
        with MMapFile(file_path) as f:
            f.append_data(b"")
            f.append_data(b"")
            f.append_data(b"data")
            assert f._data_end == DATA_REGION_START + 4

    def test_overwrite_corrupted_file(self, temp_dir: Path) -> None:
        file_path = temp_dir / "corrupt.mmap"
        file_path.write_bytes(b"\x00" * (HEADER_SIZE + WAL_SIZE))
        with pytest.raises(ValueError, match="Invalid magic bytes"):
            MMapFile(file_path).open()


class TestFileProperties:
    def test_size_property_returns_mmap_size(self, temp_dir: Path) -> None:
        file_path = temp_dir / "test.mmap"
        with MMapFile(file_path) as f:
            assert f.size == f._size

    def test_data_end_property(self, temp_dir: Path) -> None:
        file_path = temp_dir / "test.mmap"
        with MMapFile(file_path) as f:
            f.append_data(b"test")
            assert f.data_region_end == f._data_end
