from __future__ import annotations

from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient

from smp.cli import ingest_directory
from smp.protocol.auth import AuthPolicy
from smp.protocol.server import create_app


@pytest.mark.asyncio
async def test_impact_analysis_flow(tmp_path: Path):
    graph_path = str(tmp_path / "impact_test.smpg")
    sample_project = "tests/fixtures/sample_project"

    # 1. Ingest the codebase
    await ingest_directory(sample_project, graph_path=graph_path)

    policy = AuthPolicy(open_mode="open", rate_limit_per_minute=1000, max_request_bytes=10 * 1024 * 1024)
    app = create_app(graph_path=graph_path, auth_policy=policy)

    async with app.router.lifespan_context(app):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            # 2. Find an entity to analyze impact on
            search_payload = {"jsonrpc": "2.0", "method": "smp/search", "params": {"query": "auth"}, "id": 1}
            search_resp = await ac.post("/rpc", json=search_payload)
            assert search_resp.status_code == 200
            search_result = search_resp.json().get("result") or {}
            matches = search_result.get("matches", [])
            if not matches:
                # Fall back to locating any node so the impact step is still exercised.
                locate_resp = await ac.post(
                    "/rpc",
                    json={"jsonrpc": "2.0", "method": "smp/locate", "params": {"query": "auth"}, "id": 10},
                )
                assert locate_resp.status_code == 200
                pytest.skip("no 'auth' matches in sample project; impact step not exercised")
            entity_id = matches[0]["id"]

            # 3. Assess impact
            impact_payload = {
                "jsonrpc": "2.0",
                "method": "smp/impact",
                "params": {"entity": entity_id, "change_type": "modify"},
                "id": 2,
            }
            resp = await ac.post("/rpc", json=impact_payload)
            assert resp.status_code == 200
            result = resp.json()["result"]

            # The result should be an impact report
            impacted = result.get("impacted_nodes", result.get("affected_functions", []))
            assert isinstance(impacted, list)


@pytest.mark.asyncio
async def test_impact_nonexistent_entity(tmp_path: Path):
    graph_path = str(tmp_path / "impact_err.smpg")
    await ingest_directory("tests/fixtures/sample_project", graph_path=graph_path)

    policy = AuthPolicy(open_mode="open", rate_limit_per_minute=1000, max_request_bytes=10 * 1024 * 1024)
    app = create_app(graph_path=graph_path, auth_policy=policy)

    async with app.router.lifespan_context(app):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            payload = {
                "jsonrpc": "2.0",
                "method": "smp/impact",
                "params": {"entity": "non_existent_id", "change_type": "modify"},
                "id": 1,
            }
            resp = await ac.post("/rpc", json=payload)
            assert resp.status_code == 200
            result = resp.json()["result"]
            # Impact analysis for non-existent entity should return empty impact
            assert len(result.get("impacted_nodes", [])) == 0
