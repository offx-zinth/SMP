from __future__ import annotations

from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient

from smp.protocol.auth import AuthPolicy
from smp.protocol.server import create_app


@pytest.mark.asyncio
async def test_session_lifecycle(tmp_path: Path):
    graph_path = str(tmp_path / "session_test.smpg")
    policy = AuthPolicy(open_mode="open", rate_limit_per_minute=1000, max_request_bytes=10 * 1024 * 1024)
    app = create_app(graph_path=graph_path, auth_policy=policy)

    async with app.router.lifespan_context(app):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            # 1. Open Session
            payload_open = {
                "jsonrpc": "2.0",
                "method": "smp/session/open",
                "params": {
                    "agent_id": "test_agent",
                    "task": "system_test",
                    "scope": ["read", "write"],
                    "mode": "interactive",
                },
                "id": 1,
            }
            resp = await ac.post("/rpc", json=payload_open)
            assert resp.status_code == 200
            session_id = resp.json()["result"]["session_id"]

            # 2. Checkpoint
            # We need some files to checkpoint. Let's use /home/bhagyarekhab/SMP/smp/cli.py as a fake file.
            payload_ckpt = {
                "jsonrpc": "2.0",
                "method": "smp/checkpoint",
                "params": {"session_id": session_id, "files": ["/home/bhagyarekhab/SMP/smp/cli.py"]},
                "id": 2,
            }
            resp = await ac.post("/rpc", json=payload_ckpt)
            assert resp.status_code == 200
            checkpoint_id = resp.json()["result"]["checkpoint_id"]
            assert checkpoint_id != ""

            # 3. Rollback
            payload_rb = {
                "jsonrpc": "2.0",
                "method": "smp/rollback",
                "params": {"session_id": session_id, "checkpoint_id": checkpoint_id},
                "id": 3,
            }
            resp = await ac.post("/rpc", json=payload_rb)
            assert resp.status_code == 200
            assert resp.json()["result"]["rolled_back"] is True

            # 4. Audit check
            payload_audit = {
                "jsonrpc": "2.0",
                "method": "smp/audit/get",
                "params": {"audit_log_id": session_id},
                "id": 4,
            }
            resp = await ac.post("/rpc", json=payload_audit)
            assert resp.status_code == 200
            events = resp.json()["result"]["events"]
            assert len(events) > 0
            assert any(e["event"] == "session_open" for e in events)
            assert any(e["event"] == "checkpoint" for e in events)
            assert any(e["event"] == "rollback" for e in events)

            # 5. Close Session
            payload_close = {
                "jsonrpc": "2.0",
                "method": "smp/session/close",
                "params": {"session_id": session_id, "status": "completed"},
                "id": 5,
            }
            resp = await ac.post("/rpc", json=payload_close)
            assert resp.status_code == 200
            assert resp.json()["result"]["closed"] is True


@pytest.mark.asyncio
async def test_session_recover_nonexistent(tmp_path: Path):
    graph_path = str(tmp_path / "recover_test.smpg")
    policy = AuthPolicy(open_mode="open", rate_limit_per_minute=1000, max_request_bytes=10 * 1024 * 1024)
    app = create_app(graph_path=graph_path, auth_policy=policy)

    async with app.router.lifespan_context(app):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            payload = {
                "jsonrpc": "2.0",
                "method": "smp/session/recover",
                "params": {"session_id": "invalid_sess"},
                "id": 1,
            }
            resp = await ac.post("/rpc", json=payload)
            assert resp.status_code == 200
            assert resp.json()["result"]["recovered"] is False
            assert "session_not_found" in resp.json()["result"]["error"]
