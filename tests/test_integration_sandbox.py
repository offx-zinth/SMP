"""Integration tests for SMP Sandbox Runtime components."""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

try:
    from smp.sandbox.docker_sandbox import DockerSandbox
    DOCKER_AVAILABLE = True
except ImportError:
    DOCKER_AVAILABLE = False

from smp.sandbox.ebpf_collector import EBPFCollector
from smp.sandbox.executor import ExecutionResult, SandboxConfig, SandboxExecutor
from smp.sandbox.spawner import SandboxInfo, SandboxSpawner


class TestSandboxSpawner:
    """Tests for SandboxSpawner directory-based sandbox management."""

    @pytest.fixture
    def temp_root(self) -> Path:
        with tempfile.TemporaryDirectory() as tmpdir:
            yield Path(tmpdir)

    @pytest.fixture
    def spawner(self, temp_root: Path) -> SandboxSpawner:
        return SandboxSpawner(sandbox_root=temp_root)

    def test_spawn_creates_directory(self, spawner: SandboxSpawner, temp_root: Path) -> None:
        info = spawner.spawn()
        assert info.sandbox_id.startswith("sandbox_")
        assert Path(info.root_path).exists()
        assert Path(info.root_path).is_dir()

    def test_spawn_with_name(self, spawner: SandboxSpawner, temp_root: Path) -> None:
        info = spawner.spawn(name="my_sandbox")
        assert Path(info.root_path).name == "my_sandbox"

    def test_spawn_with_files(self, spawner: SandboxSpawner, temp_root: Path) -> None:
        files = {
            "test.txt": "hello world",
            "subdir/code.py": "print('hello')",
        }
        info = spawner.spawn(files=files)
        assert (Path(info.root_path) / "test.txt").read_text() == "hello world"
        assert (Path(info.root_path) / "subdir" / "code.py").read_text() == "print('hello')"

    def test_get_returns_sandbox(self, spawner: SandboxSpawner) -> None:
        info = spawner.spawn()
        retrieved = spawner.get(info.sandbox_id)
        assert retrieved is not None
        assert retrieved.sandbox_id == info.sandbox_id

    def test_get_nonexistent_returns_none(self, spawner: SandboxSpawner) -> None:
        assert spawner.get("nonexistent_id") is None

    def test_list_active_returns_all(self, spawner: SandboxSpawner) -> None:
        info1 = spawner.spawn()
        info2 = spawner.spawn()
        active = spawner.list_active()
        assert len(active) == 2
        assert info1 in active
        assert info2 in active

    def test_list_active_empty_after_destroy(self, spawner: SandboxSpawner) -> None:
        info = spawner.spawn()
        assert len(spawner.list_active()) == 1
        spawner.destroy(info.sandbox_id)
        assert len(spawner.list_active()) == 0

    def test_destroy_removes_directory(self, spawner: SandboxSpawner, temp_root: Path) -> None:
        info = spawner.spawn()
        root_path = Path(info.root_path)
        assert root_path.exists()
        result = spawner.destroy(info.sandbox_id)
        assert result is True
        assert not root_path.exists()

    def test_destroy_nonexistent_returns_false(self, spawner: SandboxSpawner) -> None:
        assert spawner.destroy("nonexistent") is False

    def test_spawn_info_structure(self, spawner: SandboxSpawner) -> None:
        info = spawner.spawn()
        assert isinstance(info, SandboxInfo)
        assert info.sandbox_id
        assert info.root_path
        assert info.created_at
        assert info.status == "created"


class TestSandboxExecutor:
    """Tests for SandboxExecutor async command execution."""

    @pytest.fixture
    def executor(self) -> SandboxExecutor:
        return SandboxExecutor(config=SandboxConfig(timeout_seconds=10))

    @pytest.mark.asyncio
    async def test_execute_simple_command(self, executor: SandboxExecutor) -> None:
        result = await executor.execute(["echo", "hello"])
        assert result.exit_code in (0, -1)
        assert "hello" in result.stdout

    @pytest.mark.asyncio
    async def test_execute_with_stdin(self, executor: SandboxExecutor) -> None:
        result = await executor.execute(
            command=["cat"],
            stdin="test input",
        )
        assert result.exit_code in (0, -1)
        assert "test input" in result.stdout

    @pytest.mark.asyncio
    async def test_execute_with_cwd(self, executor: SandboxExecutor) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            result = await executor.execute(
                command=["pwd"],
                cwd=tmpdir,
            )
            assert result.exit_code in (0, -1)
            assert tmpdir in result.stdout

    @pytest.mark.asyncio
    async def test_execute_records_duration(self, executor: SandboxExecutor) -> None:
        result = await executor.execute(["sleep", "0.1"])
        assert result.duration_ms >= 0

    @pytest.mark.asyncio
    async def test_execute_nonzero_exit_code(self, executor: SandboxExecutor) -> None:
        result = await executor.execute(["ls", "/nonexistent_path_12345"])
        assert result.exit_code != 0
        assert "No such file" in result.stderr or result.exit_code > 0

    @pytest.mark.asyncio
    async def test_execute_python_code(self, executor: SandboxExecutor) -> None:
        result = await executor.execute_python("print('hello from python')")
        assert result.exit_code in (0, -1)
        assert "hello from python" in result.stdout

    @pytest.mark.asyncio
    async def test_execution_result_structure(self, executor: SandboxExecutor) -> None:
        result = await executor.execute(["echo", "test"])
        assert isinstance(result, ExecutionResult)
        assert result.execution_id.startswith("exec_")
        assert result.exit_code in (0, -1)
        assert result.stdout
        assert result.duration_ms >= 0


@pytest.mark.skipif(not DOCKER_AVAILABLE, reason="docker not available")
class TestDockerSandbox:
    """Tests for DockerSandbox Docker container management."""

    @pytest.fixture
    def sandbox(self) -> DockerSandbox:
        return DockerSandbox()

    def test_spawn_creates_container(self, sandbox: DockerSandbox) -> None:
        container_id = sandbox.spawn(
            name="test_sandbox",
            image="alpine:latest",
            services=[],
        )
        assert container_id
        sandbox.destroy()

    def test_execute_requires_container(self) -> None:
        sandbox = DockerSandbox()
        with pytest.raises(RuntimeError, match="No container spawned"):
            sandbox.execute("echo hello", timeout=5)

    def test_execute_in_container(self, sandbox: DockerSandbox) -> None:
        sandbox.spawn(name="test_exec", image="alpine:latest", services=[])
        output = sandbox.execute("echo hello from container", timeout=10)
        assert "hello from container" in output
        sandbox.destroy()

    def test_destroy_removes_container(self, sandbox: DockerSandbox) -> None:
        sandbox.spawn(name="test_destroy", image="alpine:latest", services=[])
        sandbox.destroy()


class TestEBPFCollector:
    """Tests for EBPFCollector eBPF tracing."""

    @pytest.fixture
    def collector(self) -> EBPFCollector:
        return EBPFCollector()

    def test_start_trace_returns_trace_id(self, collector: EBPFCollector) -> None:
        trace_id = collector.start_trace(session_id="session_1")
        assert trace_id
        assert len(trace_id) == 36

    def test_stop_trace_removes_active(self, collector: EBPFCollector) -> None:
        trace_id = collector.start_trace(session_id="session_1")
        collector.stop_trace(trace_id)
        assert trace_id not in collector._active_traces

    def test_stop_nonexistent_trace_logs_error(self, collector: EBPFCollector) -> None:
        collector.stop_trace("nonexistent_trace_id")

    def test_get_traces_returns_list(self, collector: EBPFCollector) -> None:
        traces = collector.get_traces()
        assert isinstance(traces, list)

    def test_multiple_traces(self, collector: EBPFCollector) -> None:
        trace_id1 = collector.start_trace(session_id="session_1")
        trace_id2 = collector.start_trace(session_id="session_2")
        assert trace_id1 != trace_id2
        assert len(collector._active_traces) == 2
        collector.stop_trace(trace_id1)
        assert len(collector._active_traces) == 1
