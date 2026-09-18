from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from smp.protocol.handlers import session as session_handlers


class TestSessionOpen:
    @pytest.fixture
    def ctx_with_graph(self):
        graph = MagicMock()
        graph.upsert_session = AsyncMock()
        graph.append_audit = AsyncMock()
        graph.release_all_locks = AsyncMock(return_value=0)
        graph.delete_session = AsyncMock()
        return {"graph": graph}

    @pytest.mark.asyncio
    async def test_session_open_returns_session_id(self, ctx_with_graph):
        params = {"agent_id": "agent_1", "task": "test_task"}
        result = await session_handlers.session_open(params, ctx_with_graph)
        assert "session_id" in result
        assert result["session_id"].startswith("sess_")

    @pytest.mark.asyncio
    async def test_session_open_returns_status_open(self, ctx_with_graph):
        params = {"agent_id": "agent_1", "task": "test_task"}
        result = await session_handlers.session_open(params, ctx_with_graph)
        assert result["status"] == "open"

    @pytest.mark.asyncio
    async def test_session_open_returns_started_at(self, ctx_with_graph):
        params = {"agent_id": "agent_1", "task": "test_task"}
        result = await session_handlers.session_open(params, ctx_with_graph)
        assert "started_at" in result

    @pytest.mark.asyncio
    async def test_session_open_with_task(self, ctx_with_graph):
        params = {"agent_id": "agent_1", "task": "refactor_code"}
        result = await session_handlers.session_open(params, ctx_with_graph)
        assert "session_id" in result

    @pytest.mark.asyncio
    async def test_session_open_with_scope(self, ctx_with_graph):
        params = {"agent_id": "agent_1", "scope": ["/src/api", "/src/db"]}
        result = await session_handlers.session_open(params, ctx_with_graph)
        assert "session_id" in result

    @pytest.mark.asyncio
    async def test_session_open_with_mode_write(self, ctx_with_graph):
        params = {"agent_id": "agent_1", "mode": "write"}
        result = await session_handlers.session_open(params, ctx_with_graph)
        assert result["status"] == "open"

    @pytest.mark.asyncio
    async def test_session_open_with_mode_read(self, ctx_with_graph):
        params = {"agent_id": "agent_1", "mode": "read"}
        result = await session_handlers.session_open(params, ctx_with_graph)
        assert result["status"] == "open"

    @pytest.mark.asyncio
    async def test_session_open_default_mode_is_read(self, ctx_with_graph):
        params = {"agent_id": "agent_1"}
        result = await session_handlers.session_open(params, ctx_with_graph)
        assert result["status"] == "open"

    @pytest.mark.asyncio
    async def test_session_open_persists_to_graph(self, ctx_with_graph):
        graph = ctx_with_graph["graph"]
        params = {"agent_id": "agent_1"}
        await session_handlers.session_open(params, ctx_with_graph)
        graph.upsert_session.assert_called_once()

    @pytest.mark.asyncio
    async def test_session_open_records_audit(self, ctx_with_graph):
        graph = ctx_with_graph["graph"]
        params = {"agent_id": "agent_1", "task": "audit_test"}
        await session_handlers.session_open(params, ctx_with_graph)
        graph.append_audit.assert_called_once()


class TestSessionClose:
    @pytest.fixture
    def ctx_with_graph(self):
        graph = MagicMock()
        graph.get_session = AsyncMock()
        graph.release_all_locks = AsyncMock(return_value=0)
        graph.delete_session = AsyncMock()
        graph.append_audit = AsyncMock()
        return {"graph": graph}

    @pytest.mark.asyncio
    async def test_session_close_not_found(self, ctx_with_graph):
        graph = ctx_with_graph["graph"]
        graph.get_session = AsyncMock(return_value=None)
        params = {"session_id": "nonexistent"}
        result = await session_handlers.session_close(params, ctx_with_graph)
        assert result["closed"] is False
        assert result["error"] == "session_not_found"

    @pytest.mark.asyncio
    async def test_session_close_success(self, ctx_with_graph):
        graph = ctx_with_graph["graph"]
        graph.get_session = AsyncMock(return_value={"session_id": "s1", "status": "open", "locked_files": []})
        graph.release_all_locks = AsyncMock(return_value=0)
        params = {"session_id": "s1", "status": "completed"}
        result = await session_handlers.session_close(params, ctx_with_graph)
        assert result["closed"] is True

    @pytest.mark.asyncio
    async def test_session_close_returns_status(self, ctx_with_graph):
        graph = ctx_with_graph["graph"]
        graph.get_session = AsyncMock(return_value={"session_id": "s1", "status": "open", "locked_files": []})
        params = {"session_id": "s1", "status": "completed"}
        result = await session_handlers.session_close(params, ctx_with_graph)
        assert result["status"] == "completed"

    @pytest.mark.asyncio
    async def test_session_close_with_default_status(self, ctx_with_graph):
        graph = ctx_with_graph["graph"]
        graph.get_session = AsyncMock(return_value={"session_id": "s1", "status": "open", "locked_files": []})
        params = {"session_id": "s1"}
        result = await session_handlers.session_close(params, ctx_with_graph)
        assert result["status"] == "completed"

    @pytest.mark.asyncio
    async def test_session_close_releases_locks(self, ctx_with_graph):
        graph = ctx_with_graph["graph"]
        graph.get_session = AsyncMock(return_value={"session_id": "s1", "status": "open", "locked_files": []})
        graph.release_all_locks = AsyncMock(return_value=5)
        params = {"session_id": "s1"}
        result = await session_handlers.session_close(params, ctx_with_graph)
        assert result["released_locks"] == 5

    @pytest.mark.asyncio
    async def test_session_close_deletes_session(self, ctx_with_graph):
        graph = ctx_with_graph["graph"]
        graph.get_session = AsyncMock(return_value={"session_id": "s1", "status": "open", "locked_files": []})
        params = {"session_id": "s1"}
        await session_handlers.session_close(params, ctx_with_graph)
        graph.delete_session.assert_called_once_with("s1")

    @pytest.mark.asyncio
    async def test_session_close_with_interrupted_status(self, ctx_with_graph):
        graph = ctx_with_graph["graph"]
        graph.get_session = AsyncMock(return_value={"session_id": "s1", "status": "open", "locked_files": []})
        params = {"session_id": "s1", "status": "interrupted"}
        result = await session_handlers.session_close(params, ctx_with_graph)
        assert result["status"] == "interrupted"


class TestSessionRecover:
    @pytest.fixture
    def ctx_with_graph(self):
        graph = MagicMock()
        graph.get_session = AsyncMock()
        return {"graph": graph}

    @pytest.mark.asyncio
    async def test_session_recover_not_found(self, ctx_with_graph):
        graph = ctx_with_graph["graph"]
        graph.get_session = AsyncMock(return_value=None)
        params = {"session_id": "ghost_session"}
        result = await session_handlers.session_recover(params, ctx_with_graph)
        assert result["recovered"] is False
        assert result["error"] == "session_not_found"

    @pytest.mark.asyncio
    async def test_session_recover_success(self, ctx_with_graph):
        graph = ctx_with_graph["graph"]
        session_data = {
            "session_id": "s1",
            "agent_id": "a1",
            "task": "test",
            "status": "open",
        }
        graph.get_session = AsyncMock(return_value=session_data)
        params = {"session_id": "s1"}
        result = await session_handlers.session_recover(params, ctx_with_graph)
        assert result["recovered"] is True

    @pytest.mark.asyncio
    async def test_session_recover_returns_session_data(self, ctx_with_graph):
        graph = ctx_with_graph["graph"]
        session_data = {
            "session_id": "s1",
            "agent_id": "a1",
            "task": "test",
            "status": "open",
        }
        graph.get_session = AsyncMock(return_value=session_data)
        params = {"session_id": "s1"}
        result = await session_handlers.session_recover(params, ctx_with_graph)
        assert result["session"] == session_data

    @pytest.mark.asyncio
    async def test_session_recover_with_checkpoints(self, ctx_with_graph):
        graph = ctx_with_graph["graph"]
        session_data = {
            "session_id": "s1",
            "checkpoints": [{"checkpoint_id": "ck1"}, {"checkpoint_id": "ck2"}],
        }
        graph.get_session = AsyncMock(return_value=session_data)
        params = {"session_id": "s1"}
        result = await session_handlers.session_recover(params, ctx_with_graph)
        assert result["recovered"] is True
        assert "checkpoints" in result["session"]

    @pytest.mark.asyncio
    async def test_session_recover_with_locked_files(self, ctx_with_graph):
        graph = ctx_with_graph["graph"]
        session_data = {
            "session_id": "s1",
            "locked_files": ["/src/main.py", "/src/utils.py"],
        }
        graph.get_session = AsyncMock(return_value=session_data)
        params = {"session_id": "s1"}
        result = await session_handlers.session_recover(params, ctx_with_graph)
        assert result["session"]["locked_files"] == ["/src/main.py", "/src/utils.py"]


class TestCheckpoint:
    @pytest.fixture
    def ctx_with_graph(self):
        graph = MagicMock()
        graph.get_session = AsyncMock()
        graph.find_nodes = AsyncMock(return_value=[])
        graph.upsert_session = AsyncMock()
        graph.append_audit = AsyncMock()
        return {"graph": graph}

    @pytest.mark.asyncio
    async def test_checkpoint_session_not_found(self, ctx_with_graph):
        graph = ctx_with_graph["graph"]
        graph.get_session = AsyncMock(return_value=None)
        params = {"session_id": "ghost", "files": ["a.py"]}
        result = await session_handlers.checkpoint(params, ctx_with_graph)
        assert result["created"] is False
        assert result["error"] == "session_not_found"

    @pytest.mark.asyncio
    async def test_checkpoint_success(self, ctx_with_graph):
        graph = ctx_with_graph["graph"]
        graph.get_session = AsyncMock(return_value={"session_id": "s1", "checkpoints": []})
        params = {"session_id": "s1", "files": ["/src/main.py"]}
        result = await session_handlers.checkpoint(params, ctx_with_graph)
        assert result["created"] is True

    @pytest.mark.asyncio
    async def test_checkpoint_returns_checkpoint_id(self, ctx_with_graph):
        graph = ctx_with_graph["graph"]
        graph.get_session = AsyncMock(return_value={"session_id": "s1", "checkpoints": []})
        params = {"session_id": "s1", "files": ["/src/main.py"]}
        result = await session_handlers.checkpoint(params, ctx_with_graph)
        assert "checkpoint_id" in result
        assert result["checkpoint_id"].startswith("ckpt_")

    @pytest.mark.asyncio
    async def test_checkpoint_returns_files(self, ctx_with_graph):
        graph = ctx_with_graph["graph"]
        graph.get_session = AsyncMock(return_value={"session_id": "s1", "checkpoints": []})
        params = {"session_id": "s1", "files": ["/src/main.py", "/src/utils.py"]}
        result = await session_handlers.checkpoint(params, ctx_with_graph)
        assert result["files"] == ["/src/main.py", "/src/utils.py"]

    @pytest.mark.asyncio
    async def test_checkpoint_multiple_files(self, ctx_with_graph):
        graph = ctx_with_graph["graph"]
        graph.get_session = AsyncMock(return_value={"session_id": "s1", "checkpoints": []})
        graph.find_nodes = AsyncMock(return_value=[])
        params = {"session_id": "s1", "files": ["/src/main.py", "/src/utils.py"]}
        result = await session_handlers.checkpoint(params, ctx_with_graph)
        assert result["created"] is True


class TestRollback:
    @pytest.fixture
    def ctx_with_graph(self):
        graph = MagicMock()
        graph.get_session = AsyncMock()
        graph.append_audit = AsyncMock()
        return {"graph": graph}

    @pytest.mark.asyncio
    async def test_rollback_session_not_found(self, ctx_with_graph):
        graph = ctx_with_graph["graph"]
        graph.get_session = AsyncMock(return_value=None)
        params = {"session_id": "ghost", "checkpoint_id": "ck1"}
        result = await session_handlers.rollback(params, ctx_with_graph)
        assert result["rolled_back"] is False
        assert result["error"] == "session_not_found"

    @pytest.mark.asyncio
    async def test_rollback_checkpoint_not_found(self, ctx_with_graph):
        graph = ctx_with_graph["graph"]
        graph.get_session = AsyncMock(return_value={"session_id": "s1", "checkpoints": []})
        params = {"session_id": "s1", "checkpoint_id": "nonexistent"}
        result = await session_handlers.rollback(params, ctx_with_graph)
        assert result["rolled_back"] is False
        assert result["error"] == "checkpoint_not_found"

    @pytest.mark.asyncio
    async def test_rollback_success(self, ctx_with_graph):
        graph = ctx_with_graph["graph"]
        checkpoints = [
            {
                "checkpoint_id": "ckpt_abc123",
                "files": ["/src/main.py"],
                "fingerprints": {"/src/main.py": ["abc123"]},
            }
        ]
        graph.get_session = AsyncMock(return_value={"session_id": "s1", "checkpoints": checkpoints})
        params = {"session_id": "s1", "checkpoint_id": "ckpt_abc123"}
        result = await session_handlers.rollback(params, ctx_with_graph)
        assert result["rolled_back"] is True

    @pytest.mark.asyncio
    async def test_rollback_returns_checkpoint_id(self, ctx_with_graph):
        graph = ctx_with_graph["graph"]
        checkpoints = [
            {
                "checkpoint_id": "ckpt_abc123",
                "files": ["/src/main.py"],
                "fingerprints": {},
            }
        ]
        graph.get_session = AsyncMock(return_value={"session_id": "s1", "checkpoints": checkpoints})
        params = {"session_id": "s1", "checkpoint_id": "ckpt_abc123"}
        result = await session_handlers.rollback(params, ctx_with_graph)
        assert result["checkpoint_id"] == "ckpt_abc123"

    @pytest.mark.asyncio
    async def test_rollback_returns_files(self, ctx_with_graph):
        graph = ctx_with_graph["graph"]
        checkpoints = [
            {
                "checkpoint_id": "ckpt_abc123",
                "files": ["/src/main.py", "/src/utils.py"],
                "fingerprints": {},
            }
        ]
        graph.get_session = AsyncMock(return_value={"session_id": "s1", "checkpoints": checkpoints})
        params = {"session_id": "s1", "checkpoint_id": "ckpt_abc123"}
        result = await session_handlers.rollback(params, ctx_with_graph)
        assert result["files"] == ["/src/main.py", "/src/utils.py"]

    @pytest.mark.asyncio
    async def test_rollback_returns_fingerprints(self, ctx_with_graph):
        graph = ctx_with_graph["graph"]
        fingerprints = {"/src/main.py": ["fingerprint_here"]}
        checkpoints = [
            {
                "checkpoint_id": "ckpt_abc123",
                "files": ["/src/main.py"],
                "fingerprints": fingerprints,
            }
        ]
        graph.get_session = AsyncMock(return_value={"session_id": "s1", "checkpoints": checkpoints})
        params = {"session_id": "s1", "checkpoint_id": "ckpt_abc123"}
        result = await session_handlers.rollback(params, ctx_with_graph)
        assert result["fingerprints"] == fingerprints

    @pytest.mark.asyncio
    async def test_rollback_finds_latest_matching_checkpoint(self, ctx_with_graph):
        graph = ctx_with_graph["graph"]
        checkpoints = [
            {"checkpoint_id": "ckpt_old", "files": []},
            {"checkpoint_id": "ckpt_middle", "files": []},
            {"checkpoint_id": "ckpt_new", "files": ["/src/main.py"]},
        ]
        graph.get_session = AsyncMock(return_value={"session_id": "s1", "checkpoints": checkpoints})
        params = {"session_id": "s1", "checkpoint_id": "ckpt_new"}
        result = await session_handlers.rollback(params, ctx_with_graph)
        assert result["rolled_back"] is True


class TestSessionIntegration:
    @pytest.fixture
    def ctx_with_graph(self):
        graph = MagicMock()
        graph.upsert_session = AsyncMock()
        graph.get_session = AsyncMock()
        graph.release_all_locks = AsyncMock(return_value=0)
        graph.delete_session = AsyncMock()
        graph.append_audit = AsyncMock()
        return {"graph": graph}

    @pytest.mark.asyncio
    async def test_full_session_lifecycle_open_close(self, ctx_with_graph):
        graph = ctx_with_graph["graph"]
        open_params = {"agent_id": "agent_1", "task": "integration_test"}
        open_result = await session_handlers.session_open(open_params, ctx_with_graph)
        session_id = open_result["session_id"]

        get_session_data = {
            "session_id": session_id,
            "status": "open",
            "locked_files": [],
            "checkpoints": [],
        }
        graph.get_session = AsyncMock(return_value=get_session_data)

        close_params = {"session_id": session_id}
        close_result = await session_handlers.session_close(close_params, ctx_with_graph)
        assert close_result["closed"] is True

    @pytest.mark.asyncio
    async def test_session_with_checkpoint_and_rollback(self, ctx_with_graph):
        graph = ctx_with_graph["graph"]
        open_params = {"agent_id": "agent_1", "task": "checkpoint_test"}
        open_result = await session_handlers.session_open(open_params, ctx_with_graph)
        session_id = open_result["session_id"]

        graph.get_session = AsyncMock(return_value={"session_id": session_id, "checkpoints": []})
        graph.find_nodes = AsyncMock(return_value=[])

        checkpoint_params = {"session_id": session_id, "files": ["/test.py"]}
        checkpoint_result = await session_handlers.checkpoint(checkpoint_params, ctx_with_graph)
        checkpoint_id = checkpoint_result["checkpoint_id"]

        checkpoints = [
            {
                "checkpoint_id": checkpoint_id,
                "files": ["/test.py"],
                "fingerprints": {"/test.py": ["fp1"]},
            }
        ]
        graph.get_session = AsyncMock(return_value={"session_id": session_id, "checkpoints": checkpoints})

        rollback_params = {"session_id": session_id, "checkpoint_id": checkpoint_id}
        rollback_result = await session_handlers.rollback(rollback_params, ctx_with_graph)
        assert rollback_result["rolled_back"] is True
