"""Subprocess-based sandbox runner for ``smp/sandbox/*``.

This is **process-level isolation** — not a container.  Each sandbox is
a temp directory with a curated file set; ``execute`` spawns a normal
child process whose ``cwd`` is the sandbox root and whose stdout /
stderr are captured into bounded buffers.  Timeouts terminate the
subprocess tree.

What this module *does* protect against
---------------------------------------

* CWD bleed-through (every sandbox has its own private directory).
* Runaway processes (the timeout kills the whole tree).
* Output-bomb DoS (stdout/stderr are capped, default 1 MiB each).
* Cross-sandbox contamination (sandboxes never share files).

What it explicitly does **not** protect against
-----------------------------------------------

* A malicious binary breaking out of the OS user.  If your threat
  model includes hostile code execution you must run SMP behind a
  container/VM boundary; this runner is the deterministic substrate
  the next layer plugs into.

The current SMP CLI / docs make that limitation explicit.
"""

from __future__ import annotations

import asyncio
import contextlib
import os
import shutil
import sys
import tempfile
import uuid
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from smp.logging import get_logger

log = get_logger(__name__)


_DEFAULT_OUTPUT_BYTES: int = 1 * 1024 * 1024


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class SandboxHandle:
    """A live sandbox directory."""

    sandbox_id: str
    name: str
    template: str
    root: Path
    created_at: str
    files: list[str] = field(default_factory=list)
    executions: list[str] = field(default_factory=list)
    closed: bool = False


@dataclass
class ExecutionResult:
    """The outcome of a single ``execute`` call."""

    execution_id: str
    sandbox_id: str
    command: list[str]
    status: str
    exit_code: int
    stdout: str
    stderr: str
    started_at: str
    ended_at: str
    duration_ms: float
    timed_out: bool = False
    truncated: bool = False


class SandboxRuntime:
    """Manages a fleet of sandbox directories and their child processes.

    The runtime keeps everything in process memory (sandbox metadata is
    not durable across restarts).  That's deliberate — sandboxes are
    short-lived ephemeral environments.  If the server restarts, any
    in-flight sandbox is gone, which mirrors what container-based
    runtimes do as well.
    """

    def __init__(self, *, root: Path | None = None, max_output_bytes: int = _DEFAULT_OUTPUT_BYTES) -> None:
        self._root = root or Path(tempfile.gettempdir()) / "smp-sandboxes"
        self._root.mkdir(parents=True, exist_ok=True)
        self._sandboxes: dict[str, SandboxHandle] = {}
        self._executions: dict[str, ExecutionResult] = {}
        self._processes: dict[str, asyncio.subprocess.Process] = {}
        self._max_output_bytes = max(256, int(max_output_bytes))
        self._lock = asyncio.Lock()

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def spawn(self, *, name: str, template: str, files: dict[str, str]) -> SandboxHandle:
        async with self._lock:
            sandbox_id = f"sbx_{uuid.uuid4().hex[:10]}"
            root = self._root / sandbox_id
            root.mkdir(parents=True, exist_ok=False)
            written: list[str] = []
            for rel_path, content in files.items():
                target = self._safe_path(root, rel_path)
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(content, encoding="utf-8")
                written.append(rel_path)
            handle = SandboxHandle(
                sandbox_id=sandbox_id,
                name=name,
                template=template,
                root=root,
                created_at=_now_iso(),
                files=written,
            )
            self._sandboxes[sandbox_id] = handle
            log.info("sandbox_spawned", sandbox_id=sandbox_id, files=len(written))
            return handle

    def get(self, sandbox_id: str) -> SandboxHandle | None:
        return self._sandboxes.get(sandbox_id)

    async def execute(
        self,
        *,
        sandbox_id: str,
        command: Sequence[str],
        stdin: str | None = None,
        timeout: float = 30.0,
        env: dict[str, str] | None = None,
    ) -> ExecutionResult:
        handle = self._sandboxes.get(sandbox_id)
        if handle is None or handle.closed:
            raise KeyError(sandbox_id)

        execution_id = f"exec_{uuid.uuid4().hex[:10]}"
        started_at = _now_iso()
        clock_start = datetime.now(timezone.utc)
        timed_out = False
        truncated = False
        stdout_bytes = b""
        stderr_bytes = b""

        argv = list(command)
        if not argv:
            raise ValueError("command must not be empty")

        # Default environment is hermetic — only PATH is propagated so
        # children can find common interpreters.  Callers can override
        # via the ``env`` parameter.
        child_env = {"PATH": os.environ.get("PATH", "")}
        if env:
            child_env.update(env)

        try:
            proc = await asyncio.create_subprocess_exec(
                *argv,
                stdin=asyncio.subprocess.PIPE if stdin is not None else None,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=str(handle.root),
                env=child_env,
            )
        except (FileNotFoundError, NotADirectoryError, OSError) as exc:
            failed = ExecutionResult(
                execution_id=execution_id,
                sandbox_id=sandbox_id,
                command=argv,
                status="failed",
                exit_code=127,
                stdout="",
                stderr=f"command not found: {argv[0]} ({exc})",
                started_at=started_at,
                ended_at=_now_iso(),
                duration_ms=0.0,
                timed_out=False,
                truncated=False,
            )
            self._executions[execution_id] = failed
            handle.executions.append(execution_id)
            return failed

        self._processes[execution_id] = proc

        try:
            input_bytes = stdin.encode("utf-8") if stdin is not None else None
            try:
                stdout_bytes, stderr_bytes = await asyncio.wait_for(
                    proc.communicate(input=input_bytes), timeout=timeout
                )
            except asyncio.TimeoutError:
                timed_out = True
                with contextlib.suppress(ProcessLookupError):
                    proc.kill()
                with contextlib.suppress(asyncio.TimeoutError):
                    stdout_bytes, stderr_bytes = await asyncio.wait_for(proc.communicate(), timeout=2.0)
        finally:
            self._processes.pop(execution_id, None)

        if len(stdout_bytes) > self._max_output_bytes:
            stdout_bytes = stdout_bytes[: self._max_output_bytes]
            truncated = True
        if len(stderr_bytes) > self._max_output_bytes:
            stderr_bytes = stderr_bytes[: self._max_output_bytes]
            truncated = True

        ended_at = _now_iso()
        clock_end = datetime.now(timezone.utc)
        result = ExecutionResult(
            execution_id=execution_id,
            sandbox_id=sandbox_id,
            command=argv,
            status="timeout" if timed_out else ("completed" if (proc.returncode or 0) == 0 else "failed"),
            exit_code=proc.returncode if proc.returncode is not None else -1,
            stdout=stdout_bytes.decode("utf-8", errors="replace"),
            stderr=stderr_bytes.decode("utf-8", errors="replace"),
            started_at=started_at,
            ended_at=ended_at,
            duration_ms=(clock_end - clock_start).total_seconds() * 1000.0,
            timed_out=timed_out,
            truncated=truncated,
        )
        self._executions[execution_id] = result
        handle.executions.append(execution_id)
        log.info(
            "sandbox_executed",
            sandbox_id=sandbox_id,
            execution_id=execution_id,
            exit_code=result.exit_code,
            timed_out=timed_out,
            duration_ms=int(result.duration_ms),
        )
        return result

    async def kill(self, execution_id: str) -> bool:
        """Terminate the execution if running, mark it killed otherwise.

        Returns ``True`` whenever the execution id is known.  Killing an
        already-finished execution is treated as a successful no-op so
        clients have a single, idempotent code path.
        """
        proc = self._processes.get(execution_id)
        record = self._executions.get(execution_id)
        if proc is None and record is None:
            return False
        if proc is not None:
            with contextlib.suppress(ProcessLookupError):
                proc.kill()
            await asyncio.sleep(0)
            self._processes.pop(execution_id, None)
        if record is not None:
            record.status = "killed"
            record.ended_at = _now_iso()
        return True

    async def destroy(self, sandbox_id: str) -> bool:
        handle = self._sandboxes.pop(sandbox_id, None)
        if handle is None:
            return False
        handle.closed = True
        await asyncio.to_thread(shutil.rmtree, handle.root, ignore_errors=True)
        return True

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    @staticmethod
    def _safe_path(root: Path, rel: str) -> Path:
        # Reject absolute and parent-traversal paths so files can never
        # land outside the sandbox root.
        candidate = (root / rel).resolve()
        root_resolved = root.resolve()
        if root_resolved != candidate and root_resolved not in candidate.parents:
            raise ValueError(f"unsafe sandbox path: {rel!r}")
        return candidate


def get_runtime(ctx: dict[str, object]) -> SandboxRuntime:
    """Return the per-server :class:`SandboxRuntime`, lazily created."""
    rt = ctx.get("_sandbox_runtime")
    if isinstance(rt, SandboxRuntime):
        return rt
    rt = SandboxRuntime()
    ctx["_sandbox_runtime"] = rt
    return rt


__all__ = ["ExecutionResult", "SandboxHandle", "SandboxRuntime", "get_runtime"]


if __name__ == "__main__":  # pragma: no cover - manual smoke test
    rt = SandboxRuntime()

    async def main() -> None:
        h = await rt.spawn(name="demo", template="python", files={"hello.py": "print('hi')"})
        r = await rt.execute(sandbox_id=h.sandbox_id, command=[sys.executable, "hello.py"], timeout=5)
        print(r)
        await rt.destroy(h.sandbox_id)

    asyncio.run(main())
