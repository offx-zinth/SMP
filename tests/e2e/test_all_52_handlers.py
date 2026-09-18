from __future__ import annotations

from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient

from smp.protocol.auth import AuthPolicy
from smp.protocol.server import _HANDLERS, create_app


@pytest.mark.asyncio
async def test_all_handlers_dispatch(tmp_path: Path):
    graph_path = str(tmp_path / "handlers_test.smpg")

    policy = AuthPolicy(open_mode="open", rate_limit_per_minute=10000, max_request_bytes=10 * 1024 * 1024)
    app = create_app(graph_path=graph_path, auth_policy=policy)

    # We need some data for handlers to not just return empty/none
    # We can use a small ingestion or just call them and check for 200 OK

    async with app.router.lifespan_context(app):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            for method in _HANDLERS:
                payload = {"jsonrpc": "2.0", "method": method, "params": {}, "id": "test_id"}

                # We expect 200 OK because the dispatcher should find the handler.
                # The handler might return a JSON-RPC error if params are missing,
                # but the HTTP response should be 200.
                response = await ac.post("/rpc", json=payload)

                assert response.status_code == 200, f"Handler {method} failed with status {response.status_code}"
                data = response.json()
                assert "jsonrpc" in data
                assert data["jsonrpc"] == "2.0"
                # It should either have a result or an error (not a crash)
                assert "result" in data or "error" in data, f"Handler {method} returned invalid JSON-RPC: {data}"


@pytest.mark.asyncio
async def test_handler_not_found(tmp_path: Path):
    graph_path = str(tmp_path / "not_found_test.smpg")
    policy = AuthPolicy(open_mode="open", rate_limit_per_minute=1000, max_request_bytes=10 * 1024 * 1024)
    app = create_app(graph_path=graph_path, auth_policy=policy)

    async with app.router.lifespan_context(app):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            payload = {"jsonrpc": "2.0", "method": "smp/non_existent_method", "params": {}, "id": 1}
            response = await ac.post("/rpc", json=payload)
            assert response.status_code == 200
            data = response.json()
            assert "error" in data
            assert data["error"]["code"] == -32601
            assert "Method not found" in data["error"]["message"]
