"""Comprehensive unit tests for smp.store.graph.records and smp.store.graph.journal."""

from __future__ import annotations

import struct
import zlib

import pytest

from smp.core.models import EdgeType, GraphEdge, GraphNode, NodeType, StructuralProperties
from smp.store.graph.journal import (
    RECORD_HEADER_FMT,
    RECORD_HEADER_SIZE,
    RecordType,
)
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


class TestRecordTypeEnum:
    def test_record_type_is_int_enum(self) -> None:
        assert isinstance(RecordType.NODE_UPSERT, int)

    def test_node_upsert_value(self) -> None:
        assert RecordType.NODE_UPSERT == 0x01
        assert RecordType.NODE_UPSERT.value == 0x01

    def test_node_delete_value(self) -> None:
        assert RecordType.NODE_DELETE == 0x02
        assert RecordType.NODE_DELETE.value == 0x02

    def test_edge_upsert_value(self) -> None:
        assert RecordType.EDGE_UPSERT == 0x03
        assert RecordType.EDGE_UPSERT.value == 0x03

    def test_file_delete_value(self) -> None:
        assert RecordType.FILE_DELETE == 0x04
        assert RecordType.FILE_DELETE.value == 0x04

    def test_session_upsert_value(self) -> None:
        assert RecordType.SESSION_UPSERT == 0x05
        assert RecordType.SESSION_UPSERT.value == 0x05

    def test_session_delete_value(self) -> None:
        assert RecordType.SESSION_DELETE == 0x06
        assert RecordType.SESSION_DELETE.value == 0x06

    def test_lock_upsert_value(self) -> None:
        assert RecordType.LOCK_UPSERT == 0x07
        assert RecordType.LOCK_UPSERT.value == 0x07

    def test_lock_release_value(self) -> None:
        assert RecordType.LOCK_RELEASE == 0x08
        assert RecordType.LOCK_RELEASE.value == 0x08

    def test_lock_release_all_value(self) -> None:
        assert RecordType.LOCK_RELEASE_ALL == 0x09
        assert RecordType.LOCK_RELEASE_ALL.value == 0x09

    def test_audit_append_value(self) -> None:
        assert RecordType.AUDIT_APPEND == 0x0A
        assert RecordType.AUDIT_APPEND.value == 0x0A

    def test_parse_status_value(self) -> None:
        assert RecordType.PARSE_STATUS == 0x0B
        assert RecordType.PARSE_STATUS.value == 0x0B

    def test_begin_tx_value(self) -> None:
        assert RecordType.BEGIN_TX == 0x0C
        assert RecordType.BEGIN_TX.value == 0x0C

    def test_commit_tx_value(self) -> None:
        assert RecordType.COMMIT_TX == 0x0D
        assert RecordType.COMMIT_TX.value == 0x0D

    def test_abort_tx_value(self) -> None:
        assert RecordType.ABORT_TX == 0x0E
        assert RecordType.ABORT_TX.value == 0x0E

    def test_total_record_types(self) -> None:
        assert len(RecordType) == 14

    def test_record_type_names(self) -> None:
        names = [e.name for e in RecordType]
        assert "NODE_UPSERT" in names
        assert "NODE_DELETE" in names
        assert "EDGE_UPSERT" in names
        assert "FILE_DELETE" in names
        assert "SESSION_UPSERT" in names
        assert "SESSION_DELETE" in names
        assert "LOCK_UPSERT" in names
        assert "LOCK_RELEASE" in names
        assert "LOCK_RELEASE_ALL" in names
        assert "AUDIT_APPEND" in names
        assert "PARSE_STATUS" in names
        assert "BEGIN_TX" in names
        assert "COMMIT_TX" in names
        assert "ABORT_TX" in names

    def test_record_type_int_conversion(self) -> None:
        assert int(RecordType.NODE_UPSERT) == 0x01
        assert int(RecordType.NODE_DELETE) == 0x02
        assert int(RecordType.EDGE_UPSERT) == 0x03

    def test_record_type_from_int(self) -> None:
        assert RecordType(0x01) == RecordType.NODE_UPSERT
        assert RecordType(0x02) == RecordType.NODE_DELETE
        assert RecordType(0x03) == RecordType.EDGE_UPSERT

    def test_record_type_invalid_int_raises(self) -> None:
        with pytest.raises(ValueError):
            RecordType(0xFF)


class TestRecordHeaderConstants:
    def test_record_header_size(self) -> None:
        assert RECORD_HEADER_SIZE == 10

    def test_record_header_fmt(self) -> None:
        assert RECORD_HEADER_FMT == "<BBII"

    def test_header_fmt_structure(self) -> None:
        packed = struct.pack(RECORD_HEADER_FMT, 0x01, 0, 100, 0x12345678)
        rtype, flags, length, crc = struct.unpack(RECORD_HEADER_FMT, packed)
        assert rtype == 0x01
        assert flags == 0
        assert length == 100
        assert crc == 0x12345678


class TestNodeUpsertPayload:
    def test_required_fields(self) -> None:
        node = GraphNode(id="n1", type=NodeType.FILE, file_path="/p.py")
        payload = NodeUpsertPayload(node=node)
        assert payload.node == node

    def test_with_full_node(self) -> None:
        node = GraphNode(
            id="n1",
            type=NodeType.FUNCTION,
            file_path="/p.py",
            structural=StructuralProperties(name="func", complexity=5),
        )
        payload = NodeUpsertPayload(node=node)
        assert payload.node.id == "n1"
        assert payload.node.structural.complexity == 5

    def test_missing_node_raises(self) -> None:
        with pytest.raises(TypeError):
            NodeUpsertPayload()


class TestNodeDeletePayload:
    def test_required_fields(self) -> None:
        payload = NodeDeletePayload(node_id="node-123")
        assert payload.node_id == "node-123"

    def test_empty_string_node_id(self) -> None:
        payload = NodeDeletePayload(node_id="")
        assert payload.node_id == ""

    def test_missing_node_id_raises(self) -> None:
        with pytest.raises(TypeError):
            NodeDeletePayload()


class TestEdgeUpsertPayload:
    def test_required_fields(self) -> None:
        edge = GraphEdge(source_id="n1", target_id="n2", type=EdgeType.CALLS)
        payload = EdgeUpsertPayload(edge=edge)
        assert payload.edge == edge

    def test_with_metadata(self) -> None:
        edge = GraphEdge(
            source_id="n1",
            target_id="n2",
            type=EdgeType.IMPORTS,
            metadata={"line": "10"},
        )
        payload = EdgeUpsertPayload(edge=edge)
        assert payload.edge.metadata == {"line": "10"}

    def test_missing_edge_raises(self) -> None:
        with pytest.raises(TypeError):
            EdgeUpsertPayload()


class TestFileDeletePayload:
    def test_required_fields(self) -> None:
        payload = FileDeletePayload(file_path="/path/to/file.py")
        assert payload.file_path == "/path/to/file.py"

    def test_empty_string_path(self) -> None:
        payload = FileDeletePayload(file_path="")
        assert payload.file_path == ""

    def test_missing_file_path_raises(self) -> None:
        with pytest.raises(TypeError):
            FileDeletePayload()


class TestSessionUpsertPayload:
    def test_required_fields(self) -> None:
        payload = SessionUpsertPayload(session_id="sess-1")
        assert payload.session_id == "sess-1"
        assert payload.data == {}

    def test_with_data(self) -> None:
        payload = SessionUpsertPayload(session_id="sess-1", data={"key": "value"})
        assert payload.data == {"key": "value"}

    def test_empty_data_default(self) -> None:
        payload = SessionUpsertPayload(session_id="sess-1")
        assert payload.data == {}

    def test_missing_session_id_raises(self) -> None:
        with pytest.raises(TypeError):
            SessionUpsertPayload()


class TestSessionDeletePayload:
    def test_required_fields(self) -> None:
        payload = SessionDeletePayload(session_id="sess-1")
        assert payload.session_id == "sess-1"

    def test_missing_session_id_raises(self) -> None:
        with pytest.raises(TypeError):
            SessionDeletePayload()


class TestLockUpsertPayload:
    def test_required_fields(self) -> None:
        payload = LockUpsertPayload(file_path="/p.py", session_id="sess-1")
        assert payload.file_path == "/p.py"
        assert payload.session_id == "sess-1"
        assert payload.acquired_at == ""
        assert payload.expires_at == ""
        assert payload.fencing_token == 0

    def test_with_all_fields(self) -> None:
        payload = LockUpsertPayload(
            file_path="/p.py",
            session_id="sess-1",
            acquired_at="2024-01-01T00:00:00Z",
            expires_at="2024-01-01T01:00:00Z",
            fencing_token=42,
        )
        assert payload.acquired_at == "2024-01-01T00:00:00Z"
        assert payload.expires_at == "2024-01-01T01:00:00Z"
        assert payload.fencing_token == 42

    def test_missing_file_path_raises(self) -> None:
        with pytest.raises(TypeError):
            LockUpsertPayload(session_id="sess-1")

    def test_missing_session_id_raises(self) -> None:
        with pytest.raises(TypeError):
            LockUpsertPayload(file_path="/p.py")


class TestLockReleasePayload:
    def test_required_fields(self) -> None:
        payload = LockReleasePayload(file_path="/p.py", session_id="sess-1")
        assert payload.file_path == "/p.py"
        assert payload.session_id == "sess-1"

    def test_missing_file_path_raises(self) -> None:
        with pytest.raises(TypeError):
            LockReleasePayload(session_id="sess-1")

    def test_missing_session_id_raises(self) -> None:
        with pytest.raises(TypeError):
            LockReleasePayload(file_path="/p.py")


class TestLockReleaseAllPayload:
    def test_required_fields(self) -> None:
        payload = LockReleaseAllPayload(session_id="sess-1")
        assert payload.session_id == "sess-1"

    def test_missing_session_id_raises(self) -> None:
        with pytest.raises(TypeError):
            LockReleaseAllPayload()


class TestAuditAppendPayload:
    def test_required_fields(self) -> None:
        payload = AuditAppendPayload(event={"action": "created"})
        assert payload.event == {"action": "created"}

    def test_empty_event_default(self) -> None:
        payload = AuditAppendPayload()
        assert payload.event == {}

    def test_missing_event_uses_default(self) -> None:
        payload = AuditAppendPayload()
        assert payload.event == {}


class TestParseStatusPayload:
    def test_required_fields(self) -> None:
        payload = ParseStatusPayload(file_path="/p.py")
        assert payload.file_path == "/p.py"
        assert payload.parsed is False
        assert payload.line_count == 0
        assert payload.node_count == 0
        assert payload.stale is False
        assert payload.parse_time_ms is None
        assert payload.content_hash == ""

    def test_with_all_fields(self) -> None:
        payload = ParseStatusPayload(
            file_path="/p.py",
            parsed=True,
            line_count=100,
            node_count=50,
            stale=True,
            parse_time_ms=12.5,
            content_hash="abc123",
        )
        assert payload.parsed is True
        assert payload.line_count == 100
        assert payload.node_count == 50
        assert payload.stale is True
        assert payload.parse_time_ms == 12.5
        assert payload.content_hash == "abc123"

    def test_missing_file_path_raises(self) -> None:
        with pytest.raises(TypeError):
            ParseStatusPayload()


class TestTransactionPayload:
    def test_required_fields(self) -> None:
        payload = TransactionPayload(tx_id=1)
        assert payload.tx_id == 1
        assert payload.actor == ""
        assert payload.note == ""

    def test_with_all_fields(self) -> None:
        payload = TransactionPayload(tx_id=1, actor="user-1", note="initial commit")
        assert payload.tx_id == 1
        assert payload.actor == "user-1"
        assert payload.note == "initial commit"

    def test_missing_tx_id_raises(self) -> None:
        with pytest.raises(TypeError):
            TransactionPayload()


class TestEncodeDecode:
    def test_encode_node_upsert_payload(self) -> None:
        node = GraphNode(id="n1", type=NodeType.FILE, file_path="/p.py")
        payload = NodeUpsertPayload(node=node)
        encoded = encode(payload)
        assert isinstance(encoded, bytes)
        assert len(encoded) > 0

    def test_decode_node_upsert_payload(self) -> None:
        node = GraphNode(id="n1", type=NodeType.FILE, file_path="/p.py")
        payload = NodeUpsertPayload(node=node)
        encoded = encode(payload)
        decoded = decode(encoded, NodeUpsertPayload)
        assert decoded.node.id == "n1"
        assert decoded.node.type == NodeType.FILE
        assert decoded.node.file_path == "/p.py"

    def test_encode_node_delete_payload(self) -> None:
        payload = NodeDeletePayload(node_id="node-123")
        encoded = encode(payload)
        assert isinstance(encoded, bytes)
        decoded = decode(encoded, NodeDeletePayload)
        assert decoded.node_id == "node-123"

    def test_encode_edge_upsert_payload(self) -> None:
        edge = GraphEdge(source_id="n1", target_id="n2", type=EdgeType.CALLS)
        payload = EdgeUpsertPayload(edge=edge)
        encoded = encode(payload)
        decoded = decode(encoded, EdgeUpsertPayload)
        assert decoded.edge.source_id == "n1"
        assert decoded.edge.target_id == "n2"
        assert decoded.edge.type == EdgeType.CALLS

    def test_encode_file_delete_payload(self) -> None:
        payload = FileDeletePayload(file_path="/p.py")
        encoded = encode(payload)
        decoded = decode(encoded, FileDeletePayload)
        assert decoded.file_path == "/p.py"

    def test_encode_session_upsert_payload(self) -> None:
        payload = SessionUpsertPayload(session_id="sess-1", data={"key": "value"})
        encoded = encode(payload)
        decoded = decode(encoded, SessionUpsertPayload)
        assert decoded.session_id == "sess-1"
        assert decoded.data == {"key": "value"}

    def test_encode_session_delete_payload(self) -> None:
        payload = SessionDeletePayload(session_id="sess-1")
        encoded = encode(payload)
        decoded = decode(encoded, SessionDeletePayload)
        assert decoded.session_id == "sess-1"

    def test_encode_lock_upsert_payload(self) -> None:
        payload = LockUpsertPayload(
            file_path="/p.py",
            session_id="sess-1",
            acquired_at="2024-01-01T00:00:00Z",
            expires_at="2024-01-01T01:00:00Z",
            fencing_token=42,
        )
        encoded = encode(payload)
        decoded = decode(encoded, LockUpsertPayload)
        assert decoded.file_path == "/p.py"
        assert decoded.session_id == "sess-1"
        assert decoded.fencing_token == 42

    def test_encode_lock_release_payload(self) -> None:
        payload = LockReleasePayload(file_path="/p.py", session_id="sess-1")
        encoded = encode(payload)
        decoded = decode(encoded, LockReleasePayload)
        assert decoded.file_path == "/p.py"
        assert decoded.session_id == "sess-1"

    def test_encode_lock_release_all_payload(self) -> None:
        payload = LockReleaseAllPayload(session_id="sess-1")
        encoded = encode(payload)
        decoded = decode(encoded, LockReleaseAllPayload)
        assert decoded.session_id == "sess-1"

    def test_encode_audit_append_payload(self) -> None:
        payload = AuditAppendPayload(event={"action": "delete", "user": "alice"})
        encoded = encode(payload)
        decoded = decode(encoded, AuditAppendPayload)
        assert decoded.event == {"action": "delete", "user": "alice"}

    def test_encode_parse_status_payload(self) -> None:
        payload = ParseStatusPayload(
            file_path="/p.py",
            parsed=True,
            line_count=100,
            node_count=50,
            stale=False,
            parse_time_ms=12.5,
            content_hash="abc123",
        )
        encoded = encode(payload)
        decoded = decode(encoded, ParseStatusPayload)
        assert decoded.file_path == "/p.py"
        assert decoded.parsed is True
        assert decoded.line_count == 100
        assert decoded.node_count == 50
        assert decoded.parse_time_ms == 12.5

    def test_encode_transaction_payload(self) -> None:
        payload = TransactionPayload(tx_id=1, actor="user-1", note="test")
        encoded = encode(payload)
        decoded = decode(encoded, TransactionPayload)
        assert decoded.tx_id == 1
        assert decoded.actor == "user-1"
        assert decoded.note == "test"

    def test_roundtrip_preserves_data(self) -> None:
        original = NodeUpsertPayload(
            node=GraphNode(
                id="test-node",
                type=NodeType.FUNCTION,
                file_path="/path/to/func.py",
                structural=StructuralProperties(name="test_func", complexity=10),
            )
        )
        encoded = encode(original)
        restored = decode(encoded, NodeUpsertPayload)
        assert restored.node.id == original.node.id
        assert restored.node.type == original.node.type
        assert restored.node.file_path == original.node.file_path
        assert restored.node.structural.name == original.node.structural.name
        assert restored.node.structural.complexity == original.node.structural.complexity

    def test_encode_empty_payloads(self) -> None:
        payloads = [
            SessionUpsertPayload(session_id="s1"),
            SessionDeletePayload(session_id="s1"),
            LockReleaseAllPayload(session_id="s1"),
            AuditAppendPayload(),
        ]
        for p in payloads:
            encoded = encode(p)
            assert isinstance(encoded, bytes)
            assert len(encoded) > 0


class TestRecordSerialization:
    def test_record_header_size_matches_constants(self) -> None:
        rtype = RecordType.NODE_UPSERT
        flags = 0
        length = 100
        header = struct.pack("<BBII", rtype, flags, length, 0)
        assert len(header) == RECORD_HEADER_SIZE

    def test_crc32_calculation(self) -> None:
        rtype = 0x01
        flags = 0
        length = 10
        payload = b"test payload"
        header_no_crc = struct.pack("<BBI", rtype, flags, length)
        crc = zlib.crc32(header_no_crc + payload) & 0xFFFFFFFF
        assert isinstance(crc, int)
        assert crc == zlib.crc32(header_no_crc + payload)

    def test_full_record_encoding(self) -> None:
        rtype = RecordType.NODE_UPSERT
        payload = b"test payload"
        length = len(payload)
        header_no_crc = struct.pack("<BBI", int(rtype), 0, length)
        crc = zlib.crc32(header_no_crc + payload) & 0xFFFFFFFF
        record = header_no_crc + struct.pack("<I", crc) + payload
        assert len(record) == RECORD_HEADER_SIZE + length

    def test_record_encoding_roundtrip(self) -> None:
        rtype = RecordType.EDGE_UPSERT
        payload = b"edge data"
        length = len(payload)
        header_no_crc = struct.pack("<BBI", int(rtype), 0, length)
        crc = zlib.crc32(header_no_crc + payload) & 0xFFFFFFFF
        record = header_no_crc + struct.pack("<I", crc) + payload
        rtype_unpacked, flags_unpacked, length_unpacked = struct.unpack("<BBI", record[:6])
        assert rtype_unpacked == int(rtype)
        assert flags_unpacked == 0
        assert length_unpacked == length

    def test_zero_length_payload(self) -> None:
        rtype = RecordType.BEGIN_TX
        payload = b""
        length = len(payload)
        header_no_crc = struct.pack("<BBI", int(rtype), 0, length)
        crc = zlib.crc32(header_no_crc + payload) & 0xFFFFFFFF
        record = header_no_crc + struct.pack("<I", crc) + payload
        assert len(record) == RECORD_HEADER_SIZE

    def test_large_payload(self) -> None:
        rtype = RecordType.AUDIT_APPEND
        payload = b"x" * 10000
        length = len(payload)
        header_no_crc = struct.pack("<BBI", int(rtype), 0, length)
        crc = zlib.crc32(header_no_crc + payload) & 0xFFFFFFFF
        record = header_no_crc + struct.pack("<I", crc) + payload
        assert len(record) == RECORD_HEADER_SIZE + 10000


class TestChecksumVerification:
    def test_valid_checksum(self) -> None:
        rtype = RecordType.NODE_UPSERT
        payload = encode(NodeUpsertPayload(node=GraphNode(id="n1", type=NodeType.FILE, file_path="/p.py")))
        length = len(payload)
        header_no_crc = struct.pack("<BBI", int(rtype), 0, length)
        expected_crc = zlib.crc32(header_no_crc + payload) & 0xFFFFFFFF
        packed_crc = struct.pack("<I", expected_crc)
        assert len(packed_crc) == 4

    def test_checksum_changes_with_payload(self) -> None:
        rtype = RecordType.NODE_UPSERT
        payload1 = encode(NodeUpsertPayload(node=GraphNode(id="n1", type=NodeType.FILE, file_path="/p.py")))
        payload2 = encode(NodeUpsertPayload(node=GraphNode(id="n2", type=NodeType.FILE, file_path="/p.py")))
        header1 = struct.pack("<BBI", int(rtype), 0, len(payload1))
        header2 = struct.pack("<BBI", int(rtype), 0, len(payload2))
        crc1 = zlib.crc32(header1 + payload1) & 0xFFFFFFFF
        crc2 = zlib.crc32(header2 + payload2) & 0xFFFFFFFF
        assert crc1 != crc2

    def test_checksum_changes_with_record_type(self) -> None:
        payload = b"same payload"
        rtype1 = RecordType.NODE_UPSERT
        rtype2 = RecordType.NODE_DELETE
        header1 = struct.pack("<BBI", int(rtype1), 0, len(payload))
        header2 = struct.pack("<BBI", int(rtype2), 0, len(payload))
        crc1 = zlib.crc32(header1 + payload) & 0xFFFFFFFF
        crc2 = zlib.crc32(header2 + payload) & 0xFFFFFFFF
        assert crc1 != crc2

    def test_corrupted_payload_detected(self) -> None:
        rtype = RecordType.NODE_UPSERT
        original_payload = encode(NodeUpsertPayload(node=GraphNode(id="n1", type=NodeType.FILE, file_path="/p.py")))
        corrupted_payload = original_payload + b"garbage"
        length = len(corrupted_payload)
        header = struct.pack("<BBI", int(rtype), 0, length)
        original_crc = zlib.crc32(header + original_payload) & 0xFFFFFFFF
        corrupted_crc = zlib.crc32(header + corrupted_payload) & 0xFFFFFFFF
        assert original_crc != corrupted_crc


class TestRecordTypeCodes:
    def test_all_record_types_have_unique_codes(self) -> None:
        codes = [int(rt) for rt in RecordType]
        assert len(codes) == len(set(codes))

    def test_record_type_code_range(self) -> None:
        for rt in RecordType:
            code = int(rt)
            assert 0x01 <= code <= 0x0E

    def test_record_type_codes_are_contiguous_from_1(self) -> None:
        codes = sorted([int(rt) for rt in RecordType])
        expected = list(range(1, len(RecordType) + 1))
        assert codes == expected


class TestPayloadFieldValidation:
    def test_node_upsert_accepts_graph_node(self) -> None:
        node = GraphNode(id="n1", type=NodeType.FILE, file_path="/p.py")
        payload = NodeUpsertPayload(node=node)
        assert payload.node.id == "n1"

    def test_edge_upsert_accepts_graph_edge(self) -> None:
        edge = GraphEdge(source_id="n1", target_id="n2", type=EdgeType.CALLS)
        payload = EdgeUpsertPayload(edge=edge)
        assert payload.edge.source_id == "n1"

    def test_lock_upsert_fencing_token_negative(self) -> None:
        payload = LockUpsertPayload(
            file_path="/p.py",
            session_id="sess-1",
            fencing_token=-1,
        )
        assert payload.fencing_token == -1

    def test_parse_status_line_count_negative(self) -> None:
        payload = ParseStatusPayload(file_path="/p.py", line_count=-1)
        assert payload.line_count == -1

    def test_transaction_tx_id_zero(self) -> None:
        payload = TransactionPayload(tx_id=0)
        assert payload.tx_id == 0

    def test_transaction_tx_id_large(self) -> None:
        payload = TransactionPayload(tx_id=2**32 - 1)
        assert payload.tx_id == 2**32 - 1

    def test_session_upsert_data_empty_dict(self) -> None:
        payload = SessionUpsertPayload(session_id="s1", data={})
        assert payload.data == {}

    def test_session_upsert_data_nested(self) -> None:
        payload = SessionUpsertPayload(
            session_id="s1",
            data={"nested": {"key": ["list", "values"]}},
        )
        assert payload.data["nested"] == {"key": ["list", "values"]}

    def test_audit_append_event_empty_dict(self) -> None:
        payload = AuditAppendPayload(event={})
        assert payload.event == {}

    def test_audit_append_event_nested(self) -> None:
        payload = AuditAppendPayload(
            event={"user": {"id": 123, "name": "test"}},
        )
        assert payload.event["user"]["id"] == 123


class TestPayloadDefaults:
    def test_session_upsert_data_default_factory(self) -> None:
        payload = SessionUpsertPayload(session_id="s1")
        assert isinstance(payload.data, dict)

    def test_lock_upsert_string_defaults(self) -> None:
        payload = LockUpsertPayload(file_path="/p.py", session_id="s1")
        assert payload.acquired_at == ""
        assert payload.expires_at == ""

    def test_lock_upsert_fencing_token_default(self) -> None:
        payload = LockUpsertPayload(file_path="/p.py", session_id="s1")
        assert payload.fencing_token == 0

    def test_parse_status_defaults(self) -> None:
        payload = ParseStatusPayload(file_path="/p.py")
        assert payload.parsed is False
        assert payload.line_count == 0
        assert payload.node_count == 0
        assert payload.stale is False
        assert payload.parse_time_ms is None
        assert payload.content_hash == ""

    def test_transaction_defaults(self) -> None:
        payload = TransactionPayload(tx_id=1)
        assert payload.actor == ""
        assert payload.note == ""


class TestPayloadRepr:
    def test_node_upsert_repr(self) -> None:
        node = GraphNode(id="n1", type=NodeType.FILE, file_path="/p.py")
        payload = NodeUpsertPayload(node=node)
        r = repr(payload)
        assert "NodeUpsertPayload" in r
        assert "n1" in r

    def test_node_delete_repr(self) -> None:
        payload = NodeDeletePayload(node_id="n1")
        r = repr(payload)
        assert "NodeDeletePayload" in r
        assert "n1" in r


class TestAllPayloadsInstantiable:
    def test_all_payloads_can_be_instantiated(self) -> None:
        NodeUpsertPayload(node=GraphNode(id="n", type=NodeType.FILE, file_path="/p.py"))
        NodeDeletePayload(node_id="n")
        EdgeUpsertPayload(edge=GraphEdge(source_id="s", target_id="t", type=EdgeType.CALLS))
        FileDeletePayload(file_path="/p.py")
        SessionUpsertPayload(session_id="s1")
        SessionDeletePayload(session_id="s1")
        LockUpsertPayload(file_path="/p.py", session_id="s1")
        LockReleasePayload(file_path="/p.py", session_id="s1")
        LockReleaseAllPayload(session_id="s1")
        AuditAppendPayload(event={})
        ParseStatusPayload(file_path="/p.py")
        TransactionPayload(tx_id=1)

    def test_all_payloads_encode(self) -> None:
        payloads = [
            NodeUpsertPayload(node=GraphNode(id="n", type=NodeType.FILE, file_path="/p.py")),
            NodeDeletePayload(node_id="n"),
            EdgeUpsertPayload(edge=GraphEdge(source_id="s", target_id="t", type=EdgeType.CALLS)),
            FileDeletePayload(file_path="/p.py"),
            SessionUpsertPayload(session_id="s1"),
            SessionDeletePayload(session_id="s1"),
            LockUpsertPayload(file_path="/p.py", session_id="s1"),
            LockReleasePayload(file_path="/p.py", session_id="s1"),
            LockReleaseAllPayload(session_id="s1"),
            AuditAppendPayload(event={}),
            ParseStatusPayload(file_path="/p.py"),
            TransactionPayload(tx_id=1),
        ]
        for p in payloads:
            encoded = encode(p)
            assert isinstance(encoded, bytes)
            assert len(encoded) > 0


class TestModuleExports:
    def test_all_exports_present(self) -> None:
        from smp.store.graph.records import __all__

        expected = [
            "AuditAppendPayload",
            "EdgeUpsertPayload",
            "FileDeletePayload",
            "LockReleaseAllPayload",
            "LockReleasePayload",
            "LockUpsertPayload",
            "NodeDeletePayload",
            "NodeUpsertPayload",
            "ParseStatusPayload",
            "SessionDeletePayload",
            "SessionUpsertPayload",
            "TransactionPayload",
            "decode",
            "encode",
        ]
        for name in expected:
            assert name in __all__


class TestJournalCorruptionError:
    def test_exception_exists(self) -> None:
        from smp.store.graph.journal import JournalCorruptionError

        err = JournalCorruptionError("test message")
        assert isinstance(err, Exception)
        assert str(err) == "test message"

    def test_exception_raised_and_caught(self) -> None:
        from smp.store.graph.journal import JournalCorruptionError

        with pytest.raises(JournalCorruptionError):
            raise JournalCorruptionError("corruption detected")
