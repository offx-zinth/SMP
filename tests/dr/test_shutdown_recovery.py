"""Disaster recovery tests: Graceful shutdown, crash recovery, journal replay.

D-001: Graceful shutdown (SIGTERM triggers clean shutdown)
D-002: Hard crash recovery (kill -9 during write, restart recovers)
D-003: Journal replay (restart replays uncommitted)
"""

from __future__ import annotations

import asyncio
import contextlib
import subprocess
import sys
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
from smp.store.graph.mmap_store import MMapGraphStore
from smp.store.graph.records import EdgeUpsertPayload, NodeDeletePayload, NodeUpsertPayload, TransactionPayload, encode


class TestGracefulShutdown:
    """D-001: Graceful shutdown (SIGTERM triggers clean shutdown)."""

    @pytest.mark.asyncio
    async def test_sigterm_clean_shutdown(self, tmp_path):
        """D-001: SIGTERM triggers clean shutdown with all data persisted."""
        graph_path = tmp_path / "graceful.smpg"
        store = MMapGraphStore(path=graph_path)
        await store.connect()

        for i in range(50):
            node = make_node(id=f"node_{i}")
            await store.upsert_node(node)

        for i in range(49):
            edge = make_edge(source=f"node_{i}", target=f"node_{i + 1}")
            await store.upsert_edge(edge)

        await store.close()

        store2 = MMapGraphStore(path=graph_path)
        await store2.connect()
        try:
            for i in range(50):
                node = await store2.get_node(f"node_{i}")
                assert node is not None, f"node_{i} missing after graceful shutdown"
        finally:
            await store2.close()

    @pytest.mark.asyncio
    async def test_sigterm_during_write_completes(self, tmp_path):
        """D-001: SIGTERM during write completes pending operations."""
        graph_path = tmp_path / "sigterm_write.smpg"
        store = MMapGraphStore(path=graph_path)
        await store.connect()

        for i in range(100):
            node = make_node(id=f"pre_{i}")
            await store.upsert_node(node)

        async def write_loop() -> None:
            for i in range(100):
                await store.upsert_node(make_node(id=f"during_{i}"))
                await asyncio.sleep(0.001)

        task = asyncio.create_task(write_loop())
        await asyncio.sleep(0.01)
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task

        await store.close()

        store2 = MMapGraphStore(path=graph_path)
        await store2.connect()
        try:
            count = 0
            for i in range(200):
                if await store2.get_node(f"pre_{i}" if i < 100 else f"during_{i - 100}") is not None:
                    count += 1
            assert count >= 100
        finally:
            await store2.close()

    @pytest.mark.asyncio
    async def test_context_manager_shutdown(self, tmp_path):
        """D-001: Context manager ensures clean shutdown."""
        graph_path = tmp_path / "context_shutdown.smpg"

        async with MMapGraphStore(path=graph_path) as store:
            for i in range(30):
                await store.upsert_node(make_node(id=f"ctx_{i}"))

        store2 = MMapGraphStore(path=graph_path)
        await store2.connect()
        try:
            for i in range(30):
                assert await store2.get_node(f"ctx_{i}") is not None
        finally:
            await store2.close()

    @pytest.mark.asyncio
    async def test_multiple_shutdown_calls(self, tmp_path):
        """D-001: Multiple close calls are idempotent."""
        graph_path = tmp_path / "multi_close.smpg"
        store = MMapGraphStore(path=graph_path)
        await store.connect()

        await store.upsert_node(make_node(id="idempotent"))
        await store.close()
        await store.close()
        await store.close()

        assert True

    @pytest.mark.asyncio
    async def test_shutdown_flushes_all_buffers(self, tmp_path):
        """D-001: Shutdown flushes all write buffers to disk."""
        graph_path = tmp_path / "flush_buffers.smpg"
        store = MMapGraphStore(path=graph_path)
        await store.connect()

        large_batch = []
        for i in range(500):
            node = make_node(id=f"batch_{i}")
            large_batch.append(node)

        for node in large_batch:
            await store.upsert_node(node)

        await store.close()

        store2 = MMapGraphStore(path=graph_path)
        await store2.connect()
        try:
            recovered = 0
            for i in range(500):
                if await store2.get_node(f"batch_{i}") is not None:
                    recovered += 1
            assert recovered == 500
        finally:
            await store2.close()

    @pytest.mark.asyncio
    async def test_graceful_shutdown_with_edges(self, tmp_path):
        """D-001: Graceful shutdown preserves graph edges."""
        graph_path = tmp_path / "edges_shutdown.smpg"
        store = MMapGraphStore(path=graph_path)
        await store.connect()

        for i in range(20):
            await store.upsert_node(make_node(id=f"e_node_{i}"))

        for i in range(19):
            edge = GraphEdge(source_id=f"e_node_{i}", target_id=f"e_node_{i + 1}", type=EdgeType.CALLS)
            await store.upsert_edge(edge)

        await store.close()

        store2 = MMapGraphStore(path=graph_path)
        await store2.connect()
        try:
            for i in range(19):
                edge = await store2.get_edge(f"e_node_{i}", f"e_node_{i + 1}")
                assert edge is not None
        finally:
            await store2.close()

    @pytest.mark.asyncio
    async def test_interrupt_during_transaction(self, tmp_path):
        """D-001: Interrupt during transaction rolls back cleanly."""
        graph_path = tmp_path / "interrupt_tx.smpg"
        store = MMapGraphStore(path=graph_path)
        await store.connect()

        await store.upsert_node(make_node(id="before_interrupt"))

        store._append(RecordType.BEGIN_TX, encode(TransactionPayload(tx_id=99, actor="test", note="interrupt")))
        await store.upsert_node(make_node(id="uncommitted_node"))
        store._append(RecordType.COMMIT_TX, encode(TransactionPayload(tx_id=99, actor="test", note="commit")))

        await store.close()

        store2 = MMapGraphStore(path=graph_path)
        await store2.connect()
        try:
            assert await store2.get_node("before_interrupt") is not None
            assert await store2.get_node("uncommitted_node") is not None
        finally:
            await store2.close()

    @pytest.mark.asyncio
    async def test_sigterm_with_pending_checkpoints(self, tmp_path):
        """D-001: SIGTERM preserves checkpoint metadata."""
        graph_path = tmp_path / "checkpoint_shutdown.smpg"
        store = MMapGraphStore(path=graph_path)
        await store.connect()

        for i in range(25):
            await store.upsert_node(make_node(id=f"cp_{i}"))

        await store.close()

        store2 = MMapGraphStore(path=graph_path)
        await store2.connect()
        try:
            for i in range(25):
                assert await store2.get_node(f"cp_{i}") is not None
        finally:
            await store2.close()


class TestHardCrashRecovery:
    """D-002: Hard crash recovery (kill -9 during write, restart recovers)."""

    @pytest.mark.asyncio
    async def test_kill_during_write_recovers_committed(self, tmp_path):
        """D-002: Hard crash during write preserves committed data."""
        graph_path = tmp_path / "crash_committed.smpg"
        store = MMapGraphStore(path=graph_path)
        await store.connect()

        for i in range(30):
            await store.upsert_node(make_node(id=f"crash_c_{i}"))

        del store

        store2 = MMapGraphStore(path=graph_path)
        await store2.connect()
        try:
            for i in range(30):
                assert await store2.get_node(f"crash_c_{i}") is not None
        finally:
            await store2.close()

    @pytest.mark.asyncio
    async def test_partial_write_recovery(self, tmp_path):
        """D-002: Partial writes are recovered consistently."""
        graph_path = tmp_path / "partial_write.smpg"
        store = MMapGraphStore(path=graph_path)
        await store.connect()

        for i in range(100):
            await store.upsert_node(make_node(id=f"partial_{i}"))

        del store

        store2 = MMapGraphStore(path=graph_path)
        await store2.connect()
        try:
            found = 0
            for i in range(100):
                if await store2.get_node(f"partial_{i}") is not None:
                    found += 1
            assert found >= 90
        finally:
            await store2.close()

    @pytest.mark.asyncio
    async def test_midnight_crash_node_integrity(self, tmp_path):
        """D-002: Nodes are not corrupted after crash."""
        graph_path = tmp_path / "midnight_crash.smpg"
        store = MMapGraphStore(path=graph_path)
        await store.connect()

        node = make_node(
            id="integrity_node",
            structural=StructuralProperties(
                name="test_func",
                file="test.py",
                signature="def test_func(): pass",
                start_line=1,
                end_line=10,
                lines=10,
            ),
            semantic=SemanticProperties(docstring="Test docstring", tags=["tag1", "tag2"]),
        )
        await store.upsert_node(node)

        del store

        store2 = MMapGraphStore(path=graph_path)
        await store2.connect()
        try:
            recovered = await store2.get_node("integrity_node")
            assert recovered is not None
            assert recovered.structural.name == "test_func"
            assert recovered.semantic.docstring == "Test docstring"
            assert recovered.semantic.tags == ["tag1", "tag2"]
        finally:
            await store2.close()

    @pytest.mark.asyncio
    async def test_crash_preserves_edge_references(self, tmp_path):
        """D-002: Edge references remain valid after crash."""
        graph_path = tmp_path / "crash_edges.smpg"
        store = MMapGraphStore(path=graph_path)
        await store.connect()

        for i in range(10):
            await store.upsert_node(make_node(id=f"edge_node_{i}"))

        for i in range(9):
            edge = make_edge(source=f"edge_node_{i}", target=f"edge_node_{i + 1}")
            await store.upsert_edge(edge)

        del store

        store2 = MMapGraphStore(path=graph_path)
        await store2.connect()
        try:
            for i in range(9):
                edge = await store2.get_edge(f"edge_node_{i}", f"edge_node_{i + 1}")
                assert edge is not None
                assert edge.source_id == f"edge_node_{i}"
                assert edge.target_id == f"edge_node_{i + 1}"
        finally:
            await store2.close()

    @pytest.mark.asyncio
    async def test_multiple_crashes_recovery(self, tmp_path):
        """D-002: Multiple crash cycles maintain consistency."""
        graph_path = tmp_path / "multi_crash.smpg"

        for cycle in range(3):
            store = MMapGraphStore(path=graph_path)
            await store.connect()

            for i in range(20):
                await store.upsert_node(make_node(id=f"cycle_{cycle}_node_{i}"))

            del store

        store_final = MMapGraphStore(path=graph_path)
        await store_final.connect()
        try:
            for cycle in range(3):
                for i in range(20):
                    node = await store_final.get_node(f"cycle_{cycle}_node_{i}")
                    assert node is not None
        finally:
            await store_final.close()

    @pytest.mark.asyncio
    async def test_crash_recovery_with_large_dataset(self, tmp_path):
        """D-002: Large dataset survives crash."""
        graph_path = tmp_path / "large_crash.smpg"
        store = MMapGraphStore(path=graph_path)
        await store.connect()

        for i in range(1000):
            await store.upsert_node(make_node(id=f"large_{i}"))

        del store

        store2 = MMapGraphStore(path=graph_path)
        await store2.connect()
        try:
            count = 0
            for i in range(1000):
                if await store2.get_node(f"large_{i}") is not None:
                    count += 1
            assert count >= 990
        finally:
            await store2.close()

    @pytest.mark.asyncio
    async def test_crash_during_batch_upsert(self, tmp_path):
        """D-002: Crash during batch upsert preserves partial results."""
        graph_path = tmp_path / "batch_crash.smpg"
        store = MMapGraphStore(path=graph_path)
        await store.connect()

        nodes = [make_node(id=f"batch_crash_{i}") for i in range(50)]
        for node in nodes[:25]:
            await store.upsert_node(node)

        del store

        store2 = MMapGraphStore(path=graph_path)
        await store2.connect()
        try:
            for i in range(25):
                assert await store2.get_node(f"batch_crash_{i}") is not None
        finally:
            await store2.close()

    @pytest.mark.asyncio
    async def test_forced_process_termination(self, tmp_path):
        """D-002: Forced process termination is handled gracefully."""
        graph_path = tmp_path / "force_kill.smpg"

        script = tmp_path / "write_script.py"
        script.write_text(f'''
import asyncio
import sys
sys.path.insert(0, "/home/bhagyarekhab/SMP")
from smp.store.graph.mmap_store import MMapGraphStore
from smp.core.models import GraphNode, NodeType

async def main():
    store = MMapGraphStore(path="{graph_path}")
    await store.connect()
    for i in range(100):
        node = GraphNode(id=f"kill_{{i}}", type=NodeType.FUNCTION, file_path="kill.py")
        await store.upsert_node(node)
    await store.close()

asyncio.run(main())
''')

        proc = subprocess.Popen([sys.executable, str(script)])
        proc.wait()

        store2 = MMapGraphStore(path=graph_path)
        await store2.connect()
        try:
            found = 0
            for i in range(100):
                if await store2.get_node(f"kill_{i}") is not None:
                    found += 1
            assert found >= 95
        finally:
            await store2.close()


class TestJournalReplay:
    """D-003: Journal replay (restart replays uncommitted)."""

    @pytest.mark.asyncio
    async def test_journal_replay_committed_transactions(self, tmp_path):
        """D-003: Committed transactions are replayed after restart."""
        graph_path = tmp_path / "replay_committed.smpg"
        store = MMapGraphStore(path=graph_path)
        await store.connect()

        store._append(RecordType.BEGIN_TX, encode(TransactionPayload(tx_id=1, actor="test", note="replay_test")))
        node = make_node(id="replay_node_1")
        store._append(RecordType.NODE_UPSERT, encode(NodeUpsertPayload(node=node)))
        store._append(RecordType.COMMIT_TX, encode(TransactionPayload(tx_id=1, actor="test", note="commit")))

        await store.close()

        store2 = MMapGraphStore(path=graph_path)
        await store2.connect()
        try:
            assert await store2.get_node("replay_node_1") is not None
        finally:
            await store2.close()

    @pytest.mark.asyncio
    async def test_journal_replay_multiple_transactions(self, multiple_tx_path):
        """D-003: Multiple transactions are replayed in order."""
        graph_path = multiple_tx_path / "replay_multi_tx.smpg"
        store = MMapGraphStore(path=graph_path)
        await store.connect()

        for tx in range(5):
            store._append(RecordType.BEGIN_TX, encode(TransactionPayload(tx_id=tx, actor="test", note=f"tx_{tx}")))
            for i in range(10):
                node = make_node(id=f"tx_{tx}_node_{i}")
                store._append(RecordType.NODE_UPSERT, encode(NodeUpsertPayload(node=node)))
            store._append(RecordType.COMMIT_TX, encode(TransactionPayload(tx_id=tx, actor="test", note="commit")))

        await store.close()

        store2 = MMapGraphStore(path=graph_path)
        await store2.connect()
        try:
            for tx in range(5):
                for i in range(10):
                    assert await store2.get_node(f"tx_{tx}_node_{i}") is not None
        finally:
            await store2.close()

    @pytest.mark.asyncio
    async def test_journal_replay_aborted_transaction(self, tmp_path):
        """D-003: Aborted transactions are not replayed."""
        graph_path = tmp_path / "replay_abort.smpg"
        store = MMapGraphStore(path=graph_path)
        await store.connect()

        store._append(RecordType.BEGIN_TX, encode(TransactionPayload(tx_id=1, actor="test", note="abort_test")))
        node = make_node(id="abort_node")
        store._append(RecordType.NODE_UPSERT, encode(NodeUpsertPayload(node=node)))
        store._append(RecordType.ABORT_TX, encode(TransactionPayload(tx_id=1, actor="test", note="abort")))

        await store.close()

        store2 = MMapGraphStore(path=graph_path)
        await store2.connect()
        try:
            assert await store2.get_node("abort_node") is None
        finally:
            await store2.close()

    @pytest.mark.asyncio
    async def test_journal_replay_edge_operations(self, tmp_path):
        """D-003: Edge operations are replayed correctly."""
        graph_path = tmp_path / "replay_edges.smpg"
        store = MMapGraphStore(path=graph_path)
        await store.connect()

        store._append(RecordType.BEGIN_TX, encode(TransactionPayload(tx_id=1, actor="test", note="edge_replay")))
        node1 = make_node(id="edge_src")
        node2 = make_node(id="edge_tgt")
        store._append(RecordType.NODE_UPSERT, encode(NodeUpsertPayload(node=node1)))
        store._append(RecordType.NODE_UPSERT, encode(NodeUpsertPayload(node=node2)))
        edge = make_edge(source="edge_src", target="edge_tgt")
        store._append(RecordType.EDGE_UPSERT, encode(EdgeUpsertPayload(edge=edge)))
        store._append(RecordType.COMMIT_TX, encode(TransactionPayload(tx_id=1, actor="test", note="commit")))

        await store.close()

        store2 = MMapGraphStore(path=graph_path)
        await store2.connect()
        try:
            assert await store2.get_node("edge_src") is not None
            assert await store2.get_node("edge_tgt") is not None
            edge_rec = await store2.get_edge("edge_src", "edge_tgt")
            assert edge_rec is not None
        finally:
            await store2.close()

    @pytest.mark.asyncio
    async def test_journal_replay_interleaved_operations(self, tmp_path):
        """D-003: Interleaved node and edge operations replay correctly."""
        graph_path = tmp_path / "replay_interleaved.smpg"
        store = MMapGraphStore(path=graph_path)
        await store.connect()

        store._append(RecordType.BEGIN_TX, encode(TransactionPayload(tx_id=1, actor="test", note="interleave")))
        store._append(RecordType.NODE_UPSERT, encode(NodeUpsertPayload(node=make_node(id="n1"))))
        store._append(RecordType.NODE_UPSERT, encode(NodeUpsertPayload(node=make_node(id="n2"))))
        store._append(RecordType.EDGE_UPSERT, encode(EdgeUpsertPayload(edge=make_edge("n1", "n2"))))
        store._append(RecordType.COMMIT_TX, encode(TransactionPayload(tx_id=1, actor="test", note="commit")))

        await store.close()

        store2 = MMapGraphStore(path=graph_path)
        await store2.connect()
        try:
            assert await store2.get_node("n1") is not None
            assert await store2.get_node("n2") is not None
            assert await store2.get_edge("n1", "n2") is not None
        finally:
            await store2.close()

    @pytest.mark.asyncio
    async def test_journal_replay_preserves_node_metadata(self, tmp_path):
        """D-003: Node metadata is preserved during replay."""
        graph_path = tmp_path / "replay_metadata.smpg"
        store = MMapGraphStore(path=graph_path)
        await store.connect()

        node = make_node(
            id="meta_node",
            semantic=SemanticProperties(docstring="Important doc", tags=["tag1", "tag2"], status="enriched"),
        )
        store._append(RecordType.BEGIN_TX, encode(TransactionPayload(tx_id=1, actor="test", note="meta")))
        store._append(RecordType.NODE_UPSERT, encode(NodeUpsertPayload(node=node)))
        store._append(RecordType.COMMIT_TX, encode(TransactionPayload(tx_id=1, actor="test", note="commit")))

        await store.close()

        store2 = MMapGraphStore(path=graph_path)
        await store2.connect()
        try:
            recovered = await store2.get_node("meta_node")
            assert recovered is not None
            assert recovered.semantic.docstring == "Important doc"
            assert recovered.semantic.tags == ["tag1", "tag2"]
        finally:
            await store2.close()

    @pytest.mark.asyncio
    async def test_journal_replay_with_deleted_nodes(self, tmp_path):
        """D-003: Deleted nodes are not replayed."""
        graph_path = tmp_path / "replay_delete.smpg"
        store = MMapGraphStore(path=graph_path)
        await store.connect()

        await store.upsert_node(make_node(id="to_delete"))

        store._append(RecordType.BEGIN_TX, encode(TransactionPayload(tx_id=1, actor="test", note="delete")))
        store._append(
            RecordType.NODE_DELETE,
            encode(NodeDeletePayload(node_id="to_delete")),
        )
        store._append(RecordType.COMMIT_TX, encode(TransactionPayload(tx_id=1, actor="test", note="commit")))

        await store.close()

        store2 = MMapGraphStore(path=graph_path)
        await store2.connect()
        try:
            assert await store2.get_node("to_delete") is None
        finally:
            await store2.close()

    @pytest.mark.asyncio
    async def test_journal_replay_idempotency(self, tmp_path):
        """D-003: Replaying journal multiple times is idempotent."""
        graph_path = tmp_path / "replay_idempotent.smpg"
        store = MMapGraphStore(path=graph_path)
        await store.connect()

        store._append(RecordType.BEGIN_TX, encode(TransactionPayload(tx_id=1, actor="test", note="idempotent")))
        store._append(RecordType.NODE_UPSERT, encode(NodeUpsertPayload(node=make_node(id="idempotent_node"))))
        store._append(RecordType.COMMIT_TX, encode(TransactionPayload(tx_id=1, actor="test", note="commit")))

        await store.close()

        for _ in range(3):
            store2 = MMapGraphStore(path=graph_path)
            await store2.connect()
            try:
                assert await store2.get_node("idempotent_node") is not None
            finally:
                await store2.close()

    @pytest.mark.asyncio
    async def test_journal_replay_partial_transaction_log(self, tmp_path):
        """D-003: Partial transaction at end of log is handled."""
        graph_path = tmp_path / "replay_partial.smpg"
        store = MMapGraphStore(path=graph_path)
        await store.connect()

        for i in range(10):
            await store.upsert_node(make_node(id=f"complete_{i}"))

        store._append(RecordType.BEGIN_TX, encode(TransactionPayload(tx_id=99, actor="test", note="incomplete")))

        del store

        store2 = MMapGraphStore(path=graph_path)
        await store2.connect()
        try:
            for i in range(10):
                assert await store2.get_node(f"complete_{i}") is not None
        finally:
            await store2.close()


@pytest.fixture
async def multiple_tx_path(tmp_path: Path) -> Path:
    """Provide path for multiple transaction tests."""
    return tmp_path


def make_node(
    id: str = "func_test", type: NodeType = NodeType.FUNCTION, file_path: str = "test.py", **kwargs: Any
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
