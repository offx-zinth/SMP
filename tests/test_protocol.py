"""Protocol tests — JSON-RPC 2.0 endpoint testing — SMP(3)."""

import asyncio
import uuid
from contextlib import asynccontextmanager

import msgspec
import pytest
from starlette.testclient import TestClient
from fastapi import FastAPI, Request
from fastapi.responses import Response

__import__("pysqlite3")
import sys
sys.modules["sqlite3"] = sys.modules.pop("pysqlite3")

from smp.core.models import (
    EdgeType,
    GraphEdge,
    GraphNode,
    NodeType,
    SemanticProperties,
    StructuralProperties,
)
from smp.engine.enricher import StaticSemanticEnricher
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


def _make_node(id: str, type: NodeType, name: str, file_path: str, start_line: int = 1, end_line: int = 10, docstring: str = "") -> GraphNode:
    return GraphNode(
        id=id,
        type=type,
        file_path=file_path,
        structural=StructuralProperties(
            name=name,
            file=file_path,
            signature=f"{type.value.lower()} {name}",
            start_line=start_line,
            end_line=end_line,
            lines=end_line - start_line + 1,
        ),
        semantic=SemanticProperties(
            docstring=docstring,
            status="enriched" if docstring else "no_metadata",
        ),
    )


@pytest.fixture(scope="module")
def app_client():
    """Create app + stores all within the same event loop via FastAPI lifespan."""
    graph = Neo4jGraphStore()
    vector = ChromaVectorStore(collection_name=f"smp_rt_{uuid.uuid4().hex[:8]}")
    enricher = StaticSemanticEnricher()
    registry = ParserRegistry()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        await graph.connect()
        await graph.clear()
        nodes = [
            _make_node("f.py::File::f.py::1", NodeType.FILE, "f.py", "f.py", 1, 20),
            _make_node("f.py::Function::alpha::3", NodeType.FUNCTION, "alpha", "f.py", 3, 8, docstring="Alpha function."),
            _make_node("f.py::Function::beta::10", NodeType.FUNCTION, "beta", "f.py", 10, 15),
        ]
        edges = [
            GraphEdge(source_id="f.py::File::f.py::1", target_id="f.py::Function::alpha::3", type=EdgeType.DEFINES),
            GraphEdge(source_id="f.py::File::f.py::1", target_id="f.py::Function::beta::10", type=EdgeType.DEFINES),
            GraphEdge(source_id="f.py::Function::alpha::3", target_id="f.py::Function::beta::10", type=EdgeType.CALLS),
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
        app.state.safety = None
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
            safety=request.app.state.safety,
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
    body = _parse(app_client.post("/rpc", content=_rpc("smp/navigate", {"query": "f.py::Function::alpha::3"})).content)
    assert body["jsonrpc"] == "2.0"
    assert body["error"] is None
    assert body["result"]["entity"]["name"] == "alpha"


def test_navigate_missing(app_client):
    body = _parse(app_client.post("/rpc", content=_rpc("smp/navigate", {"query": "nonexistent"})).content)
    assert body["error"] is None
    assert "error" in body["result"]


def test_trace(app_client):
    body = _parse(app_client.post("/rpc", content=_rpc("smp/trace", {"start": "f.py::Function::alpha::3"})).content)
    assert body["error"] is None
    assert "beta" in {n["name"] for n in body["result"]}


def test_context(app_client):
    body = _parse(app_client.post("/rpc", content=_rpc("smp/context", {"file_path": "f.py"})).content)
    assert body["error"] is None
    assert len(body["result"]["functions_defined"]) >= 2


def test_impact(app_client):
    body = _parse(app_client.post("/rpc", content=_rpc("smp/impact", {"entity": "f.py::Function::beta::10"})).content)
    assert body["error"] is None
    assert body["result"]["entity"]["name"] == "beta"


def test_locate(app_client):
    body = _parse(app_client.post("/rpc", content=_rpc("smp/locate", {"query": "alpha function"})).content)
    assert body["error"] is None
    assert isinstance(body["result"], list)


def test_flow(app_client):
    body = _parse(app_client.post("/rpc", content=_rpc("smp/flow", {"start": "f.py::Function::alpha::3", "end": "f.py::Function::beta::10"})).content)
    assert body["error"] is None
    assert len(body["result"]["path"]) >= 1


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
    payload = msgspec.json.encode({"jsonrpc": "2.0", "method": "smp/navigate", "params": {"query": "f.py::Function::alpha::3"}})
    assert app_client.post("/rpc", content=payload).status_code == 204
