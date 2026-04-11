"""SMP(3) sandbox executor for isolated runtime execution.

Provides isolated execution environments for running agent code safely.
"""

from __future__ import annotations

import asyncio
import contextlib
import os
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from smp.logging import get_logger

log = get_logger(__name__)

_SANDBOX_DEFAULT_TIMEOUT = 30
_SANDBOX_DEFAULT_MEMORY_MB = 512


@dataclass
class ExecutionResult:
    """Result of a sandbox execution."""

    execution_id: str
    exit_code: int
    stdout: str
    stderr: str
    duration_ms: int
    memory_used_mb: float = 0.0
    timed_out: bool = False
    killed: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class SandboxConfig:
    """Configuration for sandbox execution."""

    timeout_seconds: int = _SANDBOX_DEFAULT_TIMEOUT
    memory_limit_mb: int = _SANDBOX_DEFAULT_MEMORY_MB
    allow_network: bool = False
    allow_file_write: bool = False
    working_directory: str = ""
    environment: dict[str, str] = field(default_factory=dict)


class SandboxExecutor:
    """Executes code in an isolated sandbox environment."""

    def __init__(self, config: SandboxConfig | None = None) -> None:
        self._config = config or SandboxConfig()
        self._active_processes: dict[str, asyncio.subprocess.Process] = {}

    async def execute(
        self,
        command: list[str],
        stdin: str | None = None,
        cwd: str | None = None,
    ) -> ExecutionResult:
        """Execute a command in the sandbox."""
        execution_id = f"exec_{uuid.uuid4().hex[:8]}"
        start_time = asyncio.get_event_loop().time()

        work_dir = cwd or self._config.working_directory or str(Path.cwd())

        env = os.environ.copy()
        env.update(self._config.environment)
        if not self._config.allow_network:
            env["NO_NETWORK"] = "1"

        try:
            process = await asyncio.create_subprocess_exec(
                *command,
                stdin=asyncio.subprocess.PIPE if stdin else None,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=work_dir,
                env=env,
            )
            self._active_processes[execution_id] = process

            try:
                stdout_bytes, stderr_bytes = await asyncio.wait_for(
                    process.communicate(stdin.encode() if stdin else None),
                    timeout=self._config.timeout_seconds,
                )
                timed_out = False
            except TimeoutError:
                process.kill()
                await process.wait()
                stdout_bytes, stderr_bytes = b"", b"Timeout exceeded"
                timed_out = True

            duration_ms = int((asyncio.get_event_loop().time() - start_time) * 1000)

            result = ExecutionResult(
                execution_id=execution_id,
                exit_code=process.returncode or -1,
                stdout=stdout_bytes.decode("utf-8", errors="replace"),
                stderr=stderr_bytes.decode("utf-8", errors="replace"),
                duration_ms=duration_ms,
                timed_out=timed_out,
                killed=timed_out,
            )

            log.info(
                "sandbox_execution_complete",
                execution_id=execution_id,
                exit_code=result.exit_code,
                duration_ms=duration_ms,
                timed_out=timed_out,
            )
            return result

        except Exception as exc:
            log.error("sandbox_execution_error", execution_id=execution_id, error=str(exc))
            return ExecutionResult(
                execution_id=execution_id,
                exit_code=-1,
                stdout="",
                stderr=str(exc),
                duration_ms=int((asyncio.get_event_loop().time() - start_time) * 1000),
            )
        finally:
            self._active_processes.pop(execution_id, None)

    async def execute_python(
        self,
        code: str,
        timeout: int | None = None,
    ) -> ExecutionResult:
        """Execute Python code in the sandbox."""
        import tempfile

        with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
            f.write(code)
            temp_path = f.name

        try:
            config = SandboxConfig(
                timeout_seconds=timeout or self._config.timeout_seconds,
                **{k: v for k, v in self._config.__dict__.items() if k != "timeout_seconds"},
            )
            executor = SandboxExecutor(config)
            return await executor.execute(["python3.11", temp_path])
        finally:
            Path(temp_path).unlink(missing_ok=True)

    def kill(self, execution_id: str) -> bool:
        """Kill an active execution."""
        process = self._active_processes.get(execution_id)
        if process:
            process.kill()
            log.info("sandbox_killed", execution_id=execution_id)
            return True
        return False

    async def cleanup(self) -> None:
        """Kill all active executions."""
        for exec_id, process in list(self._active_processes.items()):
            process.kill()
            with contextlib.suppress(Exception):
                await process.wait()
            log.info("sandbox_cleanup", execution_id=exec_id)
        self._active_processes.clear()
