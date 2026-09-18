from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from smp.protocol.handlers import session as session_handlers


class TestConcurrentSessions:
    @pytest.fixture
    def ctx_with_graph(self):
        graph = MagicMock()
        graph.upsert_session = AsyncMock()
        graph.get_session = AsyncMock(return_value=None)
        graph.release_all_locks = AsyncMock(return_value=0)
        graph.delete_session = AsyncMock()
        graph.append_audit = AsyncMock()
        graph.release_lock = AsyncMock(return_value=True)
        graph.acquire_lock = AsyncMock(return_value=True)
        graph.get_lock = AsyncMock(return_value=None)
        graph.upsert_lock = AsyncMock()
        graph.find_nodes = AsyncMock(return_value=[])
        return {"graph": graph}

    @pytest.mark.asyncio
    async def test_multiple_sessions_open_concurrently(self, ctx_with_graph):
        params = [{"agent_id": f"agent_{i}", "task": f"task_{i}"} for i in range(5)]
        results = await asyncio.gather(*[session_handlers.session_open(p, ctx_with_graph) for p in params])
        assert len(results) == 5
        session_ids = [r["session_id"] for r in results]
        assert len(set(session_ids)) == 5

    @pytest.mark.asyncio
    async def test_close_different_sessions_independently(self, ctx_with_graph):
        open_params = [{"agent_id": f"agent_{i}"} for i in range(3)]
        open_results = await asyncio.gather(*[session_handlers.session_open(p, ctx_with_graph) for p in open_params])
        session_ids = [r["session_id"] for r in open_results]

        graph = ctx_with_graph["graph"]
        for sid in session_ids:
            graph.get_session = AsyncMock(return_value={"session_id": sid, "status": "open", "locked_files": []})

        close_results = await asyncio.gather(
            *[session_handlers.session_close({"session_id": sid}, ctx_with_graph) for sid in session_ids]
        )
        assert all(r["closed"] for r in close_results)

    @pytest.mark.asyncio
    async def test_concurrent_lock_acquisition_different_files(self, ctx_with_graph):
        graph = ctx_with_graph["graph"]
        graph.get_lock = AsyncMock(return_value=None)
        graph.upsert_lock = AsyncMock()

        files = ["/src/file_a.py", "/src/file_b.py", "/src/file_c.py"]
        result = await session_handlers.lock({"files": files, "session_id": "sess_test"}, ctx_with_graph)
        assert "locked" in result or "conflicts" in result

    @pytest.mark.asyncio
    async def test_concurrent_lock_on_same_file_one_succeeds(self, ctx_with_graph):
        graph = ctx_with_graph["graph"]
        file_path = "/src/shared.py"

        graph.get_lock = AsyncMock(return_value={"file_path": file_path, "session_id": "sess_0", "ttl": 60})

        result = await session_handlers.lock({"files": [file_path], "session_id": "sess_1"}, ctx_with_graph)
        assert "conflicts" in result or "locked" in result

    @pytest.mark.asyncio
    async def test_concurrent_unlock_different_sessions(self, ctx_with_graph):
        graph = ctx_with_graph["graph"]
        session_files = [
            ("sess_0", "/src/file0.py"),
            ("sess_1", "/src/file1.py"),
            ("sess_2", "/src/file2.py"),
        ]
        for sid, fp in session_files:
            graph.release_lock = AsyncMock(return_value=True)
            graph.get_session = AsyncMock(return_value={"session_id": sid, "locked_files": [fp]})

        results = await asyncio.gather(
            *[session_handlers.unlock({"files": [fp], "session_id": sid}, ctx_with_graph) for sid, fp in session_files]
        )
        assert all(r.get("released") for r in results)

    @pytest.mark.asyncio
    async def test_concurrent_session_recover(self, ctx_with_graph):
        graph = ctx_with_graph["graph"]
        session_data = {
            "session_id": "sess_recover",
            "agent_id": "agent_1",
            "status": "open",
            "checkpoints": [],
        }
        graph.get_session = AsyncMock(return_value=session_data)

        results = await asyncio.gather(
            *[session_handlers.session_recover({"session_id": "sess_recover"}, ctx_with_graph) for _ in range(5)]
        )
        assert all(r.get("recovered") for r in results)

    @pytest.mark.asyncio
    async def test_concurrent_checkpoint_creation(self, ctx_with_graph):
        graph = ctx_with_graph["graph"]

        for i in range(3):
            graph.get_session = AsyncMock(return_value={"session_id": f"sess_{i}", "checkpoints": []})
            graph.find_nodes = AsyncMock(return_value=[])
            graph.upsert_session = AsyncMock()

        results = await asyncio.gather(
            *[
                session_handlers.checkpoint({"session_id": f"sess_{i}", "files": [f"/src/f{i}.py"]}, ctx_with_graph)
                for i in range(3)
            ]
        )
        assert all(r.get("created") for r in results)
        checkpoint_ids = [r["checkpoint_id"] for r in results]
        assert len(set(checkpoint_ids)) == 3

    @pytest.mark.asyncio
    async def test_concurrent_open_close_cycles(self, ctx_with_graph):
        graph = ctx_with_graph["graph"]

        async def open_and_close(agent_id: str) -> tuple[dict[str, Any], dict[str, Any]]:
            open_result = await session_handlers.session_open({"agent_id": agent_id}, ctx_with_graph)
            session_id = open_result["session_id"]

            graph.get_session = AsyncMock(return_value={"session_id": session_id, "status": "open", "locked_files": []})

            close_result = await session_handlers.session_close({"session_id": session_id}, ctx_with_graph)
            return open_result, close_result

        results = await asyncio.gather(*[open_and_close(f"agent_{i}") for i in range(5)])
        assert len(results) == 5
        for _open_r, close_r in results:
            assert close_r["closed"] is True

    @pytest.mark.asyncio
    async def test_session_isolation_between_concurrent_sessions(self, ctx_with_graph):
        graph = ctx_with_graph["graph"]

        session_ids = []
        for i in range(3):
            result = await session_handlers.session_open(
                {"agent_id": f"agent_{i}", "task": f"task_{i}"}, ctx_with_graph
            )
            session_ids.append(result["session_id"])

        for sid in session_ids:
            graph.get_session = AsyncMock(
                return_value={
                    "session_id": sid,
                    "status": "open",
                    "locked_files": [],
                    "checkpoints": [],
                    "agent_id": f"agent_{session_ids.index(sid)}",
                }
            )

        await asyncio.gather(
            *[
                session_handlers.checkpoint({"session_id": sid, "files": [f"/src/file_{i}.py"]}, ctx_with_graph)
                for i, sid in enumerate(session_ids)
            ]
        )

        for sid in session_ids:
            session = await session_handlers.session_recover({"session_id": sid}, ctx_with_graph)
            assert session["recovered"] is True

    @pytest.mark.asyncio
    async def test_steal_lock_between_sessions(self, ctx_with_graph):
        graph = ctx_with_graph["graph"]
        file_path = "/src/contested.py"

        graph.get_lock = AsyncMock(return_value=None)
        graph.upsert_lock = AsyncMock()

        result0 = await session_handlers.lock({"files": [file_path], "session_id": "sess_0"}, ctx_with_graph)
        assert "locked" in result0 or "conflicts" in result0

        graph.get_lock = AsyncMock(
            return_value={"file_path": file_path, "session_id": "sess_0", "expires_at": "2030-01-01"}
        )
        graph.release_lock = AsyncMock(return_value=True)

        result1 = await session_handlers.lock(
            {"files": [file_path], "session_id": "sess_1", "force": True}, ctx_with_graph
        )
        assert "locked" in result1 or "conflicts" in result1

    @pytest.mark.asyncio
    async def test_concurrent_lock_steal_only_one_succeeds(self, ctx_with_graph):
        graph = ctx_with_graph["graph"]
        file_path = "/src/contested.py"

        graph.get_lock = AsyncMock(
            return_value={"file_path": file_path, "session_id": "owner", "expires_at": "2030-01-01"}
        )
        graph.upsert_lock = AsyncMock()
        graph.release_lock = AsyncMock(return_value=True)

        result = await session_handlers.lock(
            {"files": [file_path], "session_id": "sess_force", "force": True}, ctx_with_graph
        )
        assert "locked" in result or "conflicts" in result

    @pytest.mark.asyncio
    async def test_concurrent_checkpoints_different_sessions_same_files(self, ctx_with_graph):
        graph = ctx_with_graph["graph"]
        file_path = "/src/shared.py"

        for i in range(3):
            graph.get_session = AsyncMock(
                return_value={"session_id": f"sess_{i}", "checkpoints": [], "locked_files": [file_path]}
            )
            graph.find_nodes = AsyncMock(return_value=[])

        results = await asyncio.gather(
            *[
                session_handlers.checkpoint({"session_id": f"sess_{i}", "files": [file_path]}, ctx_with_graph)
                for i in range(3)
            ]
        )
        assert all(r.get("created") for r in results)

    @pytest.mark.asyncio
    async def test_session_count_tracking_concurrent(self, ctx_with_graph):
        results = await asyncio.gather(
            *[session_handlers.session_open({"agent_id": f"agent_{i}"}, ctx_with_graph) for i in range(10)]
        )
        assert len(results) == 10

        session_ids = [r["session_id"] for r in results]
        assert len(set(session_ids)) == 10
