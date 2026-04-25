"""Session, safety, and audit handlers.

Provides:

* ``smp/session/open`` / ``smp/session/close`` / ``smp/session/recover``
* ``smp/dryrun`` / ``smp/checkpoint`` / ``smp/rollback``
* ``smp/lock`` / ``smp/unlock`` / ``smp/audit/get``

Sessions, locks and audit events are persisted via the durable
:class:`~smp.store.graph.mmap_store.MMapGraphStore` interface
(:meth:`upsert_session`, :meth:`upsert_lock`,
:meth:`append_audit`).  Any store that doesn't yet implement these
async methods (raising :class:`NotImplementedError`) falls back to a
per-process ``ctx`` dict so callers always get a deterministic shape.

Locks are implemented as **time-bounded leases**: each acquisition
returns a fencing token together with an ``expires_at`` timestamp.
Stale leases are reclaimed automatically the next time a conflicting
acquisition is attempted, which keeps the surface honest even when
agents crash without releasing.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

import msgspec

from smp.core.models import (
    AuditGetParams,
    CheckpointParams,
    DryRunParams,
    LockParams,
    RollbackParams,
    SessionCloseParams,
    SessionOpenParams,
    SessionRecoverParams,
)
from smp.logging import get_logger

log = get_logger(__name__)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _now_iso() -> str:
    return _now().isoformat()


# ---------------------------------------------------------------------------
# In-memory fallbacks (only used when the graph store doesn't implement
# the durable session/lock surface).
# ---------------------------------------------------------------------------


def _session_store(ctx: dict[str, Any]) -> dict[str, dict[str, Any]]:
    store = ctx.setdefault("_sessions", {})
    if not isinstance(store, dict):  # defensive
        store = {}
        ctx["_sessions"] = store
    return store


def _lock_store(ctx: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return ctx.setdefault("_locks", {})  # type: ignore[no-any-return]


def _audit_log(ctx: dict[str, Any]) -> list[dict[str, Any]]:
    return ctx.setdefault("_audit_log", [])  # type: ignore[no-any-return]


# ---------------------------------------------------------------------------
# Persistence helpers
# ---------------------------------------------------------------------------


async def _persist_session(graph: Any, session: dict[str, Any]) -> None:
    try:
        await graph.upsert_session(session)
    except (NotImplementedError, AttributeError):
        return


async def _load_session(graph: Any, ctx: dict[str, Any], session_id: str) -> dict[str, Any] | None:
    try:
        loaded = await graph.get_session(session_id)
    except (NotImplementedError, AttributeError):
        loaded = None
    if loaded:
        return loaded
    return _session_store(ctx).get(session_id)


async def _record_audit(graph: Any, ctx: dict[str, Any], event: dict[str, Any]) -> None:
    """Append an audit event durably (graph store) and to the per-process log."""
    _audit_log(ctx).append(event)
    try:
        await graph.append_audit(event)
    except (NotImplementedError, AttributeError):
        return


# ---------------------------------------------------------------------------
# Lock helpers
# ---------------------------------------------------------------------------


def _is_lock_stale(info: dict[str, Any], at: datetime) -> bool:
    expires_at = info.get("expires_at")
    if not expires_at:
        return False
    try:
        deadline = datetime.fromisoformat(str(expires_at))
    except ValueError:
        return False
    if deadline.tzinfo is None:
        deadline = deadline.replace(tzinfo=timezone.utc)
    return deadline < at


async def _get_lock(graph: Any, ctx: dict[str, Any], file_path: str) -> dict[str, Any] | None:
    try:
        existing = await graph.get_lock(file_path)
    except (NotImplementedError, AttributeError):
        existing = _lock_store(ctx).get(file_path)
    return dict(existing) if isinstance(existing, dict) else existing


async def _release_lock(graph: Any, ctx: dict[str, Any], file_path: str, session_id: str) -> bool:
    try:
        ok = await graph.release_lock(file_path, session_id)
    except (NotImplementedError, AttributeError):
        existing = _lock_store(ctx).get(file_path)
        if existing and existing.get("session_id") == session_id:
            _lock_store(ctx).pop(file_path, None)
            return True
        return False
    return bool(ok)


async def _acquire_lock(
    graph: Any,
    ctx: dict[str, Any],
    file_path: str,
    session_id: str,
    *,
    ttl: timedelta,
    now: datetime,
) -> dict[str, Any]:
    """Persist a fresh lock and return the lease record."""
    expires_at = (now + ttl).isoformat()
    acquired_at = now.isoformat()
    try:
        await graph.upsert_lock(
            file_path,
            session_id,
            acquired_at=acquired_at,
            expires_at=expires_at,
        )
    except TypeError:
        # Older stores without keyword args
        try:
            await graph.upsert_lock(file_path, session_id)
        except (NotImplementedError, AttributeError):
            _lock_store(ctx)[file_path] = {
                "session_id": session_id,
                "acquired_at": acquired_at,
                "expires_at": expires_at,
            }
    except (NotImplementedError, AttributeError):
        _lock_store(ctx)[file_path] = {
            "session_id": session_id,
            "acquired_at": acquired_at,
            "expires_at": expires_at,
        }

    lease = await _get_lock(graph, ctx, file_path) or {
        "session_id": session_id,
        "acquired_at": acquired_at,
        "expires_at": expires_at,
    }
    return lease


# ---------------------------------------------------------------------------
# Session lifecycle
# ---------------------------------------------------------------------------


async def session_open(params: dict[str, Any], ctx: dict[str, Any]) -> dict[str, Any]:
    """Handle ``smp/session/open``."""
    p = msgspec.convert(params, SessionOpenParams)
    graph = ctx["graph"]

    session_id = f"sess_{uuid.uuid4().hex[:12]}"
    session = {
        "session_id": session_id,
        "agent_id": p.agent_id,
        "task": p.task,
        "scope": list(p.scope),
        "mode": p.mode,
        "status": "open",
        "started_at": _now_iso(),
        "checkpoints": [],
        "locked_files": [],
    }

    _session_store(ctx)[session_id] = session
    await _persist_session(graph, session)
    await _record_audit(
        graph,
        ctx,
        {"ts": session["started_at"], "event": "session_open", "session_id": session_id, "agent_id": p.agent_id},
    )

    return {"session_id": session_id, "status": "open", "started_at": session["started_at"]}


async def session_close(params: dict[str, Any], ctx: dict[str, Any]) -> dict[str, Any]:
    """Handle ``smp/session/close``."""
    p = msgspec.convert(params, SessionCloseParams)
    graph = ctx["graph"]

    session = await _load_session(graph, ctx, p.session_id)
    if session is None:
        return {"session_id": p.session_id, "closed": False, "error": "session_not_found"}

    session["status"] = p.status or "completed"
    session["ended_at"] = _now_iso()

    released = 0
    try:
        released = await graph.release_all_locks(p.session_id)
    except (NotImplementedError, AttributeError):
        locks = _lock_store(ctx)
        held = [fp for fp, info in locks.items() if info.get("session_id") == p.session_id]
        for fp in held:
            locks.pop(fp, None)
            released += 1

    try:
        await graph.delete_session(p.session_id)
    except (NotImplementedError, AttributeError):
        pass
    _session_store(ctx).pop(p.session_id, None)
    await _record_audit(
        graph,
        ctx,
        {
            "ts": session["ended_at"],
            "event": "session_close",
            "session_id": p.session_id,
            "status": session["status"],
            "released_locks": released,
        },
    )

    return {"session_id": p.session_id, "closed": True, "status": session["status"], "released_locks": released}


async def session_recover(params: dict[str, Any], ctx: dict[str, Any]) -> dict[str, Any]:
    """Handle ``smp/session/recover``."""
    p = msgspec.convert(params, SessionRecoverParams)
    graph = ctx["graph"]

    session = await _load_session(graph, ctx, p.session_id)
    if session is None:
        return {"session_id": p.session_id, "recovered": False, "error": "session_not_found"}

    return {"session_id": p.session_id, "recovered": True, "session": session}


# ---------------------------------------------------------------------------
# Dryrun / checkpoint / rollback
# ---------------------------------------------------------------------------


async def dryrun(params: dict[str, Any], ctx: dict[str, Any]) -> dict[str, Any]:
    """Handle ``smp/dryrun`` — preview the structural diff for a proposed change."""
    p = msgspec.convert(params, DryRunParams)
    engine = ctx["engine"]

    diff = await engine.diff_file(p.file_path, p.proposed_content or None)
    return {
        "session_id": p.session_id,
        "file_path": p.file_path,
        "change_summary": p.change_summary,
        "diff": diff,
    }


async def checkpoint(params: dict[str, Any], ctx: dict[str, Any]) -> dict[str, Any]:
    """Handle ``smp/checkpoint`` — snapshot fingerprints for given files."""
    p = msgspec.convert(params, CheckpointParams)
    graph = ctx["graph"]

    session = await _load_session(graph, ctx, p.session_id)
    if session is None:
        return {"checkpoint_id": "", "created": False, "error": "session_not_found"}

    fingerprints: dict[str, list[str]] = {}
    for file_path in p.files:
        nodes = await graph.find_nodes(file_path=file_path)
        fingerprints[file_path] = [node.fingerprint() for node in nodes]

    checkpoint_id = f"ckpt_{uuid.uuid4().hex[:10]}"
    record = {
        "checkpoint_id": checkpoint_id,
        "files": list(p.files),
        "fingerprints": fingerprints,
        "created_at": _now_iso(),
    }
    session.setdefault("checkpoints", []).append(record)
    await _persist_session(graph, session)
    await _record_audit(
        graph,
        ctx,
        {"ts": record["created_at"], "event": "checkpoint", "session_id": p.session_id, "checkpoint_id": checkpoint_id},
    )

    return {"checkpoint_id": checkpoint_id, "created": True, "files": list(p.files)}


async def rollback(params: dict[str, Any], ctx: dict[str, Any]) -> dict[str, Any]:
    """Handle ``smp/rollback`` — locate a checkpoint within a session."""
    p = msgspec.convert(params, RollbackParams)
    graph = ctx["graph"]

    session = await _load_session(graph, ctx, p.session_id)
    if session is None:
        return {"rolled_back": False, "error": "session_not_found"}

    for record in reversed(session.get("checkpoints", [])):
        if record.get("checkpoint_id") == p.checkpoint_id:
            await _record_audit(
                graph,
                ctx,
                {
                    "ts": _now_iso(),
                    "event": "rollback",
                    "session_id": p.session_id,
                    "checkpoint_id": p.checkpoint_id,
                },
            )
            return {
                "rolled_back": True,
                "checkpoint_id": p.checkpoint_id,
                "files": record.get("files", []),
                "fingerprints": record.get("fingerprints", {}),
            }

    return {"rolled_back": False, "checkpoint_id": p.checkpoint_id, "error": "checkpoint_not_found"}


# ---------------------------------------------------------------------------
# Locks
# ---------------------------------------------------------------------------


async def lock(params: dict[str, Any], ctx: dict[str, Any]) -> dict[str, Any]:
    """Handle ``smp/lock`` — acquire time-bounded leases for files.

    Behaviour:

    * Each lease records ``acquired_at`` and ``expires_at`` (from
      ``ttl_seconds``).  Other agents see conflicts until the lease
      expires or is explicitly released.
    * Expired leases are cleaned up automatically when the next
      acquisition request arrives.
    * ``force=True`` steals an active lease (audit-logged); useful for
      operator recovery when the original holder is known to be gone.
    """
    p = msgspec.convert(params, LockParams)
    graph = ctx["graph"]
    ttl = timedelta(seconds=max(1, int(p.ttl_seconds or 300)))
    now = _now()

    locked: list[dict[str, Any]] = []
    conflicts: list[dict[str, Any]] = []
    for file_path in p.files:
        existing = await _get_lock(graph, ctx, file_path)
        if existing and existing.get("session_id") and existing["session_id"] != p.session_id:
            if _is_lock_stale(existing, now):
                await _release_lock(graph, ctx, file_path, str(existing["session_id"]))
                await _record_audit(
                    graph,
                    ctx,
                    {
                        "ts": now.isoformat(),
                        "event": "lock_expired",
                        "session_id": existing["session_id"],
                        "file_path": file_path,
                    },
                )
                existing = None
            elif p.force:
                await _release_lock(graph, ctx, file_path, str(existing["session_id"]))
                await _record_audit(
                    graph,
                    ctx,
                    {
                        "ts": now.isoformat(),
                        "event": "lock_stolen",
                        "stolen_from": existing["session_id"],
                        "stolen_by": p.session_id,
                        "file_path": file_path,
                    },
                )
                existing = None
            else:
                conflicts.append(
                    {
                        "file": file_path,
                        "held_by": existing["session_id"],
                        "expires_at": existing.get("expires_at", ""),
                    }
                )
                continue

        lease = await _acquire_lock(graph, ctx, file_path, p.session_id, ttl=ttl, now=now)
        await _record_audit(
            graph,
            ctx,
            {
                "ts": now.isoformat(),
                "event": "lock_acquired",
                "session_id": p.session_id,
                "file_path": file_path,
                "expires_at": lease.get("expires_at", ""),
                "fencing_token": lease.get("fencing_token", 0),
            },
        )
        locked.append({"file": file_path, "fencing_token": lease.get("fencing_token", 0), "expires_at": lease.get("expires_at", "")})

    session = await _load_session(graph, ctx, p.session_id)
    if session is not None:
        session_locks = set(session.get("locked_files", []))
        session_locks.update(item["file"] for item in locked)
        session["locked_files"] = sorted(session_locks)
        await _persist_session(graph, session)

    return {
        "session_id": p.session_id,
        "locked": [item["file"] for item in locked],
        "leases": locked,
        "conflicts": conflicts,
    }


async def unlock(params: dict[str, Any], ctx: dict[str, Any]) -> dict[str, Any]:
    """Handle ``smp/unlock`` — release locks for files."""
    p = msgspec.convert(params, LockParams)
    graph = ctx["graph"]

    released: list[str] = []
    for file_path in p.files:
        if await _release_lock(graph, ctx, file_path, p.session_id):
            released.append(file_path)
            await _record_audit(
                graph,
                ctx,
                {
                    "ts": _now_iso(),
                    "event": "lock_released",
                    "session_id": p.session_id,
                    "file_path": file_path,
                },
            )

    session = await _load_session(graph, ctx, p.session_id)
    if session is not None:
        remaining = [fp for fp in session.get("locked_files", []) if fp not in released]
        session["locked_files"] = remaining
        await _persist_session(graph, session)

    return {"session_id": p.session_id, "released": released}


# ---------------------------------------------------------------------------
# Audit
# ---------------------------------------------------------------------------


async def audit_get(params: dict[str, Any], ctx: dict[str, Any]) -> dict[str, Any]:
    """Handle ``smp/audit/get`` — return collected audit events.

    Pulls from the durable backend first (``graph.list_audit``) and
    falls back to ``ctx["_audit_log"]`` if the store does not implement
    audit persistence.  When ``audit_log_id`` is set we filter to
    matching ``session_id`` events for backwards compatibility.
    """
    p = msgspec.convert(params, AuditGetParams)
    graph = ctx["graph"]

    log_entries: list[dict[str, Any]] = []
    try:
        log_entries = list(await graph.list_audit())
    except (NotImplementedError, AttributeError):
        log_entries = list(_audit_log(ctx))

    if p.audit_log_id:
        filtered = [e for e in log_entries if e.get("session_id") == p.audit_log_id]
        if filtered:
            log_entries = filtered

    return {"audit_log_id": p.audit_log_id, "events": log_entries, "count": len(log_entries)}


__all__ = [
    "audit_get",
    "checkpoint",
    "dryrun",
    "lock",
    "rollback",
    "session_close",
    "session_open",
    "session_recover",
    "unlock",
]
