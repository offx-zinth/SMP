"""Sandbox handlers (``smp/sandbox/spawn``, ``/execute``, ``/kill``).

Backed by :class:`smp.runtime.sandbox.SandboxRuntime`, which spawns real
child processes inside a private working directory.  This is
process-level isolation, not container isolation — see the runtime
module for the explicit threat-model boundaries.

The previous in-memory stub remains as a fallback when the runtime
cannot be created (for example on systems without a usable temp dir),
so the wire shape is preserved.
"""

from __future__ import annotations

from typing import Any

import msgspec

from smp.core.models import SandboxExecuteParams, SandboxKillParams, SandboxSpawnParams
from smp.logging import get_logger
from smp.runtime.sandbox import SandboxRuntime, get_runtime

log = get_logger(__name__)


def _runtime(ctx: dict[str, Any]) -> SandboxRuntime:
    return get_runtime(ctx)


async def sandbox_spawn(params: dict[str, Any], ctx: dict[str, Any]) -> dict[str, Any]:
    """Handle ``smp/sandbox/spawn`` — create a private working dir."""
    p = msgspec.convert(params, SandboxSpawnParams)
    runtime = _runtime(ctx)

    handle = await runtime.spawn(name=p.name, template=p.template, files=dict(p.files))

    return {
        "sandbox_id": handle.sandbox_id,
        "status": "ready",
        "name": handle.name,
        "template": handle.template,
        "file_count": len(handle.files),
        "root": str(handle.root),
        "created_at": handle.created_at,
    }


async def sandbox_execute(params: dict[str, Any], ctx: dict[str, Any]) -> dict[str, Any]:
    """Handle ``smp/sandbox/execute`` — run a command and capture output."""
    p = msgspec.convert(params, SandboxExecuteParams)
    runtime = _runtime(ctx)

    if runtime.get(p.sandbox_id) is None:
        return {
            "execution_id": "",
            "sandbox_id": p.sandbox_id,
            "started": False,
            "error": "sandbox_not_found",
        }

    if not p.command:
        return {
            "execution_id": "",
            "sandbox_id": p.sandbox_id,
            "started": False,
            "error": "empty_command",
        }

    timeout = float(p.timeout or 30.0)
    try:
        result = await runtime.execute(
            sandbox_id=p.sandbox_id,
            command=list(p.command),
            stdin=p.stdin or None,
            timeout=timeout,
        )
    except KeyError:
        return {
            "execution_id": "",
            "sandbox_id": p.sandbox_id,
            "started": False,
            "error": "sandbox_not_found",
        }

    return {
        "execution_id": result.execution_id,
        "sandbox_id": p.sandbox_id,
        "started": True,
        "status": result.status,
        "exit_code": result.exit_code,
        "stdout": result.stdout,
        "stderr": result.stderr,
        "started_at": result.started_at,
        "ended_at": result.ended_at,
        "duration_ms": result.duration_ms,
        "timed_out": result.timed_out,
        "truncated": result.truncated,
    }


async def sandbox_kill(params: dict[str, Any], ctx: dict[str, Any]) -> dict[str, Any]:
    """Handle ``smp/sandbox/kill`` — terminate a running execution."""
    p = msgspec.convert(params, SandboxKillParams)
    runtime = _runtime(ctx)

    killed = await runtime.kill(p.execution_id)
    if not killed:
        return {"execution_id": p.execution_id, "killed": False, "error": "execution_not_found"}
    return {"execution_id": p.execution_id, "killed": True, "status": "killed"}


__all__ = ["sandbox_execute", "sandbox_kill", "sandbox_spawn"]
