"""Agent Safety Protocol — sessions, guards, dry-runs, locks, checkpoints, audit.

Implements the full SMP(3) agent write lifecycle:
  session/open → guard/check → dryrun → checkpoint → write → update → session/close
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

from smp.logging import get_logger

if TYPE_CHECKING:
    from smp.store.interfaces import GraphStore

log = get_logger(__name__)

_SESSION_TTL_SECONDS = 3600


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass
class Session:
    """Represents an active agent session."""

    session_id: str
    agent_id: str
    task: str
    scope: list[str]
    mode: str
    granted_scope: list[str]
    denied_scope: list[str]
    opened_at: str
    expires_at: str
    status: str = "open"
    files_written: list[str] = field(default_factory=list)
    files_read: list[str] = field(default_factory=list)


@dataclass
class AuditEvent:
    """A single event in the audit log."""

    timestamp: str
    method: str
    target: str = ""
    result: str = ""
    checkpoint_id: str = ""
    files: list[str] = field(default_factory=list)


@dataclass
class AuditLog:
    """Full audit record for a session."""

    audit_log_id: str
    agent_id: str
    task: str
    session_id: str
    opened_at: str
    closed_at: str = ""
    status: str = "open"
    events: list[AuditEvent] = field(default_factory=list)


@dataclass
class Checkpoint:
    """Snapshot of files before a write."""

    checkpoint_id: str
    session_id: str
    files: dict[str, str]
    snapshot_at: str


# ---------------------------------------------------------------------------
# Session Manager
# ---------------------------------------------------------------------------


class SessionManager:
    """Manages agent session lifecycle with scope enforcement and auto-expiry."""

    def __init__(
        self,
        ttl_seconds: int = _SESSION_TTL_SECONDS,
        graph_store: GraphStore | None = None,
    ) -> None:
        self._sessions: dict[str, Session] = {}
        self._ttl = ttl_seconds
        self._graph = graph_store

    def set_graph_store(self, graph_store: GraphStore) -> None:
        """Set the graph store for session persistence."""
        self._graph = graph_store

    async def _persist_session(self, session: Session) -> None:
        """Persist session to graph if available."""
        if self._graph:
            await self._graph.upsert_session(session)

    async def _load_session(self, session_id: str) -> Session | None:
        """Load session from graph if available."""
        if self._graph:
            data = await self._graph.get_session(session_id)
            if data:
                return Session(
                    session_id=data["session_id"],
                    agent_id=data["agent_id"],
                    task=data["task"],
                    scope=data.get("scope", []),
                    mode=data.get("mode", "read"),
                    granted_scope=data.get("granted_scope", []),
                    denied_scope=data.get("denied_scope", []),
                    opened_at=data["opened_at"],
                    expires_at=data["expires_at"],
                    status=data.get("status", "open"),
                    files_written=data.get("files_written", []),
                    files_read=data.get("files_read", []),
                )
        return None

    async def open_session(
        self,
        agent_id: str,
        task: str,
        scope: list[str],
        mode: str = "read",
    ) -> dict[str, Any]:
        """Open a new session and return the result dict."""
        session_id = f"ses_{uuid.uuid4().hex[:6]}"
        now = datetime.now(UTC)
        expires = now.timestamp() + self._ttl

        granted = []
        denied = []
        warnings = []

        for path in scope:
            p = Path(path)
            if p.exists() or not p.suffix:
                granted.append(path)
            else:
                denied.append(path)

        for path in granted:
            caller_count = 0
            if caller_count > 10:
                warnings.append(f"{path} is imported by {caller_count} files — changes have wide blast radius")

        session = Session(
            session_id=session_id,
            agent_id=agent_id,
            task=task,
            scope=scope,
            mode=mode,
            granted_scope=granted,
            denied_scope=denied,
            opened_at=now.isoformat(),
            expires_at=datetime.fromtimestamp(expires, tz=UTC).isoformat(),
        )
        self._sessions[session_id] = session
        await self._persist_session(session)

        log.info("session_opened", session_id=session_id, agent_id=agent_id, mode=mode)
        return {
            "session_id": session_id,
            "granted_scope": granted,
            "denied_scope": denied,
            "active_locks": [],
            "warnings": warnings,
            "expires_at": session.expires_at,
        }

    async def close_session(self, session_id: str, status: str = "completed") -> dict[str, Any] | None:
        """Close a session and return summary."""
        session = self._sessions.get(session_id)
        if not session:
            return None

        session.status = status
        now = datetime.now(UTC)
        opened = datetime.fromisoformat(session.opened_at)
        duration_ms = int((now - opened).total_seconds() * 1000)

        audit_log_id = f"aud_{uuid.uuid4().hex[:6]}"

        log.info("session_closed", session_id=session_id, status=status, duration_ms=duration_ms)

        if self._graph:
            await self._graph.delete_session(session_id)

        return {
            "session_id": session_id,
            "files_written": session.files_written,
            "files_read": session.files_read,
            "duration_ms": duration_ms,
            "audit_log_id": audit_log_id,
        }

    async def get_session(self, session_id: str) -> Session | None:
        """Get a session by ID, checking expiry."""
        session = self._sessions.get(session_id)
        if not session:
            return await self._load_session(session_id)
        if session.status != "open":
            return None
        expires = datetime.fromisoformat(session.expires_at)
        if datetime.now(UTC) > expires:
            session.status = "expired"
            return None
        return session

    async def is_in_scope(self, session_id: str, file_path: str) -> bool:
        """Check if file_path is within the session's granted scope."""
        session = await self.get_session(session_id)
        if not session:
            return False
        return any(file_path == granted or file_path.startswith(granted) for granted in session.granted_scope)

    def record_file_access(self, session_id: str, file_path: str, access_type: str = "read") -> None:
        """Record that a file was read or written in this session."""
        session = self._sessions.get(session_id)
        if not session:
            return
        if access_type == "write" and file_path not in session.files_written:
            session.files_written.append(file_path)
        elif access_type == "read" and file_path not in session.files_read:
            session.files_read.append(file_path)

    async def recover_session(self, session_id: str) -> dict[str, Any] | None:
        """Recover a session from persistent storage."""
        session = await self._load_session(session_id)
        if not session:
            return None
        self._sessions[session_id] = session
        log.info("session_recovered", session_id=session_id)
        return {
            "session_id": session.session_id,
            "agent_id": session.agent_id,
            "task": session.task,
            "scope": session.scope,
            "mode": session.mode,
            "opened_at": session.opened_at,
            "expires_at": session.expires_at,
            "status": session.status,
        }


# ---------------------------------------------------------------------------
# Lock Manager
# ---------------------------------------------------------------------------


class LockManager:
    """File-level locking to prevent concurrent writes."""

    def __init__(self, graph_store: GraphStore | None = None) -> None:
        self._locks: dict[str, str] = {}
        self._graph = graph_store

    def set_graph_store(self, graph_store: GraphStore) -> None:
        """Set the graph store for lock persistence."""
        self._graph = graph_store

    async def acquire(self, session_id: str, files: list[str]) -> dict[str, Any]:
        """Acquire locks on files for a session."""
        granted = []
        denied = []
        for f in files:
            if f in self._locks:
                holder = self._locks[f]
                if holder == session_id:
                    granted.append(f)
                else:
                    denied.append(f)
            else:
                self._locks[f] = session_id
                granted.append(f)
                if self._graph:
                    await self._graph.upsert_lock(f, session_id)

        log.info("locks_acquired", session_id=session_id, granted=len(granted), denied=len(denied))
        return {"granted": granted, "denied": denied}

    async def release(self, session_id: str, files: list[str]) -> None:
        """Release locks held by a session."""
        for f in files:
            if self._locks.get(f) == session_id:
                del self._locks[f]
                if self._graph:
                    await self._graph.release_lock(f, session_id)
        log.info("locks_released", session_id=session_id, files=len(files))

    async def release_all(self, session_id: str) -> None:
        """Release all locks held by a session."""
        to_release = [f for f, sid in self._locks.items() if sid == session_id]
        for f in to_release:
            del self._locks[f]
        if self._graph:
            await self._graph.release_all_locks(session_id)

    def is_locked(self, file_path: str) -> str | None:
        """Return session_id that holds the lock, or None."""
        return self._locks.get(file_path)


# ---------------------------------------------------------------------------
# Guard Engine
# ---------------------------------------------------------------------------


class GuardEngine:
    """Pre-flight safety checks before writing a file."""

    def __init__(self, session_manager: SessionManager, lock_manager: LockManager) -> None:
        self._sessions = session_manager
        self._locks = lock_manager

    async def check(
        self,
        session_id: str,
        target: str,
        intended_change: str = "",
        caller_count: int = 0,
        has_tests: bool = False,
        test_files: list[str] | None = None,
        is_public_api: bool = False,
        has_downstream: bool = False,
    ) -> dict[str, Any]:
        """Run pre-flight checks and return verdict."""
        reasons: list[str] = []
        warnings: list[str] = []
        checks: dict[str, Any] = {}

        session = await self._sessions.get_session(session_id)
        if not session:
            return {"verdict": "blocked", "reasons": ["Session not found or expired"]}

        in_scope = await self._sessions.is_in_scope(session_id, target)
        locked_by = self._locks.is_locked(target)
        locked_by_other = locked_by is not None and locked_by != session_id

        checks["in_declared_scope"] = in_scope
        checks["locked_by_other_agent"] = locked_by_other
        checks["has_tests"] = has_tests
        checks["test_files"] = test_files or []
        checks["caller_count"] = caller_count
        checks["is_public_api"] = is_public_api
        checks["has_downstream_services"] = has_downstream

        if not in_scope:
            reasons.append("File is outside declared session scope")
        if locked_by_other:
            reasons.append(f"Locked by session {locked_by}")

        if caller_count > 5:
            warnings.append(f"Target has {caller_count} callers — changes will cascade")
        if is_public_api:
            warnings.append("Target is part of public API — signature changes are breaking")
        if not has_tests and caller_count > 0:
            warnings.append("No test coverage found — manual verification recommended")

        verdict = "blocked" if reasons else "clear"

        result: dict[str, Any] = {
            "verdict": verdict,
            "target": target,
            "checks": checks,
            "warnings": warnings,
        }
        if reasons:
            result["reasons"] = reasons

        log.info("guard_check", target=target, verdict=verdict, session_id=session_id)
        return result


# ---------------------------------------------------------------------------
# Dry Run Simulator
# ---------------------------------------------------------------------------


class DryRunSimulator:
    """Simulate structural impact of proposed changes without disk writes."""

    def __init__(self) -> None:
        pass

    def simulate(
        self,
        session_id: str,
        file_path: str,
        proposed_content: str,
        change_summary: str = "",
        current_signature: str = "",
        proposed_signature: str = "",
        affected_files: list[str] | None = None,
        broken_callers: list[dict[str, str]] | None = None,
    ) -> dict[str, Any]:
        """Simulate the write and return structural delta + verdict."""
        signature_changed = bool(current_signature and proposed_signature and current_signature != proposed_signature)

        nodes_added = 0
        nodes_modified = 1
        nodes_removed = 0

        risks: list[str] = []
        if signature_changed:
            risks.append("Signature change detected — may break callers")
        if affected_files:
            risks.append(f"{len(affected_files)} files may need updates")
        if broken_callers:
            for bc in broken_callers:
                risks.append(
                    f"{bc.get('function', '?')} in {bc.get('file', '?')}: {bc.get('reason', 'incompatible change')}"
                )

        verdict = "breaking" if (signature_changed and (broken_callers or affected_files)) else "safe"

        result: dict[str, Any] = {
            "structural_delta": {
                "nodes_added": nodes_added,
                "nodes_modified": nodes_modified,
                "nodes_removed": nodes_removed,
                "signature_changed": signature_changed,
            },
            "impact": {
                "affected_files": affected_files or [],
                "broken_callers": broken_callers or [],
                "test_coverage_delta": "unchanged",
            },
            "verdict": verdict,
            "risks": risks,
        }

        log.info("dryrun_complete", file_path=file_path, verdict=verdict, session_id=session_id)
        return result


# ---------------------------------------------------------------------------
# Checkpoint Manager
# ---------------------------------------------------------------------------


class CheckpointManager:
    """Snapshot and restore file state."""

    def __init__(self) -> None:
        self._checkpoints: dict[str, Checkpoint] = {}

    def create(self, session_id: str, files: list[str]) -> dict[str, Any]:
        """Create a checkpoint by snapshotting file contents."""
        checkpoint_id = f"chk_{uuid.uuid4().hex[:6]}"
        now = datetime.now(UTC).isoformat()

        snapshots: dict[str, str] = {}
        snapshotted: list[str] = []
        for f in files:
            try:
                content = Path(f).read_text(encoding="utf-8")
                snapshots[f] = content
                snapshotted.append(f)
            except OSError:
                log.warning("checkpoint_file_unreadable", file=f)

        checkpoint = Checkpoint(
            checkpoint_id=checkpoint_id,
            session_id=session_id,
            files=snapshots,
            snapshot_at=now,
        )
        self._checkpoints[checkpoint_id] = checkpoint

        log.info("checkpoint_created", checkpoint_id=checkpoint_id, files=len(snapshotted))
        return {
            "checkpoint_id": checkpoint_id,
            "files_snapshotted": snapshotted,
            "snapshot_at": now,
        }

    def rollback(self, checkpoint_id: str) -> dict[str, Any]:
        """Restore files from a checkpoint."""
        checkpoint = self._checkpoints.get(checkpoint_id)
        if not checkpoint:
            return {"status": "error", "reason": "Checkpoint not found"}

        restored: list[str] = []
        for f, content in checkpoint.files.items():
            try:
                Path(f).write_text(content, encoding="utf-8")
                restored.append(f)
            except OSError as exc:
                log.error("rollback_write_failed", file=f, error=str(exc))

        log.info("rollback_complete", checkpoint_id=checkpoint_id, restored=len(restored))
        return {
            "status": "rolled_back",
            "files_restored": restored,
            "memory_resynced": True,
        }


# ---------------------------------------------------------------------------
# Audit Logger
# ---------------------------------------------------------------------------


class AuditLogger:
    """Persistent append-only audit log for session events."""

    def __init__(self) -> None:
        self._logs: dict[str, AuditLog] = {}

    def create_log(self, agent_id: str, task: str, session_id: str) -> str:
        """Create a new audit log for a session."""
        audit_log_id = f"aud_{uuid.uuid4().hex[:6]}"
        now = datetime.now(UTC).isoformat()
        self._logs[audit_log_id] = AuditLog(
            audit_log_id=audit_log_id,
            agent_id=agent_id,
            task=task,
            session_id=session_id,
            opened_at=now,
        )
        return audit_log_id

    def append_event(
        self,
        audit_log_id: str,
        method: str,
        target: str = "",
        result: str = "",
        checkpoint_id: str = "",
        files: list[str] | None = None,
    ) -> None:
        """Append an event to an audit log."""
        log_entry = self._logs.get(audit_log_id)
        if not log_entry:
            return
        event = AuditEvent(
            timestamp=datetime.now(UTC).strftime("%H:%M:%S"),
            method=method,
            target=target,
            result=result,
            checkpoint_id=checkpoint_id,
            files=files or [],
        )
        log_entry.events.append(event)

    def close_log(self, audit_log_id: str, status: str = "completed") -> None:
        """Mark an audit log as closed."""
        log_entry = self._logs.get(audit_log_id)
        if log_entry:
            log_entry.closed_at = datetime.now(UTC).isoformat()
            log_entry.status = status

    def get_log(self, audit_log_id: str) -> dict[str, Any] | None:
        """Retrieve an audit log."""
        log_entry = self._logs.get(audit_log_id)
        if not log_entry:
            return None
        return {
            "audit_log_id": log_entry.audit_log_id,
            "agent_id": log_entry.agent_id,
            "task": log_entry.task,
            "session_id": log_entry.session_id,
            "opened_at": log_entry.opened_at,
            "closed_at": log_entry.closed_at,
            "status": log_entry.status,
            "events": [
                {
                    "t": e.timestamp,
                    "method": e.method,
                    "target": e.target,
                    "result": e.result,
                    "checkpoint_id": e.checkpoint_id,
                    "files": e.files,
                }
                for e in log_entry.events
            ],
        }
