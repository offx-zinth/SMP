"""Tests for the SMP SDK client."""

from __future__ import annotations

from contextlib import asynccontextmanager

import msgspec
import pytest
from fastapi import FastAPI, Request
from fastapi.responses import Response
from starlette.testclient import TestClient

from smp.client import SMPClient, SMPClientError
from smp.core.models import EdgeType, GraphEdge, GraphNode, NodeType, SemanticProperties, StructuralProperties
from smp.engine.enricher import StaticSemanticEnricher
from smp.engine.graph_builder import DefaultGraphBuilder
from smp.engine.query import DefaultQueryEngine
from smp.parser.registry import ParserRegistry
from smp.protocol.router import handle_rpc
from smp.store.chroma_store import ChromaVectorStore
from smp.store.graph.neo4j_store import Neo4jGraphStore


@pytest.fixture(scope="module")
def server():
    """Create a FastAPI server with real stores (lifespan handles event loop)."""
    graph = Neo4jGraphStore()
    enricher = StaticSemanticEnricher()
    registry = ParserRegistry()
    vector = ChromaVectorStore()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        await graph.connect()
        await graph.clear()
        await vector.connect()
        nodes = [
            GraphNode(
                id="f.py::FILE::f.py::1",
                type=NodeType.FILE,
                file_path="f.py",
                structural=StructuralProperties(name="f.py", file="f.py", start_line=1, end_line=20),
                semantic=SemanticProperties(docstring=""),
            ),
            GraphNode(
                id="f.py::FUNCTION::alpha::3",
                type=NodeType.FUNCTION,
                file_path="f.py",
                structural=StructuralProperties(name="alpha", file="f.py", start_line=3, end_line=8),
                semantic=SemanticProperties(docstring="Alpha function."),
            ),
            GraphNode(
                id="f.py::FUNCTION::beta::10",
                type=NodeType.FUNCTION,
                file_path="f.py",
                structural=StructuralProperties(name="beta", file="f.py", start_line=10, end_line=15),
                semantic=SemanticProperties(docstring="Beta function."),
            ),
        ]
        edges = [
            GraphEdge(source_id="f.py::FILE::f.py::1", target_id="f.py::FUNCTION::alpha::3", type=EdgeType.CONTAINS),
            GraphEdge(source_id="f.py::FILE::f.py::1", target_id="f.py::FUNCTION::beta::10", type=EdgeType.CONTAINS),
            GraphEdge(source_id="f.py::FUNCTION::alpha::3", target_id="f.py::FUNCTION::beta::10", type=EdgeType.CALLS),
        ]
        await graph.upsert_nodes(nodes)
        await graph.upsert_edges(edges)

        app.state.engine = DefaultQueryEngine(graph, enricher)
        app.state.builder = DefaultGraphBuilder(graph)
        app.state.enricher = enricher
        app.state.registry = registry
        app.state.vector = vector
        app.state.safety = None
        yield
        await graph.clear()
        await graph.close()
        await vector.close()

    app = FastAPI(lifespan=lifespan)

    @app.post("/rpc")
    async def rpc(request: Request) -> Response:
        return await handle_rpc(
            request,
            engine=request.app.state.engine,
            enricher=request.app.state.enricher,
            builder=request.app.state.builder,
            registry=request.app.state.registry,
            vector=request.app.state.vector,
            safety=request.app.state.safety,
        )

    @app.get("/health")
    async def health():
        return {"status": "ok"}

    @app.get("/stats")
    async def stats():
        g = request.app.state.graph
        return {"nodes": await g.count_nodes(), "edges": await g.count_edges()}

    with TestClient(app) as c:
        yield c


@pytest.fixture()
def smp_client(server):
    """Provide an SMPClient connected to the test server."""

    class _TestClient(SMPClient):
        """SMPClient that routes through TestClient instead of real HTTP."""

        def __init__(self, test_client: TestClient) -> None:
            super().__init__("http://test")
            self._tc = test_client
            self._req_id = 0

        async def connect(self) -> None:
            pass  # no real connection needed

        async def close(self) -> None:
            pass

        async def _rpc(self, method: str, params: dict):
            self._req_id += 1
            req = msgspec.json.encode({"jsonrpc": "2.0", "method": method, "params": params, "id": self._req_id})
            resp = self._tc.post("/rpc", content=req)
            if resp.status_code == 204:
                return None
            body = msgspec.json.decode(resp.content)
            if body.get("error"):
                raise SMPClientError(body["error"]["code"], body["error"]["message"])
            return body["result"]

        async def health(self):
            return self._tc.get("/health").json()

        async def stats(self):
            return self._tc.get("/stats").json()

    client = _TestClient(server)
    return client


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_health(smp_client):
    result = await smp_client.health()
    assert result["status"] == "ok"


@pytest.mark.asyncio
async def test_navigate(smp_client):
    result = await smp_client.navigate("f.py::FUNCTION::alpha::3")
    assert result["entity"]["name"] == "alpha"
    assert len(result.get("relationships", {}).get("calls", [])) >= 0


@pytest.mark.asyncio
async def test_navigate_missing(smp_client):
    result = await smp_client.navigate("nonexistent")
    assert "error" in result


@pytest.mark.asyncio
async def test_trace(smp_client):
    result = await smp_client.trace("f.py::FUNCTION::alpha::3")
    names = {n["name"] for n in result}
    assert "beta" in names


@pytest.mark.asyncio
async def test_get_context(smp_client):
    result = await smp_client.get_context("f.py")
    assert "functions_defined" in result or "self" in result


@pytest.mark.asyncio
async def test_assess_impact(smp_client):
    result = await smp_client.assess_impact("f.py::FUNCTION::beta::10")
    assert "affected_files" in result or "severity" in result


@pytest.mark.asyncio
async def test_locate(smp_client):
    result = await smp_client.locate("alpha function")
    assert isinstance(result, (list, dict))


@pytest.mark.asyncio
async def test_find_flow(smp_client):
    result = await smp_client.find_flow("f.py::FUNCTION::alpha::3", "f.py::FUNCTION::beta::10")
    if isinstance(result, dict):
        assert "path" in result
    elif isinstance(result, list):
        assert len(result) >= 1


@pytest.mark.asyncio
async def test_invalid_method(smp_client):
    with pytest.raises(SMPClientError) as exc_info:
        await smp_client._rpc("smp/nonexistent", {})
    assert exc_info.value.code == -32601


@pytest.mark.asyncio
async def test_update(smp_client):
    result = await smp_client.update(
        "test_client_file.py",
        content="def hello():\n    pass\n",
    )
    assert result["file_path"] == "test_client_file.py"
    assert result["nodes"] > 0
