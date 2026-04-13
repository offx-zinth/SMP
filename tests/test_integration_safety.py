"""Integration tests for SMP Agent Safety components."""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from smp.engine.runtime_linker import RuntimeLinker
from smp.engine.safety import (
    AuditLogger,
    CheckpointManager,
    DryRunSimulator,
    GuardEngine,
    LockManager,
    SessionManager,
)


class TestSessionManager:
    """Tests for SessionManager."""

    @pytest.fixture
    def mgr(self) -> SessionManager:
        return SessionManager(ttl_seconds=3600)

    async def test_open_session_returns_session_id(self, mgr: SessionManager) -> None:
        result = await mgr.open_session(
            agent_id="agent_001",
            task="refactor auth module",
            scope=["smp/", "tests/"],
            mode="read",
        )
        assert "session_id" in result
        assert result["session_id"].startswith("ses_")
        assert "smp/" in result["granted_scope"]
        assert "tests/" in result["granted_scope"]
        assert "expires_at" in result

    async def test_open_session_denies_nonexistent_files(self, mgr: SessionManager) -> None:
        result = await mgr.open_session(
            agent_id="agent_001",
            task="create new file",
            scope=["nonexistent/file.py"],
            mode="write",
        )
        assert result["granted_scope"] == []
        assert result["denied_scope"] == ["nonexistent/file.py"]

    async def test_close_session_returns_summary(self, mgr: SessionManager) -> None:
        opened = await mgr.open_session(
            agent_id="agent_001",
            task="test task",
            scope=["src/"],
            mode="read",
        )
        session_id = opened["session_id"]

        closed = await mgr.close_session(session_id)
        assert closed is not None
        assert closed["session_id"] == session_id
        assert "duration_ms" in closed
        assert "audit_log_id" in closed

    async def test_close_session_unknown_id_returns_none(self, mgr: SessionManager) -> None:
        result = await mgr.close_session("ses_unknown")
        assert result is None

    async def test_get_session_returns_session(self, mgr: SessionManager) -> None:
        opened = await mgr.open_session(
            agent_id="agent_001",
            task="test task",
            scope=["src/"],
            mode="read",
        )
        session_id = opened["session_id"]

        session = await mgr.get_session(session_id)
        assert session is not None
        assert session.session_id == session_id
        assert session.agent_id == "agent_001"
        assert session.status == "open"

    async def test_get_session_expired_returns_none(self) -> None:
        mgr = SessionManager(ttl_seconds=0)
        opened = await mgr.open_session(
            agent_id="agent_001",
            task="test task",
            scope=["src/"],
            mode="read",
        )
        session_id = opened["session_id"]

        import asyncio

        await asyncio.sleep(0.01)

        session = await mgr.get_session(session_id)
        assert session is None

    async def test_record_file_access(self, mgr: SessionManager) -> None:
        opened = await mgr.open_session(
            agent_id="agent_001",
            task="test task",
            scope=["src/"],
            mode="read",
        )
        session_id = opened["session_id"]

        mgr.record_file_access(session_id, "src/main.py", "read")
        mgr.record_file_access(session_id, "src/main.py", "write")
        mgr.record_file_access(session_id, "src/utils.py", "write")

        session = await mgr.get_session(session_id)
        assert session is not None
        assert "src/main.py" in session.files_read
        assert "src/main.py" in session.files_written
        assert "src/utils.py" in session.files_written


class TestLockManager:
    """Tests for LockManager."""

    @pytest.fixture
    def mgr(self) -> LockManager:
        return LockManager()

    async def test_acquire_lock_grants_to_new_session(self, mgr: LockManager) -> None:
        result = await mgr.acquire("ses_001", ["src/main.py", "src/utils.py"])
        assert result["granted"] == ["src/main.py", "src/utils.py"]
        assert result["denied"] == []

    async def test_acquire_lock_denies_to_other_session(self, mgr: LockManager) -> None:
        await mgr.acquire("ses_001", ["src/main.py"])
        result = await mgr.acquire("ses_002", ["src/main.py"])
        assert result["granted"] == []
        assert result["denied"] == ["src/main.py"]

    async def test_acquire_lock_same_session_reacquires(self, mgr: LockManager) -> None:
        await mgr.acquire("ses_001", ["src/main.py"])
        result = await mgr.acquire("ses_001", ["src/main.py"])
        assert result["granted"] == ["src/main.py"]
        assert result["denied"] == []

    async def test_is_locked_returns_holder(self, mgr: LockManager) -> None:
        await mgr.acquire("ses_001", ["src/main.py"])
        assert mgr.is_locked("src/main.py") == "ses_001"

    async def test_is_locked_returns_none_when_unlocked(self, mgr: LockManager) -> None:
        assert mgr.is_locked("src/main.py") is None

    async def test_release_lock_releases(self, mgr: LockManager) -> None:
        await mgr.acquire("ses_001", ["src/main.py"])
        await mgr.release("ses_001", ["src/main.py"])
        assert mgr.is_locked("src/main.py") is None

    async def test_release_lock_ignores_wrong_session(self, mgr: LockManager) -> None:
        await mgr.acquire("ses_001", ["src/main.py"])
        await mgr.release("ses_002", ["src/main.py"])
        assert mgr.is_locked("src/main.py") == "ses_001"

    async def test_release_all_locks(self, mgr: LockManager) -> None:
        await mgr.acquire("ses_001", ["src/main.py", "src/utils.py"])
        await mgr.release_all("ses_001")
        assert mgr.is_locked("src/main.py") is None
        assert mgr.is_locked("src/utils.py") is None


class TestGuardEngine:
    """Tests for GuardEngine."""

    @pytest.fixture
    def session_mgr(self) -> SessionManager:
        return SessionManager()

    @pytest.fixture
    def lock_mgr(self) -> LockManager:
        return LockManager()

    @pytest.fixture
    def guard(self, session_mgr: SessionManager, lock_mgr: LockManager) -> GuardEngine:
        return GuardEngine(session_mgr, lock_mgr)

    async def test_guard_check_clear(self, guard: GuardEngine, session_mgr: SessionManager) -> None:
        opened = await session_mgr.open_session(
            agent_id="agent_001",
            task="update auth",
            scope=["smp/"],
            mode="write",
        )
        session_mgr.record_file_access(opened["session_id"], "smp/core/models.py", "write")

        result = await guard.check(
            session_id=opened["session_id"],
            target="smp/core/models.py",
            caller_count=2,
            has_tests=True,
        )
        assert result["verdict"] == "clear"
        assert result["target"] == "smp/core/models.py"
        assert result["checks"]["in_declared_scope"] is True
        assert result["checks"]["locked_by_other_agent"] is False

    async def test_guard_blocked_outside_scope(self, guard: GuardEngine, session_mgr: SessionManager) -> None:
        opened = await session_mgr.open_session(
            agent_id="agent_001",
            task="update auth",
            scope=["src/auth.py"],
            mode="write",
        )

        result = await guard.check(
            session_id=opened["session_id"],
            target="src/other.py",
        )
        assert result["verdict"] == "blocked"
        assert "File is outside declared session scope" in result["reasons"]

    async def test_guard_blocked_by_lock(
        self,
        guard: GuardEngine,
        session_mgr: SessionManager,
        lock_mgr: LockManager,
    ) -> None:
        opened = await session_mgr.open_session(
            agent_id="agent_001",
            task="update auth",
            scope=["src/auth.py"],
            mode="write",
        )
        await lock_mgr.acquire("ses_other", ["src/auth.py"])

        result = await guard.check(
            session_id=opened["session_id"],
            target="src/auth.py",
        )
        assert result["verdict"] == "blocked"
        assert any("Locked by session" in r for r in result["reasons"])

    async def test_guard_warnings_high_caller_count(self, guard: GuardEngine, session_mgr: SessionManager) -> None:
        opened = await session_mgr.open_session(
            agent_id="agent_001",
            task="update core",
            scope=["smp/"],
            mode="write",
        )

        result = await guard.check(
            session_id=opened["session_id"],
            target="smp/core/models.py",
            caller_count=10,
            has_tests=False,
        )
        assert result["verdict"] == "clear"
        assert any("cascade" in w for w in result["warnings"])
        assert any("No test coverage" in w for w in result["warnings"])

    async def test_guard_warnings_public_api(self, guard: GuardEngine, session_mgr: SessionManager) -> None:
        opened = await session_mgr.open_session(
            agent_id="agent_001",
            task="update api",
            scope=["src/api.py"],
            mode="write",
        )

        result = await guard.check(
            session_id=opened["session_id"],
            target="src/api.py",
            is_public_api=True,
        )
        assert "public API" in result["warnings"][0]


class TestDryRunSimulator:
    """Tests for DryRunSimulator."""

    @pytest.fixture
    def sim(self) -> DryRunSimulator:
        return DryRunSimulator()

    def test_simulate_safe_no_changes(self, sim: DryRunSimulator) -> None:
        result = sim.simulate(
            session_id="ses_001",
            file_path="src/utils.py",
            proposed_content="def foo(): pass",
        )
        assert result["verdict"] == "safe"
        assert result["structural_delta"]["nodes_modified"] == 1
        assert result["structural_delta"]["signature_changed"] is False

    def test_simulate_breaking_with_signature_change(self, sim: DryRunSimulator) -> None:
        result = sim.simulate(
            session_id="ses_001",
            file_path="src/api.py",
            proposed_content="def new_api(): pass",
            current_signature="def old_api():",
            proposed_signature="def new_api():",
            broken_callers=[{"function": "caller", "file": "src/main.py", "reason": "signature mismatch"}],
        )
        assert result["verdict"] == "breaking"
        assert result["structural_delta"]["signature_changed"] is True
        assert len(result["risks"]) > 0

    def test_simulate_affected_files(self, sim: DryRunSimulator) -> None:
        result = sim.simulate(
            session_id="ses_001",
            file_path="src/base.py",
            proposed_content="class NewBase: pass",
            affected_files=["src/derived.py", "src/consumer.py"],
        )
        assert result["verdict"] == "safe"
        assert len(result["impact"]["affected_files"]) == 2


class TestCheckpointManager:
    """Tests for CheckpointManager."""

    @pytest.fixture
    def mgr(self) -> CheckpointManager:
        return CheckpointManager()

    @pytest.fixture
    def temp_file(self) -> Path:
        with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
            f.write("original content\nline 2\nline 3\n")
            return Path(f.name)

    def test_create_checkpoint(self, mgr: CheckpointManager, temp_file: Path) -> None:
        result = mgr.create("ses_001", [str(temp_file)])
        assert "checkpoint_id" in result
        assert result["checkpoint_id"].startswith("chk_")
        assert result["files_snapshotted"] == [str(temp_file)]

    def test_rollback_restores_content(self, mgr: CheckpointManager, temp_file: Path) -> None:
        create_result = mgr.create("ses_001", [str(temp_file)])

        temp_file.write_text("modified content\n")

        rollback_result = mgr.rollback(create_result["checkpoint_id"])
        assert rollback_result["status"] == "rolled_back"
        assert str(temp_file) in rollback_result["files_restored"]
        assert temp_file.read_text() == "original content\nline 2\nline 3\n"

    def test_rollback_unknown_checkpoint(self, mgr: CheckpointManager) -> None:
        result = mgr.rollback("chk_unknown")
        assert result["status"] == "error"
        assert "not found" in result["reason"]


class TestAuditLogger:
    """Tests for AuditLogger."""

    @pytest.fixture
    def logger(self) -> AuditLogger:
        return AuditLogger()

    def test_create_log_returns_id(self, logger: AuditLogger) -> None:
        audit_log_id = logger.create_log(
            agent_id="agent_001",
            task="refactor auth",
            session_id="ses_001",
        )
        assert audit_log_id.startswith("aud_")

    def test_append_event(self, logger: AuditLogger) -> None:
        audit_log_id = logger.create_log(
            agent_id="agent_001",
            task="refactor auth",
            session_id="ses_001",
        )
        logger.append_event(
            audit_log_id=audit_log_id,
            method="write",
            target="src/auth.py",
            result="success",
            checkpoint_id="chk_001",
            files=["src/auth.py"],
        )

        log = logger.get_log(audit_log_id)
        assert log is not None
        assert len(log["events"]) == 1
        assert log["events"][0]["method"] == "write"
        assert log["events"][0]["target"] == "src/auth.py"

    def test_append_event_unknown_log_ignores(self, logger: AuditLogger) -> None:
        logger.append_event(
            audit_log_id="aud_unknown",
            method="write",
            target="src/auth.py",
        )

    def test_close_log(self, logger: AuditLogger) -> None:
        audit_log_id = logger.create_log(
            agent_id="agent_001",
            task="refactor auth",
            session_id="ses_001",
        )
        logger.close_log(audit_log_id, status="completed")

        log = logger.get_log(audit_log_id)
        assert log is not None
        assert log["status"] == "completed"
        assert log["closed_at"] != ""

    def test_get_log_unknown_returns_none(self, logger: AuditLogger) -> None:
        result = logger.get_log("aud_unknown")
        assert result is None


class TestRuntimeLinker:
    """Tests for RuntimeLinker."""

    @pytest.fixture
    def linker(self) -> RuntimeLinker:
        return RuntimeLinker()

    def test_record_call_returns_edge(self, linker: RuntimeLinker) -> None:
        edge = linker.record_call(
            source_id="node_001",
            target_id="node_002",
            session_id="ses_001",
            duration_ms=50,
        )
        assert edge.source_id == "node_001"
        assert edge.target_id == "node_002"
        assert edge.edge_type == "CALLS_RUNTIME"
        assert edge.duration_ms == 50

    def test_record_call_increments_counts(self, linker: RuntimeLinker) -> None:
        linker.record_call("node_001", "node_002", "ses_001")
        linker.record_call("node_001", "node_002", "ses_001")
        linker.record_call("node_001", "node_002", "ses_001")

        stats = linker.get_stats()
        assert stats["total_calls"] == 3
        assert stats["unique_paths"] == 1

    def test_start_trace_returns_trace_id(self, linker: RuntimeLinker) -> None:
        trace_id = linker.start_trace(session_id="ses_001", agent_id="agent_001")
        assert trace_id.startswith("trc_")

    def test_end_trace_returns_trace(self, linker: RuntimeLinker) -> None:
        trace_id = linker.start_trace(session_id="ses_001", agent_id="agent_001")
        linker.record_call("node_001", "node_002", "ses_001")
        linker.record_call("node_002", "node_003", "ses_001")

        trace = linker.end_trace(trace_id)
        assert trace is not None
        assert trace.trace_id == trace_id
        assert len(trace.edges) == 2
        assert len(trace.nodes_visited) == 3

    def test_end_trace_unknown_returns_none(self, linker: RuntimeLinker) -> None:
        result = linker.end_trace("trc_unknown")
        assert result is None

    def test_get_trace(self, linker: RuntimeLinker) -> None:
        trace_id = linker.start_trace(session_id="ses_001", agent_id="agent_001")
        trace = linker.get_trace(trace_id)
        assert trace is not None
        assert trace.trace_id == trace_id

    def test_get_session_traces(self, linker: RuntimeLinker) -> None:
        linker.start_trace(session_id="ses_001", agent_id="agent_001")
        trace = linker.get_trace(linker.start_trace(session_id="ses_001", agent_id="agent_001"))
        assert trace is not None
        assert trace.session_id == "ses_001"

    def test_get_hot_paths(self, linker: RuntimeLinker) -> None:
        linker.record_call("A", "B", "ses_001")
        linker.record_call("A", "B", "ses_001")
        linker.record_call("A", "B", "ses_001")
        linker.record_call("A", "B", "ses_001")
        linker.record_call("A", "B", "ses_001")

        linker.record_call("A", "C", "ses_001")
        linker.record_call("A", "C", "ses_001")

        linker.record_call("B", "C", "ses_001")

        hot = linker.get_hot_paths(threshold=5)
        assert len(hot) == 1
        assert hot[0]["source_id"] == "A"
        assert hot[0]["target_id"] == "B"
        assert hot[0]["call_count"] == 5

    def test_get_hot_paths_default_threshold(self, linker: RuntimeLinker) -> None:
        linker.record_call("A", "B", "ses_001")
        linker.record_call("A", "B", "ses_001")

        hot = linker.get_hot_paths()
        assert len(hot) == 0

    def test_clear(self, linker: RuntimeLinker) -> None:
        linker.record_call("node_001", "node_002", "ses_001")
        linker.start_trace(session_id="ses_001", agent_id="agent_001")

        linker.clear()

        stats = linker.get_stats()
        assert stats["total_calls"] == 0
        assert stats["active_traces"] == 0

    def test_get_stats(self, linker: RuntimeLinker) -> None:
        linker.record_call("A", "B", "ses_001")
        linker.record_call("B", "C", "ses_001")
        linker.start_trace(session_id="ses_001", agent_id="agent_001")

        stats = linker.get_stats()
        assert stats["total_calls"] == 2
        assert stats["unique_paths"] == 2
        assert stats["active_traces"] == 1
        assert stats["sessions_with_traces"] == 1
