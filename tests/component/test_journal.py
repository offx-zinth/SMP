from __future__ import annotations

import shutil
import struct
import tempfile
import zlib
from pathlib import Path

import pytest

from smp.core.models import EdgeType, GraphEdge, GraphNode, NodeType, StructuralProperties
from smp.store.graph.journal import RECORD_HEADER_SIZE, Journal, JournalCorruptionError, RecordType
from smp.store.graph.mmap_file import DATA_REGION_START, MMapFile
from smp.store.graph.records import (
    AuditAppendPayload,
    EdgeUpsertPayload,
    FileDeletePayload,
    LockReleaseAllPayload,
    LockReleasePayload,
    LockUpsertPayload,
    NodeDeletePayload,
    NodeUpsertPayload,
    ParseStatusPayload,
    SessionDeletePayload,
    SessionUpsertPayload,
    TransactionPayload,
    decode,
    encode,
)


@pytest.fixture
def journal_setup():
    tmp_dir = tempfile.mkdtemp()
    path = Path(tmp_dir) / "test.journal.smpg"
    mmap_file = MMapFile(path)
    mmap_file.open()
    journal = Journal(mmap_file)
    yield journal, mmap_file
    mmap_file.close()
    shutil.rmtree(tmp_dir)


class TestJournalBasic:
    def test_append_single(self, journal_setup):
        journal, _ = journal_setup
        payload = b"hello world"
        offset = journal.append(RecordType.AUDIT_APPEND, payload)

        assert offset == DATA_REGION_START
        records = list(journal.replay())
        assert len(records) == 1
        rtype, p, off = records[0]
        assert rtype == RecordType.AUDIT_APPEND
        assert p == payload
        assert off == offset

    def test_append_multiple(self, journal_setup):
        journal, _ = journal_setup
        payloads = [b"p1", b"p2", b"p3"]
        offsets = []
        for _, p in enumerate(payloads):
            offsets.append(journal.append(RecordType.AUDIT_APPEND, p))

        assert len(offsets) == 3
        assert offsets[0] == DATA_REGION_START
        assert offsets[1] == offsets[0] + RECORD_HEADER_SIZE + len(payloads[0])

        records = list(journal.replay())
        assert len(records) == 3
        for i in range(3):
            assert records[i][1] == payloads[i]
            assert records[i][2] == offsets[i]

    def test_append_batch(self, journal_setup):
        journal, _ = journal_setup
        batch = [
            (RecordType.NODE_UPSERT, b"node1"),
            (RecordType.NODE_DELETE, b"node2"),
            (RecordType.EDGE_UPSERT, b"edge1"),
        ]
        offsets = journal.append_batch(batch)

        assert len(offsets) == 3
        assert offsets[0] == DATA_REGION_START

        records = list(journal.replay())
        assert len(records) == 3
        for i in range(3):
            assert records[i][0] == batch[i][0]
            assert records[i][1] == batch[i][1]
            assert records[i][2] == offsets[i]

    def test_append_batch_empty(self, journal_setup):
        journal, _ = journal_setup
        offsets = journal.append_batch([])
        assert offsets == []
        assert len(list(journal.replay())) == 0

    def test_empty_payload(self, journal_setup):
        journal, _ = journal_setup
        offset = journal.append(RecordType.AUDIT_APPEND, b"")
        records = list(journal.replay())
        assert len(records) == 1
        assert records[0][1] == b""
        assert records[0][2] == offset


class TestJournalReplay:
    def test_replay_empty(self, journal_setup):
        journal, _ = journal_setup
        records = list(journal.replay())
        assert records == []

    def test_replay_order(self, journal_setup):
        journal, _ = journal_setup
        for i in range(100):
            journal.append(RecordType.AUDIT_APPEND, struct.pack("<I", i))

        records = list(journal.replay())
        assert len(records) == 100
        for i in range(100):
            assert struct.unpack("<I", records[i][1])[0] == i

    def test_replay_large_number_of_records(self, journal_setup):
        journal, _ = journal_setup
        count = 1000
        for _ in range(count):
            journal.append(RecordType.AUDIT_APPEND, b"data")

        assert len(list(journal.replay())) == count


class TestJournalMaintenance:
    def test_truncate(self, journal_setup):
        journal, mmap_file = journal_setup
        journal.append(RecordType.AUDIT_APPEND, b"data1")
        journal.append(RecordType.AUDIT_APPEND, b"data2")

        assert len(list(journal.replay())) == 2
        journal.truncate()

        assert len(list(journal.replay())) == 0
        assert mmap_file.data_region_end == DATA_REGION_START

    def test_truncate_empty(self, journal_setup):
        journal, _ = journal_setup
        journal.truncate()
        assert len(list(journal.replay())) == 0


class TestJournalPersistence:
    def test_persistence_roundtrip(self):
        tmp_dir = tempfile.mkdtemp()
        try:
            path = Path(tmp_dir) / "persist.smpg"

            # Write phase
            mmap_file = MMapFile(path)
            mmap_file.open()
            journal = Journal(mmap_file)
            payload = b"persistent data"
            offset = journal.append(RecordType.AUDIT_APPEND, payload)
            mmap_file.close()

            # Read phase
            mmap_file_2 = MMapFile(path)
            mmap_file_2.open()
            journal_2 = Journal(mmap_file_2)
            records = list(journal_2.replay())
            mmap_file_2.close()

            assert len(records) == 1
            assert records[0][0] == RecordType.AUDIT_APPEND
            assert records[0][1] == payload
            assert records[0][2] == offset
        finally:
            shutil.rmtree(tmp_dir)

    def test_persistence_multiple_records(self):
        tmp_dir = tempfile.mkdtemp()
        try:
            path = Path(tmp_dir) / "persist_multi.smpg"
            mmap_file = MMapFile(path)
            mmap_file.open()
            journal = Journal(mmap_file)

            data = [b"d1", b"d2", b"d3"]
            for d in data:
                journal.append(RecordType.AUDIT_APPEND, d)
            mmap_file.close()

            mmap_file_2 = MMapFile(path)
            mmap_file_2.open()
            journal_2 = Journal(mmap_file_2)
            records = list(journal_2.replay())
            mmap_file_2.close()

            assert len(records) == 3
            for i in range(3):
                assert records[i][1] == data[i]
        finally:
            shutil.rmtree(tmp_dir)


class TestJournalCorruption:
    def test_truncated_header(self, journal_setup):
        journal, mmap_file = journal_setup
        journal.append(RecordType.AUDIT_APPEND, b"data")

        # Set data_end to just after start but before header ends
        mmap_file._data_end = DATA_REGION_START + 5
        mmap_file._write_data_end(mmap_file._data_end)

        with pytest.raises(JournalCorruptionError, match="Truncated record header"):
            list(journal.replay())

    def test_truncated_payload(self, journal_setup):
        journal, mmap_file = journal_setup
        payload = b"some longer payload"
        journal.append(RecordType.AUDIT_APPEND, payload)

        # Set data_end to cut off the payload
        mmap_file._data_end = DATA_REGION_START + RECORD_HEADER_SIZE + 5
        mmap_file._write_data_end(mmap_file._data_end)

        with pytest.raises(JournalCorruptionError, match="Truncated record payload"):
            list(journal.replay())

    def test_crc_mismatch(self, journal_setup):
        journal, mmap_file = journal_setup
        journal.append(RecordType.AUDIT_APPEND, b"data")

        # Corrupt the payload byte
        mmap_file.mmap[DATA_REGION_START + RECORD_HEADER_SIZE] ^= 0xFF

        with pytest.raises(JournalCorruptionError, match="CRC mismatch"):
            list(journal.replay())

    def test_unknown_record_type(self, journal_setup):
        journal, mmap_file = journal_setup

        # Manually write a record with invalid type
        payload = b"data"
        length = len(payload)
        header_no_crc = struct.pack("<BBI", 0xFE, 0, length)  # 0xFE is not in RecordType
        crc = zlib.crc32(header_no_crc + payload) & 0xFFFFFFFF
        full_record = header_no_crc + struct.pack("<I", crc) + payload

        mmap_file.append_data(full_record)

        with pytest.raises(JournalCorruptionError, match="Unknown record type"):
            list(journal.replay())


class TestJournalIntegration:
    def test_large_payload_growth(self, journal_setup):
        journal, _ = journal_setup
        # Create a payload larger than initial data pages (64KB)
        large_payload = b"x" * (100 * 1024)
        offset = journal.append(RecordType.AUDIT_APPEND, large_payload)

        records = list(journal.replay())
        assert len(records) == 1
        assert records[0][1] == large_payload
        assert records[0][2] == offset

    def test_payload_types(self, journal_setup):
        journal, _ = journal_setup

        # Test all payload structs from records.py
        test_cases = [
            (
                RecordType.NODE_UPSERT,
                NodeUpsertPayload(
                    node=GraphNode(
                        id="n1", type=NodeType.FUNCTION, file_path="f", structural=StructuralProperties(name="n")
                    )
                ),
            ),
            (RecordType.NODE_DELETE, NodeDeletePayload(node_id="n1")),
            (
                RecordType.EDGE_UPSERT,
                EdgeUpsertPayload(edge=GraphEdge(source_id="n1", target_id="n2", type=EdgeType.CALLS)),
            ),
            (RecordType.FILE_DELETE, FileDeletePayload(file_path="f1")),
            (RecordType.SESSION_UPSERT, SessionUpsertPayload(session_id="s1", data={"foo": "bar"})),
            (RecordType.SESSION_DELETE, SessionDeletePayload(session_id="s1")),
            (RecordType.LOCK_UPSERT, LockUpsertPayload(file_path="f1", session_id="s1")),
            (RecordType.LOCK_RELEASE, LockReleasePayload(file_path="f1", session_id="s1")),
            (RecordType.LOCK_RELEASE_ALL, LockReleaseAllPayload(session_id="s1")),
            (RecordType.AUDIT_APPEND, AuditAppendPayload(event={"event": "test"})),
            (RecordType.PARSE_STATUS, ParseStatusPayload(file_path="f1", parsed=True)),
            (RecordType.BEGIN_TX, TransactionPayload(tx_id=1, actor="user")),
            (RecordType.COMMIT_TX, TransactionPayload(tx_id=1)),
            (RecordType.ABORT_TX, TransactionPayload(tx_id=2)),
        ]

        for rtype, payload_struct in test_cases:
            payload_bytes = encode(payload_struct)
            journal.append(rtype, payload_bytes)

        records = list(journal.replay())
        assert len(records) == len(test_cases)

        for i, (rtype, payload_struct) in enumerate(test_cases):
            rec_type, rec_payload, _ = records[i]
            assert rec_type == rtype

            # Decode and verify
            struct_type = type(payload_struct)
            decoded = decode(rec_payload, struct_type)
            assert decoded == payload_struct

    def test_concurrent_write_simulation(self, journal_setup):
        # Journal is not thread-safe by design, but we can check if sequential batch
        # writes behave correctly.
        journal, _ = journal_setup

        for i in range(10):
            journal.append_batch(
                [
                    (RecordType.AUDIT_APPEND, f"batch_{i}_1".encode()),
                    (RecordType.AUDIT_APPEND, f"batch_{i}_2".encode()),
                ]
            )

        records = list(journal.replay())
        assert len(records) == 20
        for i in range(10):
            assert records[2 * i][1] == f"batch_{i}_1".encode()
            assert records[2 * i + 1][1] == f"batch_{i}_2".encode()

    def test_fsync_call(self, journal_setup):
        journal, mmap_file = journal_setup

        # We can't easily check if os.fsync was called without mocking,
        # but we can verify that append(fsync=True) doesn't crash and
        # that we can still replay.
        journal.append(RecordType.AUDIT_APPEND, b"sync_test", fsync=True)

        records = list(journal.replay())
        assert len(records) == 1
        assert records[0][1] == b"sync_test"

    def test_batch_mixed_types(self, journal_setup):
        journal, _ = journal_setup
        batch = [
            (RecordType.NODE_UPSERT, b"n1"),
            (RecordType.EDGE_UPSERT, b"e1"),
            (RecordType.NODE_DELETE, b"n1"),
            (RecordType.AUDIT_APPEND, b"a1"),
        ]
        journal.append_batch(batch)

        records = list(journal.replay())
        assert len(records) == 4
        for i in range(4):
            assert records[i][0] == batch[i][0]
            assert records[i][1] == batch[i][1]
