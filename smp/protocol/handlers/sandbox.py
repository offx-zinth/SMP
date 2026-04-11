"""Handler for sandbox methods (smp/sandbox/spawn, etc.)."""

from __future__ import annotations

from typing import Any

import msgspec

from smp.logging import get_logger
from smp.protocol.handlers.base import MethodHandler
from smp.sandbox.executor import SandboxExecutor
from smp.sandbox.spawner import SandboxSpawner

log = get_logger(__name__)


class SandboxSpawnHandler(MethodHandler):
    """Handles smp/sandbox/spawn method."""

    @property
    def method(self) -> str:
        return "smp/sandbox/spawn"

    async def handle(
        self,
        params: dict[str, Any],
        context: dict[str, Any],
    ) -> dict[str, Any]:
        # In a real implementation, these would come from context/session
        # For now, we'll use defaults and extract from params if provided
        sp = msgspec.convert(params, dict)  # Use raw params since no model exists yet
        
        spawner = SandboxSpawner()
        
        sandbox_info = spawner.spawn(
            name=sp.get("name"),
            template=sp.get("template"),
            files=sp.get("files")
        )
        
        return {
            "sandbox_id": sandbox_info.sandbox_id,
            "root_path": sandbox_info.root_path,
            "created_at": sandbox_info.created_at,
            "status": sandbox_info.status,
        }


class SandboxExecuteHandler(MethodHandler):
    """Handles smp/sandbox/execute method."""

    @property
    def method(self) -> str:
        return "smp/sandbox/execute"

    async def handle(
        self,
        params: dict[str, Any],
        context: dict[str, Any],
    ) -> dict[str, Any]:
        sep = msgspec.convert(params, dict)  # Use raw params
        
        # Create executor with default config
        executor = SandboxExecutor()
        
        # Execute the command
        result = await executor.execute(
            command=sep.get("command", []),
            stdin=sep.get("stdin"),
            cwd=sep.get("working_directory")
        )
        
        return {
            "execution_id": result.execution_id,
            "exit_code": result.exit_code,
            "stdout": result.stdout,
            "stderr": result.stderr,
            "duration_ms": result.duration_ms,
            "memory_used_mb": result.memory_used_mb,
            "timed_out": result.timed_out,
            "killed": result.killed,
            "metadata": result.metadata,
        }


class SandboxDestroyHandler(MethodHandler):
    """Handles smp/sandbox/destroy method."""

    @property
    def method(self) -> str:
        return "smp/sandbox/destroy"

    async def handle(
        self,
        params: dict[str, Any],
        context: dict[str, Any],
    ) -> dict[str, Any]:
        sdp = msgspec.convert(params, dict)  # Use raw params
        
        spawner = SandboxSpawner()
        sandbox_id = sdp.get("sandbox_id")
        
        if not sandbox_id:
            return {"error": "sandbox_id is required"}
        
        destroyed = spawner.destroy(sandbox_id)
        
        if destroyed:
            return {
                "sandbox_id": sandbox_id,
                "status": "destroyed",
                "destroyed_at": msgspec.time.format_time(msgspec.time.now(), "%Y-%m-%dT%H:%M:%SZ"),
            }
        else:
            return {"error": f"Sandbox not found: {sandbox_id}"}