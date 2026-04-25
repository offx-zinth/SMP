"""Phase 2 tests: transactions, durability modes, crash recovery, integrity.

These tests confirm:

* Records inside an open transaction only become visible after commit.
* A simulated crash mid-transaction drops the partial work on replay.
* :class:`DurabilityMode` controls call sites of ``flush`` / ``fsync``.
* :meth:`MMapGraphStore.integrity_report` surfaces dangling references
  and corruption in a structured form.
"""

from __future__ import annotations

import struct
from pathlib import Path
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
from smp.store.graph.mmap_file import OFF_DATA_END, OFF_VERSION
from smp.store.graph.mmap_store import DurabilityMode, MMapGraphStore


def _node(node_id: str, name: str = "fn", file_path: str = "src/x.py") -> GraphNode:
    return GraphNode(
        id=node_id,
        type=NodeType.FUNCTION,
        file_path=file_path,
        structural=StructuralProperties(name=name, file=file_path, signature=f"def {name}():", start_line=1),
        semantic=SemanticProperties(),
    )


class TestTransactionCommit:
    """Basic transaction lifecycle on a single store."""

    async def test_commit_writes_become_visible_on_reopen(self, tmp_path: Path) -> None:
        path = tmp_path / "graph.smpg"
        store = MMapGraphStore(path)
        await store.connect()
        async with store.transaction(actor="agent1") as tx_id:
            assert tx_id == 1
            assert store.active_transaction == 1
            await store.upsert_node(_node("n1"))
            await store.upsert_node(_node("n2"))
        assert store.active_transaction is None
        await store.close()

        reopened = MMapGraphStore(path)
        await reopened.connect()
        try:
            assert await reopened.count_nodes() == 2
            assert await reopened.get_node("n1") is not None
            assert await reopened.get_node("n2") is not None
        finally:
            await reopened.close()

    async def test_explicit_abort_drops_work(self, tmp_path: Path) -> None:
        path = tmp_path / "graph.smpg"
        store = MMapGraphStore(path)
        await store.connect()
        with pytest.raises(RuntimeError, match="boom"):
            async with store.transaction():
                await store.upsert_node(_node("n1"))
                raise RuntimeError("boom")
        await store.close()

        reopened = MMapGraphStore(path)
        await reopened.connect()
        try:
            assert await reopened.count_nodes() == 0
            assert await reopened.get_node("n1") is None
        finally:
            await reopened.close()

    async def test_serial_transactions(self, tmp_path: Path) -> None:
        path = tmp_path / "graph.smpg"
        store = MMapGraphStore(path)
        await store.connect()
        async with store.transaction():
            await store.upsert_node(_node("a"))
        async with store.transaction():
            await store.upsert_node(_node("b"))
            await store.upsert_edge(GraphEdge(source_id="a", target_id="b", type=EdgeType.CALLS))
        await store.close()

        reopened = MMapGraphStore(path)
        await reopened.connect()
        try:
            assert await reopened.count_nodes() == 2
            assert await reopened.count_edges() == 1
        finally:
            await reopened.close()


class TestCrashRecovery:
    """Transactions that never commit must not appear after reopen."""

    async def _simulate_partial_commit(self, path: Path) -> None:
        """Write a BEGIN_TX + records + intentionally truncate before COMMIT_TX."""
        store = MMapGraphStore(path)
        await store.connect()
        # Commit one good transaction first
        async with store.transaction():
            await store.upsert_node(_node("good"))
        # Begin a second one and write some records, but exit without commit by
        # patching the file at the OS level.
        async with store.transaction():
            await store.upsert_node(_node("dirty1"))
            await store.upsert_node(_node("dirty2"))
            # Manually shorten data_end to chop the COMMIT marker that will
            # be written when the context manager exits — the simplest way
            # to fake "we crashed before commit" is to grab the offset now,
            # let the commit run, then rewind.
            crash_point = store.file.data_region_end

        # Now rewind data_end to drop the COMMIT_TX record without touching the
        # bytes — they remain on disk but are outside the valid journal range.
        with open(path, "r+b") as fh:
            fh.seek(OFF_DATA_END)
            fh.write(struct.pack("<Q", crash_point))
            # Recompute and rewrite the header CRC so validation still passes.
            fh.seek(0)
            from smp.store.graph.mmap_file import HEADER_SIZE, OFF_CRC, OFF_ROOTS  # local import to avoid cycle

            fh.seek(OFF_ROOTS)
            header_data = fh.read(HEADER_SIZE - OFF_ROOTS)
            import zlib

            crc = zlib.crc32(header_data) & 0xFFFFFFFF
            fh.seek(OFF_CRC)
            fh.write(struct.pack("<I", crc))
        await store.close()

    async def test_uncommitted_transaction_dropped_on_replay(self, tmp_path: Path) -> None:
        path = tmp_path / "graph.smpg"
        await self._simulate_partial_commit(path)

        reopened = MMapGraphStore(path)
        await reopened.connect()
        try:
            assert await reopened.get_node("good") is not None
            assert await reopened.get_node("dirty1") is None
            assert await reopened.get_node("dirty2") is None
            assert await reopened.count_nodes() == 1
        finally:
            await reopened.close()

    async def test_corrupted_payload_raises_on_replay(self, tmp_path: Path) -> None:
        path = tmp_path / "graph.smpg"
        store = MMapGraphStore(path)
        await store.connect()
        await store.upsert_node(_node("a"))
        end = store.file.data_region_end
        await store.close()

        # Flip a byte inside the last record's payload — CRC must catch this.
        with open(path, "r+b") as fh:
            fh.seek(end - 5)
            fh.write(b"\xff")

        reopened = MMapGraphStore(path)
        with pytest.raises(Exception):  # noqa: B017,PT011
            await reopened.connect()


class TestDurabilityModes:
    """``DurabilityMode`` controls when the file is flushed."""

    async def test_sync_mode_fsyncs_each_write(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        path = tmp_path / "graph.smpg"
        store = MMapGraphStore(path, durability=DurabilityMode.SYNC)
        await store.connect()

        calls: list[str] = []
        original_fsync = store.file.fsync
        original_flush = store.file.flush

        def record_fsync() -> None:
            calls.append("fsync")
            original_fsync()

        def record_flush() -> None:
            calls.append("flush")
            original_flush()

        monkeypatch.setattr(store.file, "fsync", record_fsync)
        monkeypatch.setattr(store.file, "flush", record_flush)

        await store.upsert_node(_node("a"))
        await store.upsert_node(_node("b"))
        await store.close()

        assert calls.count("fsync") >= 2

    async def test_periodic_mode_flushes_after_threshold(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        path = tmp_path / "graph.smpg"
        store = MMapGraphStore(path, durability=DurabilityMode.PERIODIC, flush_every=4)
        await store.connect()

        flush_calls: list[str] = []
        original = store.file.flush

        def record() -> None:
            flush_calls.append("flush")
            original()

        monkeypatch.setattr(store.file, "flush", record)

        for i in range(10):
            await store.upsert_node(_node(f"n{i}"))
        await store.close()
        # 10 writes / 4 every = 2 periodic flushes (plus close-time flush)
        assert len(flush_calls) >= 2


class TestIntegrityReport:
    """``integrity_report`` surfaces structural problems in the live store."""

    async def test_clean_store_is_ok(self, tmp_path: Path) -> None:
        path = tmp_path / "graph.smpg"
        store = MMapGraphStore(path)
        await store.connect()
        await store.upsert_nodes([_node("a"), _node("b")])
        await store.upsert_edge(GraphEdge(source_id="a", target_id="b", type=EdgeType.CALLS))
        report = await store.integrity_report()
        try:
            assert report["ok"] is True
            assert report["warnings"] == []
            assert report["errors"] == []
            assert report["stats"]["nodes"] == 2
            assert report["stats"]["edges"] == 1
            assert report["stats"]["records"] >= 3
        finally:
            await store.close()

    async def test_dangling_edges_are_flagged(self, tmp_path: Path) -> None:
        path = tmp_path / "graph.smpg"
        store = MMapGraphStore(path)
        await store.connect()
        await store.upsert_node(_node("a"))
        await store.upsert_edge(GraphEdge(source_id="a", target_id="ghost", type=EdgeType.CALLS))
        report = await store.integrity_report()
        try:
            kinds = [w["kind"] for w in report["warnings"]]
            assert "dangling_incoming_edges" in kinds
        finally:
            await store.close()

    async def test_lock_pointing_to_unknown_session_is_flagged(self, tmp_path: Path) -> None:
        path = tmp_path / "graph.smpg"
        store = MMapGraphStore(path)
        await store.connect()
        await store.upsert_lock("a.py", "ghost-session")
        report = await store.integrity_report()
        try:
            kinds = [w["kind"] for w in report["warnings"]]
            assert "lock_unknown_session" in kinds
        finally:
            await store.close()


class TestIntegrityHandler:
    """``smp/integrity/check`` exposes the store-level report when no node_id."""

    async def test_store_level_check_returns_report(self, tmp_path: Path) -> None:
        from smp.engine.graph_builder import DefaultGraphBuilder
        from smp.engine.query import DefaultQueryEngine
        from smp.protocol.handlers.sync import integrity_check

        path = tmp_path / "graph.smpg"
        store = MMapGraphStore(path)
        await store.connect()
        await store.upsert_node(_node("a"))
        ctx: dict[str, Any] = {
            "graph": store,
            "engine": DefaultQueryEngine(graph_store=store),
            "builder": DefaultGraphBuilder(store),
        }

        result = await integrity_check({}, ctx)
        try:
            assert result["scope"] == "store"
            assert result["ok"] is True
            assert result["stats"]["nodes"] == 1
        finally:
            await store.close()

    async def test_node_level_check_still_works(self, tmp_path: Path) -> None:
        import json
        import hashlib

        from smp.engine.graph_builder import DefaultGraphBuilder
        from smp.engine.query import DefaultQueryEngine
        from smp.protocol.handlers.sync import _node_signature, integrity_check

        path = tmp_path / "graph.smpg"
        store = MMapGraphStore(path)
        await store.connect()
        node = _node("a", name="alpha")
        await store.upsert_node(node)
        ctx: dict[str, Any] = {
            "graph": store,
            "engine": DefaultQueryEngine(graph_store=store),
            "builder": DefaultGraphBuilder(store),
        }
        signature = _node_signature(node)

        good = await integrity_check({"node_id": "a", "current_state": {"signature": signature}}, ctx)
        bad = await integrity_check({"node_id": "a", "current_state": {"signature": "wrong"}}, ctx)
        try:
            assert good["matches"] is True
            assert bad["matches"] is False
        finally:
            await store.close()
        del json, hashlib  # silence unused-import linters
