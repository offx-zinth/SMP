from __future__ import annotations

from collections.abc import AsyncIterator, Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from smp.store.graph.mmap_store import MMapGraphStore


@pytest.fixture
async def audit_graph_store(tmp_path: Path) -> AsyncIterator[MMapGraphStore]:
    graph_path = tmp_path / "audit_test.smpg"
    store = MMapGraphStore(path=str(graph_path))
    await store.connect()
    try:
        yield store
    finally:
        await store.close()


@pytest.fixture
async def fresh_audit_store(audit_graph_store: MMapGraphStore) -> MMapGraphStore:
    await audit_graph_store.clear()
    return audit_graph_store


@pytest.fixture
def make_audit_event() -> Callable[..., dict[str, Any]]:
    _counter = 0

    def _create_event(
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
        result = {
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

    return _create_event


class TestAuditEvents:
    """Test basic audit event creation and appending."""

    async def test_append_single_event(
        self, fresh_audit_store: MMapGraphStore, make_audit_event: Callable[..., dict[str, Any]]
    ) -> None:
        event = make_audit_event(event="session_open", session_id="s1", actor="user1")
        await fresh_audit_store.append_audit(event)
        logs = await fresh_audit_store.list_audit()
        assert len(logs) == 1
        assert logs[0]["event"] == "session_open"

    async def test_append_multiple_events(
        self, fresh_audit_store: MMapGraphStore, make_audit_event: Callable[..., dict[str, Any]]
    ) -> None:
        events = [
            make_audit_event(event="session_open", session_id="s1"),
            make_audit_event(event="lock_acquire", session_id="s1"),
            make_audit_event(event="lock_release", session_id="s1"),
        ]
        for e in events:
            await fresh_audit_store.append_audit(e)
        logs = await fresh_audit_store.list_audit()
        assert len(logs) == 3

    async def test_append_empty_event(self, fresh_audit_store: MMapGraphStore) -> None:
        event: dict[str, Any] = {}
        await fresh_audit_store.append_audit(event)
        logs = await fresh_audit_store.list_audit()
        assert len(logs) == 1

    async def test_append_event_with_nested_metadata(
        self, fresh_audit_store: MMapGraphStore, make_audit_event: Callable[..., dict[str, Any]]
    ) -> None:
        event = make_audit_event(
            event="file_access",
            metadata={"files": ["/a.py", "/b.py"], "options": {"recursive": True}},
        )
        await fresh_audit_store.append_audit(event)
        logs = await fresh_audit_store.list_audit()
        assert logs[0]["metadata"]["files"] == ["/a.py", "/b.py"]
        assert logs[0]["metadata"]["options"]["recursive"] is True


class TestAuditRetrieval:
    """Test audit log retrieval and filtering."""

    async def test_list_audit_empty(self, fresh_audit_store: MMapGraphStore) -> None:
        logs = await fresh_audit_store.list_audit()
        assert logs == []

    async def test_list_audit_returns_copy(
        self, fresh_audit_store: MMapGraphStore, make_audit_event: Callable[..., dict[str, Any]]
    ) -> None:
        event = make_audit_event(event="test")
        await fresh_audit_store.append_audit(event)
        logs = await fresh_audit_store.list_audit()
        logs.clear()
        logs2 = await fresh_audit_store.list_audit()
        assert len(logs2) == 1

    async def test_audit_events_ordered_by_timestamp(
        self, fresh_audit_store: MMapGraphStore, make_audit_event: Callable[..., dict[str, Any]]
    ) -> None:
        e1 = make_audit_event(event="first", action="create")
        e2 = make_audit_event(event="second", action="update")
        e3 = make_audit_event(event="third", action="delete")
        await fresh_audit_store.append_audit(e1)
        await fresh_audit_store.append_audit(e2)
        await fresh_audit_store.append_audit(e3)
        logs = await fresh_audit_store.list_audit()
        assert logs[0]["event"] == "first"
        assert logs[1]["event"] == "second"
        assert logs[2]["event"] == "third"

    async def test_audit_event_fields_preserved(
        self, fresh_audit_store: MMapGraphStore, make_audit_event: Callable[..., dict[str, Any]]
    ) -> None:
        event = make_audit_event(
            event="lock_acquire",
            session_id="sess_123",
            actor="user_456",
            target="/workspace/file.py",
            action="write",
            status="granted",
        )
        await fresh_audit_store.append_audit(event)
        logs = await fresh_audit_store.list_audit()
        assert logs[0]["session_id"] == "sess_123"
        assert logs[0]["actor"] == "user_456"
        assert logs[0]["target"] == "/workspace/file.py"
        assert logs[0]["action"] == "write"
        assert logs[0]["status"] == "granted"


class TestAuditPersistence:
    """Test audit log persistence across restarts."""

    async def test_audit_events_persist_after_reopen(
        self, tmp_path: Path, make_audit_event: Callable[..., dict[str, Any]]
    ) -> None:
        graph_path = tmp_path / "persist_audit.smpg"
        store1 = MMapGraphStore(path=str(graph_path))
        await store1.connect()
        await store1.append_audit(make_audit_event(event="event1"))
        await store1.append_audit(make_audit_event(event="event2"))
        await store1.close()

        store2 = MMapGraphStore(path=str(graph_path))
        await store2.connect()
        logs = await store2.list_audit()
        await store2.close()

        assert len(logs) == 2
        assert logs[0]["event"] == "event1"
        assert logs[1]["event"] == "event2"

    async def test_audit_persistence_with_large_payload(
        self, tmp_path: Path, make_audit_event: Callable[..., dict[str, Any]]
    ) -> None:
        graph_path = tmp_path / "large_audit.smpg"
        store1 = MMapGraphStore(path=str(graph_path))
        await store1.connect()

        large_metadata = {"data": "X" * 10000}
        event = make_audit_event(event="large_event", metadata=large_metadata)
        await store1.append_audit(event)
        await store1.close()

        store2 = MMapGraphStore(path=str(graph_path))
        await store2.connect()
        logs = await store2.list_audit()
        await store2.close()

        assert logs[0]["metadata"]["data"] == "X" * 10000


class TestAuditSessionTracking:
    """Test session-level audit tracking."""

    async def test_audit_tracks_session_lifecycle(
        self, fresh_audit_store: MMapGraphStore, make_audit_event: Callable[..., dict[str, Any]]
    ) -> None:
        session_id = "session_lifecycle_test"
        await fresh_audit_store.append_audit(make_audit_event(event="session_open", session_id=session_id))
        await fresh_audit_store.append_audit(make_audit_event(event="session_lock", session_id=session_id))
        await fresh_audit_store.append_audit(make_audit_event(event="session_unlock", session_id=session_id))
        await fresh_audit_store.append_audit(make_audit_event(event="session_close", session_id=session_id))

        logs = await fresh_audit_store.list_audit()
        session_logs = [e for e in logs if e["session_id"] == session_id]
        assert len(session_logs) == 4

    async def test_audit_actor_identity_tracked(
        self, fresh_audit_store: MMapGraphStore, make_audit_event: Callable[..., dict[str, Any]]
    ) -> None:
        actors = ["user_alice", "user_bob", "user_carol"]
        for i, actor in enumerate(actors):
            await fresh_audit_store.append_audit(make_audit_event(event=f"action_{i}", actor=actor))

        logs = await fresh_audit_store.list_audit()
        actor_set = {e["actor"] for e in logs}
        assert actor_set == set(actors)


class TestAuditEventTypes:
    """Test different types of audit events."""

    async def test_audit_session_events(
        self, fresh_audit_store: MMapGraphStore, make_audit_event: Callable[..., dict[str, Any]]
    ) -> None:
        events = ["session_open", "session_lock", "session_unlock", "session_close", "session_checkpoint"]
        for e in events:
            await fresh_audit_store.append_audit(make_audit_event(event=e))
        logs = await fresh_audit_store.list_audit()
        logged_events = {log["event"] for log in logs}
        assert logged_events == set(events)

    async def test_audit_lock_events(
        self, fresh_audit_store: MMapGraphStore, make_audit_event: Callable[..., dict[str, Any]]
    ) -> None:
        await fresh_audit_store.append_audit(
            make_audit_event(event="lock_acquire", target="/file.py", status="granted")
        )
        await fresh_audit_store.append_audit(
            make_audit_event(event="lock_release", target="/file.py", status="released")
        )
        logs = await fresh_audit_store.list_audit()
        assert logs[0]["event"] == "lock_acquire"
        assert logs[1]["event"] == "lock_release"

    async def test_audit_file_operation_events(
        self, fresh_audit_store: MMapGraphStore, make_audit_event: Callable[..., dict[str, Any]]
    ) -> None:
        await fresh_audit_store.append_audit(
            make_audit_event(event="file_read", target="/path/to/file.py", action="read", status="success")
        )
        await fresh_audit_store.append_audit(
            make_audit_event(event="file_write", target="/path/to/file.py", action="write", status="success")
        )
        logs = await fresh_audit_store.list_audit()
        assert len(logs) == 2


class TestAuditEdgeCases:
    """Test edge cases for audit logging."""

    async def test_audit_with_unicode_content(
        self, fresh_audit_store: MMapGraphStore, make_audit_event: Callable[..., dict[str, Any]]
    ) -> None:
        event = make_audit_event(
            event="unicode_test",
            actor="用户1",
            target="/路径/文件.py",
            metadata={"note": "这是一个测试"},
        )
        await fresh_audit_store.append_audit(event)
        logs = await fresh_audit_store.list_audit()
        assert logs[0]["actor"] == "用户1"
        assert logs[0]["target"] == "/路径/文件.py"

    async def test_audit_with_special_characters(
        self, fresh_audit_store: MMapGraphStore, make_audit_event: Callable[..., dict[str, Any]]
    ) -> None:
        event = make_audit_event(
            event="special_chars",
            actor="user@example.com",
            target="/path with spaces/and#special@chars",
            metadata={"key": "value with:colons"},
        )
        await fresh_audit_store.append_audit(event)
        logs = await fresh_audit_store.list_audit()
        assert logs[0]["actor"] == "user@example.com"

    async def test_audit_with_none_values(
        self, fresh_audit_store: MMapGraphStore, make_audit_event: Callable[..., dict[str, Any]]
    ) -> None:
        event = make_audit_event(event="none_test")
        event["optional_field"] = None
        await fresh_audit_store.append_audit(event)
        logs = await fresh_audit_store.list_audit()
        assert "optional_field" in logs[0]
        assert logs[0]["optional_field"] is None


class TestAuditPerformance:
    """Test audit logging performance."""

    async def test_append_many_events(
        self, fresh_audit_store: MMapGraphStore, make_audit_event: Callable[..., dict[str, Any]]
    ) -> None:
        for i in range(100):
            await fresh_audit_store.append_audit(make_audit_event(event=f"event_{i}"))
        logs = await fresh_audit_store.list_audit()
        assert len(logs) == 100

    async def test_audit_timeline_integrity(
        self, fresh_audit_store: MMapGraphStore, make_audit_event: Callable[..., dict[str, Any]]
    ) -> None:
        for i in range(50):
            await fresh_audit_store.append_audit(make_audit_event(event="seq_event", action=str(i)))
        logs = await fresh_audit_store.list_audit()
        for i, log in enumerate(logs):
            assert log["action"] == str(i)
