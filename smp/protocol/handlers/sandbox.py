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

import os
from typing import Any

import msgspec

from smp.core.models import SandboxExecuteParams, SandboxKillParams, SandboxSpawnParams
from smp.logging import get_logger
from smp.runtime.sandbox import SandboxRuntime, get_runtime

log = get_logger(__name__)


def _is_command_allowed(command: list[str]) -> bool:
    """Check if the command is in the allowlist defined by SMP_SANDBOX_ALLOWED_COMMANDS."""
    allowed_env = os.environ.get("SMP_SANDBOX_ALLOWED_COMMANDS")
    if not allowed_env:
        return True  # Default to allow all if not configured

    allowed_cmds = [c.strip() for c in allowed_env.split(",") if c.strip()]
    if not command:
        return False

    # Check if the base command (first element) is allowed
    return command[0] in allowed_cmds


def _runtime(ctx: dict[str, Any]) -> SandboxRuntime:
    return get_runtime(ctx)


async def sandbox_spawn(params: dict[str, Any], ctx: dict[str, Any]) -> dict[str, Any]:
    """Handle ``smp/sandbox/spawn`` — create a private working dir."""
    p = msgspec.convert(params, SandboxSpawnParams)
    runtime = _runtime(ctx)

    handle = await runtime.spawn(
        name=p.name or "",
        template=p.template or "",
        files=dict(p.files),
    )

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

    if not _is_command_allowed(list(p.command)):
        log.warning("sandbox_execute_command_forbidden", command=p.command)
        return {
            "execution_id": "",
            "sandbox_id": p.sandbox_id,
            "started": False,
            "error": "command_forbidden",
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
