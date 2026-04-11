"""Tests for core msgspec data models — SMP(3) partitioned schema."""

from __future__ import annotations

import msgspec

from smp.core.models import (
    AnnotateParams,
    AuditGetParams,
    CheckpointParams,
    ContextParams,
    Document,
    DryRunParams,
    EdgeType,
    EnrichBatchParams,
    EnrichParams,
    FlowParams,
    GraphEdge,
    GraphNode,
    GuardCheckParams,
    ImpactParams,
    JsonRpcError,
    JsonRpcRequest,
    JsonRpcResponse,
    Language,
    LocateParams,
    LockParams,
    NavigateParams,
    NodeType,
    ParseError,
    RollbackParams,
    SearchParams,
    SemanticProperties,
    SessionCloseParams,
    SessionOpenParams,
    StructuralProperties,
    TagParams,
    TraceParams,
    UpdateParams,
)
from tests.conftest import make_edge, make_node


class TestGraphNode:
    def test_defaults(self) -> None:
        node = make_node()
        assert node.id == "func_login"
        assert node.type == NodeType.FUNCTION
        assert node.structural.name == "login"
        assert node.structural.start_line == 10

    def test_fingerprint(self) -> None:
        node = make_node()
        assert node.fingerprint() == "src/auth/login.py::Function::login::10"

    def test_serialization_roundtrip(self) -> None:
        node = make_node(
            semantic=SemanticProperties(
                docstring="Authenticate user.",
                status="enriched",
                source_hash="abc123",
            )
        )
        data = msgspec.json.encode(node)
        decoded = msgspec.json.decode(data, type=GraphNode)
        assert decoded.id == node.id
        assert decoded.semantic is not None
        assert decoded.semantic.docstring == "Authenticate user."
        assert decoded.semantic.status == "enriched"

    def test_structural_partition(self) -> None:
        node = make_node()
        assert node.structural.signature == "def login(user: User) -> Token:"
        assert node.structural.lines == 16
        assert node.structural.complexity == 0

    def test_semantic_partition(self) -> None:
        node = make_node()
        assert node.semantic.status == "enriched"
        assert node.semantic.docstring == "Authenticate user and return token."
        assert node.semantic.decorators == []
        assert node.semantic.tags == []

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


class TestStructuralProperties:
    def test_defaults(self) -> None:
        sp = StructuralProperties()
        assert sp.name == ""
        assert sp.complexity == 0
        assert sp.parameters == 0

    def test_frozen(self) -> None:
        sp = StructuralProperties(name="test", lines=10)
        try:
            sp.name = "other"  # type: ignore[misc]
        except AttributeError:
            pass
        else:
            raise AssertionError("Should raise")


class TestSemanticProperties:
    def test_defaults(self) -> None:
        sp = SemanticProperties()
        assert sp.status == "no_metadata"
        assert sp.docstring == ""
        assert sp.description is None
        assert sp.manually_set is False
        assert sp.source_hash == ""

    def test_with_annotations(self) -> None:
        from smp.core.models import Annotations
        sp = SemanticProperties(
            docstring="Test function.",
            annotations=Annotations(
                params={"x": "int"},
                returns="str",
                throws=["ValueError"],
            ),
        )
        assert sp.annotations is not None
        assert sp.annotations.params == {"x": "int"}
        assert sp.annotations.returns == "str"
        assert sp.annotations.throws == ["ValueError"]


class TestDocument:
    def test_empty(self) -> None:
        doc = Document(file_path="test.py")
        assert doc.nodes == []
        assert doc.edges == []
        assert doc.errors == []

    def test_with_content(self) -> None:
        nodes = [
            make_node(),
            make_node(
                id="func_logout",
                structural=StructuralProperties(
                    name="logout",
                    file="src/auth/login.py",
                    signature="def logout():",
                    start_line=30,
                    end_line=35,
                    lines=6,
                ),
            ),
        ]
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
        p = NavigateParams(query="login")
        assert p.include_relationships is True

    def test_trace_params_defaults(self) -> None:
        p = TraceParams(start="x")
        assert p.relationship == "CALLS"
        assert p.depth == 3

    def test_context_params(self) -> None:
        p = ContextParams(file_path="test.py", scope="review")
        assert p.scope == "review"

    def test_update_params(self) -> None:
        p = UpdateParams(file_path="test.py", content="x = 1")
        assert p.language == Language.PYTHON

    def test_impact_params(self) -> None:
        p = ImpactParams(entity="x")
        assert p.change_type == "delete"

    def test_locate_params(self) -> None:
        p = LocateParams(query="find auth logic")
        assert p.top_k == 5

    def test_flow_params(self) -> None:
        p = FlowParams(start="a", end="b")
        assert p.flow_type == "data"


class TestSMP3Params:
    def test_enrich_params(self) -> None:
        p = EnrichParams(node_id="func_x")
        assert p.force is False

    def test_enrich_batch_params(self) -> None:
        p = EnrichBatchParams(scope="package:src/auth")
        assert p.force is False

    def test_session_open_params(self) -> None:
        p = SessionOpenParams(agent_id="agent_1", task="fix bug", scope=["src/auth.py"], mode="write")
        assert p.mode == "write"

    def test_session_close_params(self) -> None:
        p = SessionCloseParams(session_id="ses_1", status="completed")
        assert p.status == "completed"

    def test_guard_check_params(self) -> None:
        p = GuardCheckParams(session_id="ses_1", target="src/auth.py")
        assert p.target == "src/auth.py"

    def test_dryrun_params(self) -> None:
        p = DryRunParams(session_id="ses_1", file_path="src/auth.py", proposed_content="x=1")
        assert p.proposed_content == "x=1"

    def test_checkpoint_params(self) -> None:
        p = CheckpointParams(session_id="ses_1", files=["src/auth.py"])
        assert len(p.files) == 1

    def test_rollback_params(self) -> None:
        p = RollbackParams(session_id="ses_1", checkpoint_id="chk_1")
        assert p.checkpoint_id == "chk_1"

    def test_search_params(self) -> None:
        p = SearchParams(query="auth login", match="all")
        assert p.match == "all"

    def test_annotate_params(self) -> None:
        p = AnnotateParams(node_id="func_x", description="Handles login", tags=["auth"])
        assert p.force is False

    def test_tag_params(self) -> None:
        p = TagParams(scope="package:src/auth", tags=["billing"], action="add")
        assert p.action == "add"

    def test_lock_params(self) -> None:
        p = LockParams(session_id="ses_1", files=["src/auth.py"])
        assert len(p.files) == 1

    def test_audit_get_params(self) -> None:
        p = AuditGetParams(audit_log_id="aud_1")
        assert p.audit_log_id == "aud_1"
