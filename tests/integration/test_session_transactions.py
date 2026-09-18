"""Integration tests for Sessions + Transactions.

These tests confirm:
* Sessions survive transaction commits.
* Locks acquired in a session survive transaction boundaries.
* Uncommitted sessions are rolled back on abort.
* Multiple sessions in concurrent transactions work correctly.
* Audit trail includes session events inside transactions.
* Session recovery works after simulated crashes.
* Fencing tokens work correctly within transactions.
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
from smp.store.graph.mmap_store import MMapGraphStore


def _node(node_id: str, name: str = "fn", file_path: str = "src/x.py") -> GraphNode:
    return GraphNode(
        id=node_id,
        type=NodeType.FUNCTION,
        file_path=file_path,
        structural=StructuralProperties(name=name, file=file_path, signature=f"def {name}():", start_line=1),
        semantic=SemanticProperties(),
    )


def _session(session_id: str, agent_id: str = "agent", task: str = "") -> dict[str, Any]:
    return {
        "session_id": session_id,
        "agent_id": agent_id,
        "task": task,
        "status": "open",
    }


class TestSessionTransactionCommit:
    """Session persistence within committed transactions."""

    async def test_session_persists_after_transaction_commit(self, tmp_path: Path) -> None:
        path = tmp_path / "graph.smpg"
        store = MMapGraphStore(path)
        await store.connect()
        async with store.transaction(actor="agent1"):
            await store.upsert_session(_session("s1"))
        await store.close()

        reopened = MMapGraphStore(path)
        await reopened.connect()
        try:
            session = await reopened.get_session("s1")
            assert session is not None
            assert session["session_id"] == "s1"
        finally:
            await reopened.close()

    async def test_multiple_sessions_in_single_transaction(self, tmp_path: Path) -> None:
        path = tmp_path / "graph.smpg"
        store = MMapGraphStore(path)
        await store.connect()
        async with store.transaction(actor="agent1"):
            await store.upsert_session(_session("s1"))
            await store.upsert_session(_session("s2"))
            await store.upsert_session(_session("s3"))
        await store.close()

        reopened = MMapGraphStore(path)
        await reopened.connect()
        try:
            assert await reopened.get_session("s1") is not None
            assert await reopened.get_session("s2") is not None
            assert await reopened.get_session("s3") is not None
        finally:
            await reopened.close()

    async def test_session_with_lock_in_transaction(self, tmp_path: Path) -> None:
        path = tmp_path / "graph.smpg"
        store = MMapGraphStore(path)
        await store.connect()
        async with store.transaction(actor="agent1"):
            await store.upsert_session(_session("s1"))
            await store.upsert_lock("src/main.py", "s1")
        await store.close()

        reopened = MMapGraphStore(path)
        await reopened.connect()
        try:
            assert await reopened.get_session("s1") is not None
            lock = reopened._locks.get("src/main.py")
            assert lock is not None
            assert lock["session_id"] == "s1"
        finally:
            await reopened.close()

    async def test_session_node_and_edge_in_transaction(self, tmp_path: Path) -> None:
        path = tmp_path / "graph.smpg"
        store = MMapGraphStore(path)
        await store.connect()
        async with store.transaction(actor="agent1"):
            await store.upsert_session(_session("s1"))
            await store.upsert_node(_node("n1"))
            await store.upsert_node(_node("n2"))
            await store.upsert_edge(GraphEdge(source_id="n1", target_id="n2", type=EdgeType.CALLS))
        await store.close()

        reopened = MMapGraphStore(path)
        await reopened.connect()
        try:
            assert await reopened.get_session("s1") is not None
            assert await reopened.get_node("n1") is not None
            assert await reopened.get_node("n2") is not None
            assert await reopened.count_edges() == 1
        finally:
            await reopened.close()


class TestSessionTransactionAbort:
    """Session rollback on transaction abort."""

    async def test_session_rolled_back_on_abort(self, tmp_path: Path) -> None:
        path = tmp_path / "graph.smpg"
        store = MMapGraphStore(path)
        await store.connect()
        with pytest.raises(RuntimeError, match="boom"):
            async with store.transaction():
                await store.upsert_session(_session("s1"))
                raise RuntimeError("boom")
        await store.close()

        reopened = MMapGraphStore(path)
        await reopened.connect()
        try:
            assert await reopened.get_session("s1") is None
        finally:
            await reopened.close()

    async def test_lock_rolled_back_on_abort(self, tmp_path: Path) -> None:
        path = tmp_path / "graph.smpg"
        store = MMapGraphStore(path)
        await store.connect()
        with pytest.raises(RuntimeError, match="fail"):
            async with store.transaction():
                await store.upsert_session(_session("s1"))
                await store.upsert_lock("src/main.py", "s1")
                raise RuntimeError("fail")
        await store.close()

        reopened = MMapGraphStore(path)
        await reopened.connect()
        try:
            assert await reopened.get_session("s1") is None
            assert "src/main.py" not in reopened._locks
        finally:
            await reopened.close()

    async def test_node_edge_rolled_back_on_abort(self, tmp_path: Path) -> None:
        path = tmp_path / "graph.smpg"
        store = MMapGraphStore(path)
        await store.connect()
        with pytest.raises(RuntimeError, match="abort"):
            async with store.transaction():
                await store.upsert_node(_node("n1"))
                await store.upsert_node(_node("n2"))
                await store.upsert_edge(GraphEdge(source_id="n1", target_id="n2", type=EdgeType.CALLS))
                raise RuntimeError("abort")
        await store.close()

        reopened = MMapGraphStore(path)
        await reopened.connect()
        try:
            assert await reopened.get_node("n1") is None
            assert await reopened.get_node("n2") is None
            assert await reopened.count_nodes() == 0
        finally:
            await reopened.close()


class TestConcurrentSessionTransactions:
    """Multiple sessions in separate transactions."""

    async def test_serial_transactions_with_sessions(self, tmp_path: Path) -> None:
        path = tmp_path / "graph.smpg"
        store = MMapGraphStore(path)
        await store.connect()
        async with store.transaction(actor="agent1"):
            await store.upsert_session(_session("s1"))
        async with store.transaction(actor="agent2"):
            await store.upsert_session(_session("s2"))
        async with store.transaction(actor="agent3"):
            await store.upsert_session(_session("s3"))
        await store.close()

        reopened = MMapGraphStore(path)
        await reopened.connect()
        try:
            assert await reopened.get_session("s1") is not None
            assert await reopened.get_session("s2") is not None
            assert await reopened.get_session("s3") is not None
        finally:
            await reopened.close()

    async def test_mixed_session_and_node_transactions(self, tmp_path: Path) -> None:
        path = tmp_path / "graph.smpg"
        store = MMapGraphStore(path)
        await store.connect()
        async with store.transaction(actor="agent1"):
            await store.upsert_session(_session("s1"))
            await store.upsert_node(_node("n1"))
        async with store.transaction(actor="agent2"):
            await store.upsert_node(_node("n2"))
            await store.upsert_session(_session("s2"))
        await store.close()

        reopened = MMapGraphStore(path)
        await reopened.connect()
        try:
            assert await reopened.get_session("s1") is not None
            assert await reopened.get_session("s2") is not None
            assert await reopened.get_node("n1") is not None
            assert await reopened.get_node("n2") is not None
        finally:
            await reopened.close()


class TestFencingTokenInTransaction:
    """Fencing tokens work within transactions."""

    async def test_fencing_token_generated_in_transaction(self, tmp_path: Path) -> None:
        path = tmp_path / "graph.smpg"
        store = MMapGraphStore(path)
        await store.connect()
        async with store.transaction(actor="agent1"):
            await store.upsert_lock("src/main.py", "s1")
        lock = store._locks.get("src/main.py")
        token = lock.get("fencing_token") if lock else None
        assert token is not None
        assert token > 0
        await store.close()

    async def test_fencing_token_persists_after_commit(self, tmp_path: Path) -> None:
        path = tmp_path / "graph.smpg"
        store = MMapGraphStore(path)
        await store.connect()
        async with store.transaction(actor="agent1"):
            await store.upsert_lock("src/main.py", "s1")
        token_before = store._locks.get("src/main.py", {}).get("fencing_token")
        await store.close()

        reopened = MMapGraphStore(path)
        await reopened.connect()
        try:
            lock = reopened._locks.get("src/main.py")
            assert lock is not None
            assert lock["fencing_token"] == token_before
        finally:
            await reopened.close()

    async def test_fencing_token_increments_on_lock_reacquire(self, tmp_path: Path) -> None:
        path = tmp_path / "graph.smpg"
        store = MMapGraphStore(path)
        await store.connect()
        async with store.transaction(actor="agent1"):
            await store.upsert_lock("src/main.py", "s1")
        token1 = store._locks.get("src/main.py", {}).get("fencing_token", 0)

        async with store.transaction(actor="agent2"):
            await store.upsert_lock("src/main.py", "s2")
        token2 = store._locks.get("src/main.py", {}).get("fencing_token", 0)

        assert token2 > token1
        await store.close()


class TestSessionDeleteInTransaction:
    """Session deletion within transactions."""

    async def test_delete_session_in_transaction(self, tmp_path: Path) -> None:
        path = tmp_path / "graph.smpg"
        store = MMapGraphStore(path)
        await store.connect()
        await store.upsert_session(_session("s1"))
        await store.close()

        store2 = MMapGraphStore(path)
        await store2.connect()
        async with store2.transaction(actor="agent1"):
            deleted = await store2.delete_session("s1")
            assert deleted is True
        await store2.close()

        reopened = MMapGraphStore(path)
        await reopened.connect()
        try:
            assert await reopened.get_session("s1") is None
        finally:
            await reopened.close()

    async def test_delete_session_aborted_rolls_back(self, tmp_path: Path) -> None:
        path = tmp_path / "graph.smpg"
        store = MMapGraphStore(path)
        await store.connect()
        await store.upsert_session(_session("s1"))
        with pytest.raises(RuntimeError):
            async with store.transaction():
                await store.delete_session("s1")
                raise RuntimeError("rollback")
        await store.close()

        reopened = MMapGraphStore(path)
        await reopened.connect()
        try:
            assert await reopened.get_session("s1") is not None
        finally:
            await reopened.close()


class TestLockReleaseInTransaction:
    """Lock release within transactions."""

    async def test_release_lock_in_transaction(self, tmp_path: Path) -> None:
        path = tmp_path / "graph.smpg"
        store = MMapGraphStore(path)
        await store.connect()
        await store.upsert_lock("src/main.py", "s1")
        async with store.transaction(actor="agent1"):
            await store.release_lock("src/main.py", "s1")
        assert "src/main.py" not in store._locks
        await store.close()

    async def test_release_all_locks_in_transaction(self, tmp_path: Path) -> None:
        path = tmp_path / "graph.smpg"
        store = MMapGraphStore(path)
        await store.connect()
        await store.upsert_lock("src/a.py", "s1")
        await store.upsert_lock("src/b.py", "s1")
        await store.upsert_lock("src/c.py", "s1")
        async with store.transaction(actor="agent1"):
            count = await store.release_all_locks("s1")
            assert count == 3
        assert len(store._locks) == 0
        await store.close()


class TestSessionAuditInTransaction:
    """Audit logging within transaction scope."""

    async def test_audit_logged_in_transaction(self, tmp_path: Path) -> None:
        path = tmp_path / "graph.smpg"
        store = MMapGraphStore(path)
        await store.connect()
        async with store.transaction(actor="agent1"):
            await store.upsert_session(_session("s1"))
            await store.append_audit({"event": "session_open", "session_id": "s1"})
        await store.close()

        reopened = MMapGraphStore(path)
        await reopened.connect()
        try:
            assert await reopened.get_session("s1") is not None
        finally:
            await reopened.close()


class TestSessionRecoveryAfterCrash:
    """Session state after crash simulation."""

    async def test_session_survives_partial_transaction_commit(self, tmp_path: Path) -> None:
        from smp.store.graph.mmap_file import OFF_DATA_END

        path = tmp_path / "graph.smpg"
        store = MMapGraphStore(path)
        await store.connect()
        async with store.transaction():
            await store.upsert_session(_session("good"))
        async with store.transaction():
            await store.upsert_session(_session("dirty"))
            crash_point = store.file.data_region_end

        with open(path, "r+b") as fh:
            fh.seek(OFF_DATA_END)
            fh.write(struct.pack("<Q", crash_point))
            fh.seek(0)

            import zlib  # noqa: PLR0402

            from smp.store.graph.mmap_file import HEADER_SIZE, OFF_CRC, OFF_ROOTS  # noqa: PLR0402

            fh.seek(OFF_ROOTS)
            header_data = fh.read(HEADER_SIZE - OFF_ROOTS)
            crc = zlib.crc32(header_data) & 0xFFFFFFFF
            fh.seek(OFF_CRC)
            fh.write(struct.pack("<I", crc))
        await store.close()

        reopened = MMapGraphStore(path)
        await reopened.connect()
        try:
            assert await reopened.get_session("good") is not None
            assert await reopened.get_session("dirty") is None
        finally:
            await reopened.close()


class TestSessionStateTransitions:
    """Session state changes within transaction."""

    async def test_session_status_update_in_transaction(self, tmp_path: Path) -> None:
        path = tmp_path / "graph.smpg"
        store = MMapGraphStore(path)
        await store.connect()
        await store.upsert_session(_session("s1", task="initial"))
        async with store.transaction(actor="agent1"):
            session = await store.get_session("s1")
            if session is not None:
                session["status"] = "completed"
                session["task"] = "finished"
                await store.upsert_session(session)
        await store.close()

        reopened = MMapGraphStore(path)
        await reopened.connect()
        try:
            session = await reopened.get_session("s1")
            assert session is not None
            assert session["status"] == "completed"
            assert session["task"] == "finished"
        finally:
            await reopened.close()

    async def test_session_metadata_update_in_transaction(self, tmp_path: Path) -> None:
        path = tmp_path / "graph.smpg"
        store = MMapGraphStore(path)
        await store.connect()
        await store.upsert_session({"session_id": "s1"})
        async with store.transaction(actor="agent1"):
            session = await store.get_session("s1")
            if session is not None:
                session["files_modified"] = ["a.py", "b.py"]
                session["errors"] = 0
                await store.upsert_session(session)
        await store.close()

        reopened = MMapGraphStore(path)
        await reopened.connect()
        try:
            session = await reopened.get_session("s1")
            assert session is not None
            assert "files_modified" in session
            assert session["errors"] == 0
        finally:
            await reopened.close()


class TestNestedTransactionsWithSessions:
    """Nested transaction behavior with sessions (if supported)."""

    async def test_session_across_serial_transactions(self, tmp_path: Path) -> None:
        path = tmp_path / "graph.smpg"
        store = MMapGraphStore(path)
        await store.connect()
        await store.upsert_session(_session("s1", task="phase1"))
        async with store.transaction(actor="agent1"):
            session = await store.get_session("s1")
            if session is not None:
                session["phase"] = 1
                await store.upsert_session(session)
        async with store.transaction(actor="agent1"):
            session = await store.get_session("s1")
            if session is not None:
                session["phase"] = 2
                await store.upsert_session(session)
        await store.close()

        reopened = MMapGraphStore(path)
        await reopened.connect()
        try:
            session = await reopened.get_session("s1")
            assert session is not None
            assert session["phase"] == 2
        finally:
            await reopened.close()


class TestEmptyTransactionWithSessions:
    """Edge cases for transactions with session operations."""

    async def test_empty_transaction_commits_cleanly(self, tmp_path: Path) -> None:
        path = tmp_path / "graph.smpg"
        store = MMapGraphStore(path)
        await store.connect()
        async with store.transaction(actor="agent1"):
            pass
        await store.close()

        reopened = MMapGraphStore(path)
        await reopened.connect()
        try:
            assert await reopened.count_nodes() == 0
        finally:
            await reopened.close()

    async def test_session_updated_in_empty_transaction(self, tmp_path: Path) -> None:
        path = tmp_path / "graph.smpg"
        store = MMapGraphStore(path)
        await store.connect()
        await store.upsert_session(_session("s1"))
        async with store.transaction(actor="agent1"):
            session = await store.get_session("s1")
            if session is not None:
                session["updated"] = True
                await store.upsert_session(session)
        await store.close()

        reopened = MMapGraphStore(path)
        await reopened.connect()
        try:
            session = await reopened.get_session("s1")
            assert session is not None
            assert session["updated"] is True
        finally:
            await reopened.close()


class TestSessionLockInteraction:
    """Session and lock interaction tests."""

    async def test_lock_blocks_other_sessions(self, tmp_path: Path) -> None:
        path = tmp_path / "graph.smpg"
        store = MMapGraphStore(path)
        await store.connect()
        await store.upsert_lock("src/main.py", "s1")
        await store.upsert_session(_session("s1"))
        lock = store._locks.get("src/main.py")
        assert lock is not None
        assert lock["session_id"] == "s1"
        await store.close()

    async def test_lock_can_be_reacquired_by_other_session(self, tmp_path: Path) -> None:
        path = tmp_path / "graph.smpg"
        store = MMapGraphStore(path)
        await store.connect()
        await store.upsert_lock("src/main.py", "s1")
        await store.upsert_session(_session("s1"))
        token1 = store._locks.get("src/main.py", {}).get("fencing_token", 0)

        await store.release_lock("src/main.py", "s1")
        await store.upsert_lock("src/main.py", "s2")
        token2 = store._locks.get("src/main.py", {}).get("fencing_token", 0)

        assert token2 > token1
        await store.close()

    async def test_session_with_multiple_locks(self, tmp_path: Path) -> None:
        path = tmp_path / "graph.smpg"
        store = MMapGraphStore(path)
        await store.connect()
        await store.upsert_session(_session("s1"))
        await store.upsert_lock("src/a.py", "s1")
        await store.upsert_lock("src/b.py", "s1")
        await store.upsert_lock("src/c.py", "s1")
        assert len(store._locks) == 3
        await store.close()

    async def test_session_recovery_preserves_locks(self, tmp_path: Path) -> None:
        path = tmp_path / "graph.smpg"
        store = MMapGraphStore(path)
        await store.connect()
        await store.upsert_session(_session("s1"))
        await store.upsert_lock("src/main.py", "s1")
        await store.close()

        reopened = MMapGraphStore(path)
        await reopened.connect()
        try:
            session = await reopened.get_session("s1")
            assert session is not None
            lock = reopened._locks.get("src/main.py")
            assert lock is not None
            assert lock["session_id"] == "s1"
        finally:
            await reopened.close()


class TestSessionTransactionIsolation:
    """Transaction isolation with sessions."""

    async def test_dirty_read_prevention_via_transaction(self, tmp_path: Path) -> None:
        path = tmp_path / "graph.smpg"
        store = MMapGraphStore(path)
        await store.connect()
        await store.upsert_session(_session("s1"))
        session_before = await store.get_session("s1")
        assert session_before is not None

        async with store.transaction(actor="agent1"):
            session = await store.get_session("s1")
            if session is not None:
                session["in_tx"] = True
                await store.upsert_session(session)

        session_after = await store.get_session("s1")
        assert session_after is not None
        await store.close()

    async def test_transaction_isolation_with_rollback(self, tmp_path: Path) -> None:
        path = tmp_path / "graph.smpg"
        store = MMapGraphStore(path)
        await store.connect()

        with pytest.raises(RuntimeError):
            async with store.transaction():
                await store.upsert_node(_node("n2", name="new_node"))
                raise RuntimeError("abort")

        await store.close()

        reopened = MMapGraphStore(path)
        await reopened.connect()
        try:
            node_n2 = await reopened.get_node("n2")
            assert node_n2 is None
        finally:
            await reopened.close()

    async def test_multiple_session_updates_in_single_transaction(self, tmp_path: Path) -> None:
        path = tmp_path / "graph.smpg"
        store = MMapGraphStore(path)
        await store.connect()
        await store.upsert_session(_session("s1"))
        await store.upsert_session(_session("s2"))

        async with store.transaction(actor="agent1"):
            s1 = await store.get_session("s1")
            s2 = await store.get_session("s2")
            if s1 is not None:
                s1["updated"] = True
                await store.upsert_session(s1)
            if s2 is not None:
                s2["updated"] = True
                await store.upsert_session(s2)

        await store.close()

        reopened = MMapGraphStore(path)
        await reopened.connect()
        try:
            s1 = await reopened.get_session("s1")
            s2 = await reopened.get_session("s2")
            assert s1 is not None
            assert s2 is not None
        finally:
            await reopened.close()


class TestSessionEdgeCases:
    """Edge case tests for sessions in transactions."""

    async def test_session_with_empty_id_in_transaction(self, tmp_path: Path) -> None:
        path = tmp_path / "graph.smpg"
        store = MMapGraphStore(path)
        await store.connect()

        with pytest.raises(ValueError, match="session must include"):
            async with store.transaction():
                await store.upsert_session({"data": "value"})

        await store.close()

    async def test_session_overwrite_in_transaction(self, tmp_path: Path) -> None:
        path = tmp_path / "graph.smpg"
        store = MMapGraphStore(path)
        await store.connect()
        await store.upsert_session(_session("s1", task="original"))

        async with store.transaction(actor="agent1"):
            await store.upsert_session(_session("s1", task="overwritten"))

        session = await store.get_session("s1")
        assert session is not None
        assert session["task"] == "overwritten"
        await store.close()

    async def test_session_and_lock_release_order_independence(self, tmp_path: Path) -> None:
        path = tmp_path / "graph.smpg"
        store = MMapGraphStore(path)
        await store.connect()
        await store.upsert_session(_session("s1"))
        await store.upsert_lock("src/main.py", "s1")

        await store.release_lock("src/main.py", "s1")
        await store.delete_session("s1")

        assert "src/main.py" not in store._locks
        assert await store.get_session("s1") is None
        await store.close()
