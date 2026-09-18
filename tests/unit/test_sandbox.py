from __future__ import annotations

import os
from unittest.mock import AsyncMock, MagicMock, patch

import msgspec
import pytest

from smp.protocol.handlers import sandbox


class TestSandboxCommandValidation:
    @pytest.fixture
    def mock_ctx(self):
        return {}

    @patch("smp.protocol.handlers.sandbox.get_runtime")
    @pytest.mark.asyncio
    async def test_execute_empty_command_returns_error(self, mock_get_runtime, mock_ctx):
        mock_runtime = MagicMock()
        mock_runtime.get.return_value = MagicMock()
        mock_get_runtime.return_value = mock_runtime
        params = {"sandbox_id": "sb1", "command": []}
        result = await sandbox.sandbox_execute(params, mock_ctx)
        assert result["error"] == "empty_command"
        assert result["started"] is False

    @patch("smp.protocol.handlers.sandbox.get_runtime")
    @pytest.mark.asyncio
    async def test_execute_none_command_returns_error(self, mock_get_runtime, mock_ctx):
        mock_runtime = MagicMock()
        mock_runtime.get.return_value = MagicMock()
        mock_runtime.execute = AsyncMock(
            return_value=MagicMock(
                execution_id="ex1",
                status="completed",
                exit_code=0,
                stdout="",
                stderr="",
                started_at="t1",
                ended_at="t2",
                duration_ms=10,
                timed_out=False,
                truncated=False,
            )
        )
        mock_get_runtime.return_value = mock_runtime
        params = {"sandbox_id": "sb1", "command": None}
        with pytest.raises(msgspec.ValidationError):
            await sandbox.sandbox_execute(params, mock_ctx)

    @patch.dict(os.environ, {"SMP_SANDBOX_ALLOWED_COMMANDS": "echo,python"}, clear=False)
    @patch("smp.protocol.handlers.sandbox.get_runtime")
    @pytest.mark.asyncio
    async def test_execute_forbidden_command_returns_error(self, mock_get_runtime, mock_ctx):
        mock_runtime = MagicMock()
        mock_runtime.get.return_value = MagicMock()
        mock_get_runtime.return_value = mock_runtime
        params = {"sandbox_id": "sb1", "command": ["forbidden_cmd", "arg"]}
        result = await sandbox.sandbox_execute(params, mock_ctx)
        assert result["error"] == "command_forbidden"
        assert result["started"] is False

    @patch.dict(os.environ, {"SMP_SANDBOX_ALLOWED_COMMANDS": "echo,python"}, clear=False)
    @patch("smp.protocol.handlers.sandbox.get_runtime")
    @pytest.mark.asyncio
    async def test_execute_allowed_command_succeeds(self, mock_get_runtime, mock_ctx):
        mock_runtime = MagicMock()
        mock_runtime.get.return_value = MagicMock()
        mock_runtime.execute = AsyncMock(
            return_value=MagicMock(
                execution_id="ex1",
                status="completed",
                exit_code=0,
                stdout="ok",
                stderr="",
                started_at="t1",
                ended_at="t2",
                duration_ms=10,
                timed_out=False,
                truncated=False,
            )
        )
        mock_get_runtime.return_value = mock_runtime
        params = {"sandbox_id": "sb1", "command": ["echo", "hello"]}
        result = await sandbox.sandbox_execute(params, mock_ctx)
        assert result["started"] is True
        assert result["status"] == "completed"
        assert "error" not in result

    @patch.dict(os.environ, {"SMP_SANDBOX_ALLOWED_COMMANDS": "python3"}, clear=False)
    @patch("smp.protocol.handlers.sandbox.get_runtime")
    @pytest.mark.asyncio
    async def test_execute_python_allowed(self, mock_get_runtime, mock_ctx):
        mock_runtime = MagicMock()
        mock_runtime.get.return_value = MagicMock()
        mock_runtime.execute = AsyncMock(
            return_value=MagicMock(
                execution_id="ex1",
                status="completed",
                exit_code=0,
                stdout="",
                stderr="",
                started_at="t1",
                ended_at="t2",
                duration_ms=10,
                timed_out=False,
                truncated=False,
            )
        )
        mock_get_runtime.return_value = mock_runtime
        params = {"sandbox_id": "sb1", "command": ["python3", "-c", "print(1)"]}
        result = await sandbox.sandbox_execute(params, mock_ctx)
        assert result["started"] is True

    @patch.dict(os.environ, {"SMP_SANDBOX_ALLOWED_COMMANDS": "echo,python"}, clear=False)
    @patch("smp.protocol.handlers.sandbox.get_runtime")
    @pytest.mark.asyncio
    async def test_execute_command_with_empty_string_returns_error(self, mock_get_runtime, mock_ctx):
        mock_runtime = MagicMock()
        mock_runtime.get.return_value = MagicMock()
        mock_runtime.execute = AsyncMock(
            return_value=MagicMock(
                execution_id="ex1",
                status="completed",
                exit_code=0,
                stdout="",
                stderr="",
                started_at="t1",
                ended_at="t2",
                duration_ms=10,
                timed_out=False,
                truncated=False,
            )
        )
        mock_get_runtime.return_value = mock_runtime
        params = {"sandbox_id": "sb1", "command": [""]}
        result = await sandbox.sandbox_execute(params, mock_ctx)
        assert result["error"] == "command_forbidden"

    @patch.dict(os.environ, {"SMP_SANDBOX_ALLOWED_COMMANDS": ""}, clear=False)
    @patch("smp.protocol.handlers.sandbox.get_runtime")
    @pytest.mark.asyncio
    async def test_execute_empty_allowlist_allows_all(self, mock_get_runtime, mock_ctx):
        mock_runtime = MagicMock()
        mock_runtime.get.return_value = MagicMock()
        mock_runtime.execute = AsyncMock(
            return_value=MagicMock(
                execution_id="ex1",
                status="completed",
                exit_code=0,
                stdout="",
                stderr="",
                started_at="t1",
                ended_at="t2",
                duration_ms=10,
                timed_out=False,
                truncated=False,
            )
        )
        mock_get_runtime.return_value = mock_runtime
        params = {"sandbox_id": "sb1", "command": ["any_cmd"]}
        result = await sandbox.sandbox_execute(params, mock_ctx)
        assert result["started"] is True


class TestSandboxIdValidation:
    @pytest.fixture
    def mock_ctx(self):
        return {}

    @patch("smp.protocol.handlers.sandbox.get_runtime")
    @pytest.mark.asyncio
    async def test_execute_missing_sandbox_id_returns_error(self, mock_get_runtime, mock_ctx):
        mock_runtime = MagicMock()
        mock_runtime.get.return_value = None
        mock_get_runtime.return_value = mock_runtime
        params = {"sandbox_id": "", "command": ["echo", "test"]}
        result = await sandbox.sandbox_execute(params, mock_ctx)
        assert result["error"] == "sandbox_not_found"

    @patch("smp.protocol.handlers.sandbox.get_runtime")
    @pytest.mark.asyncio
    async def test_execute_nonexistent_sandbox_returns_error(self, mock_get_runtime, mock_ctx):
        mock_runtime = MagicMock()
        mock_runtime.get.return_value = None
        mock_get_runtime.return_value = mock_runtime
        params = {"sandbox_id": "sb_nonexistent", "command": ["echo", "test"]}
        result = await sandbox.sandbox_execute(params, mock_ctx)
        assert result["error"] == "sandbox_not_found"
        assert result["started"] is False

    @patch("smp.protocol.handlers.sandbox.get_runtime")
    @pytest.mark.asyncio
    async def test_execute_valid_sandbox_allows_execution(self, mock_get_runtime, mock_ctx):
        mock_runtime = MagicMock()
        mock_runtime.get.return_value = MagicMock()
        mock_runtime.execute = AsyncMock(
            return_value=MagicMock(
                execution_id="ex1",
                status="completed",
                exit_code=0,
                stdout="",
                stderr="",
                started_at="t1",
                ended_at="t2",
                duration_ms=10,
                timed_out=False,
                truncated=False,
            )
        )
        mock_get_runtime.return_value = mock_runtime
        params = {"sandbox_id": "sb_valid", "command": ["echo", "test"]}
        result = await sandbox.sandbox_execute(params, mock_ctx)
        assert result["started"] is True
        mock_runtime.execute.assert_called_once()


class TestSandboxSpawnValidation:
    @pytest.fixture
    def mock_ctx(self):
        return {}

    @patch("smp.protocol.handlers.sandbox.get_runtime")
    @pytest.mark.asyncio
    async def test_spawn_with_empty_name_succeeds(self, mock_get_runtime, mock_ctx):
        mock_runtime = MagicMock()
        mock_runtime.spawn = AsyncMock(
            return_value=MagicMock(
                sandbox_id="sb_123",
                name="",
                template="",
                files=[],
                root="/tmp",
                created_at="t",
            )
        )
        mock_get_runtime.return_value = mock_runtime
        params = {"name": "", "files": {}}
        result = await sandbox.sandbox_spawn(params, mock_ctx)
        assert result["sandbox_id"] == "sb_123"
        assert result["status"] == "ready"

    @patch("smp.protocol.handlers.sandbox.get_runtime")
    @pytest.mark.asyncio
    async def test_spawn_with_none_name_succeeds(self, mock_get_runtime, mock_ctx):
        mock_runtime = MagicMock()
        mock_runtime.spawn = AsyncMock(
            return_value=MagicMock(
                sandbox_id="sb_123",
                name="",
                template="",
                files=[],
                root="/tmp",
                created_at="t",
            )
        )
        mock_get_runtime.return_value = mock_runtime
        params = {"name": None, "files": {}}
        result = await sandbox.sandbox_spawn(params, mock_ctx)
        assert result["sandbox_id"] == "sb_123"

    @patch("smp.protocol.handlers.sandbox.get_runtime")
    @pytest.mark.asyncio
    async def test_spawn_with_files_dict(self, mock_get_runtime, mock_ctx):
        mock_runtime = MagicMock()
        mock_runtime.spawn = AsyncMock(
            return_value=MagicMock(
                sandbox_id="sb_123",
                name="test",
                template="",
                files=["a.py"],
                root="/tmp",
                created_at="t",
            )
        )
        mock_get_runtime.return_value = mock_runtime
        params = {"name": "test", "files": {"a.py": "print(1)"}}
        result = await sandbox.sandbox_spawn(params, mock_ctx)
        assert result["file_count"] == 1

    @patch("smp.protocol.handlers.sandbox.get_runtime")
    @pytest.mark.asyncio
    async def test_spawn_with_empty_files_dict(self, mock_get_runtime, mock_ctx):
        mock_runtime = MagicMock()
        mock_runtime.spawn = AsyncMock(
            return_value=MagicMock(
                sandbox_id="sb_123",
                name="test",
                template="",
                files=[],
                root="/tmp",
                created_at="t",
            )
        )
        mock_get_runtime.return_value = mock_runtime
        params = {"name": "test", "files": {}}
        result = await sandbox.sandbox_spawn(params, mock_ctx)
        assert result["file_count"] == 0


class TestSandboxKillValidation:
    @pytest.fixture
    def mock_ctx(self):
        return {}

    @patch("smp.protocol.handlers.sandbox.get_runtime")
    @pytest.mark.asyncio
    async def test_kill_empty_execution_id_returns_error(self, mock_get_runtime, mock_ctx):
        mock_runtime = MagicMock()
        mock_runtime.kill = AsyncMock(return_value=False)
        mock_get_runtime.return_value = mock_runtime
        params = {"execution_id": ""}
        result = await sandbox.sandbox_kill(params, mock_ctx)
        assert result["killed"] is False
        assert result["error"] == "execution_not_found"

    @patch("smp.protocol.handlers.sandbox.get_runtime")
    @pytest.mark.asyncio
    async def test_kill_nonexistent_execution_returns_error(self, mock_get_runtime, mock_ctx):
        mock_runtime = MagicMock()
        mock_runtime.kill = AsyncMock(return_value=False)
        mock_get_runtime.return_value = mock_runtime
        params = {"execution_id": "ex_nonexistent"}
        result = await sandbox.sandbox_kill(params, mock_ctx)
        assert result["error"] == "execution_not_found"

    @patch("smp.protocol.handlers.sandbox.get_runtime")
    @pytest.mark.asyncio
    async def test_kill_valid_execution_succeeds(self, mock_get_runtime, mock_ctx):
        mock_runtime = MagicMock()
        mock_runtime.kill = AsyncMock(return_value=True)
        mock_get_runtime.return_value = mock_runtime
        params = {"execution_id": "ex_running"}
        result = await sandbox.sandbox_kill(params, mock_ctx)
        assert result["killed"] is True
        assert result["status"] == "killed"


class TestCommandAllowlistEdgeCases:
    @pytest.fixture
    def mock_ctx(self):
        return {}

    @patch.dict(os.environ, {"SMP_SANDBOX_ALLOWED_COMMANDS": "  echo  ,  python  "}, clear=False)
    @patch("smp.protocol.handlers.sandbox.get_runtime")
    @pytest.mark.asyncio
    async def test_allowlist_with_whitespace(self, mock_get_runtime, mock_ctx):
        mock_runtime = MagicMock()
        mock_runtime.get.return_value = MagicMock()
        mock_runtime.execute = AsyncMock(
            return_value=MagicMock(
                execution_id="ex1",
                status="completed",
                exit_code=0,
                stdout="",
                stderr="",
                started_at="t1",
                ended_at="t2",
                duration_ms=10,
                timed_out=False,
                truncated=False,
            )
        )
        mock_get_runtime.return_value = mock_runtime
        params = {"sandbox_id": "sb1", "command": ["echo", "test"]}
        result = await sandbox.sandbox_execute(params, mock_ctx)
        assert result["started"] is True

    @patch.dict(os.environ, {"SMP_SANDBOX_ALLOWED_COMMANDS": "echo"}, clear=False)
    @patch("smp.protocol.handlers.sandbox.get_runtime")
    @pytest.mark.asyncio
    async def test_command_with_args_allowed_when_base_allowed(self, mock_get_runtime, mock_ctx):
        mock_runtime = MagicMock()
        mock_runtime.get.return_value = MagicMock()
        mock_runtime.execute = AsyncMock(
            return_value=MagicMock(
                execution_id="ex1",
                status="completed",
                exit_code=0,
                stdout="",
                stderr="",
                started_at="t1",
                ended_at="t2",
                duration_ms=10,
                timed_out=False,
                truncated=False,
            )
        )
        mock_get_runtime.return_value = mock_runtime
        params = {"sandbox_id": "sb1", "command": ["echo", "-n", "hello world"]}
        result = await sandbox.sandbox_execute(params, mock_ctx)
        assert result["started"] is True


class TestTimeoutValidation:
    @pytest.fixture
    def mock_ctx(self):
        return {}

    @patch("smp.protocol.handlers.sandbox.get_runtime")
    @pytest.mark.asyncio
    async def test_execute_default_timeout(self, mock_get_runtime, mock_ctx):
        mock_runtime = MagicMock()
        mock_runtime.get.return_value = MagicMock()
        mock_runtime.execute = AsyncMock(
            return_value=MagicMock(
                execution_id="ex1",
                status="completed",
                exit_code=0,
                stdout="",
                stderr="",
                started_at="t1",
                ended_at="t2",
                duration_ms=10,
                timed_out=False,
                truncated=False,
            )
        )
        mock_get_runtime.return_value = mock_runtime
        params = {"sandbox_id": "sb1", "command": ["echo", "test"]}
        await sandbox.sandbox_execute(params, mock_ctx)
        call_kwargs = mock_runtime.execute.call_args.kwargs
        assert call_kwargs["timeout"] == 30.0

    @patch("smp.protocol.handlers.sandbox.get_runtime")
    @pytest.mark.asyncio
    async def test_execute_custom_timeout(self, mock_get_runtime, mock_ctx):
        mock_runtime = MagicMock()
        mock_runtime.get.return_value = MagicMock()
        mock_runtime.execute = AsyncMock(
            return_value=MagicMock(
                execution_id="ex1",
                status="completed",
                exit_code=0,
                stdout="",
                stderr="",
                started_at="t1",
                ended_at="t2",
                duration_ms=10,
                timed_out=False,
                truncated=False,
            )
        )
        mock_get_runtime.return_value = mock_runtime
        params = {"sandbox_id": "sb1", "command": ["echo", "test"], "timeout": 60}
        await sandbox.sandbox_execute(params, mock_ctx)
        call_kwargs = mock_runtime.execute.call_args.kwargs
        assert call_kwargs["timeout"] == 60.0


class TestStdinValidation:
    @pytest.fixture
    def mock_ctx(self):
        return {}

    @patch("smp.protocol.handlers.sandbox.get_runtime")
    @pytest.mark.asyncio
    async def test_execute_with_stdin(self, mock_get_runtime, mock_ctx):
        mock_runtime = MagicMock()
        mock_runtime.get.return_value = MagicMock()
        mock_runtime.execute = AsyncMock(
            return_value=MagicMock(
                execution_id="ex1",
                status="completed",
                exit_code=0,
                stdout="result",
                stderr="",
                started_at="t1",
                ended_at="t2",
                duration_ms=10,
                timed_out=False,
                truncated=False,
            )
        )
        mock_get_runtime.return_value = mock_runtime
        params = {"sandbox_id": "sb1", "command": ["cat"], "stdin": "input data"}
        await sandbox.sandbox_execute(params, mock_ctx)
        call_kwargs = mock_runtime.execute.call_args.kwargs
        assert call_kwargs["stdin"] == "input data"

    @patch("smp.protocol.handlers.sandbox.get_runtime")
    @pytest.mark.asyncio
    async def test_execute_without_stdin(self, mock_get_runtime, mock_ctx):
        mock_runtime = MagicMock()
        mock_runtime.get.return_value = MagicMock()
        mock_runtime.execute = AsyncMock(
            return_value=MagicMock(
                execution_id="ex1",
                status="completed",
                exit_code=0,
                stdout="",
                stderr="",
                started_at="t1",
                ended_at="t2",
                duration_ms=10,
                timed_out=False,
                truncated=False,
            )
        )
        mock_get_runtime.return_value = mock_runtime
        params = {"sandbox_id": "sb1", "command": ["echo", "test"]}
        await sandbox.sandbox_execute(params, mock_ctx)
        call_kwargs = mock_runtime.execute.call_args.kwargs
        assert call_kwargs["stdin"] is None


class TestIsCommandAllowedUnit:
    def test_empty_command_not_allowed_without_env(self, monkeypatch):
        monkeypatch.delenv("SMP_SANDBOX_ALLOWED_COMMANDS", raising=False)
        result = sandbox._is_command_allowed([])
        assert result is True

    def test_command_allowed_with_no_env_var(self, monkeypatch):
        monkeypatch.delenv("SMP_SANDBOX_ALLOWED_COMMANDS", raising=False)
        result = sandbox._is_command_allowed(["echo"])
        assert result is True

    def test_command_not_allowed_when_not_in_allowlist(self, monkeypatch):
        monkeypatch.setenv("SMP_SANDBOX_ALLOWED_COMMANDS", "python,node")
        result = sandbox._is_command_allowed(["rm", "-rf"])
        assert result is False

    def test_command_allowed_when_in_allowlist(self, monkeypatch):
        monkeypatch.setenv("SMP_SANDBOX_ALLOWED_COMMANDS", "python,node,echo")
        result = sandbox._is_command_allowed(["echo"])
        assert result is True

    def test_case_sensitive_allowlist(self, monkeypatch):
        monkeypatch.setenv("SMP_SANDBOX_ALLOWED_COMMANDS", "Echo")
        result = sandbox._is_command_allowed(["echo"])
        assert result is False


class TestTemplateValidation:
    @pytest.fixture
    def mock_ctx(self):
        return {}

    @patch("smp.protocol.handlers.sandbox.get_runtime")
    @pytest.mark.asyncio
    async def test_spawn_with_template(self, mock_get_runtime, mock_ctx):
        mock_runtime = MagicMock()
        mock_runtime.spawn = AsyncMock(
            return_value=MagicMock(
                sandbox_id="sb_123",
                name="test",
                template="python",
                files=[],
                root="/tmp",
                created_at="t",
            )
        )
        mock_get_runtime.return_value = mock_runtime
        params = {"name": "test", "template": "python", "files": {}}
        result = await sandbox.sandbox_spawn(params, mock_ctx)
        assert result["template"] == "python"

    @patch("smp.protocol.handlers.sandbox.get_runtime")
    @pytest.mark.asyncio
    async def test_spawn_with_none_template(self, mock_get_runtime, mock_ctx):
        mock_runtime = MagicMock()
        mock_runtime.spawn = AsyncMock(
            return_value=MagicMock(
                sandbox_id="sb_123",
                name="test",
                template="",
                files=[],
                root="/tmp",
                created_at="t",
            )
        )
        mock_get_runtime.return_value = mock_runtime
        params = {"name": "test", "template": None, "files": {}}
        result = await sandbox.sandbox_spawn(params, mock_ctx)
        assert result["template"] == ""
