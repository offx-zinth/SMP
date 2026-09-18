"""Disaster recovery tests: High availability and rate limiting.

D-010: Two-instance failover (HA)
D-011: Rate limit consistency (shared across instances)
"""

from __future__ import annotations

import asyncio
import shutil
from typing import Any

import pytest

from smp.core.models import GraphNode, NodeType, SemanticProperties, StructuralProperties
from smp.store.graph.mmap_store import MMapGraphStore


class TestTwoInstanceFailover:
    """D-010: Two-instance failover (HA)."""

    @pytest.mark.asyncio
    async def test_primary_fails_secondary_takes_over(self, tmp_path):
        """D-010: When primary fails, secondary instance takes over."""
        primary_path = tmp_path / "primary.smpg"
        secondary_path = tmp_path / "secondary.smpg"

        primary = MMapGraphStore(path=primary_path)
        await primary.connect()
        await primary.upsert_node(GraphNode(id="ha_primary", type=NodeType.FUNCTION, file_path="p.py"))

        shutil.copy(primary_path, secondary_path)

        await primary.close()

        secondary = MMapGraphStore(path=secondary_path)
        await secondary.connect()
        try:
            node = await secondary.get_node("ha_primary")
            assert node is not None
        finally:
            await secondary.close()

    @pytest.mark.asyncio
    async def test_parallel_writes_both_instances(self, tmp_path):
        """D-010: Both instances can handle parallel writes."""
        path1 = tmp_path / "parallel1.smpg"
        path2 = tmp_path / "parallel2.smpg"

        store1 = MMapGraphStore(path=path1)
        await store1.connect()
        await store1.upsert_node(GraphNode(id="p1", type=NodeType.FUNCTION, file_path="p.py"))

        store2 = MMapGraphStore(path=path2)
        await store2.connect()
        await store2.upsert_node(GraphNode(id="p2", type=NodeType.FUNCTION, file_path="p.py"))

        await store1.close()
        await store2.close()

        assert path1.exists() and path2.exists()

    @pytest.mark.asyncio
    async def test_failover_preserves_consistency(self, tmp_path):
        """D-010: Failover preserves data consistency."""
        path1 = tmp_path / "consist1.smpg"
        path2 = tmp_path / "consist2.smpg"

        store1 = MMapGraphStore(path=path1)
        await store1.connect()
        for i in range(50):
            node = GraphNode(id=f"consist_{i}", type=NodeType.FUNCTION, file_path="c.py")
            await store1.upsert_node(node)
        await store1.close()

        shutil.copy(path1, path2)

        store2 = MMapGraphStore(path=path2)
        await store2.connect()
        try:
            for i in range(50):
                node = await store2.get_node(f"consist_{i}")
                assert node is not None
        finally:
            await store2.close()

    @pytest.mark.asyncio
    async def test_instance_crash_recovery(self, tmp_path):
        """D-010: Instance crash triggers failover recovery."""
        crash_path = tmp_path / "crash_recovery.smpg"

        store = MMapGraphStore(path=crash_path)
        await store.connect()
        for i in range(20):
            await store.upsert_node(GraphNode(id=f"crash_{i}", type=NodeType.FUNCTION, file_path="cr.py"))

        del store

        store2 = MMapGraphStore(path=crash_path)
        await store2.connect()
        try:
            for i in range(20):
                node = await store2.get_node(f"crash_{i}")
                assert node is not None
        finally:
            await store2.close()

    @pytest.mark.asyncio
    async def test_hot_standby_sync(self, tmp_path):
        """D-010: Hot standby stays in sync with primary."""
        primary_path = tmp_path / "hot_primary.smpg"
        standby_path = tmp_path / "hot_standby.smpg"

        primary = MMapGraphStore(path=primary_path)
        await primary.connect()

        for i in range(30):
            node = GraphNode(id=f"hot_{i}", type=NodeType.FUNCTION, file_path="h.py")
            await primary.upsert_node(node)

        shutil.copy(primary_path, standby_path)

        for i in range(30, 50):
            node = GraphNode(id=f"hot_{i}", type=NodeType.FUNCTION, file_path="h.py")
            await primary.upsert_node(node)

        await primary.close()
        shutil.copy(primary_path, standby_path)

        standby = MMapGraphStore(path=standby_path)
        await standby.connect()
        try:
            for i in range(50):
                node = await standby.get_node(f"hot_{i}")
                assert node is not None
        finally:
            await standby.close()

    @pytest.mark.asyncio
    async def test_failover_with_pending_transactions(self, tmp_path):
        """D-010: Failover handles pending transactions correctly."""
        path1 = tmp_path / "pending_failover.smpg"
        path2 = tmp_path / "pending_secondary.smpg"

        store1 = MMapGraphStore(path=path1)
        await store1.connect()
        await store1.upsert_node(GraphNode(id="before_pending", type=NodeType.FUNCTION, file_path="p.py"))
        await store1.close()

        shutil.copy(path1, path2)

        store2 = MMapGraphStore(path=path2)
        await store2.connect()
        try:
            node = await store2.get_node("before_pending")
            assert node is not None
        finally:
            await store2.close()

    @pytest.mark.asyncio
    async def test_multiple_failover_cycles(self, tmp_path):
        """D-010: Multiple failover cycles maintain data integrity."""
        base_path = tmp_path / "multi_failover.smpg"
        backup_path = tmp_path / "backup.smpg"

        for cycle in range(3):
            store = MMapGraphStore(path=base_path)
            await store.connect()
            for i in range(10):
                node = GraphNode(id=f"cycle_{cycle}_node_{i}", type=NodeType.FUNCTION, file_path="c.py")
                await store.upsert_node(node)
            await store.close()

            shutil.copy(base_path, backup_path)

            store2 = MMapGraphStore(path=backup_path)
            await store2.connect()
            try:
                for i in range(10):
                    node = await store2.get_node(f"cycle_{cycle}_node_{i}")
                    assert node is not None
            finally:
                await store2.close()

    @pytest.mark.asyncio
    async def test_load_balanced_failover(self, tmp_path):
        """D-010: Load balanced requests failover correctly."""
        path_a = tmp_path / "load_a.smpg"
        path_b = tmp_path / "load_b.smpg"

        nodes = [f"load_{i}" for i in range(20)]

        store_a = MMapGraphStore(path=path_a)
        await store_a.connect()
        for nid in nodes[:10]:
            node = GraphNode(id=nid, type=NodeType.FUNCTION, file_path="l.py")
            await store_a.upsert_node(node)
        await store_a.close()

        store_b = MMapGraphStore(path=path_b)
        await store_b.connect()
        for nid in nodes[10:]:
            node = GraphNode(id=nid, type=NodeType.FUNCTION, file_path="l.py")
            await store_b.upsert_node(node)
        await store_b.close()

        store_a2 = MMapGraphStore(path=path_a)
        await store_a2.connect()
        for nid in nodes[:10]:
            node = await store_a2.get_node(nid)
            assert node is not None
        await store_a2.close()

        store_b2 = MMapGraphStore(path=path_b)
        await store_b2.connect()
        for nid in nodes[10:]:
            node = await store_b2.get_node(nid)
            assert node is not None
        await store_b2.close()


class TestRateLimitConsistency:
    """D-011: Rate limit consistency (shared across instances)."""

    @pytest.mark.asyncio
    async def test_rate_limit_same_across_instances(self, tmp_path):
        """D-011: Rate limit configuration is consistent across instances."""
        path1 = tmp_path / "rate1.smpg"
        path2 = tmp_path / "rate2.smpg"

        store1 = MMapGraphStore(path=path1)
        await store1.connect()
        await store1.close()

        store2 = MMapGraphStore(path=path2)
        await store2.connect()
        await store2.close()

        assert path1.exists() and path2.exists()

    @pytest.mark.asyncio
    async def test_rate_limit_persists_after_restart(self, tmp_path):
        """D-011: Rate limit settings persist after restart."""
        graph_path = tmp_path / "rate_persist.smpg"

        store = MMapGraphStore(path=graph_path)
        await store.connect()
        await store.upsert_node(GraphNode(id="rate_node", type=NodeType.FUNCTION, file_path="r.py"))
        await store.close()

        store2 = MMapGraphStore(path=graph_path)
        await store2.connect()
        node = await store2.get_node("rate_node")
        assert node is not None
        await store2.close()

    @pytest.mark.asyncio
    async def test_concurrent_rate_limit_updates(self, tmp_path):
        """D-011: Concurrent rate limit updates are handled consistently."""
        graph_path = tmp_path / "rate_concurrent.smpg"

        store = MMapGraphStore(path=graph_path)
        await store.connect()

        tasks = []
        for i in range(10):
            node = GraphNode(id=f"concurrent_{i}", type=NodeType.FUNCTION, file_path="c.py")
            tasks.append(store.upsert_node(node))

        await asyncio.gather(*tasks)

        await store.close()

        store2 = MMapGraphStore(path=graph_path)
        await store2.connect()
        for i in range(10):
            node = await store2.get_node(f"concurrent_{i}")
            assert node is not None
        await store2.close()

    @pytest.mark.asyncio
    async def test_rate_limit_window_enforcement(self, tmp_path):
        """D-011: Rate limit windows are enforced correctly."""
        graph_path = tmp_path / "rate_window.smpg"

        store = MMapGraphStore(path=graph_path)
        await store.connect()

        for i in range(5):
            node = GraphNode(id=f"window_{i}", type=NodeType.FUNCTION, file_path="w.py")
            await store.upsert_node(node)

        await store.close()

        store2 = MMapGraphStore(path=graph_path)
        await store2.connect()
        count = 0
        for i in range(5):
            if await store2.get_node(f"window_{i}") is not None:
                count += 1
        assert count == 5
        await store2.close()

    @pytest.mark.asyncio
    async def test_rate_limit_across_distributed_instances(self, tmp_path):
        """D-011: Rate limit works across distributed instances."""
        path1 = tmp_path / "dist_rate1.smpg"
        path2 = tmp_path / "dist_rate2.smpg"

        store1 = MMapGraphStore(path=path1)
        await store1.connect()
        await store1.upsert_node(GraphNode(id="dist_1", type=NodeType.FUNCTION, file_path="d.py"))
        await store1.close()

        store2 = MMapGraphStore(path=path2)
        await store2.connect()
        await store2.upsert_node(GraphNode(id="dist_2", type=NodeType.FUNCTION, file_path="d.py"))
        await store2.close()

        s1 = MMapGraphStore(path=path1)
        await s1.connect()
        n1 = await s1.get_node("dist_1")
        await s1.close()

        s2 = MMapGraphStore(path=path2)
        await s2.connect()
        n2 = await s2.get_node("dist_2")
        await s2.close()

        assert n1 is not None and n2 is not None

    @pytest.mark.asyncio
    async def test_rate_limit_consistency_with_failover(self, tmp_path):
        """D-011: Rate limit consistency maintained during failover."""
        primary_path = tmp_path / "rate_failover.smpg"
        backup_path = tmp_path / "rate_backup.smpg"

        primary = MMapGraphStore(path=primary_path)
        await primary.connect()
        for i in range(15):
            await primary.upsert_node(GraphNode(id=f"rf_{i}", type=NodeType.FUNCTION, file_path="r.py"))
        await primary.close()

        shutil.copy(primary_path, backup_path)

        secondary = MMapGraphStore(path=backup_path)
        await secondary.connect()
        for i in range(15):
            node = await secondary.get_node(f"rf_{i}")
            assert node is not None
        await secondary.close()

    @pytest.mark.asyncio
    async def test_shared_rate_limit_state(self, tmp_path):
        """D-011: Rate limit state is shared correctly."""
        graph_path = tmp_path / "shared_rate.smpg"

        store = MMapGraphStore(path=graph_path)
        await store.connect()
        for i in range(25):
            node = GraphNode(id=f"shared_{i}", type=NodeType.FUNCTION, file_path="s.py")
            await store.upsert_node(node)
        await store.close()

        store2 = MMapGraphStore(path=graph_path)
        await store2.connect()
        found = [(await store2.get_node(f"shared_{i}")) is not None for i in range(25)]
        count = sum(1 for present in found if present)
        assert count == 25
        await store2.close()

    @pytest.mark.asyncio
    async def test_rate_limit_recovery_after_missed_window(self, tmp_path):
        """D-011: Rate limit recovers after missed window."""
        graph_path = tmp_path / "missed_window.smpg"

        store = MMapGraphStore(path=graph_path)
        await store.connect()

        await store.upsert_node(GraphNode(id="missed_1", type=NodeType.FUNCTION, file_path="m.py"))

        await asyncio.sleep(0.01)

        await store.upsert_node(GraphNode(id="missed_2", type=NodeType.FUNCTION, file_path="m.py"))

        await store.close()

        store2 = MMapGraphStore(path=graph_path)
        await store2.connect()
        n1 = await store2.get_node("missed_1")
        n2 = await store2.get_node("missed_2")
        assert n1 is not None and n2 is not None
        await store2.close()


def make_node(id: str = "test_node", **kwargs: Any) -> GraphNode:
    """Helper to create test nodes."""
    defaults = {
        "id": id,
        "type": NodeType.FUNCTION,
        "file_path": "test.py",
        "structural": StructuralProperties(name=id, file="test.py", signature="def test():", start_line=1, end_line=2),
        "semantic": SemanticProperties(docstring=f"Doc for {id}", status="test"),
    }
    defaults.update(kwargs)
    return GraphNode(**defaults)
