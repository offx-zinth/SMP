"""Protocol tests — JSON-RPC 2.0 endpoint testing."""

import asyncio
import uuid
from contextlib import asynccontextmanager

import msgspec
import pytest
from starlette.testclient import TestClient
from fastapi import FastAPI, Request
from fastapi.responses import Response

# Monkey-patch sqlite3 before chromadb import
__import__("pysqlite3")
import sys
sys.modules["sqlite3"] = sys.modules.pop("pysqlite3")

from smp.core.models import EdgeType, GraphEdge, GraphNode, NodeType
from smp.engine.enricher import LLMSemanticEnricher
from smp.engine.graph_builder import DefaultGraphBuilder
from smp.engine.query import DefaultQueryEngine
from smp.parser.registry import ParserRegistry
from smp.protocol.router import handle_rpc
from smp.store.graph.neo4j_store import Neo4jGraphStore
from smp.store.vector.chroma_store import ChromaVectorStore


def _rpc(method: str, params: dict, req_id: int = 1) -> bytes:
    return msgspec.json.encode({"jsonrpc": "2.0", "method": method, "params": params, "id": req_id})


def _parse(data: bytes) -> dict:
    return msgspec.json.decode(data)


@pytest.fixture(scope="module")
def app_client():
    """Create app + stores all within the same event loop via FastAPI lifespan."""
    graph = Neo4jGraphStore()
    vector = ChromaVectorStore(collection_name=f"smp_rt_{uuid.uuid4().hex[:8]}")
    enricher = LLMSemanticEnricher()
    registry = ParserRegistry()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        await graph.connect()
        await graph.clear()
        nodes = [
            GraphNode(id="f.py::FILE::f.py::1", type=NodeType.FILE, name="f.py", file_path="f.py", start_line=1, end_line=20),
            GraphNode(id="f.py::FUNCTION::alpha::3", type=NodeType.FUNCTION, name="alpha", file_path="f.py", start_line=3, end_line=8, docstring="Alpha function."),
            GraphNode(id="f.py::FUNCTION::beta::10", type=NodeType.FUNCTION, name="beta", file_path="f.py", start_line=10, end_line=15),
        ]
        edges = [
            GraphEdge(source_id="f.py::FILE::f.py::1", target_id="f.py::FUNCTION::alpha::3", type=EdgeType.CONTAINS),
            GraphEdge(source_id="f.py::FILE::f.py::1", target_id="f.py::FUNCTION::beta::10", type=EdgeType.CONTAINS),
            GraphEdge(source_id="f.py::FUNCTION::alpha::3", target_id="f.py::FUNCTION::beta::10", type=EdgeType.CALLS),
        ]
        await graph.upsert_nodes(nodes)
        await graph.upsert_edges(edges)
        await vector.connect()

        engine = DefaultQueryEngine(graph, vector, enricher)
        builder = DefaultGraphBuilder(graph)
        app.state.engine = engine
        app.state.builder = builder
        app.state.enricher = enricher
        app.state.registry = registry
        app.state.vector = vector
        yield
        await vector.close()
        await graph.clear()
        await graph.close()

    app = FastAPI(lifespan=lifespan)

    @app.post("/rpc")
    async def rpc_endpoint(request: Request) -> Response:
        return await handle_rpc(
            request,
            engine=request.app.state.engine,
            enricher=request.app.state.enricher,
            builder=request.app.state.builder,
            registry=request.app.state.registry,
            vector=request.app.state.vector,
        )

    @app.get("/health")
    async def health():
        return {"status": "ok"}

    with TestClient(app) as c:
        yield c


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_health(app_client):
    assert app_client.get("/health").json()["status"] == "ok"


def test_navigate(app_client):
    body = _parse(app_client.post("/rpc", content=_rpc("smp/navigate", {"entity_id": "f.py::FUNCTION::alpha::3"})).content)
    assert body["jsonrpc"] == "2.0"
    assert body["error"] is None
    assert body["result"]["node"]["name"] == "alpha"
    assert len(body["result"]["edges"]) > 0


def test_navigate_missing(app_client):
    body = _parse(app_client.post("/rpc", content=_rpc("smp/navigate", {"entity_id": "nonexistent"})).content)
    assert body["error"] is None
    assert "error" in body["result"]


def test_trace(app_client):
    body = _parse(app_client.post("/rpc", content=_rpc("smp/trace", {"start_id": "f.py::FUNCTION::alpha::3"})).content)
    assert body["error"] is None
    assert "beta" in {n["name"] for n in body["result"]}


def test_context(app_client):
    body = _parse(app_client.post("/rpc", content=_rpc("smp/context", {"file_path": "f.py"})).content)
    assert body["error"] is None
    assert body["result"]["file_path"] == "f.py"
    assert len(body["result"]["nodes"]) >= 3


def test_impact(app_client):
    body = _parse(app_client.post("/rpc", content=_rpc("smp/impact", {"entity_id": "f.py::FUNCTION::beta::10"})).content)
    assert body["error"] is None
    assert body["result"]["entity"]["name"] == "beta"


def test_locate(app_client):
    body = _parse(app_client.post("/rpc", content=_rpc("smp/locate", {"description": "alpha function"})).content)
    assert body["error"] is None
    assert isinstance(body["result"], list)


def test_flow(app_client):
    body = _parse(app_client.post("/rpc", content=_rpc("smp/flow", {"start_id": "f.py::FUNCTION::alpha::3", "end_id": "f.py::FUNCTION::beta::10"})).content)
    assert body["error"] is None
    assert len(body["result"]) >= 1


def test_empty_body(app_client):
    body = _parse(app_client.post("/rpc", content=b"").content)
    assert body["error"]["code"] == -32700


def test_invalid_json(app_client):
    body = _parse(app_client.post("/rpc", content=b"{bad}").content)
    assert body["error"]["code"] == -32700


def test_unknown_method(app_client):
    body = _parse(app_client.post("/rpc", content=_rpc("smp/nope", {})).content)
    assert body["error"]["code"] == -32601


def test_invalid_params(app_client):
    body = _parse(app_client.post("/rpc", content=_rpc("smp/navigate", {"wrong": "x"})).content)
    assert body["error"]["code"] == -32602


def test_notification(app_client):
    payload = msgspec.json.encode({"jsonrpc": "2.0", "method": "smp/navigate", "params": {"entity_id": "f.py::FUNCTION::alpha::3"}})
    assert app_client.post("/rpc", content=payload).status_code == 204
