from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from smp.store.graph.mmap_store import MMapGraphStore


@pytest.fixture
async def audit_store(tmp_path: Path) -> AsyncIterator[MMapGraphStore]:
    graph_path = tmp_path / "audit_compliance.smpg"
    store = MMapGraphStore(path=str(graph_path))
    await store.connect()
    try:
        yield store
    finally:
        await store.close()


@pytest.fixture
async def fresh_audit_store(audit_store: MMapGraphStore) -> MMapGraphStore:
    await audit_store.clear()
    return audit_store


@pytest.fixture
def make_audit_event() -> type[dict[str, Any]]:
    _counter = 0

    def _create(
        event: str = "test_event",
        session_id: str = "session_1",
        actor: str = "actor_1",
        target: str | None = None,
        action: str | None = None,
        status: str = "success",
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        nonlocal _counter
        _counter += 1
        result: dict[str, Any] = {
            "event": event,
            "session_id": session_id,
            "actor": actor,
            "timestamp": datetime.now(UTC).isoformat(),
            "status": status,
        }
        if target:
            result["target"] = target
        if action:
            result["action"] = action
        if metadata:
            result["metadata"] = metadata
        return result

    return _create


class TestAuditTrailC002:
    """C-002: Verify that audit events are recorded and persist."""

    async def test_audit_event_recorded(
        self, fresh_audit_store: MMapGraphStore, make_audit_event: dict[str, Any]
    ) -> None:
        event = make_audit_event(event="node_upsert", session_id="s1", actor="admin")
        await fresh_audit_store.append_audit(event)

        logs = await fresh_audit_store.list_audit()
        assert len(logs) == 1
        assert logs[0]["event"] == "node_upsert"

    async def test_audit_event_persists_after_close(self, tmp_path: Path, make_audit_event: dict[str, Any]) -> None:
        graph_path = tmp_path / "persist_audit.smpg"
        store = MMapGraphStore(path=str(graph_path))
        await store.connect()

        await store.append_audit(make_audit_event(event="write_1", session_id="s1"))
        await store.append_audit(make_audit_event(event="write_2", session_id="s1"))
        await store.close()

        store2 = MMapGraphStore(path=str(graph_path))
        await store2.connect()
        logs = await store2.list_audit()
        await store2.close()

        assert len(logs) == 2
        assert logs[0]["event"] == "write_1"
        assert logs[1]["event"] == "write_2"

    async def test_audit_multiple_mutations_logged(
        self, fresh_audit_store: MMapGraphStore, make_audit_event: dict[str, Any]
    ) -> None:
        events = [
            make_audit_event(event="node_upsert", action="create"),
            make_audit_event(event="edge_upsert", action="create"),
            make_audit_event(event="node_delete", action="delete"),
        ]
        for e in events:
            await fresh_audit_store.append_audit(e)

        logs = await fresh_audit_store.list_audit()
        assert len(logs) == 3

    async def test_audit_data_mutation_includes_target(
        self, fresh_audit_store: MMapGraphStore, make_audit_event: dict[str, Any]
    ) -> None:
        event = make_audit_event(event="file_write", target="/workspace/src/main.py", action="write")
        await fresh_audit_store.append_audit(event)

        logs = await fresh_audit_store.list_audit()
        assert logs[0]["target"] == "/workspace/src/main.py"
        assert logs[0]["action"] == "write"

    async def test_audit_timestamp_preserved(
        self, fresh_audit_store: MMapGraphStore, make_audit_event: dict[str, Any]
    ) -> None:
        event = make_audit_event(event="test_timestamp")
        await fresh_audit_store.append_audit(event)
        logs = await fresh_audit_store.list_audit()

        assert "timestamp" in logs[0]
        assert isinstance(logs[0]["timestamp"], str)


class TestAuditTrailC006:
    """C-006: Verify that audit logs capture the actor identity."""

    async def test_actor_identity_captured(
        self, fresh_audit_store: MMapGraphStore, make_audit_event: dict[str, Any]
    ) -> None:
        event = make_audit_event(event="admin_action", actor="admin_user")
        await fresh_audit_store.append_audit(event)

        logs = await fresh_audit_store.list_audit()
        assert logs[0]["actor"] == "admin_user"

    async def test_multiple_actors_tracked_separately(
        self, fresh_audit_store: MMapGraphStore, make_audit_event: dict[str, Any]
    ) -> None:
        actors = ["alice", "bob", "carol"]
        for actor in actors:
            await fresh_audit_store.append_audit(make_audit_event(event="action", session_id="s1", actor=actor))

        logs = await fresh_audit_store.list_audit()
        logged_actors = {log["actor"] for log in logs}
        assert logged_actors == set(actors)

    async def test_session_lifecycle_with_actor(
        self, fresh_audit_store: MMapGraphStore, make_audit_event: dict[str, Any]
    ) -> None:
        session_id = "session_compliance_test"
        await fresh_audit_store.append_audit(
            make_audit_event(event="session_open", session_id=session_id, actor="alice")
        )
        await fresh_audit_store.append_audit(
            make_audit_event(event="session_lock", session_id=session_id, actor="alice")
        )
        await fresh_audit_store.append_audit(
            make_audit_event(event="session_unlock", session_id=session_id, actor="alice")
        )
        await fresh_audit_store.append_audit(
            make_audit_event(event="session_close", session_id=session_id, actor="alice")
        )

        logs = await fresh_audit_store.list_audit()
        assert all(log["actor"] == "alice" for log in logs)
        assert all(log["session_id"] == session_id for log in logs)

    async def test_actor_identity_in_read_operations(
        self, fresh_audit_store: MMapGraphStore, make_audit_event: dict[str, Any]
    ) -> None:
        event = make_audit_event(event="query_execute", actor="analyst", status="success")
        await fresh_audit_store.append_audit(event)

        logs = await fresh_audit_store.list_audit()
        assert logs[0]["actor"] == "analyst"
        assert logs[0]["status"] == "success"

    async def test_actor_identity_in_write_operations(
        self, fresh_audit_store: MMapGraphStore, make_audit_event: dict[str, Any]
    ) -> None:
        event = make_audit_event(event="node_create", actor="developer", status="success")
        await fresh_audit_store.append_audit(event)

        logs = await fresh_audit_store.list_audit()
        assert logs[0]["actor"] == "developer"

    async def test_actor_identity_in_delete_operations(
        self, fresh_audit_store: MMapGraphStore, make_audit_event: dict[str, Any]
    ) -> None:
        event = make_audit_event(event="node_delete", actor="admin", status="success")
        await fresh_audit_store.append_audit(event)

        logs = await fresh_audit_store.list_audit()
        assert logs[0]["actor"] == "admin"


class TestAuditCompliance:
    """Additional compliance tests for audit trail."""

    async def test_audit_returns_copy(
        self, fresh_audit_store: MMapGraphStore, make_audit_event: dict[str, Any]
    ) -> None:
        await fresh_audit_store.append_audit(make_audit_event(event="test"))
        logs = await fresh_audit_store.list_audit()
        logs.clear()
        logs2 = await fresh_audit_store.list_audit()

        assert len(logs2) == 1

    async def test_audit_order_preserved(
        self, fresh_audit_store: MMapGraphStore, make_audit_event: dict[str, Any]
    ) -> None:
        for i in range(5):
            await fresh_audit_store.append_audit(make_audit_event(event=f"event_{i}", action=str(i)))

        logs = await fresh_audit_store.list_audit()
        for i, log in enumerate(logs):
            assert log["action"] == str(i)

    async def test_audit_with_large_metadata(self, tmp_path: Path, make_audit_event: dict[str, Any]) -> None:
        graph_path = tmp_path / "large_meta.smpg"
        store = MMapGraphStore(path=str(graph_path))
        await store.connect()

        large_meta = {"data": "X" * 5000}
        await store.append_audit(make_audit_event(event="bulk_ingest", metadata=large_meta))
        await store.close()

        store2 = MMapGraphStore(path=str(graph_path))
        await store2.connect()
        logs = await store2.list_audit()
        await store2.close()

        assert logs[0]["metadata"]["data"] == "X" * 5000

    async def test_audit_with_unicode_actor(
        self, fresh_audit_store: MMapGraphStore, make_audit_event: dict[str, Any]
    ) -> None:
        event = make_audit_event(event="unicode_test", actor="用户_alice", target="/路径/文件.py")
        await fresh_audit_store.append_audit(event)

        logs = await fresh_audit_store.list_audit()
        assert logs[0]["actor"] == "用户_alice"

    async def test_audit_filter_by_session(
        self, fresh_audit_store: MMapGraphStore, make_audit_event: dict[str, Any]
    ) -> None:
        await fresh_audit_store.append_audit(make_audit_event(event="action", session_id="s1"))
        await fresh_audit_store.append_audit(make_audit_event(event="action", session_id="s2"))
        await fresh_audit_store.append_audit(make_audit_event(event="action", session_id="s1"))

        logs = await fresh_audit_store.list_audit()
        s1_logs = [e for e in logs if e["session_id"] == "s1"]
        assert len(s1_logs) == 2

    async def test_audit_integrity_after_recovery(self, tmp_path: Path, make_audit_event: dict[str, Any]) -> None:
        graph_path = tmp_path / "recovery_audit.smpg"
        store = MMapGraphStore(path=str(graph_path))
        await store.connect()

        for i in range(10):
            await store.append_audit(make_audit_event(event=f"event_{i}"))

        await store.close()
        store2 = MMapGraphStore(path=str(graph_path))
        await store2.connect()

        for i in range(10, 20):
            await store2.append_audit(make_audit_event(event=f"event_{i}"))

        logs = await store2.list_audit()
        await store2.close()

        assert len(logs) == 20

    async def test_audit_empty_initially(self, fresh_audit_store: MMapGraphStore) -> None:
        logs = await fresh_audit_store.list_audit()
        assert logs == []

    async def test_audit_status_failure_logged(
        self, fresh_audit_store: MMapGraphStore, make_audit_event: dict[str, Any]
    ) -> None:
        event = make_audit_event(event="failed_operation", status="failure", action="delete")
        await fresh_audit_store.append_audit(event)

        logs = await fresh_audit_store.list_audit()
        assert logs[0]["status"] == "failure"
        assert logs[0]["event"] == "failed_operation"
