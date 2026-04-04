"""Tests for core msgspec data models."""

from __future__ import annotations

import msgspec

from smp.core.models import (
    EdgeType,
    GraphEdge,
    GraphNode,
    JsonRpcError,
    JsonRpcRequest,
    JsonRpcResponse,
    NodeType,
    SemanticInfo,
    Document,
    Language,
    ParseError,
    NavigateParams,
    TraceParams,
    ContextParams,
    ImpactParams,
    LocateParams,
    FlowParams,
    UpdateParams,
)
from tests.conftest import make_edge, make_node


class TestGraphNode:
    def test_defaults(self) -> None:
        node = make_node()
        assert node.id == "func_login"
        assert node.type == NodeType.FUNCTION
        assert node.name == "login"
        assert node.start_line == 10

    def test_fingerprint(self) -> None:
        node = make_node()
        assert node.fingerprint() == "src/auth/login.py::FUNCTION::login::10"

    def test_serialization_roundtrip(self) -> None:
        node = make_node(semantic=SemanticInfo(purpose="Auth", confidence=0.95))
        data = msgspec.json.encode(node)
        decoded = msgspec.json.decode(data, type=GraphNode)
        assert decoded.id == node.id
        assert decoded.semantic is not None
        assert decoded.semantic.purpose == "Auth"
        assert decoded.semantic.confidence == 0.95

    def test_empty_metadata(self) -> None:
        node = make_node()
        assert node.metadata == {}

    def test_all_node_types(self) -> None:
        for nt in NodeType:
            node = make_node(id=f"node_{nt.value}", type=nt)
            assert node.type == nt


class TestGraphEdge:
    def test_defaults(self) -> None:
        edge = make_edge()
        assert edge.source_id == "func_login"
        assert edge.target_id == "func_validate"
        assert edge.type == EdgeType.CALLS

    def test_serialization_roundtrip(self) -> None:
        edge = make_edge()
        data = msgspec.json.encode(edge)
        decoded = msgspec.json.decode(data, type=GraphEdge)
        assert decoded.source_id == edge.source_id
        assert decoded.type == edge.type

    def test_all_edge_types(self) -> None:
        for et in EdgeType:
            edge = make_edge(edge_type=et)
            assert edge.type == et


class TestSemanticInfo:
    def test_frozen(self) -> None:
        sem = SemanticInfo(purpose="test", confidence=0.5)
        assert sem.purpose == "test"
        # frozen=True means it's immutable
        try:
            sem.purpose = "other"  # type: ignore[misc]
            assert False, "Should raise"
        except AttributeError:
            pass

    def test_with_embedding(self) -> None:
        emb = [0.1, -0.2, 0.3]
        sem = SemanticInfo(purpose="test", embedding=emb, confidence=1.0)
        assert sem.embedding == emb

    def test_none_embedding(self) -> None:
        sem = SemanticInfo(purpose="test", confidence=0.0)
        assert sem.embedding is None


class TestDocument:
    def test_empty(self) -> None:
        doc = Document(file_path="test.py")
        assert doc.nodes == []
        assert doc.edges == []
        assert doc.errors == []

    def test_with_content(self) -> None:
        nodes = [make_node(), make_node(id="func_logout", name="logout")]
        edges = [make_edge()]
        doc = Document(
            file_path="src/auth.py",
            language=Language.PYTHON,
            nodes=nodes,
            edges=edges,
        )
        assert len(doc.nodes) == 2
        assert len(doc.edges) == 1

    def test_with_errors(self) -> None:
        doc = Document(
            file_path="bad.py",
            errors=[ParseError(message="unexpected token", line=5, column=10)],
        )
        assert len(doc.errors) == 1
        assert doc.errors[0].line == 5


class TestJsonRpc:
    def test_request(self) -> None:
        req = JsonRpcRequest(method="smp/navigate", params={"id": "x"}, id=1)
        assert req.jsonrpc == "2.0"
        assert req.method == "smp/navigate"

    def test_request_serialization(self) -> None:
        req = JsonRpcRequest(method="smp/context", params={"file_path": "test.py"}, id=42)
        data = msgspec.json.encode(req)
        decoded = msgspec.json.decode(data, type=JsonRpcRequest)
        assert decoded.id == 42
        assert decoded.params["file_path"] == "test.py"

    def test_response_success(self) -> None:
        resp = JsonRpcResponse(result={"nodes": 5}, id=1)
        assert resp.error is None

    def test_response_error(self) -> None:
        err = JsonRpcError(code=-32601, message="Method not found")
        resp = JsonRpcResponse(error=err, id=1)
        assert resp.result is None
        assert resp.error is not None
        assert resp.error.code == -32601


class TestQueryParams:
    def test_navigate_params(self) -> None:
        p = NavigateParams(entity_id="x")
        assert p.depth == 1

    def test_trace_params_defaults(self) -> None:
        p = TraceParams(start_id="x")
        assert p.edge_type == EdgeType.CALLS
        assert p.depth == 5
        assert p.max_nodes == 100

    def test_context_params(self) -> None:
        p = ContextParams(file_path="test.py", scope="review")
        assert p.include_semantic is True

    def test_update_params(self) -> None:
        p = UpdateParams(file_path="test.py", content="x = 1")
        assert p.language == Language.PYTHON

    def test_impact_params(self) -> None:
        p = ImpactParams(entity_id="x")
        assert p.depth == 10

    def test_locate_params(self) -> None:
        p = LocateParams(description="find auth logic")
        assert p.top_k == 5

    def test_flow_params(self) -> None:
        p = FlowParams(start_id="a", end_id="b")
        assert p.max_depth == 20
