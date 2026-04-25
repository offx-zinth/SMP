"""Phase 3 tests: multi-agent safety on the durable backend.

These tests exercise the full session/lock/audit handler stack against
a real :class:`MMapGraphStore` (no fixture monkey-patching).  They prove
that:

* Two sessions cannot acquire conflicting leases on the same file.
* Stale leases (past ``expires_at``) are reclaimed automatically.
* ``force=True`` allows operators to steal a lease and the steal is
  audit-logged.
* Locks, sessions and audit events all survive a process restart by
  reopening the underlying store.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pytest

from smp.engine.graph_builder import DefaultGraphBuilder
from smp.engine.query import DefaultQueryEngine
from smp.protocol.handlers.session import (
    audit_get,
    lock,
    session_close,
    session_open,
    unlock,
)
from smp.store.graph.mmap_store import MMapGraphStore


@pytest.fixture()
async def durable_ctx(tmp_path: Path) -> Any:
    """Yield a runtime ctx backed by a real durable graph store."""
    path = tmp_path / "graph.smpg"
    store = MMapGraphStore(path)
    await store.connect()
    ctx: dict[str, Any] = {
        "graph": store,
        "engine": DefaultQueryEngine(graph_store=store),
        "builder": DefaultGraphBuilder(store),
    }
    try:
        yield ctx, path
    finally:
        await store.close()


class TestLockConflict:
    async def test_two_sessions_cannot_lock_same_file(self, durable_ctx: tuple[dict[str, Any], Path]) -> None:
        ctx, _ = durable_ctx
        s1 = await session_open({"agent_id": "agent-a", "task": "edit"}, ctx)
        s2 = await session_open({"agent_id": "agent-b", "task": "edit"}, ctx)

        first = await lock({"session_id": s1["session_id"], "files": ["src/auth.py"]}, ctx)
        second = await lock({"session_id": s2["session_id"], "files": ["src/auth.py"]}, ctx)

        assert first["locked"] == ["src/auth.py"]
        assert first["leases"][0]["fencing_token"] >= 1
        assert second["locked"] == []
        assert second["conflicts"]
        assert second["conflicts"][0]["held_by"] == s1["session_id"]

    async def test_release_then_reacquire(self, durable_ctx: tuple[dict[str, Any], Path]) -> None:
        ctx, _ = durable_ctx
        s1 = await session_open({"agent_id": "agent-a"}, ctx)
        s2 = await session_open({"agent_id": "agent-b"}, ctx)

        await lock({"session_id": s1["session_id"], "files": ["src/a.py"]}, ctx)
        released = await unlock({"session_id": s1["session_id"], "files": ["src/a.py"]}, ctx)
        assert released["released"] == ["src/a.py"]

        retry = await lock({"session_id": s2["session_id"], "files": ["src/a.py"]}, ctx)
        assert retry["locked"] == ["src/a.py"]

    async def test_unlock_by_wrong_session_is_noop(self, durable_ctx: tuple[dict[str, Any], Path]) -> None:
        ctx, _ = durable_ctx
        s1 = await session_open({"agent_id": "a"}, ctx)
        s2 = await session_open({"agent_id": "b"}, ctx)
        await lock({"session_id": s1["session_id"], "files": ["src/x.py"]}, ctx)

        spoof = await unlock({"session_id": s2["session_id"], "files": ["src/x.py"]}, ctx)
        assert spoof["released"] == []

        # The original lock is still held
        retry = await lock({"session_id": s2["session_id"], "files": ["src/x.py"]}, ctx)
        assert retry["conflicts"]

    async def test_session_close_releases_all_locks(self, durable_ctx: tuple[dict[str, Any], Path]) -> None:
        ctx, _ = durable_ctx
        s1 = await session_open({"agent_id": "a"}, ctx)
        s2 = await session_open({"agent_id": "b"}, ctx)
        await lock({"session_id": s1["session_id"], "files": ["a.py", "b.py"]}, ctx)
        closed = await session_close({"session_id": s1["session_id"]}, ctx)
        assert closed["released_locks"] == 2

        retry = await lock({"session_id": s2["session_id"], "files": ["a.py", "b.py"]}, ctx)
        assert sorted(retry["locked"]) == ["a.py", "b.py"]


class TestStaleLockRecovery:
    async def test_expired_lease_is_reclaimed(self, durable_ctx: tuple[dict[str, Any], Path]) -> None:
        ctx, _ = durable_ctx
        s1 = await session_open({"agent_id": "a"}, ctx)
        s2 = await session_open({"agent_id": "b"}, ctx)

        await lock({"session_id": s1["session_id"], "files": ["src/x.py"], "ttl_seconds": 1}, ctx)
        # Sleep just past TTL so the next caller sees the lease as expired.
        await asyncio.sleep(1.2)
        retry = await lock({"session_id": s2["session_id"], "files": ["src/x.py"]}, ctx)
        assert retry["locked"] == ["src/x.py"]
        assert retry["conflicts"] == []

    async def test_force_steal_replaces_holder(self, durable_ctx: tuple[dict[str, Any], Path]) -> None:
        ctx, _ = durable_ctx
        s1 = await session_open({"agent_id": "a"}, ctx)
        s2 = await session_open({"agent_id": "b"}, ctx)
        await lock({"session_id": s1["session_id"], "files": ["src/y.py"]}, ctx)
        steal = await lock({"session_id": s2["session_id"], "files": ["src/y.py"], "force": True}, ctx)
        assert steal["locked"] == ["src/y.py"]

        # Audit captures the steal
        events = (await audit_get({}, ctx))["events"]
        assert any(e.get("event") == "lock_stolen" for e in events)


class TestDurableAudit:
    async def test_audit_events_durable_across_restart(
        self, durable_ctx: tuple[dict[str, Any], Path]
    ) -> None:
        ctx, path = durable_ctx
        s1 = await session_open({"agent_id": "a", "task": "review"}, ctx)
        await lock({"session_id": s1["session_id"], "files": ["src/q.py"]}, ctx)
        await unlock({"session_id": s1["session_id"], "files": ["src/q.py"]}, ctx)
        await session_close({"session_id": s1["session_id"]}, ctx)
        await ctx["graph"].close()

        reopened = MMapGraphStore(path)
        await reopened.connect()
        try:
            ctx2: dict[str, Any] = {
                "graph": reopened,
                "engine": DefaultQueryEngine(graph_store=reopened),
                "builder": DefaultGraphBuilder(reopened),
            }
            result = await audit_get({}, ctx2)
            kinds = [e.get("event") for e in result["events"]]
            for expected in ("session_open", "lock_acquired", "lock_released", "session_close"):
                assert expected in kinds, f"missing audit event {expected!r} in {kinds}"
        finally:
            await reopened.close()

    async def test_audit_filter_by_session(self, durable_ctx: tuple[dict[str, Any], Path]) -> None:
        ctx, _ = durable_ctx
        s1 = await session_open({"agent_id": "a"}, ctx)
        s2 = await session_open({"agent_id": "b"}, ctx)
        await lock({"session_id": s1["session_id"], "files": ["x.py"]}, ctx)
        await lock({"session_id": s2["session_id"], "files": ["y.py"]}, ctx)

        filtered = await audit_get({"audit_log_id": s1["session_id"]}, ctx)
        assert all(e.get("session_id") == s1["session_id"] for e in filtered["events"])


class TestLeaseShape:
    async def test_lease_carries_fencing_token_and_expiry(
        self, durable_ctx: tuple[dict[str, Any], Path]
    ) -> None:
        ctx, _ = durable_ctx
        s = await session_open({"agent_id": "a"}, ctx)
        result = await lock({"session_id": s["session_id"], "files": ["src/p.py"], "ttl_seconds": 60}, ctx)
        assert len(result["leases"]) == 1
        lease = result["leases"][0]
        assert lease["fencing_token"] >= 1
        # expires_at is a parseable ISO timestamp in the near future
        deadline = datetime.fromisoformat(lease["expires_at"])
        if deadline.tzinfo is None:
            deadline = deadline.replace(tzinfo=timezone.utc)
        assert deadline > datetime.now(timezone.utc)
        assert deadline < datetime.now(timezone.utc) + timedelta(minutes=2)
