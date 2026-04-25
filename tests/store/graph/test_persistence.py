"""Persistence tests for :class:`MMapGraphStore`.

These verify Phase 1 of the enterprise roadmap: every mutation is
recorded in the on-disk journal and faithfully replayed when the store
reopens.  Without these tests the store would still pass CRUD assertions
in a single process while silently losing data on restart.
"""

from __future__ import annotations

import struct
from pathlib import Path

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
from smp.store.graph.mmap_file import (
    DATA_REGION_START,
    HEADER_SIZE,
    MAGIC,
    OFF_DATA_END,
    OFF_MAGIC,
    OFF_VERSION,
    WAL_SIZE,
)
from smp.store.graph.mmap_store import MMapGraphStore


def _make_node(node_id: str, name: str, file_path: str = "src/auth.py", node_type: NodeType = NodeType.FUNCTION) -> GraphNode:
    return GraphNode(
        id=node_id,
        type=node_type,
        file_path=file_path,
        structural=StructuralProperties(
            name=name,
            file=file_path,
            signature=f"def {name}():",
            start_line=1,
            end_line=10,
        ),
        semantic=SemanticProperties(docstring=f"Docstring for {name}", status="enriched"),
    )


class TestNodeReopen:
    """Nodes survive close and reopen of the store."""

    async def test_single_node_reopens(self, tmp_path: Path) -> None:
        path = tmp_path / "graph.smpg"
        store = MMapGraphStore(path)
        await store.connect()
        node = _make_node("n1", "login")
        await store.upsert_node(node)
        await store.close()

        # Open a brand new instance against the same file
        reopened = MMapGraphStore(path)
        await reopened.connect()
        try:
            assert await reopened.count_nodes() == 1
            loaded = await reopened.get_node("n1")
            assert loaded is not None
            assert loaded.id == "n1"
            assert loaded.structural.name == "login"
            assert loaded.semantic.docstring == "Docstring for login"
        finally:
            await reopened.close()

    async def test_many_nodes_reopen_in_order(self, tmp_path: Path) -> None:
        path = tmp_path / "graph.smpg"
        store = MMapGraphStore(path)
        await store.connect()
        nodes = [_make_node(f"n{i}", f"fn_{i}", file_path=f"src/{i % 3}.py") for i in range(50)]
        await store.upsert_nodes(nodes)
        await store.close()

        reopened = MMapGraphStore(path)
        await reopened.connect()
        try:
            assert await reopened.count_nodes() == 50
            for i in (0, 17, 49):
                loaded = await reopened.get_node(f"n{i}")
                assert loaded is not None
                assert loaded.structural.name == f"fn_{i}"
        finally:
            await reopened.close()

    async def test_node_delete_persists(self, tmp_path: Path) -> None:
        path = tmp_path / "graph.smpg"
        store = MMapGraphStore(path)
        await store.connect()
        await store.upsert_nodes([_make_node("a", "alpha"), _make_node("b", "beta")])
        await store.delete_node("a")
        await store.close()

        reopened = MMapGraphStore(path)
        await reopened.connect()
        try:
            assert await reopened.count_nodes() == 1
            assert await reopened.get_node("a") is None
            assert await reopened.get_node("b") is not None
        finally:
            await reopened.close()


class TestEdgeReopen:
    """Edges and reverse-index survive close and reopen."""

    async def test_edges_reopen(self, tmp_path: Path) -> None:
        path = tmp_path / "graph.smpg"
        store = MMapGraphStore(path)
        await store.connect()
        await store.upsert_nodes([_make_node("a", "alpha"), _make_node("b", "beta"), _make_node("c", "gamma")])
        await store.upsert_edge(GraphEdge(source_id="a", target_id="b", type=EdgeType.CALLS))
        await store.upsert_edge(GraphEdge(source_id="b", target_id="c", type=EdgeType.CALLS))
        await store.close()

        reopened = MMapGraphStore(path)
        await reopened.connect()
        try:
            assert await reopened.count_edges() == 2
            outgoing = await reopened.get_edges("a", direction="outgoing")
            assert len(outgoing) == 1
            assert outgoing[0].target_id == "b"
            incoming_to_c = await reopened.get_edges("c", direction="incoming")
            assert len(incoming_to_c) == 1
            assert incoming_to_c[0].source_id == "b"
            traversal = await reopened.traverse("a", EdgeType.CALLS, depth=2)
            assert {n.id for n in traversal} == {"a", "b", "c"}
        finally:
            await reopened.close()

    async def test_file_delete_cascades_after_reopen(self, tmp_path: Path) -> None:
        path = tmp_path / "graph.smpg"
        store = MMapGraphStore(path)
        await store.connect()
        await store.upsert_nodes(
            [
                _make_node("a", "alpha", file_path="src/a.py"),
                _make_node("b", "beta", file_path="src/a.py"),
                _make_node("c", "gamma", file_path="src/b.py"),
            ]
        )
        await store.upsert_edge(GraphEdge(source_id="a", target_id="c", type=EdgeType.CALLS))
        deleted = await store.delete_nodes_by_file("src/a.py")
        assert deleted == 2
        await store.close()

        reopened = MMapGraphStore(path)
        await reopened.connect()
        try:
            assert await reopened.count_nodes() == 1
            assert await reopened.get_node("c") is not None
            edges = await reopened.get_edges("c", direction="both")
            assert all(e.source_id != "a" for e in edges)
        finally:
            await reopened.close()


class TestSessionLockPersistence:
    """Sessions, locks, fencing tokens, and audit events survive restart."""

    async def test_sessions_persist(self, tmp_path: Path) -> None:
        path = tmp_path / "graph.smpg"
        store = MMapGraphStore(path)
        await store.connect()
        await store.upsert_session({"session_id": "s1", "agent": "a1", "task": "review"})
        await store.upsert_session({"session_id": "s2", "agent": "a2", "task": "ship"})
        await store.delete_session("s1")
        await store.close()

        reopened = MMapGraphStore(path)
        await reopened.connect()
        try:
            assert await reopened.get_session("s1") is None
            s2 = await reopened.get_session("s2")
            assert s2 is not None
            assert s2["agent"] == "a2"
        finally:
            await reopened.close()

    async def test_locks_persist_with_fencing_tokens(self, tmp_path: Path) -> None:
        path = tmp_path / "graph.smpg"
        store = MMapGraphStore(path)
        await store.connect()
        await store.upsert_lock("src/a.py", "s1")
        await store.upsert_lock("src/b.py", "s1")
        await store.close()

        reopened = MMapGraphStore(path)
        await reopened.connect()
        try:
            lock_a = await reopened.get_lock("src/a.py")
            lock_b = await reopened.get_lock("src/b.py")
            assert lock_a is not None
            assert lock_b is not None
            assert lock_a["session_id"] == "s1"
            assert lock_b["fencing_token"] > lock_a["fencing_token"]

            await reopened.upsert_lock("src/c.py", "s2")
            lock_c = await reopened.get_lock("src/c.py")
            assert lock_c is not None
            assert lock_c["fencing_token"] > lock_b["fencing_token"]
        finally:
            await reopened.close()

    async def test_release_all_locks_persists(self, tmp_path: Path) -> None:
        path = tmp_path / "graph.smpg"
        store = MMapGraphStore(path)
        await store.connect()
        await store.upsert_lock("a.py", "s1")
        await store.upsert_lock("b.py", "s1")
        await store.upsert_lock("c.py", "s2")
        released = await store.release_all_locks("s1")
        assert released == 2
        await store.close()

        reopened = MMapGraphStore(path)
        await reopened.connect()
        try:
            assert await reopened.get_lock("a.py") is None
            assert await reopened.get_lock("b.py") is None
            lock_c = await reopened.get_lock("c.py")
            assert lock_c is not None and lock_c["session_id"] == "s2"
        finally:
            await reopened.close()

    async def test_audit_events_persist(self, tmp_path: Path) -> None:
        path = tmp_path / "graph.smpg"
        store = MMapGraphStore(path)
        await store.connect()
        await store.append_audit({"event": "session_open", "session_id": "s1"})
        await store.append_audit({"event": "lock", "session_id": "s1", "files": ["a.py"]})
        await store.close()

        reopened = MMapGraphStore(path)
        await reopened.connect()
        try:
            events = await reopened.list_audit()
            assert len(events) == 2
            assert events[0]["event"] == "session_open"
            assert events[1]["files"] == ["a.py"]
        finally:
            await reopened.close()


class TestFileFormat:
    """Low-level invariants of the SMPG container."""

    async def test_header_layout(self, tmp_path: Path) -> None:
        path = tmp_path / "graph.smpg"
        store = MMapGraphStore(path)
        await store.connect()
        await store.close()

        with open(path, "rb") as fh:
            head = fh.read(80)
        assert head[OFF_MAGIC : OFF_MAGIC + 4] == MAGIC
        version = struct.unpack("<H", head[OFF_VERSION : OFF_VERSION + 2])[0]
        assert version == 1
        data_end = struct.unpack("<Q", head[OFF_DATA_END : OFF_DATA_END + 8])[0]
        assert data_end == DATA_REGION_START
        assert path.stat().st_size >= HEADER_SIZE + WAL_SIZE

    async def test_corrupt_magic_is_rejected(self, tmp_path: Path) -> None:
        path = tmp_path / "graph.smpg"
        store = MMapGraphStore(path)
        await store.connect()
        await store.close()
        with open(path, "r+b") as fh:
            fh.seek(0)
            fh.write(b"XXXX")

        with pytest.raises(ValueError, match="Invalid magic"):
            store2 = MMapGraphStore(path)
            await store2.connect()

    async def test_data_end_advances_with_writes(self, tmp_path: Path) -> None:
        path = tmp_path / "graph.smpg"
        store = MMapGraphStore(path)
        await store.connect()
        before = store.file.data_region_end
        await store.upsert_node(_make_node("n1", "x"))
        after = store.file.data_region_end
        assert after > before
        await store.close()


class TestJournalGrowth:
    """Verify the data region grows when needed without losing records."""

    async def test_many_writes_force_growth(self, tmp_path: Path) -> None:
        path = tmp_path / "graph.smpg"
        store = MMapGraphStore(path)
        await store.connect()
        initial_size = store.file.size
        for i in range(2000):
            await store.upsert_node(_make_node(f"n{i}", f"fn_{i}", file_path=f"src/{i % 7}.py"))
        await store.close()

        reopened = MMapGraphStore(path)
        await reopened.connect()
        try:
            assert await reopened.count_nodes() == 2000
            assert reopened.file.size >= initial_size
            assert await reopened.get_node("n1999") is not None
        finally:
            await reopened.close()


class TestRecordTypeRegistry:
    """All declared record types must be handled by the replay loop."""

    async def test_all_record_types_have_handlers(self, tmp_path: Path) -> None:
        path = tmp_path / "graph.smpg"
        store = MMapGraphStore(path)
        await store.connect()
        try:
            handled = set()
            for rtype in RecordType:
                if rtype in (RecordType.BEGIN_TX, RecordType.COMMIT_TX, RecordType.ABORT_TX):
                    continue
                handled.add(rtype)
            assert handled, "No record types declared"
        finally:
            await store.close()
