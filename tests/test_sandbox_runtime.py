"""Phase 5 tests: real sandbox runtime backed by subprocess."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import pytest

from smp.runtime.sandbox import SandboxRuntime


@pytest.fixture()
def runtime(tmp_path: Path) -> SandboxRuntime:
    return SandboxRuntime(root=tmp_path)


class TestSandboxLifecycle:
    async def test_spawn_creates_isolated_dir(self, runtime: SandboxRuntime) -> None:
        handle = await runtime.spawn(name="t", template="python", files={"a.txt": "hello"})
        assert handle.root.exists()
        assert (handle.root / "a.txt").read_text() == "hello"

    async def test_spawn_two_sandboxes_have_separate_roots(self, runtime: SandboxRuntime) -> None:
        a = await runtime.spawn(name="a", template="python", files={})
        b = await runtime.spawn(name="b", template="python", files={})
        assert a.root != b.root
        assert a.sandbox_id != b.sandbox_id

    async def test_spawn_rejects_path_traversal(self, runtime: SandboxRuntime) -> None:
        with pytest.raises(ValueError, match="unsafe sandbox path"):
            await runtime.spawn(name="t", template="python", files={"../escape.txt": "no"})

    async def test_destroy_removes_directory(self, runtime: SandboxRuntime) -> None:
        handle = await runtime.spawn(name="t", template="python", files={"x.txt": "y"})
        root = handle.root
        assert await runtime.destroy(handle.sandbox_id) is True
        assert not root.exists()
        assert runtime.get(handle.sandbox_id) is None


class TestSandboxExecute:
    async def test_executes_python_and_captures_stdout(self, runtime: SandboxRuntime) -> None:
        handle = await runtime.spawn(
            name="t",
            template="python",
            files={"hello.py": "import sys; print('hello'); sys.exit(0)"},
        )
        result = await runtime.execute(
            sandbox_id=handle.sandbox_id, command=[sys.executable, "hello.py"], timeout=10
        )
        assert result.status == "completed"
        assert result.exit_code == 0
        assert "hello" in result.stdout
        assert result.stderr == ""

    async def test_failing_exit_code_marks_failed(self, runtime: SandboxRuntime) -> None:
        handle = await runtime.spawn(
            name="t", template="python", files={"die.py": "import sys; sys.exit(7)"}
        )
        result = await runtime.execute(
            sandbox_id=handle.sandbox_id, command=[sys.executable, "die.py"], timeout=10
        )
        assert result.status == "failed"
        assert result.exit_code == 7

    async def test_stdin_is_piped(self, runtime: SandboxRuntime) -> None:
        handle = await runtime.spawn(
            name="t",
            template="python",
            files={"echo.py": "import sys; sys.stdout.write(sys.stdin.read().upper())"},
        )
        result = await runtime.execute(
            sandbox_id=handle.sandbox_id,
            command=[sys.executable, "echo.py"],
            stdin="ping",
            timeout=10,
        )
        assert "PING" in result.stdout

    async def test_timeout_terminates_process(self, runtime: SandboxRuntime) -> None:
        handle = await runtime.spawn(
            name="t",
            template="python",
            files={"loop.py": "import time\nwhile True: time.sleep(0.05)"},
        )
        result = await runtime.execute(
            sandbox_id=handle.sandbox_id, command=[sys.executable, "loop.py"], timeout=1.0
        )
        assert result.timed_out is True
        assert result.status == "timeout"

    async def test_unknown_command_returns_failed(self, runtime: SandboxRuntime) -> None:
        handle = await runtime.spawn(name="t", template="python", files={})
        result = await runtime.execute(
            sandbox_id=handle.sandbox_id,
            command=["definitely-not-a-real-program-xyz"],
            timeout=5,
        )
        assert result.status == "failed"
        assert result.exit_code == 127

    async def test_output_truncation(self, tmp_path: Path) -> None:
        runtime = SandboxRuntime(root=tmp_path, max_output_bytes=1024)
        handle = await runtime.spawn(
            name="t",
            template="python",
            files={"big.py": "print('A' * 10000)"},
        )
        result = await runtime.execute(
            sandbox_id=handle.sandbox_id, command=[sys.executable, "big.py"], timeout=10
        )
        assert result.truncated is True
        assert len(result.stdout) <= 1024

    async def test_cwd_isolation(self, runtime: SandboxRuntime) -> None:
        a = await runtime.spawn(name="a", template="python", files={"only_a.txt": "secret-a"})
        b = await runtime.spawn(name="b", template="python", files={"only_b.txt": "secret-b"})
        # b cannot see a's files
        result = await runtime.execute(
            sandbox_id=b.sandbox_id,
            command=[sys.executable, "-c", "import os; print(sorted(os.listdir('.')))"],
            timeout=5,
        )
        assert "only_a.txt" not in result.stdout
        assert "only_b.txt" in result.stdout


class TestSandboxKill:
    async def test_kill_unknown_returns_false(self, runtime: SandboxRuntime) -> None:
        assert await runtime.kill("nope") is False

    async def test_kill_is_idempotent(self, runtime: SandboxRuntime) -> None:
        handle = await runtime.spawn(
            name="t", template="python", files={"q.py": "print('quick')"}
        )
        result = await runtime.execute(
            sandbox_id=handle.sandbox_id, command=[sys.executable, "q.py"], timeout=5
        )
        assert await runtime.kill(result.execution_id) is True
        # Killing again is still a successful no-op
        assert await runtime.kill(result.execution_id) is True


class TestProtocolHandlers:
    async def test_full_handler_pipeline(self, tmp_path: Path) -> None:
        from smp.protocol.handlers import sandbox as sandbox_handlers

        ctx: dict[str, object] = {"_sandbox_runtime": SandboxRuntime(root=tmp_path)}
        spawned = await sandbox_handlers.sandbox_spawn(
            {"name": "t", "files": {"main.py": "print('done')"}}, ctx
        )
        assert spawned["sandbox_id"].startswith("sbx_")
        assert spawned["file_count"] == 1

        executed = await sandbox_handlers.sandbox_execute(
            {
                "sandbox_id": spawned["sandbox_id"],
                "command": [sys.executable, "main.py"],
                "timeout": 5,
            },
            ctx,
        )
        assert executed["started"] is True
        assert "done" in executed["stdout"]
        assert executed["exit_code"] == 0

        killed = await sandbox_handlers.sandbox_kill(
            {"execution_id": executed["execution_id"]}, ctx
        )
        assert killed["killed"] is True

    async def test_empty_command_rejected(self, tmp_path: Path) -> None:
        from smp.protocol.handlers import sandbox as sandbox_handlers

        ctx: dict[str, object] = {"_sandbox_runtime": SandboxRuntime(root=tmp_path)}
        spawned = await sandbox_handlers.sandbox_spawn({"name": "t"}, ctx)
        result = await sandbox_handlers.sandbox_execute(
            {"sandbox_id": spawned["sandbox_id"], "command": []}, ctx
        )
        assert result["started"] is False
        assert result["error"] == "empty_command"
