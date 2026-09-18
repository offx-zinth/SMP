from __future__ import annotations

from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient

from smp.cli import ingest_directory
from smp.observability.backup import restore
from smp.protocol.auth import AuthPolicy
from smp.protocol.server import create_app


@pytest.mark.asyncio
async def test_backup_restore_cycle(tmp_path: Path):
    graph_path = str(tmp_path / "backup_test.smpg")
    backup_path = str(tmp_path / "backup.smpg")
    sample_project = "tests/fixtures/sample_project"

    # 1. Initial Ingestion
    await ingest_directory(sample_project, graph_path=graph_path)

    policy = AuthPolicy(open_mode="open", rate_limit_per_minute=1000, max_request_bytes=10 * 1024 * 1024)
    app = create_app(graph_path=graph_path, auth_policy=policy)

    async with app.router.lifespan_context(app):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            # 2. Perform Backup
            resp = await ac.post("/admin/backup", json={"target": backup_path})
            assert resp.status_code == 200
            backup_info = resp.json()
            assert "backed_up_to" in backup_info

            # 3. Modify graph - let's check node count first
            stats_before = await ac.get("/stats")
            nodes_before = stats_before.json()["nodes"]

            # To modify, we can use smp/update or similar.
            # For simplicity, let's just clear it using the CLI since it's easier to wipe everything.
            # But wait, we must stop the server to use the CLI safely if it connects to the same file.
            # Actually, create_app's lifespan handles the connection.

    # Stop server (by exiting the async with AsyncClient and letting app go out of scope?
    # No, the app state might still have open handles. In tests, create_app is just a factory.
    # The lifespan is triggered by the ASGI server. In httpx.AsyncClient with ASGITransport,
    # it doesn't automatically trigger lifespan unless we use a specific runner.
    # Actually, create_app doesn't open the store until the lifespan starts.
    # httpx AsyncClient with ASGITransport doesn't trigger lifespan.

    # Let's use the CLI to modify the graph.
    await ingest_directory(sample_project, graph_path=graph_path, clear=True)
    # To make it different, let's just use a different directory or no directory.
    # Or just delete the file.
    Path(graph_path).unlink()

    # 4. Restore
    await restore(target=graph_path, source=backup_path)

    # 5. Verify
    # Restart "server" (re-create app and check stats)
    app = create_app(graph_path=graph_path, auth_policy=policy)
    async with app.router.lifespan_context(app):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            # We need to trigger the lifespan for /stats to work because it uses app.state.graph
            # Since AsyncClient doesn't trigger lifespan, we can't use /stats directly unless we
            # manually trigger it or use a real server.
            # Alternatively, we can just check the file size or use MMapGraphStore directly.

            from smp.store.graph.mmap_store import MMapGraphStore

            store = MMapGraphStore(path=graph_path)
            await store.connect()
            nodes_after = await store.count_nodes()
            await store.close()

            assert nodes_after == nodes_before


@pytest.mark.asyncio
async def test_backup_missing_target(tmp_path: Path):
    graph_path = str(tmp_path / "backup_err.smpg")
    await ingest_directory("tests/fixtures/sample_project", graph_path=graph_path)

    policy = AuthPolicy(open_mode="open", rate_limit_per_minute=1000, max_request_bytes=10 * 1024 * 1024)
    app = create_app(graph_path=graph_path, auth_policy=policy)

    async with app.router.lifespan_context(app):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            # Missing target in payload
            resp = await ac.post("/admin/backup", json={})
            assert resp.status_code == 400
            assert "missing 'target' path" in resp.json()["error"]["message"]
