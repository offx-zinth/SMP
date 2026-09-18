from __future__ import annotations

from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient

from smp.cli import ingest_directory
from smp.protocol.auth import AuthPolicy
from smp.protocol.server import create_app


class TestFullIngestionFlow:
    @pytest.mark.asyncio
    async def test_full_ingestion_flow(self, tmp_path: Path):
        graph_path = str(tmp_path / "test_graph.smpg")
        sample_project = "tests/fixtures/sample_project"

        stats = await ingest_directory(
            sample_project,
            graph_path=graph_path,
            clear=True,
        )

        assert stats["files"] > 0
        assert stats["nodes"] > 0

    @pytest.mark.asyncio
    async def test_ingestion_with_clear(self, tmp_path: Path):
        graph_path = str(tmp_path / "test_graph_clear.smpg")
        sample_project = "tests/fixtures/sample_project"

        await ingest_directory(sample_project, graph_path=graph_path)

        stats = await ingest_directory(sample_project, graph_path=graph_path, clear=True)
        assert stats["files"] > 0

    @pytest.mark.asyncio
    async def test_ingestion_invalid_path(self):
        with pytest.raises(ValueError, match="Not a directory"):
            await ingest_directory("/non/existent/path")

    @pytest.mark.asyncio
    async def test_ingestion_empty_directory(self, tmp_path: Path):
        empty_dir = tmp_path / "empty"
        empty_dir.mkdir()
        graph_path = str(tmp_path / "empty_graph.smpg")

        stats = await ingest_directory(str(empty_dir), graph_path=graph_path)
        assert stats["files"] == 0
        assert stats["nodes"] == 0

    @pytest.mark.asyncio
    async def test_ingestion_skips_large_files(self, tmp_path: Path):
        large_dir = tmp_path / "large_project"
        large_dir.mkdir()
        large_file = large_dir / "big.py"
        large_file.write_text("x" * 2_000_000)

        graph_path = str(tmp_path / "large_graph.smpg")
        stats = await ingest_directory(str(large_dir), graph_path=graph_path)

        assert stats["skipped"] == 1
        assert stats["files"] == 0

    @pytest.mark.asyncio
    async def test_ingestion_skips_hidden_directories(self, tmp_path: Path):
        project_dir = tmp_path / "my_project"
        project_dir.mkdir()
        (project_dir / "visible.py").write_text("def foo(): pass")
        hidden = project_dir / ".hidden"
        hidden.mkdir()
        (hidden / "hidden.py").write_text("def hidden(): pass")

        graph_path = str(tmp_path / "hidden_graph.smpg")
        stats = await ingest_directory(str(project_dir), graph_path=graph_path)

        assert stats["files"] == 1

    @pytest.mark.asyncio
    async def test_ingestion_skips_pycache(self, tmp_path: Path):
        project_dir = tmp_path / "pycache_project"
        project_dir.mkdir()
        (project_dir / "main.py").write_text("def main(): pass")
        pycache = project_dir / "__pycache__"
        pycache.mkdir()
        (pycache / "main.pyc").write_bytes(b"fake bytecode")

        graph_path = str(tmp_path / "pycache_graph.smpg")
        stats = await ingest_directory(str(project_dir), graph_path=graph_path)

        assert stats["files"] == 1

    @pytest.mark.asyncio
    async def test_ingestion_skips_venv(self, tmp_path: Path):
        project_dir = tmp_path / "venv_project"
        project_dir.mkdir()
        (project_dir / "app.py").write_text("def app(): pass")
        venv = project_dir / "venv"
        venv.mkdir()
        (venv / "site.py").write_text("# fake venv")

        graph_path = str(tmp_path / "venv_graph.smpg")
        stats = await ingest_directory(str(project_dir), graph_path=graph_path)

        assert stats["files"] == 1

    @pytest.mark.asyncio
    async def test_graph_persistence_after_ingestion(self, tmp_path: Path):
        graph_path = str(tmp_path / "persist_graph.smpg")
        sample_project = "tests/fixtures/sample_project"

        stats1 = await ingest_directory(sample_project, graph_path=graph_path)
        nodes_first = stats1["nodes"]

        from smp.store.graph.mmap_store import MMapGraphStore

        store = MMapGraphStore(path=graph_path)
        await store.connect()
        try:
            nodes_after_reconnect = await store.count_nodes()
        finally:
            await store.disconnect()

        assert nodes_after_reconnect == nodes_first

    @pytest.mark.asyncio
    async def test_ingestion_counts_accuracy(self, tmp_path: Path):
        graph_path = str(tmp_path / "counts_graph.smpg")
        sample_project = "tests/fixtures/sample_project"

        stats = await ingest_directory(sample_project, graph_path=graph_path)

        assert stats["files"] >= 7
        assert stats["nodes"] > 0
        assert stats["errors"] == 0

    @pytest.mark.asyncio
    async def test_multiple_extensions_filter(self, tmp_path: Path):
        project_dir = tmp_path / "multi_ext"
        project_dir.mkdir()
        (project_dir / "main.py").write_text("def main(): pass")
        (project_dir / "utils.js").write_text("function util() {}")

        graph_path = str(tmp_path / "multi_ext_graph.smpg")
        stats = await ingest_directory(str(project_dir), graph_path=graph_path, extensions=(".py", ".js"))

        assert stats["files"] == 2

    @pytest.mark.asyncio
    async def test_search_returns_nodes(self, tmp_path: Path):
        graph_path = str(tmp_path / "search_graph.smpg")
        sample_project = "tests/fixtures/sample_project"

        await ingest_directory(sample_project, graph_path=graph_path, clear=True)

        policy = AuthPolicy(
            open_mode="open",
            rate_limit_per_minute=1000,
            max_request_bytes=10 * 1024 * 1024,
        )
        app = create_app(graph_path=graph_path, auth_policy=policy)

        async with app.router.lifespan_context(app):
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
                payload = {
                    "jsonrpc": "2.0",
                    "method": "smp/search",
                    "params": {"query": "auth"},
                    "id": 1,
                }
                response = await ac.post("/rpc", json=payload)
                assert response.status_code == 200
                result = response.json()
                assert "result" in result

    @pytest.mark.asyncio
    async def test_navigate_to_node(self, tmp_path: Path):
        graph_path = str(tmp_path / "nav_graph.smpg")
        sample_project = "tests/fixtures/sample_project"

        await ingest_directory(sample_project, graph_path=graph_path, clear=True)

        policy = AuthPolicy(
            open_mode="open",
            rate_limit_per_minute=1000,
            max_request_bytes=10 * 1024 * 1024,
        )
        app = create_app(graph_path=graph_path, auth_policy=policy)

        async with app.router.lifespan_context(app):
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
                search_payload = {
                    "jsonrpc": "2.0",
                    "method": "smp/search",
                    "params": {"query": "service"},
                    "id": 1,
                }
                search_response = await ac.post("/rpc", json=search_payload)
                search_result = search_response.json()

                matches = (search_result.get("result") or {}).get("matches", [])
                if matches:
                    node_id = matches[0]["id"]
                    nav_payload = {
                        "jsonrpc": "2.0",
                        "method": "smp/navigate",
                        "params": {"query": node_id},
                        "id": 2,
                    }
                    nav_response = await ac.post("/rpc", json=nav_payload)
                    assert nav_response.status_code == 200

    @pytest.mark.asyncio
    async def test_context_retrieval(self, tmp_path: Path):
        graph_path = str(tmp_path / "context_graph.smpg")
        sample_project = "tests/fixtures/sample_project"

        await ingest_directory(sample_project, graph_path=graph_path, clear=True)

        policy = AuthPolicy(
            open_mode="open",
            rate_limit_per_minute=1000,
            max_request_bytes=10 * 1024 * 1024,
        )
        app = create_app(graph_path=graph_path, auth_policy=policy)

        async with app.router.lifespan_context(app):
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
                search_payload = {
                    "jsonrpc": "2.0",
                    "method": "smp/search",
                    "params": {"query": "user"},
                    "id": 1,
                }
                search_response = await ac.post("/rpc", json=search_payload)
                search_result = search_response.json()

                matches = (search_result.get("result") or {}).get("matches", [])
                if matches:
                    node_id = matches[0]["id"]
                    ctx_payload = {
                        "jsonrpc": "2.0",
                        "method": "smp/context",
                        "params": {"file_path": matches[0].get("file_path", node_id)},
                        "id": 2,
                    }
                    ctx_response = await ac.post("/rpc", json=ctx_payload)
                    assert ctx_response.status_code == 200

    @pytest.mark.asyncio
    async def test_ingestion_handles_parse_errors_gracefully(self, tmp_path: Path):
        error_dir = tmp_path / "error_project"
        error_dir.mkdir()
        invalid_py = error_dir / "broken.py"
        invalid_py.write_text("def ???): invalid syntax here @#$")

        graph_path = str(tmp_path / "error_graph.smpg")
        stats = await ingest_directory(str(error_dir), graph_path=graph_path)

        assert stats["errors"] >= 0

    @pytest.mark.asyncio
    async def test_partial_ingestion_incremental(self, tmp_path: Path):
        graph_path = str(tmp_path / "partial_graph.smpg")
        project_dir = tmp_path / "partial_project"
        project_dir.mkdir()

        file1 = project_dir / "first.py"
        file1.write_text("def first(): pass")

        stats1 = await ingest_directory(str(project_dir), graph_path=graph_path)
        initial_nodes = stats1["nodes"]

        file2 = project_dir / "second.py"
        file2.write_text("def second(): pass")

        stats2 = await ingest_directory(str(project_dir), graph_path=graph_path)
        assert stats2["nodes"] >= initial_nodes

    @pytest.mark.asyncio
    async def test_smp_query_handler_integration(self, tmp_path: Path):
        graph_path = str(tmp_path / "query_graph.smpg")
        sample_project = "tests/fixtures/sample_project"

        await ingest_directory(sample_project, graph_path=graph_path, clear=True)

        policy = AuthPolicy(
            open_mode="open",
            rate_limit_per_minute=1000,
            max_request_bytes=10 * 1024 * 1024,
        )
        app = create_app(graph_path=graph_path, auth_policy=policy)

        async with app.router.lifespan_context(app):
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
                payload = {
                    "jsonrpc": "2.0",
                    "method": "smp/query",
                    "params": {"query": "MATCH (n) RETURN n LIMIT 5"},
                    "id": 1,
                }
                response = await ac.post("/rpc", json=payload)
                assert response.status_code == 200
                result = response.json()
                assert "result" in result or "error" in result
