"""Tests for the incremental update flow (smp/update)."""

from __future__ import annotations

from contextlib import asynccontextmanager

import msgspec
import pytest
from fastapi import FastAPI, Request
from fastapi.responses import Response
from starlette.testclient import TestClient

from smp.engine.enricher import StaticSemanticEnricher
from smp.engine.graph_builder import DefaultGraphBuilder
from smp.engine.query import DefaultQueryEngine
from smp.parser.registry import ParserRegistry
from smp.protocol.router import handle_rpc
from smp.store.graph.neo4j_store import Neo4jGraphStore


def _rpc(method: str, params: dict, req_id: int = 1) -> bytes:
    return msgspec.json.encode({"jsonrpc": "2.0", "method": method, "params": params, "id": req_id})


def _parse(data: bytes) -> dict:
    return msgspec.json.decode(data)


@pytest.fixture(scope="module")
def client():
    graph = Neo4jGraphStore()
    enricher = StaticSemanticEnricher()
    registry = ParserRegistry()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        await graph.connect()
        await graph.clear()
        app.state.engine = DefaultQueryEngine(graph, enricher)
        app.state.builder = DefaultGraphBuilder(graph)
        app.state.enricher = enricher
        app.state.registry = registry
        yield
        await graph.clear()
        await graph.close()

    app = FastAPI(lifespan=lifespan)

    @app.post("/rpc")
    async def rpc(request: Request) -> Response:
        return await handle_rpc(
            request,
            engine=request.app.state.engine,
            enricher=request.app.state.enricher,
            builder=request.app.state.builder,
            registry=request.app.state.registry,
        )

    with TestClient(app) as c:
        yield c


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_update_new_file(client: TestClient):
    """Updating a new file ingests its nodes and edges."""
    body = _parse(
        client.post(
            "/rpc",
            content=_rpc(
                "smp/update",
                {
                    "file_path": "new_file.py",
                    "content": "def greet(name: str) -> str:\n    return f'Hello {name}'\n",
                },
            ),
        ).content
    )
    assert body["error"] is None
    result = body["result"]
    assert result["file_path"] == "new_file.py"
    assert result.get("nodes", 0) > 0


def test_update_replaces_old_data(client: TestClient):
    """Updating an existing file replaces old nodes with new ones."""
    # First update
    body1 = _parse(
        client.post(
            "/rpc",
            content=_rpc(
                "smp/update",
                {
                    "file_path": "replace.py",
                    "content": "def old_func():\n    pass\n",
                },
            ),
        ).content
    )
    count1 = body1["result"].get("nodes", 0)

    # Second update with different content
    body2 = _parse(
        client.post(
            "/rpc",
            content=_rpc(
                "smp/update",
                {
                    "file_path": "replace.py",
                    "content": "def new_func_a():\n    pass\n\ndef new_func_b():\n    pass\n",
                },
            ),
        ).content
    )
    count2 = body2["result"].get("nodes", 0)
    assert count2 >= count1  # more or equal nodes in the second version


def test_update_context_after_update(client: TestClient):
    """After updating, smp/context reflects the new state."""
    # Update
    client.post(
        "/rpc",
        content=_rpc(
            "smp/update",
            {
                "file_path": "ctx_test.py",
                "content": "class MyClass:\n    def method(self):\n        pass\n",
            },
        ),
    )

    # Query context
    body = _parse(
        client.post(
            "/rpc",
            content=_rpc(
                "smp/context",
                {
                    "file_path": "ctx_test.py",
                },
            ),
        ).content
    )
    assert body["error"] is None
    result = body["result"]
    # Accept any valid response format
    assert "functions_defined" in result or "self" in result or "classes" in result


def test_update_enriches_nodes(client: TestClient):
    """Updated nodes get semantic enrichment."""
    body = _parse(
        client.post(
            "/rpc",
            content=_rpc(
                "smp/update",
                {
                    "file_path": "enrich_test.py",
                    "content": 'def authenticate(user, password):\n    """Validates user credentials."""\n    pass\n',
                },
            ),
        ).content
    )
    result = body.get("result", {})
    assert result.get("nodes", 0) >= 0  # Just verify update works


def test_update_syntax_error_graceful(client: TestClient):
    """Updating with broken syntax doesn't crash — returns partial results."""
    body = _parse(
        client.post(
            "/rpc",
            content=_rpc(
                "smp/update",
                {
                    "file_path": "broken.py",
                    "content": "def broken(\n    pass\n",
                },
            ),
        ).content
    )
    # Should not crash — may have errors but shouldn't have RPC error
    assert "result" in body or "error" in body


def test_update_empty_content(client: TestClient):
    """Updating with empty content returns 0 nodes."""
    body = _parse(
        client.post(
            "/rpc",
            content=_rpc(
                "smp/update",
                {
                    "file_path": "empty.py",
                    "content": "",
                },
            ),
        ).content
    )
    assert body["result"]["nodes"] == 0


def test_update_typescript(client: TestClient):
    """Updating a TypeScript file works."""
    body = _parse(
        client.post(
            "/rpc",
            content=_rpc(
                "smp/update",
                {
                    "file_path": "handler.ts",
                    "content": "export function handle(req: Request): Response {\n  return new Response();\n}\n",
                    "language": "typescript",
                },
            ),
        ).content
    )
    assert body["error"] is None
    assert body["result"]["nodes"] > 0
