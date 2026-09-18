"""Disaster recovery tests: Journal corruption handling.

D-004: Corrupted journal (damaged entry skipped)
"""

from __future__ import annotations

import contextlib
from typing import Any

import pytest

from smp.core.models import (
    EdgeType,
    GraphEdge,
    GraphNode,
    NodeType,
    SemanticProperties,
    StructuralProperties,
)
from smp.store.graph.journal import RecordType
from smp.store.graph.mmap_store import MMapGraphStore
from smp.store.graph.records import (
    EdgeUpsertPayload,
    NodeUpsertPayload,
    TransactionPayload,
    encode,
)


class TestCorruptedJournal:
    """D-004: Corrupted journal (damaged entry skipped)."""

    @pytest.mark.asyncio
    async def test_truncated_journal_skips_corrupt_entry(self, tmp_path):
        """D-004: Truncated journal entry is skipped, valid entries are processed."""
        graph_path = tmp_path / "truncated_journal.smpg"
        store = MMapGraphStore(path=graph_path)
        await store.connect()

        for i in range(5):
            await store.upsert_node(make_node(id=f"valid_{i}"))

        with open(graph_path, "ab") as f:
            f.write(b"\x00\xff\xfe\xdd corrupted data")
            valid_payload = encode(TransactionPayload(tx_id=999, actor="test", note="after_corruption"))
            f.write(valid_payload)

        await store.close()

        store2 = MMapGraphStore(path=graph_path)
        await store2.connect()
        try:
            for i in range(5):
                node = await store2.get_node(f"valid_{i}")
                assert node is not None, f"valid_{i} should be present"
        finally:
            await store2.close()

    @pytest.mark.asyncio
    async def test_invalid_magic_bytes_handled(self, tmp_path):
        """D-004: Invalid magic bytes in journal are handled gracefully."""
        graph_path = tmp_path / "invalid_magic.smpg"
        store = MMapGraphStore(path=graph_path)
        await store.connect()

        await store.upsert_node(make_node(id="pre_magic"))

        with open(graph_path, "ab") as f:
            f.write(b"\xaa\xbb\xcc\xdd invalid magic")
            valid_data = encode(TransactionPayload(tx_id=100, actor="test", note="valid"))
            f.write(valid_data)

        await store.close()

        store2 = MMapGraphStore(path=graph_path)
        await store2.connect()
        try:
            assert await store2.get_node("pre_magic") is not None
        finally:
            await store2.close()

    @pytest.mark.asyncio
    async def test_missing_magic_header_recovery(self, tmp_path):
        """D-004: Journal without proper magic header is handled."""
        graph_path = tmp_path / "no_magic.smpg"
        store = MMapGraphStore(path=graph_path)
        await store.connect()

        await store.upsert_node(make_node(id="header_test"))

        with open(graph_path, "ab") as f:
            f.write(b"NOHEADER")
            valid_tx = encode(TransactionPayload(tx_id=1, actor="test", note="recover"))
            f.write(valid_tx)

        await store.close()

        store2 = MMapGraphStore(path=graph_path)
        await store2.connect()
        try:
            assert await store2.get_node("header_test") is not None
        finally:
            await store2.close()

    @pytest.mark.asyncio
    async def test_checksum_mismatch_handled(self, tmp_path):
        """D-004: Checksum mismatch causes entry to be skipped."""
        graph_path = tmp_path / "checksum_fail.smpg"
        store = MMapGraphStore(path=graph_path)
        await store.connect()

        for i in range(10):
            await store.upsert_node(make_node(id=f"checksum_pre_{i}"))

        store._append(RecordType.BEGIN_TX, encode(TransactionPayload(tx_id=1, actor="test", note="checksum_test")))
        store._append(RecordType.NODE_UPSERT, encode(NodeUpsertPayload(node=make_node(id="corrupt_checksum"))))

        # Corrupt the tail record inside the live data region.
        corrupt_at = store.file.data_region_end - 20
        await store.flush()
        with open(graph_path, "r+b") as f:
            f.seek(corrupt_at)
            f.write(b"\xff\xff\xff\xff")

        await store.close()

        store2 = MMapGraphStore(path=graph_path)
        await store2.connect()
        try:
            for i in range(10):
                assert await store2.get_node(f"checksum_pre_{i}") is not None
        finally:
            await store2.close()

    @pytest.mark.asyncio
    async def test_multiple_corrupted_entries_handled(self, tmp_path):
        """D-004: Multiple corrupted entries are skipped."""
        graph_path = tmp_path / "multi_corrupt.smpg"
        store = MMapGraphStore(path=graph_path)
        await store.connect()

        for i in range(15):
            await store.upsert_node(make_node(id=f"pre_corrupt_{i}"))

        with open(graph_path, "ab") as f:
            for _ in range(3):
                f.write(b"\x00\x01\x02\x03 CORRUPT")

        store._append(RecordType.BEGIN_TX, encode(TransactionPayload(tx_id=100, actor="test", note="after_corruption")))
        store._append(RecordType.NODE_UPSERT, encode(NodeUpsertPayload(node=make_node(id="after_corruption_node"))))
        store._append(RecordType.COMMIT_TX, encode(TransactionPayload(tx_id=100, actor="test", note="commit")))

        await store.close()

        store2 = MMapGraphStore(path=graph_path)
        await store2.connect()
        try:
            for i in range(15):
                assert await store2.get_node(f"pre_corrupt_{i}") is not None
            assert await store2.get_node("after_corruption_node") is not None
        finally:
            await store2.close()

    @pytest.mark.asyncio
    async def test_corrupt_node_payload_handled(self, tmp_path):
        """D-004: Corrupted node payload in journal is skipped."""
        graph_path = tmp_path / "corrupt_node.smpg"
        store = MMapGraphStore(path=graph_path)
        await store.connect()

        await store.upsert_node(make_node(id="pre_node_corrupt"))

        store._append(RecordType.NODE_UPSERT, b"INVALID_JSON_DATA")

        store._append(RecordType.BEGIN_TX, encode(TransactionPayload(tx_id=1, actor="test", note="valid_after")))
        store._append(RecordType.NODE_UPSERT, encode(NodeUpsertPayload(node=make_node(id="valid_after_node"))))
        store._append(RecordType.COMMIT_TX, encode(TransactionPayload(tx_id=1, actor="test", note="commit")))

        await store.close()

        store2 = MMapGraphStore(path=graph_path)
        await store2.connect()
        try:
            assert await store2.get_node("pre_node_corrupt") is not None
            assert await store2.get_node("valid_after_node") is not None
        finally:
            await store2.close()

    @pytest.mark.asyncio
    async def test_corrupt_edge_payload_handled(self, tmp_path):
        """D-004: Corrupted edge payload in journal is skipped."""
        graph_path = tmp_path / "corrupt_edge.smpg"
        store = MMapGraphStore(path=graph_path)
        await store.connect()

        await store.upsert_node(make_node(id="edge_src"))
        await store.upsert_node(make_node(id="edge_tgt"))

        store._append(RecordType.EDGE_UPSERT, b"CORRUPTED_EDGE_DATA")

        store._append(RecordType.BEGIN_TX, encode(TransactionPayload(tx_id=2, actor="test", note="valid_edge")))
        store._append(RecordType.EDGE_UPSERT, encode(EdgeUpsertPayload(edge=make_edge("edge_src", "edge_tgt"))))
        store._append(RecordType.COMMIT_TX, encode(TransactionPayload(tx_id=2, actor="test", note="commit")))

        await store.close()

        store2 = MMapGraphStore(path=graph_path)
        await store2.connect()
        try:
            edge = await store2.get_edge("edge_src", "edge_tgt")
            assert edge is not None
        finally:
            await store2.close()

    @pytest.mark.asyncio
    async def test_partial_record_at_eof_handled(self, tmp_path):
        """D-004: Partial record at end of file is handled."""
        graph_path = tmp_path / "partial_eof.smpg"
        store = MMapGraphStore(path=graph_path)
        await store.connect()

        for i in range(8):
            await store.upsert_node(make_node(id=f"eof_pre_{i}"))

        with open(graph_path, "ab") as f:
            f.write(b"PARTIAL")

        await store.close()

        store2 = MMapGraphStore(path=graph_path)
        await store2.connect()
        try:
            for i in range(8):
                assert await store2.get_node(f"eof_pre_{i}") is not None
        finally:
            await store2.close()

    @pytest.mark.asyncio
    async def test_duplicate_record_type_handled(self, tmp_path):
        """D-004: Duplicate record types in sequence are handled."""
        graph_path = tmp_path / "duplicate_record.smpg"
        store = MMapGraphStore(path=graph_path)
        await store.connect()

        for i in range(3):
            store._append(RecordType.NODE_UPSERT, encode(NodeUpsertPayload(node=make_node(id=f"dup_{i}"))))

        await store.close()

        store2 = MMapGraphStore(path=graph_path)
        await store2.connect()
        try:
            for i in range(3):
                assert await store2.get_node(f"dup_{i}") is not None
        finally:
            await store2.close()

    @pytest.mark.asyncio
    async def test_journal_with_leading_garbage(self, tmp_path):
        """D-004: Journal with leading garbage is handled."""
        graph_path = tmp_path / "leading_garbage.smpg"
        store = MMapGraphStore(path=graph_path)
        await store.connect()

        with open(graph_path, "ab") as f:
            f.write(b"\x00\x11\x22\x33 GARBAGE_BEGIN")
            f.write(b"\x44\x55\x66\x77 MORE_GARBAGE")

        store._append(RecordType.BEGIN_TX, encode(TransactionPayload(tx_id=1, actor="test", note="valid_start")))
        store._append(RecordType.NODE_UPSERT, encode(NodeUpsertPayload(node=make_node(id="valid_start_node"))))
        store._append(RecordType.COMMIT_TX, encode(TransactionPayload(tx_id=1, actor="test", note="commit")))

        await store.close()

        store2 = MMapGraphStore(path=graph_path)
        await store2.connect()
        try:
            assert await store2.get_node("valid_start_node") is not None
        finally:
            await store2.close()

    @pytest.mark.asyncio
    async def test_mixed_valid_invalid_records(self, tmp_path):
        """D-004: Mixed valid and invalid records are processed correctly."""
        graph_path = tmp_path / "mixed_records.smpg"
        store = MMapGraphStore(path=graph_path)
        await store.connect()

        await store.upsert_node(make_node(id="v1"))
        store._append(RecordType.NODE_UPSERT, b"INVALID1")
        await store.upsert_node(make_node(id="v2"))
        store._append(RecordType.NODE_UPSERT, b"INVALID2")
        await store.upsert_node(make_node(id="v3"))

        await store.close()

        store2 = MMapGraphStore(path=graph_path)
        await store2.connect()
        try:
            assert await store2.get_node("v1") is not None
            assert await store2.get_node("v2") is not None
            assert await store2.get_node("v3") is not None
        finally:
            await store2.close()

    @pytest.mark.asyncio
    async def test_orphaned_commit_handled(self, tmp_path):
        """D-004: Orphaned COMMIT without BEGIN is handled."""
        graph_path = tmp_path / "orphan_commit.smpg"
        store = MMapGraphStore(path=graph_path)
        await store.connect()

        await store.upsert_node(make_node(id="pre_orphan"))

        store._append(RecordType.COMMIT_TX, encode(TransactionPayload(tx_id=999, actor="test", note="orphan")))

        await store.upsert_node(make_node(id="post_orphan"))

        await store.close()

        store2 = MMapGraphStore(path=graph_path)
        await store2.connect()
        try:
            assert await store2.get_node("pre_orphan") is not None
            assert await store2.get_node("post_orphan") is not None
        finally:
            await store2.close()

    @pytest.mark.asyncio
    async def test_oversized_record_truncated(self, tmp_path):
        """D-004: Oversized record is handled."""
        graph_path = tmp_path / "oversized.smpg"
        store = MMapGraphStore(path=graph_path)
        await store.connect()

        await store.upsert_node(make_node(id="pre_oversized"))

        large_data = b"A" * 1000000
        with contextlib.suppress(Exception):
            store._append(RecordType.NODE_UPSERT, large_data)

        await store.upsert_node(make_node(id="post_oversized"))

        await store.close()

        store2 = MMapGraphStore(path=graph_path)
        await store2.connect()
        try:
            assert await store2.get_node("pre_oversized") is not None
            assert await store2.get_node("post_oversized") is not None
        finally:
            await store2.close()


def make_node(
    id: str = "test_node", type: NodeType = NodeType.FUNCTION, file_path: str = "test.py", **kwargs: Any
) -> GraphNode:
    """Helper to create test nodes."""
    defaults = {
        "id": id,
        "type": type,
        "file_path": file_path,
        "structural": StructuralProperties(name=id, file=file_path, signature="def test():", start_line=1, end_line=2),
        "semantic": SemanticProperties(docstring=f"Doc for {id}", status="test"),
    }
    defaults.update(kwargs)
    return GraphNode(**defaults)


def make_edge(source: str = "src", target: str = "tgt", edge_type: EdgeType = EdgeType.CALLS) -> GraphEdge:
    """Helper to create test edges."""
    return GraphEdge(source_id=source, target_id=target, type=edge_type)
