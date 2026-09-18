from __future__ import annotations

import asyncio
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

from smp.protocol.handlers.session import lock, unlock
from smp.store.graph.mmap_store import MMapGraphStore


@pytest.fixture
def mock_audit_logger() -> MagicMock:
    return MagicMock()


@pytest.fixture
async def lock_graph(tmp_path: Path) -> MMapGraphStore:
    graph_path = tmp_path / "test_lock.graph.smpg"
    store = MMapGraphStore(path=str(graph_path))
    await store.connect()
    yield store
    await store.close()


@pytest.fixture
def make_lock_params() -> Callable[..., dict[str, Any]]:
    def _make(
        session_id: str = "session-1",
        files: list[str] | None = None,
        ttl_seconds: int = 300,
        force: bool = False,
    ) -> dict[str, Any]:
        return {
            "session_id": session_id,
            "files": files or [],
            "ttl_seconds": ttl_seconds,
            "force": force,
        }

    return _make


class TestLockAcquireRelease:
    """Tests for basic lock acquire and release operations."""

    @pytest.mark.asyncio
    async def test_acquire_single_file_success(
        self,
        lock_graph: MMapGraphStore,
        make_lock_params,
    ) -> None:
        ctx = {"graph": lock_graph}
        params = make_lock_params(session_id="s1", files=["a.py"])
        result = await lock(params, ctx)
        assert "a.py" in result["locked"]
        assert result["session_id"] == "s1"
        assert result["conflicts"] == []

    @pytest.mark.asyncio
    async def test_acquire_multiple_files(
        self,
        lock_graph: MMapGraphStore,
        make_lock_params,
    ) -> None:
        ctx = {"graph": lock_graph}
        params = make_lock_params(session_id="s1", files=["a.py", "b.py", "c.py"])
        result = await lock(params, ctx)
        assert len(result["locked"]) == 3
        assert "a.py" in result["locked"]
        assert "b.py" in result["locked"]
        assert "c.py" in result["locked"]

    @pytest.mark.asyncio
    async def test_acquire_creates_fencing_token(
        self,
        lock_graph: MMapGraphStore,
        make_lock_params,
    ) -> None:
        ctx = {"graph": lock_graph}
        params = make_lock_params(session_id="s1", files=["a.py"])
        result = await lock(params, ctx)
        assert len(result["leases"]) == 1
        assert result["leases"][0].get("fencing_token", 0) > 0

    @pytest.mark.asyncio
    async def test_acquire_stores_acquired_at_in_graph(
        self,
        lock_graph: MMapGraphStore,
        make_lock_params,
    ) -> None:
        ctx = {"graph": lock_graph}
        params = make_lock_params(session_id="s1", files=["a.py"])
        await lock(params, ctx)
        stored = await lock_graph.get_lock("a.py")
        assert stored is not None
        assert stored.get("acquired_at") is not None

    @pytest.mark.asyncio
    async def test_acquire_stores_expires_at(
        self,
        lock_graph: MMapGraphStore,
        make_lock_params,
    ) -> None:
        ctx = {"graph": lock_graph}
        params = make_lock_params(session_id="s1", files=["a.py"], ttl_seconds=60)
        result = await lock(params, ctx)
        assert result["leases"][0].get("expires_at")

    @pytest.mark.asyncio
    async def test_release_single_file(
        self,
        lock_graph: MMapGraphStore,
        make_lock_params,
    ) -> None:
        ctx = {"graph": lock_graph}
        await lock(make_lock_params(session_id="s1", files=["a.py"]), ctx)
        release_params = make_lock_params(session_id="s1", files=["a.py"])
        result = await unlock(release_params, ctx)
        assert "a.py" in result["released"]

    @pytest.mark.asyncio
    async def test_release_updates_removed_count(
        self,
        lock_graph: MMapGraphStore,
        make_lock_params,
    ) -> None:
        ctx = {"graph": lock_graph}
        await lock(make_lock_params(session_id="s1", files=["a.py", "b.py"]), ctx)
        release_params = make_lock_params(session_id="s1", files=["a.py"])
        result = await unlock(release_params, ctx)
        assert len(result["released"]) == 1

    @pytest.mark.asyncio
    async def test_release_missing_lock_returns_empty(
        self,
        lock_graph: MMapGraphStore,
        make_lock_params,
    ) -> None:
        ctx = {"graph": lock_graph}
        params = make_lock_params(session_id="s1", files=["nonexistent.py"])
        result = await unlock(params, ctx)
        assert result["released"] == []


class TestLockConflicts:
    """Tests for lock conflict detection."""

    @pytest.mark.asyncio
    async def test_conflict_different_session(
        self,
        lock_graph: MMapGraphStore,
        make_lock_params,
    ) -> None:
        ctx = {"graph": lock_graph}
        await lock(make_lock_params(session_id="holder", files=["a.py"]), ctx)
        params = make_lock_params(session_id="requestor", files=["a.py"])
        result = await lock(params, ctx)
        assert len(result["conflicts"]) == 1
        assert result["conflicts"][0]["file"] == "a.py"
        assert result["conflicts"][0]["held_by"] == "holder"

    @pytest.mark.asyncio
    async def test_no_conflict_same_session(
        self,
        lock_graph: MMapGraphStore,
        make_lock_params,
    ) -> None:
        ctx = {"graph": lock_graph}
        await lock(make_lock_params(session_id="s1", files=["a.py"]), ctx)
        params = make_lock_params(session_id="s1", files=["a.py", "b.py"])
        result = await lock(params, ctx)
        assert len(result["conflicts"]) == 0

    @pytest.mark.asyncio
    async def test_partial_conflict_mixed_files(
        self,
        lock_graph: MMapGraphStore,
        make_lock_params,
    ) -> None:
        ctx = {"graph": lock_graph}
        await lock(make_lock_params(session_id="s1", files=["a.py"]), ctx)
        params = make_lock_params(session_id="s2", files=["a.py", "b.py"])
        result = await lock(params, ctx)
        assert "b.py" in result["locked"]
        assert "a.py" in [c["file"] for c in result["conflicts"]]

    @pytest.mark.asyncio
    async def test_multiple_conflicts(
        self,
        lock_graph: MMapGraphStore,
        make_lock_params,
    ) -> None:
        ctx = {"graph": lock_graph}
        await lock(make_lock_params(session_id="s1", files=["a.py", "b.py"]), ctx)
        params = make_lock_params(session_id="s2", files=["a.py", "b.py", "c.py"])
        result = await lock(params, ctx)
        assert len(result["conflicts"]) == 2
        assert "c.py" in result["locked"]


class TestStaleLockCleanup:
    """Tests for automatic stale lock cleanup."""

    @pytest.mark.asyncio
    async def test_expired_lock_is_replaced(
        self,
        lock_graph: MMapGraphStore,
        make_lock_params,
    ) -> None:
        ctx = {"graph": lock_graph}
        expired_time = (datetime.now(UTC) - timedelta(hours=1)).isoformat()
        await lock_graph.upsert_lock("a.py", "old_session", acquired_at=expired_time, expires_at=expired_time)
        params = make_lock_params(session_id="new_session", files=["a.py"])
        result = await lock(params, ctx)
        assert "a.py" in result["locked"]

    @pytest.mark.asyncio
    async def test_expired_lock_returns_no_conflict(
        self,
        lock_graph: MMapGraphStore,
        make_lock_params,
    ) -> None:
        ctx = {"graph": lock_graph}
        expired_time = (datetime.now(UTC) - timedelta(hours=1)).isoformat()
        await lock_graph.upsert_lock("a.py", "old_session", acquired_at=expired_time, expires_at=expired_time)
        params = make_lock_params(session_id="new_session", files=["a.py"])
        result = await lock(params, ctx)
        assert result["conflicts"] == []

    @pytest.mark.asyncio
    async def test_valid_lock_not_replaced(
        self,
        lock_graph: MMapGraphStore,
        make_lock_params,
    ) -> None:
        ctx = {"graph": lock_graph}
        future_time = (datetime.now(UTC) + timedelta(hours=1)).isoformat()
        await lock_graph.upsert_lock("a.py", "holder", expires_at=future_time)
        params = make_lock_params(session_id="requestor", files=["a.py"])
        result = await lock(params, ctx)
        assert len(result["conflicts"]) == 1


class TestForceSteal:
    """Tests for force stealing locks."""

    @pytest.mark.asyncio
    async def test_force_steal_active_lock(
        self,
        lock_graph: MMapGraphStore,
        make_lock_params,
    ) -> None:
        ctx = {"graph": lock_graph}
        await lock(make_lock_params(session_id="holder", files=["a.py"]), ctx)
        params = make_lock_params(session_id="thief", files=["a.py"], force=True)
        result = await lock(params, ctx)
        assert "a.py" in result["locked"]

    @pytest.mark.asyncio
    async def test_force_steal_no_conflict(
        self,
        lock_graph: MMapGraphStore,
        make_lock_params,
    ) -> None:
        ctx = {"graph": lock_graph}
        future_time = (datetime.now(UTC) + timedelta(hours=1)).isoformat()
        await lock_graph.upsert_lock("a.py", "holder", expires_at=future_time)
        params = make_lock_params(session_id="thief", files=["a.py"], force=True)
        result = await lock(params, ctx)
        assert result["conflicts"] == []

    @pytest.mark.asyncio
    async def test_force_updates_fencing_token(
        self,
        lock_graph: MMapGraphStore,
        make_lock_params,
    ) -> None:
        ctx = {"graph": lock_graph}
        await lock(make_lock_params(session_id="holder", files=["a.py"]), ctx)
        first_token = (await lock_graph.get_lock("a.py"))["fencing_token"]
        params = make_lock_params(session_id="thief", files=["a.py"], force=True)
        await lock(params, ctx)
        second_token = (await lock_graph.get_lock("a.py"))["fencing_token"]
        assert second_token > first_token


class TestReleaseAllLocks:
    """Tests for releasing all locks for a session."""

    @pytest.mark.asyncio
    async def test_release_all(
        self,
        lock_graph: MMapGraphStore,
        make_lock_params,
    ) -> None:
        ctx = {"graph": lock_graph}
        await lock(make_lock_params(session_id="s1", files=["a.py", "b.py", "c.py"]), ctx)
        released = await lock_graph.release_all_locks("s1")
        assert released == 3

    @pytest.mark.asyncio
    async def test_release_all_returns_count(
        self,
        lock_graph: MMapGraphStore,
        make_lock_params,
    ) -> None:
        ctx = {"graph": lock_graph}
        await lock(make_lock_params(session_id="s1", files=["a.py", "b.py"]), ctx)
        released = await lock_graph.release_all_locks("s1")
        assert released == 2

    @pytest.mark.asyncio
    async def test_release_all_mixed_sessions(
        self,
        lock_graph: MMapGraphStore,
        make_lock_params,
    ) -> None:
        ctx = {"graph": lock_graph}
        await lock(make_lock_params(session_id="s1", files=["a.py", "b.py"]), ctx)
        await lock(make_lock_params(session_id="s2", files=["c.py"]), ctx)
        released = await lock_graph.release_all_locks("s1")
        assert released == 2
        remaining = await lock_graph.get_lock("c.py")
        assert remaining is not None


class TestLockTTL:
    """Tests for lock TTL behavior."""

    @pytest.mark.asyncio
    async def test_custom_ttl(
        self,
        lock_graph: MMapGraphStore,
        make_lock_params,
    ) -> None:
        ctx = {"graph": lock_graph}
        params = make_lock_params(session_id="s1", files=["a.py"], ttl_seconds=600)
        result = await lock(params, ctx)
        expires_at = datetime.fromisoformat(result["leases"][0]["expires_at"])
        expected = datetime.now(UTC) + timedelta(seconds=600)
        diff = abs((expires_at - expected).total_seconds())
        assert diff < 5

    @pytest.mark.asyncio
    async def test_minimum_ttl_one_second(
        self,
        lock_graph: MMapGraphStore,
        make_lock_params,
    ) -> None:
        ctx = {"graph": lock_graph}
        params = make_lock_params(session_id="s1", files=["a.py"], ttl_seconds=1)
        result = await lock(params, ctx)
        expires_at = datetime.fromisoformat(result["leases"][0]["expires_at"])
        expected = datetime.now(UTC) + timedelta(seconds=1)
        diff = abs((expires_at - expected).total_seconds())
        assert diff < 5


class TestLockMetadata:
    """Tests for lock metadata storage."""

    @pytest.mark.asyncio
    async def test_lock_persisted_in_graph(
        self,
        lock_graph: MMapGraphStore,
        make_lock_params,
    ) -> None:
        ctx = {"graph": lock_graph}
        await lock(make_lock_params(session_id="s1", files=["a.py"]), ctx)
        stored = await lock_graph.get_lock("a.py")
        assert stored is not None
        assert stored["session_id"] == "s1"

    @pytest.mark.asyncio
    async def test_fencing_token_increments(
        self,
        lock_graph: MMapGraphStore,
        make_lock_params,
    ) -> None:
        ctx = {"graph": lock_graph}
        await lock(make_lock_params(session_id="s1", files=["a.py"]), ctx)
        first = (await lock_graph.get_lock("a.py"))["fencing_token"]
        await lock(make_lock_params(session_id="s1", files=["b.py"]), ctx)
        second = (await lock_graph.get_lock("b.py"))["fencing_token"]
        assert second > first


class TestLockAuditTrail:
    """Tests for audit logging during lock operations."""

    @pytest.mark.asyncio
    async def test_acquire_creates_audit_event(
        self,
        lock_graph: MMapGraphStore,
        make_lock_params,
    ) -> None:
        ctx = {"graph": lock_graph, "_audit_log": []}
        await lock(make_lock_params(session_id="s1", files=["a.py"]), ctx)
        audit = ctx["_audit_log"]
        assert len(audit) > 0
        assert any(e.get("event") == "lock_acquired" for e in audit)

    @pytest.mark.asyncio
    async def test_force_steal_creates_audit_event(
        self,
        lock_graph: MMapGraphStore,
        make_lock_params,
    ) -> None:
        ctx = {"graph": lock_graph, "_audit_log": []}
        await lock(make_lock_params(session_id="s1", files=["a.py"]), ctx)
        ctx["_audit_log"] = []
        await lock(make_lock_params(session_id="s2", files=["a.py"], force=True), ctx)
        audit = ctx["_audit_log"]
        assert any(e.get("event") == "lock_stolen" for e in audit)

    @pytest.mark.asyncio
    async def test_expired_cleanup_creates_audit_event(
        self,
        lock_graph: MMapGraphStore,
        make_lock_params,
    ) -> None:
        ctx = {"graph": lock_graph, "_audit_log": []}
        expired = (datetime.now(UTC) - timedelta(hours=1)).isoformat()
        await lock_graph.upsert_lock("a.py", "old", expires_at=expired)
        await lock(make_lock_params(session_id="s1", files=["a.py"]), ctx)
        audit = ctx["_audit_log"]
        assert any(e.get("event") == "lock_expired" for e in audit)


class TestLockEdgeCases:
    """Tests for edge cases and boundary conditions."""

    @pytest.mark.asyncio
    async def test_empty_file_list(
        self,
        lock_graph: MMapGraphStore,
        make_lock_params,
    ) -> None:
        ctx = {"graph": lock_graph}
        params = make_lock_params(session_id="s1", files=[])
        result = await lock(params, ctx)
        assert result["locked"] == []

    @pytest.mark.asyncio
    async def test_duplicate_files_in_request(
        self,
        lock_graph: MMapGraphStore,
        make_lock_params,
    ) -> None:
        ctx = {"graph": lock_graph}
        params = make_lock_params(session_id="s1", files=["a.py", "b.py"])
        result = await lock(params, ctx)
        assert len(result["locked"]) == 2

    @pytest.mark.asyncio
    async def test_release_other_session_lock_fails(
        self,
        lock_graph: MMapGraphStore,
        make_lock_params,
    ) -> None:
        ctx = {"graph": lock_graph}
        await lock(make_lock_params(session_id="s1", files=["a.py"]), ctx)
        params = make_lock_params(session_id="s2", files=["a.py"])
        result = await unlock(params, ctx)
        assert "a.py" not in result["released"]

    @pytest.mark.asyncio
    async def test_lock_response_includes_session_id(
        self,
        lock_graph: MMapGraphStore,
        make_lock_params,
    ) -> None:
        ctx = {"graph": lock_graph}
        params = make_lock_params(session_id="test-session", files=["a.py"])
        result = await lock(params, ctx)
        assert result["session_id"] == "test-session"

    @pytest.mark.asyncio
    async def test_lock_response_has_leases_key(
        self,
        lock_graph: MMapGraphStore,
        make_lock_params,
    ) -> None:
        ctx = {"graph": lock_graph}
        params = make_lock_params(session_id="s1", files=["a.py"])
        result = await lock(params, ctx)
        assert "leases" in result

    @pytest.mark.asyncio
    async def test_concurrent_lock_same_file(
        self,
        lock_graph: MMapGraphStore,
        make_lock_params,
    ) -> None:
        ctx = {"graph": lock_graph}
        params1 = make_lock_params(session_id="s1", files=["a.py"])
        params2 = make_lock_params(session_id="s2", files=["a.py"])
        result1, result2 = await asyncio.gather(lock(params1, ctx), lock(params2, ctx))
        assert len(result1["conflicts"]) + len(result2["conflicts"]) == 1
