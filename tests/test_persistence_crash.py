from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from smp.core.models import GraphNode, NodeType, StructuralProperties
from smp.store.graph.journal import RecordType
from smp.store.graph.mmap_store import MMapGraphStore
from smp.store.graph.records import NodeUpsertPayload, TransactionPayload, encode


@pytest.mark.asyncio
async def test_persistence_crash_recovery():
    """Verify that the store can recover from an abrupt shutdown."""
    with tempfile.TemporaryDirectory() as tmp:
        graph_path = Path(tmp) / "crash_test.smpg"

        store = MMapGraphStore(graph_path)
        await store.connect()

        node = GraphNode(
            id="crash::node::1",
            type=NodeType.FUNCTION,
            file_path="crash.py",
            structural=StructuralProperties(
                name="crash_func",
                file="crash.py",
                signature="def crash_func():",
                start_line=1,
                end_line=2,
            ),
        )
        await store.upsert_node(node)

        # Simulate crash: we do NOT call store.close()
        del store

        recovered_store = MMapGraphStore(graph_path)
        await recovered_store.connect()

        try:
            recovered_node = await recovered_store.get_node("crash::node::1")
            assert recovered_node is not None
            assert recovered_node.structural.name == "crash_func"
        finally:
            await recovered_store.close()


@pytest.mark.asyncio
async def test_transactional_crash_recovery():
    """Verify that uncommitted transactions are dropped after a crash."""
    with tempfile.TemporaryDirectory() as tmp:
        graph_path = Path(tmp) / "tx_crash_test.smpg"

        store = MMapGraphStore(graph_path)
        await store.connect()

        # 1. Write a committed node
        node1 = GraphNode(
            id="committed::1",
            type=NodeType.FUNCTION,
            file_path="f1.py",
            structural=StructuralProperties(name="n1", file="f1.py", signature="", start_line=1, end_line=2),
        )
        await store.upsert_node(node1)

        # 2. Manually write a transaction that is NEVER committed
        # We use _append to bypass the context manager that would write ABORT/COMMIT
        store._append(RecordType.BEGIN_TX, encode(TransactionPayload(tx_id=1, actor="test", note="crash")))

        node2 = GraphNode(
            id="uncommitted::1",
            type=NodeType.FUNCTION,
            file_path="f2.py",
            structural=StructuralProperties(name="n2", file="f2.py", signature="", start_line=1, end_line=2),
        )
        store._append(RecordType.NODE_UPSERT, encode(NodeUpsertPayload(node=node2)))

        # Crash now
        del store

        # 3. Reopen and verify
        recovered_store = MMapGraphStore(graph_path)
        await recovered_store.connect()

        try:
            # Committed node should be there
            assert await recovered_store.get_node("committed::1") is not None
            # Uncommitted node should be gone
            assert await recovered_store.get_node("uncommitted::1") is None
        finally:
            await recovered_store.close()
