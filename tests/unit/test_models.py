"""Comprehensive unit tests for smp.core.models."""

from __future__ import annotations

import pytest

from smp.core.models import (
    AnnotateBulkItem,
    AnnotateBulkParams,
    AnnotateParams,
    Annotations,
    AuditGetParams,
    BatchUpdateParams,
    CheckpointParams,
    CommunityBoundariesParams,
    CommunityDetectParams,
    CommunityGetParams,
    CommunityListParams,
    ConflictParams,
    ContextParams,
    DiffParams,
    Document,
    DryRunParams,
    EdgeType,
    EnrichBatchParams,
    EnrichParams,
    EnrichStaleParams,
    EnrichStatusParams,
    FlowParams,
    GraphEdge,
    GraphNode,
    GuardCheckParams,
    ImpactParams,
    InlineComment,
    IntegrityBaselineParams,
    IntegrityCheckParams,
    JsonRpcError,
    JsonRpcRequest,
    JsonRpcResponse,
    Language,
    LocateParams,
    LockParams,
    MerkleImportParams,
    MerkleSyncParams,
    NavigateParams,
    NodeType,
    ParseError,
    PlanParams,
    PRCreateParams,
    ReindexParams,
    ReviewApproveParams,
    ReviewCommentParams,
    ReviewCreateParams,
    ReviewRejectParams,
    RollbackParams,
    RuntimeEdge,
    RuntimeTrace,
    SandboxExecuteParams,
    SandboxKillParams,
    SandboxSpawnParams,
    SearchParams,
    SemanticProperties,
    SessionCloseParams,
    SessionOpenParams,
    SessionRecoverParams,
    StructuralProperties,
    TagParams,
    TelemetryHotParams,
    TelemetryNodeParams,
    TelemetryParams,
    TraceParams,
    UpdateParams,
    VectorSearchParams,
    WhyParams,
)


class TestNodeType:
    def test_all_node_types_exist(self) -> None:
        assert NodeType.REPOSITORY == "Repository"
        assert NodeType.PACKAGE == "Package"
        assert NodeType.FILE == "File"
        assert NodeType.CLASS == "Class"
        assert NodeType.FUNCTION == "Function"
        assert NodeType.VARIABLE == "Variable"
        assert NodeType.INTERFACE == "Interface"
        assert NodeType.TEST == "Test"
        assert NodeType.CONFIG == "Config"

    def test_node_type_is_strenum(self) -> None:
        assert isinstance(NodeType.FILE, str)
        assert NodeType.FILE == "File"

    def test_node_type_value(self) -> None:
        assert NodeType.FUNCTION.value == "Function"

    def test_node_type_from_string(self) -> None:
        assert NodeType("File") == NodeType.FILE


class TestEdgeType:
    def test_all_edge_types_exist(self) -> None:
        assert EdgeType.CONTAINS == "CONTAINS"
        assert EdgeType.IMPORTS == "IMPORTS"
        assert EdgeType.DEFINES == "DEFINES"
        assert EdgeType.CALLS == "CALLS"
        assert EdgeType.CALLS_RUNTIME == "CALLS_RUNTIME"
        assert EdgeType.INHERITS == "INHERITS"
        assert EdgeType.IMPLEMENTS == "IMPLEMENTS"
        assert EdgeType.DEPENDS_ON == "DEPENDS_ON"
        assert EdgeType.TESTS == "TESTS"
        assert EdgeType.USES == "USES"
        assert EdgeType.REFERENCES == "REFERENCES"

    def test_edge_type_is_strenum(self) -> None:
        assert isinstance(EdgeType.CALLS, str)
        assert EdgeType.CALLS == "CALLS"

    def test_edge_type_value(self) -> None:
        assert EdgeType.CALLS.value == "CALLS"


class TestLanguage:
    def test_all_languages_exist(self) -> None:
        assert Language.PYTHON == "python"
        assert Language.JAVASCRIPT == "javascript"
        assert Language.TYPESCRIPT == "typescript"
        assert Language.JAVA == "java"
        assert Language.C == "c"
        assert Language.CPP == "cpp"
        assert Language.CSHARP == "csharp"
        assert Language.GO == "go"
        assert Language.RUST == "rust"
        assert Language.PHP == "php"
        assert Language.SWIFT == "swift"
        assert Language.KOTLIN == "kotlin"
        assert Language.RUBY == "ruby"
        assert Language.MATLAB == "matlab"
        assert Language.UNKNOWN == "unknown"

    def test_language_is_strenum(self) -> None:
        assert isinstance(Language.PYTHON, str)
        assert Language.PYTHON == "python"


class TestStructuralProperties:
    def test_defaults(self) -> None:
        sp = StructuralProperties()
        assert sp.name == ""
        assert sp.file == ""
        assert sp.signature == ""
        assert sp.start_line == 0
        assert sp.end_line == 0
        assert sp.complexity == 0
        assert sp.lines == 0
        assert sp.parameters == 0

    def test_with_values(self) -> None:
        sp = StructuralProperties(
            name="my_function",
            file="/path/to/file.py",
            signature="def my_function(arg1: int) -> str",
            start_line=10,
            end_line=20,
            complexity=5,
            lines=11,
            parameters=1,
        )
        assert sp.name == "my_function"
        assert sp.file == "/path/to/file.py"
        assert sp.signature == "def my_function(arg1: int) -> str"
        assert sp.start_line == 10
        assert sp.end_line == 20
        assert sp.complexity == 5
        assert sp.lines == 11
        assert sp.parameters == 1

    def test_empty_strings_allowed(self) -> None:
        sp = StructuralProperties(name="", file="", signature="")
        assert sp.name == ""
        assert sp.file == ""
        assert sp.signature == ""

    def test_zero_values_allowed(self) -> None:
        sp = StructuralProperties(start_line=0, end_line=0, complexity=0, lines=0, parameters=0)
        assert sp.start_line == 0
        assert sp.end_line == 0

    def test_frozen_immutable(self) -> None:
        sp = StructuralProperties(name="test")
        with pytest.raises(AttributeError):
            sp.name = "changed"

    def test_negative_line_numbers(self) -> None:
        sp = StructuralProperties(start_line=-1, end_line=-1)
        assert sp.start_line == -1
        assert sp.end_line == -1

    def test_large_values(self) -> None:
        sp = StructuralProperties(complexity=10000, lines=1000000, parameters=100)
        assert sp.complexity == 10000
        assert sp.lines == 1000000
        assert sp.parameters == 100


class TestInlineComment:
    def test_defaults(self) -> None:
        ic = InlineComment()
        assert ic.line == 0
        assert ic.text == ""

    def test_with_values(self) -> None:
        ic = InlineComment(line=42, text="# This is a comment")
        assert ic.line == 42
        assert ic.text == "# This is a comment"

    def test_empty_text_allowed(self) -> None:
        ic = InlineComment(line=10, text="")
        assert ic.text == ""

    def test_frozen_immutable(self) -> None:
        ic = InlineComment(line=1, text="test")
        with pytest.raises(AttributeError):
            ic.text = "changed"


class TestAnnotations:
    def test_defaults(self) -> None:
        ann = Annotations()
        assert ann.params == {}
        assert ann.returns is None
        assert ann.throws == []

    def test_with_values(self) -> None:
        ann = Annotations(
            params={"arg1": "int", "arg2": "str"},
            returns="str",
            throws=["ValueError", "TypeError"],
        )
        assert ann.params == {"arg1": "int", "arg2": "str"}
        assert ann.returns == "str"
        assert ann.throws == ["ValueError", "TypeError"]

    def test_empty_params(self) -> None:
        ann = Annotations(params={})
        assert ann.params == {}

    def test_empty_throws(self) -> None:
        ann = Annotations(throws=[])
        assert ann.throws == []

    def test_frozen_immutable(self) -> None:
        ann = Annotations(params={"key": "value"})
        with pytest.raises(AttributeError):
            ann.params = {"new": "value"}


class TestSemanticProperties:
    def test_defaults(self) -> None:
        sp = SemanticProperties()
        assert sp.status == "no_metadata"
        assert sp.docstring == ""
        assert sp.description is None
        assert sp.inline_comments == []
        assert sp.decorators == []
        assert sp.annotations is None
        assert sp.tags == []
        assert sp.score == 0.0
        assert sp.manually_set is False
        assert sp.source_hash == ""
        assert sp.enriched_at == ""

    def test_with_values(self) -> None:
        sp = SemanticProperties(
            status="enriched",
            docstring="This is a docstring",
            description="A description",
            inline_comments=[InlineComment(line=1, text="comment")],
            decorators=["@property", "@abstractmethod"],
            annotations=Annotations(returns="int"),
            tags=["important", "api"],
            score=0.95,
            manually_set=True,
            source_hash="abc123",
            enriched_at="2024-01-01T00:00:00Z",
        )
        assert sp.status == "enriched"
        assert sp.docstring == "This is a docstring"
        assert sp.description == "A description"
        assert len(sp.inline_comments) == 1
        assert sp.decorators == ["@property", "@abstractmethod"]
        assert sp.annotations is not None
        assert sp.tags == ["important", "api"]
        assert sp.score == 0.95
        assert sp.manually_set is True
        assert sp.source_hash == "abc123"
        assert sp.enriched_at == "2024-01-01T00:00:00Z"

    def test_score_range(self) -> None:
        sp = SemanticProperties(score=1.0)
        assert sp.score == 1.0
        sp = SemanticProperties(score=0.0)
        assert sp.score == 0.0
        sp = SemanticProperties(score=0.5)
        assert sp.score == 0.5

    def test_empty_docstring(self) -> None:
        sp = SemanticProperties(docstring="")
        assert sp.docstring == ""

    def test_empty_tags(self) -> None:
        sp = SemanticProperties(tags=[])
        assert sp.tags == []

    def test_empty_decorators(self) -> None:
        sp = SemanticProperties(decorators=[])
        assert sp.decorators == []

    def test_manually_set_false_by_default(self) -> None:
        sp = SemanticProperties()
        assert sp.manually_set is False


class TestGraphNode:
    def test_required_fields_only(self) -> None:
        node = GraphNode(id="node1", type=NodeType.FILE, file_path="/path/to/file.py")
        assert node.id == "node1"
        assert node.type == NodeType.FILE
        assert node.file_path == "/path/to/file.py"
        assert isinstance(node.structural, StructuralProperties)
        assert isinstance(node.semantic, SemanticProperties)

    def test_with_all_fields(self) -> None:
        node = GraphNode(
            id="node1",
            type=NodeType.FUNCTION,
            file_path="/path/to/file.py",
            structural=StructuralProperties(name="my_func", complexity=5),
            semantic=SemanticProperties(status="enriched", score=0.9),
        )
        assert node.id == "node1"
        assert node.type == NodeType.FUNCTION
        assert node.structural.name == "my_func"
        assert node.structural.complexity == 5
        assert node.semantic.status == "enriched"
        assert node.semantic.score == 0.9

    def test_fingerprint(self) -> None:
        node = GraphNode(
            id="node1",
            type=NodeType.FUNCTION,
            file_path="/path/to/file.py",
            structural=StructuralProperties(name="my_func", start_line=10),
        )
        fp = node.fingerprint()
        assert fp == "/path/to/file.py::Function::my_func::10"

    def test_fingerprint_with_different_lines(self) -> None:
        node1 = GraphNode(
            id="node1",
            type=NodeType.FUNCTION,
            file_path="/path/to/file.py",
            structural=StructuralProperties(name="my_func", start_line=10),
        )
        node2 = GraphNode(
            id="node2",
            type=NodeType.FUNCTION,
            file_path="/path/to/file.py",
            structural=StructuralProperties(name="my_func", start_line=20),
        )
        assert node1.fingerprint() != node2.fingerprint()

    def test_missing_required_id(self) -> None:
        with pytest.raises(TypeError):
            GraphNode(type=NodeType.FILE, file_path="/path/to/file.py")

    def test_missing_required_type(self) -> None:
        with pytest.raises(TypeError):
            GraphNode(id="node1", file_path="/path/to/file.py")

    def test_missing_required_file_path(self) -> None:
        with pytest.raises(TypeError):
            GraphNode(id="node1", type=NodeType.FILE)

    def test_empty_string_id(self) -> None:
        node = GraphNode(id="", type=NodeType.FILE, file_path="/path/to/file.py")
        assert node.id == ""

    def test_node_type_variations(self) -> None:
        for node_type in NodeType:
            node = GraphNode(id="n1", type=node_type, file_path="/p.py")
            assert node.type == node_type


class TestGraphEdge:
    def test_required_fields_only(self) -> None:
        edge = GraphEdge(source_id="node1", target_id="node2", type=EdgeType.CALLS)
        assert edge.source_id == "node1"
        assert edge.target_id == "node2"
        assert edge.type == EdgeType.CALLS
        assert edge.metadata == {}

    def test_with_metadata(self) -> None:
        edge = GraphEdge(
            source_id="node1",
            target_id="node2",
            type=EdgeType.IMPORTS,
            metadata={"imported_as": "alias", "line": "10"},
        )
        assert edge.metadata == {"imported_as": "alias", "line": "10"}

    def test_missing_source_id(self) -> None:
        with pytest.raises(TypeError):
            GraphEdge(target_id="node2", type=EdgeType.CALLS)

    def test_missing_target_id(self) -> None:
        with pytest.raises(TypeError):
            GraphEdge(source_id="node1", type=EdgeType.CALLS)

    def test_missing_type(self) -> None:
        with pytest.raises(TypeError):
            GraphEdge(source_id="node1", target_id="node2")

    def test_empty_metadata_defaults(self) -> None:
        edge = GraphEdge(source_id="n1", target_id="n2", type=EdgeType.CALLS)
        assert edge.metadata == {}

    def test_all_edge_types(self) -> None:
        for edge_type in EdgeType:
            edge = GraphEdge(source_id="n1", target_id="n2", type=edge_type)
            assert edge.type == edge_type


class TestParseError:
    def test_required_fields_only(self) -> None:
        err = ParseError(message="Syntax error")
        assert err.message == "Syntax error"
        assert err.line == 0
        assert err.column == 0
        assert err.severity == "error"

    def test_with_all_fields(self) -> None:
        err = ParseError(message="Syntax error", line=42, column=10, severity="warning")
        assert err.message == "Syntax error"
        assert err.line == 42
        assert err.column == 10
        assert err.severity == "warning"

    def test_missing_message(self) -> None:
        with pytest.raises(TypeError):
            ParseError(line=10)

    def test_severity_variations(self) -> None:
        for severity in ["error", "warning", "info"]:
            err = ParseError(message="msg", severity=severity)
            assert err.severity == severity


class TestDocument:
    def test_required_fields_only(self) -> None:
        doc = Document(file_path="/path/to/file.py")
        assert doc.file_path == "/path/to/file.py"
        assert doc.language == Language.UNKNOWN
        assert doc.content_hash == ""
        assert doc.nodes == []
        assert doc.edges == []
        assert doc.errors == []

    def test_with_all_fields(self) -> None:
        node = GraphNode(id="n1", type=NodeType.FILE, file_path="/p.py")
        edge = GraphEdge(source_id="n1", target_id="n2", type=EdgeType.CALLS)
        parse_err = ParseError(message="warning", severity="warning")
        doc = Document(
            file_path="/path/to/file.py",
            language=Language.PYTHON,
            content_hash="abc123",
            nodes=[node],
            edges=[edge],
            errors=[parse_err],
        )
        assert doc.language == Language.PYTHON
        assert doc.content_hash == "abc123"
        assert len(doc.nodes) == 1
        assert len(doc.edges) == 1
        assert len(doc.errors) == 1

    def test_missing_file_path(self) -> None:
        with pytest.raises(TypeError):
            Document(language=Language.PYTHON)

    def test_all_languages(self) -> None:
        for lang in Language:
            doc = Document(file_path="/p.py", language=lang)
            assert doc.language == lang

    def test_empty_nodes_list(self) -> None:
        doc = Document(file_path="/p.py", nodes=[])
        assert doc.nodes == []

    def test_empty_edges_list(self) -> None:
        doc = Document(file_path="/p.py", edges=[])
        assert doc.edges == []

    def test_empty_errors_list(self) -> None:
        doc = Document(file_path="/p.py", errors=[])
        assert doc.errors == []


class TestJsonRpcRequest:
    def test_defaults(self) -> None:
        req = JsonRpcRequest()
        assert req.jsonrpc == "2.0"
        assert req.method == ""
        assert req.params == {}
        assert req.id is None

    def test_with_method_and_id(self) -> None:
        req = JsonRpcRequest(method="smp/navigate", id=1)
        assert req.method == "smp/navigate"
        assert req.id == 1

    def test_with_params(self) -> None:
        req = JsonRpcRequest(method="smp/update", params={"file_path": "/p.py"})
        assert req.params == {"file_path": "/p.py"}

    def test_string_id(self) -> None:
        req = JsonRpcRequest(method="test", id="request-1")
        assert req.id == "request-1"

    def test_null_id(self) -> None:
        req = JsonRpcRequest(method="test", id=None)
        assert req.id is None

    def test_empty_method_allowed(self) -> None:
        req = JsonRpcRequest(method="")
        assert req.method == ""

    def test_empty_params_defaults(self) -> None:
        req = JsonRpcRequest()
        assert req.params == {}

    def test_jsonrpc_version_fixed(self) -> None:
        req = JsonRpcRequest(jsonrpc="2.0")
        assert req.jsonrpc == "2.0"


class TestJsonRpcError:
    def test_required_fields(self) -> None:
        err = JsonRpcError(code=-32600, message="Invalid request")
        assert err.code == -32600
        assert err.message == "Invalid request"
        assert err.data is None

    def test_with_data(self) -> None:
        err = JsonRpcError(code=-32600, message="Invalid request", data={"field": "value"})
        assert err.data == {"field": "value"}

    def test_missing_code(self) -> None:
        with pytest.raises(TypeError):
            JsonRpcError(message="error")

    def test_missing_message(self) -> None:
        with pytest.raises(TypeError):
            JsonRpcError(code=-32600)

    def test_integer_code(self) -> None:
        err = JsonRpcError(code=0, message="No error")
        assert err.code == 0

    def test_negative_error_codes(self) -> None:
        err = JsonRpcError(code=-32700, message="Parse error")
        assert err.code == -32700


class TestJsonRpcResponse:
    def test_defaults(self) -> None:
        resp = JsonRpcResponse()
        assert resp.jsonrpc == "2.0"
        assert resp.result is None
        assert resp.error is None
        assert resp.id is None

    def test_with_result(self) -> None:
        resp = JsonRpcResponse(result={"status": "ok"}, id=1)
        assert resp.result == {"status": "ok"}
        assert resp.error is None
        assert resp.id == 1

    def test_with_error(self) -> None:
        err = JsonRpcError(code=-32600, message="Invalid request")
        resp = JsonRpcResponse(error=err, id=1)
        assert resp.result is None
        assert resp.error == err

    def test_error_and_result_mutually_exclusive(self) -> None:
        err = JsonRpcError(code=-32600, message="Invalid request")
        resp = JsonRpcResponse(result={"data": "value"}, error=err, id=1)
        assert resp.result == {"data": "value"}
        assert resp.error == err

    def test_null_id(self) -> None:
        resp = JsonRpcResponse(id=None)
        assert resp.id is None


class TestUpdateParams:
    def test_required_file_path(self) -> None:
        params = UpdateParams(file_path="/path/to/file.py")
        assert params.file_path == "/path/to/file.py"
        assert params.content == ""
        assert params.change_type == "modified"
        assert params.language is None

    def test_with_all_fields(self) -> None:
        params = UpdateParams(
            file_path="/path/to/file.py",
            content="file contents",
            change_type="created",
            language=Language.PYTHON,
        )
        assert params.content == "file contents"
        assert params.change_type == "created"
        assert params.language == Language.PYTHON

    def test_missing_file_path(self) -> None:
        with pytest.raises(TypeError):
            UpdateParams(content="contents")

    def test_change_type_variations(self) -> None:
        for change_type in ["created", "modified", "deleted", "renamed"]:
            params = UpdateParams(file_path="/p.py", change_type=change_type)
            assert params.change_type == change_type

    def test_empty_content(self) -> None:
        params = UpdateParams(file_path="/p.py", content="")
        assert params.content == ""


class TestBatchUpdateParams:
    def test_defaults(self) -> None:
        params = BatchUpdateParams()
        assert params.changes == []

    def test_with_changes(self) -> None:
        params = BatchUpdateParams(
            changes=[
                {"file_path": "/p1.py", "change_type": "modified"},
                {"file_path": "/p2.py", "change_type": "created"},
            ]
        )
        assert len(params.changes) == 2

    def test_empty_changes_list(self) -> None:
        params = BatchUpdateParams(changes=[])
        assert params.changes == []


class TestReindexParams:
    def test_defaults(self) -> None:
        params = ReindexParams()
        assert params.scope == "full"

    def test_with_scope(self) -> None:
        params = ReindexParams(scope="incremental")
        assert params.scope == "incremental"

    def test_empty_scope(self) -> None:
        params = ReindexParams(scope="")
        assert params.scope == ""


class TestEnrichParams:
    def test_required_node_id(self) -> None:
        params = EnrichParams(node_id="node-123")
        assert params.node_id == "node-123"
        assert params.force is False

    def test_with_force(self) -> None:
        params = EnrichParams(node_id="node-123", force=True)
        assert params.force is True

    def test_missing_node_id(self) -> None:
        with pytest.raises(TypeError):
            EnrichParams(force=True)


class TestEnrichBatchParams:
    def test_defaults(self) -> None:
        params = EnrichBatchParams()
        assert params.scope == "full"
        assert params.force is False

    def test_with_values(self) -> None:
        params = EnrichBatchParams(scope="incremental", force=True)
        assert params.scope == "incremental"
        assert params.force is True


class TestEnrichStaleParams:
    def test_defaults(self) -> None:
        params = EnrichStaleParams()
        assert params.scope == "full"

    def test_with_scope(self) -> None:
        params = EnrichStaleParams(scope="week")
        assert params.scope == "week"


class TestEnrichStatusParams:
    def test_defaults(self) -> None:
        params = EnrichStatusParams()
        assert params.scope == "full"

    def test_with_scope(self) -> None:
        params = EnrichStatusParams(scope="day")
        assert params.scope == "day"


class TestAnnotateParams:
    def test_required_node_id(self) -> None:
        params = AnnotateParams(node_id="node-123")
        assert params.node_id == "node-123"
        assert params.description == ""
        assert params.tags == []
        assert params.force is False

    def test_with_all_fields(self) -> None:
        params = AnnotateParams(
            node_id="node-123",
            description="Important function",
            tags=["api", "critical"],
            force=True,
        )
        assert params.description == "Important function"
        assert params.tags == ["api", "critical"]
        assert params.force is True

    def test_missing_node_id(self) -> None:
        with pytest.raises(TypeError):
            AnnotateParams(description="desc")


class TestAnnotateBulkItem:
    def test_required_node_id(self) -> None:
        item = AnnotateBulkItem(node_id="node-123")
        assert item.node_id == "node-123"
        assert item.description == ""
        assert item.tags == []

    def test_with_values(self) -> None:
        item = AnnotateBulkItem(
            node_id="node-123",
            description="desc",
            tags=["tag1", "tag2"],
        )
        assert item.description == "desc"
        assert item.tags == ["tag1", "tag2"]

    def test_empty_tags(self) -> None:
        item = AnnotateBulkItem(node_id="n1", tags=[])
        assert item.tags == []


class TestAnnotateBulkParams:
    def test_defaults(self) -> None:
        params = AnnotateBulkParams()
        assert params.annotations == []

    def test_with_annotations(self) -> None:
        item1 = AnnotateBulkItem(node_id="n1", description="d1")
        item2 = AnnotateBulkItem(node_id="n2", description="d2")
        params = AnnotateBulkParams(annotations=[item1, item2])
        assert len(params.annotations) == 2


class TestTagParams:
    def test_defaults(self) -> None:
        params = TagParams()
        assert params.scope == ""
        assert params.tags == []
        assert params.action == "add"

    def test_with_values(self) -> None:
        params = TagParams(scope="file:/p.py", tags=["api"], action="remove")
        assert params.scope == "file:/p.py"
        assert params.tags == ["api"]
        assert params.action == "remove"

    def test_empty_scope(self) -> None:
        params = TagParams(scope="")
        assert params.scope == ""

    def test_action_variations(self) -> None:
        for action in ["add", "remove", "clear"]:
            params = TagParams(action=action)
            assert params.action == action


class TestSessionOpenParams:
    def test_defaults(self) -> None:
        params = SessionOpenParams()
        assert params.agent_id == ""
        assert params.task == ""
        assert params.scope == []
        assert params.mode == "read"

    def test_with_values(self) -> None:
        params = SessionOpenParams(
            agent_id="agent-1",
            task="refactoring",
            scope=["*.py"],
            mode="write",
        )
        assert params.agent_id == "agent-1"
        assert params.task == "refactoring"
        assert params.scope == ["*.py"]
        assert params.mode == "write"

    def test_empty_scope(self) -> None:
        params = SessionOpenParams(scope=[])
        assert params.scope == []

    def test_mode_variations(self) -> None:
        for mode in ["read", "write", "admin"]:
            params = SessionOpenParams(mode=mode)
            assert params.mode == mode


class TestSessionCloseParams:
    def test_defaults(self) -> None:
        params = SessionCloseParams()
        assert params.session_id == ""
        assert params.status == "completed"

    def test_with_values(self) -> None:
        params = SessionCloseParams(session_id="sess-123", status="aborted")
        assert params.session_id == "sess-123"
        assert params.status == "aborted"


class TestSessionRecoverParams:
    def test_defaults(self) -> None:
        params = SessionRecoverParams()
        assert params.session_id == ""

    def test_with_session_id(self) -> None:
        params = SessionRecoverParams(session_id="sess-123")
        assert params.session_id == "sess-123"


class TestGuardCheckParams:
    def test_defaults(self) -> None:
        params = GuardCheckParams()
        assert params.session_id == ""
        assert params.target == ""
        assert params.intended_change == ""

    def test_with_values(self) -> None:
        params = GuardCheckParams(
            session_id="sess-1",
            target="/p.py",
            intended_change="delete function foo",
        )
        assert params.session_id == "sess-1"
        assert params.target == "/p.py"
        assert params.intended_change == "delete function foo"


class TestDryRunParams:
    def test_defaults(self) -> None:
        params = DryRunParams()
        assert params.session_id == ""
        assert params.file_path == ""
        assert params.proposed_content == ""
        assert params.change_summary == ""

    def test_with_values(self) -> None:
        params = DryRunParams(
            session_id="sess-1",
            file_path="/p.py",
            proposed_content="new content",
            change_summary="refactor function",
        )
        assert params.session_id == "sess-1"
        assert params.file_path == "/p.py"
        assert params.proposed_content == "new content"
        assert params.change_summary == "refactor function"


class TestCheckpointParams:
    def test_defaults(self) -> None:
        params = CheckpointParams()
        assert params.session_id == ""
        assert params.files == []

    def test_with_values(self) -> None:
        params = CheckpointParams(session_id="sess-1", files=["/p1.py", "/p2.py"])
        assert params.session_id == "sess-1"
        assert params.files == ["/p1.py", "/p2.py"]


class TestRollbackParams:
    def test_required_fields(self) -> None:
        params = RollbackParams(session_id="sess-1", checkpoint_id="cp-123")
        assert params.session_id == "sess-1"
        assert params.checkpoint_id == "cp-123"

    def test_missing_checkpoint_id_uses_default(self) -> None:
        params = RollbackParams(session_id="sess-1")
        assert params.checkpoint_id == ""


class TestLockParams:
    def test_defaults(self) -> None:
        params = LockParams()
        assert params.session_id == ""
        assert params.files == []
        assert params.ttl_seconds == 300
        assert params.force is False

    def test_with_values(self) -> None:
        params = LockParams(
            session_id="sess-1",
            files=["/p.py"],
            ttl_seconds=600,
            force=True,
        )
        assert params.session_id == "sess-1"
        assert params.files == ["/p.py"]
        assert params.ttl_seconds == 600
        assert params.force is True

    def test_empty_files(self) -> None:
        params = LockParams(files=[])
        assert params.files == []


class TestAuditGetParams:
    def test_defaults(self) -> None:
        params = AuditGetParams()
        assert params.audit_log_id == ""

    def test_with_id(self) -> None:
        params = AuditGetParams(audit_log_id="audit-123")
        assert params.audit_log_id == "audit-123"


class TestNavigateParams:
    def test_required_query(self) -> None:
        params = NavigateParams(query="find_function")
        assert params.query == "find_function"
        assert params.include_relationships is True

    def test_with_relationships(self) -> None:
        params = NavigateParams(query="find_function", include_relationships=False)
        assert params.include_relationships is False

    def test_missing_query(self) -> None:
        with pytest.raises(TypeError):
            NavigateParams()


class TestTraceParams:
    def test_defaults(self) -> None:
        params = TraceParams()
        assert params.start == ""
        assert params.relationship == "CALLS"
        assert params.depth == 3
        assert params.direction == "outgoing"

    def test_with_values(self) -> None:
        params = TraceParams(
            start="node-1",
            relationship="IMPORTS",
            depth=5,
            direction="incoming",
        )
        assert params.start == "node-1"
        assert params.relationship == "IMPORTS"
        assert params.depth == 5
        assert params.direction == "incoming"

    def test_direction_variations(self) -> None:
        for direction in ["incoming", "outgoing", "both"]:
            params = TraceParams(direction=direction)
            assert params.direction == direction


class TestContextParams:
    def test_defaults(self) -> None:
        params = ContextParams()
        assert params.file_path == ""
        assert params.scope == "edit"
        assert params.depth == 2

    def test_with_values(self) -> None:
        params = ContextParams(file_path="/p.py", scope="file", depth=5)
        assert params.file_path == "/p.py"
        assert params.scope == "file"
        assert params.depth == 5


class TestImpactParams:
    def test_defaults(self) -> None:
        params = ImpactParams()
        assert params.entity == ""
        assert params.change_type == "delete"

    def test_with_values(self) -> None:
        params = ImpactParams(entity="function:foo", change_type="modify")
        assert params.entity == "function:foo"
        assert params.change_type == "modify"


class TestLocateParams:
    def test_defaults(self) -> None:
        params = LocateParams()
        assert params.query == ""
        assert params.fields == ["name", "docstring", "tags"]
        assert params.node_types == []
        assert params.top_k == 5

    def test_with_values(self) -> None:
        params = LocateParams(
            query="search term",
            fields=["name", "description"],
            node_types=["Function", "Class"],
            top_k=10,
        )
        assert params.query == "search term"
        assert params.fields == ["name", "description"]
        assert params.node_types == ["Function", "Class"]
        assert params.top_k == 10

    def test_empty_fields_default(self) -> None:
        params = LocateParams()
        assert params.fields == ["name", "docstring", "tags"]


class TestSearchParams:
    def test_defaults(self) -> None:
        params = SearchParams()
        assert params.query == ""
        assert params.match == "any"
        assert params.filter == {}
        assert params.top_k == 5

    def test_with_values(self) -> None:
        params = SearchParams(
            query="test",
            match="all",
            filter={"type": "Function"},
            top_k=10,
        )
        assert params.query == "test"
        assert params.match == "all"
        assert params.filter == {"type": "Function"}
        assert params.top_k == 10


class TestVectorSearchParams:
    def test_required_embedding(self) -> None:
        params = VectorSearchParams(embedding=[0.1, 0.2, 0.3])
        assert params.embedding == [0.1, 0.2, 0.3]
        assert params.top_k == 5
        assert params.where == {}

    def test_with_all_fields(self) -> None:
        params = VectorSearchParams(
            embedding=[0.1, 0.2],
            top_k=10,
            where={"node_type": "Class"},
        )
        assert params.top_k == 10
        assert params.where == {"node_type": "Class"}

    def test_missing_embedding(self) -> None:
        with pytest.raises(TypeError):
            VectorSearchParams()

    def test_empty_embedding_list(self) -> None:
        params = VectorSearchParams(embedding=[])
        assert params.embedding == []


class TestFlowParams:
    def test_defaults(self) -> None:
        params = FlowParams()
        assert params.start == ""
        assert params.end == ""
        assert params.flow_type == "data"

    def test_with_values(self) -> None:
        params = FlowParams(start="node-1", end="node-2", flow_type="control")
        assert params.start == "node-1"
        assert params.end == "node-2"
        assert params.flow_type == "control"


class TestRuntimeEdge:
    def test_defaults(self) -> None:
        edge = RuntimeEdge()
        assert edge.source_id == ""
        assert edge.target_id == ""
        assert edge.edge_type == "CALLS_RUNTIME"
        assert edge.timestamp == ""
        assert edge.session_id == ""
        assert edge.trace_id == ""
        assert edge.duration_ms == 0
        assert edge.metadata == {}

    def test_with_values(self) -> None:
        edge = RuntimeEdge(
            source_id="n1",
            target_id="n2",
            edge_type="CALLS_RUNTIME",
            timestamp="2024-01-01T00:00:00Z",
            session_id="sess-1",
            trace_id="trace-1",
            duration_ms=150,
            metadata={"key": "value"},
        )
        assert edge.source_id == "n1"
        assert edge.target_id == "n2"
        assert edge.duration_ms == 150
        assert edge.metadata == {"key": "value"}


class TestRuntimeTrace:
    def test_defaults(self) -> None:
        trace = RuntimeTrace()
        assert trace.trace_id == ""
        assert trace.session_id == ""
        assert trace.agent_id == ""
        assert trace.started_at == ""
        assert trace.ended_at == ""
        assert trace.edges == []
        assert trace.nodes_visited == []

    def test_with_values(self) -> None:
        edge = RuntimeEdge(source_id="n1", target_id="n2")
        trace = RuntimeTrace(
            trace_id="trace-1",
            session_id="sess-1",
            agent_id="agent-1",
            started_at="2024-01-01T00:00:00Z",
            ended_at="2024-01-01T00:01:00Z",
            edges=[edge],
            nodes_visited=["n1", "n2"],
        )
        assert trace.trace_id == "trace-1"
        assert len(trace.edges) == 1
        assert trace.nodes_visited == ["n1", "n2"]


class TestDiffParams:
    def test_defaults(self) -> None:
        params = DiffParams()
        assert params.from_snapshot == ""
        assert params.to_snapshot == ""
        assert params.scope == "full"

    def test_with_values(self) -> None:
        params = DiffParams(from_snapshot="snap-1", to_snapshot="snap-2", scope="file")
        assert params.from_snapshot == "snap-1"
        assert params.to_snapshot == "snap-2"
        assert params.scope == "file"


class TestPlanParams:
    def test_defaults(self) -> None:
        params = PlanParams()
        assert params.change_description == ""
        assert params.target_file == ""
        assert params.change_type == "refactor"
        assert params.scope == "full"

    def test_with_values(self) -> None:
        params = PlanParams(
            change_description="extract method",
            target_file="/p.py",
            change_type="extract",
            scope="function",
        )
        assert params.change_description == "extract method"
        assert params.target_file == "/p.py"
        assert params.change_type == "extract"
        assert params.scope == "function"


class TestConflictParams:
    def test_defaults(self) -> None:
        params = ConflictParams()
        assert params.entity == ""
        assert params.proposed_change == ""
        assert params.context == {}

    def test_with_values(self) -> None:
        params = ConflictParams(
            entity="function:foo",
            proposed_change="delete",
            context={"file": "/p.py"},
        )
        assert params.entity == "function:foo"
        assert params.proposed_change == "delete"
        assert params.context == {"file": "/p.py"}


class TestWhyParams:
    def test_defaults(self) -> None:
        params = WhyParams()
        assert params.entity == ""
        assert params.relationship == ""
        assert params.depth == 3

    def test_with_values(self) -> None:
        params = WhyParams(entity="n1", relationship="CALLS", depth=5)
        assert params.entity == "n1"
        assert params.relationship == "CALLS"
        assert params.depth == 5


class TestTelemetryParams:
    def test_defaults(self) -> None:
        params = TelemetryParams()
        assert params.action == "get_stats"
        assert params.node_id is None
        assert params.threshold is None

    def test_with_values(self) -> None:
        params = TelemetryParams(action="get_hot", node_id="n1", threshold=10)
        assert params.action == "get_hot"
        assert params.node_id == "n1"
        assert params.threshold == 10


class TestTelemetryHotParams:
    def test_required_node_id(self) -> None:
        params = TelemetryHotParams(node_id="node-123")
        assert params.node_id == "node-123"

    def test_missing_node_id(self) -> None:
        with pytest.raises(TypeError):
            TelemetryHotParams()


class TestTelemetryNodeParams:
    def test_required_node_id(self) -> None:
        params = TelemetryNodeParams(node_id="node-123")
        assert params.node_id == "node-123"

    def test_missing_node_id(self) -> None:
        with pytest.raises(TypeError):
            TelemetryNodeParams()


class TestReviewCreateParams:
    def test_defaults(self) -> None:
        params = ReviewCreateParams()
        assert params.session_id == ""
        assert params.files_changed == []
        assert params.diff_summary == ""
        assert params.reviewers == []

    def test_with_values(self) -> None:
        params = ReviewCreateParams(
            session_id="sess-1",
            files_changed=["/p1.py", "/p2.py"],
            diff_summary="refactored",
            reviewers=["alice", "bob"],
        )
        assert params.session_id == "sess-1"
        assert params.files_changed == ["/p1.py", "/p2.py"]
        assert params.diff_summary == "refactored"
        assert params.reviewers == ["alice", "bob"]


class TestReviewApproveParams:
    def test_required_fields(self) -> None:
        params = ReviewApproveParams(review_id="r-123", reviewer="alice")
        assert params.review_id == "r-123"
        assert params.reviewer == "alice"

    def test_missing_review_id_uses_default(self) -> None:
        params = ReviewApproveParams(reviewer="alice")
        assert params.review_id == ""


class TestReviewRejectParams:
    def test_required_fields(self) -> None:
        params = ReviewRejectParams(review_id="r-123", reviewer="alice", reason="needs work")
        assert params.review_id == "r-123"
        assert params.reviewer == "alice"
        assert params.reason == "needs work"


class TestReviewCommentParams:
    def test_defaults(self) -> None:
        params = ReviewCommentParams()
        assert params.review_id == ""
        assert params.author == ""
        assert params.comment == ""
        assert params.file_path is None
        assert params.line is None

    def test_with_values(self) -> None:
        params = ReviewCommentParams(
            review_id="r-1",
            author="alice",
            comment="looks good",
            file_path="/p.py",
            line=42,
        )
        assert params.file_path == "/p.py"
        assert params.line == 42


class TestPRCreateParams:
    def test_defaults(self) -> None:
        params = PRCreateParams()
        assert params.review_id == ""
        assert params.title == ""
        assert params.body == ""
        assert params.branch == ""
        assert params.base_branch == "main"

    def test_with_values(self) -> None:
        params = PRCreateParams(
            review_id="r-1",
            title="My PR",
            body="Description",
            branch="feature",
            base_branch="develop",
        )
        assert params.title == "My PR"
        assert params.base_branch == "develop"


class TestSandboxSpawnParams:
    def test_defaults(self) -> None:
        params = SandboxSpawnParams()
        assert params.name is None
        assert params.template is None
        assert params.files == {}

    def test_with_values(self) -> None:
        params = SandboxSpawnParams(
            name="my-sandbox",
            template="python3.11",
            files={"/p.py": "print('hello')"},
        )
        assert params.name == "my-sandbox"
        assert params.template == "python3.11"
        assert params.files == {"/p.py": "print('hello')"}


class TestSandboxExecuteParams:
    def test_defaults(self) -> None:
        params = SandboxExecuteParams()
        assert params.sandbox_id == ""
        assert params.command == []
        assert params.stdin is None
        assert params.timeout is None

    def test_with_values(self) -> None:
        params = SandboxExecuteParams(
            sandbox_id="sb-1",
            command=["python", "script.py"],
            stdin="input data",
            timeout=30,
        )
        assert params.sandbox_id == "sb-1"
        assert params.command == ["python", "script.py"]
        assert params.stdin == "input data"
        assert params.timeout == 30


class TestSandboxKillParams:
    def test_required_execution_id(self) -> None:
        params = SandboxKillParams(execution_id="exec-123")
        assert params.execution_id == "exec-123"

    def test_missing_execution_id_uses_default(self) -> None:
        params = SandboxKillParams()
        assert params.execution_id == ""


class TestCommunityDetectParams:
    def test_defaults(self) -> None:
        params = CommunityDetectParams()
        assert params.resolutions == []
        assert params.relationship_types == []

    def test_with_values(self) -> None:
        params = CommunityDetectParams(
            resolutions=[{"type": "Louvain", "resolution": 1.0}],
            relationship_types=["CALLS", "IMPORTS"],
        )
        assert len(params.resolutions) == 1
        assert params.relationship_types == ["CALLS", "IMPORTS"]


class TestCommunityListParams:
    def test_defaults(self) -> None:
        params = CommunityListParams()
        assert params.level is None

    def test_with_level(self) -> None:
        params = CommunityListParams(level=2)
        assert params.level == 2


class TestCommunityGetParams:
    def test_required_community_id(self) -> None:
        params = CommunityGetParams(community_id="comm-123")
        assert params.community_id == "comm-123"
        assert params.node_types == []
        assert params.include_bridges is False

    def test_with_values(self) -> None:
        params = CommunityGetParams(
            community_id="comm-123",
            node_types=["Function", "Class"],
            include_bridges=True,
        )
        assert params.node_types == ["Function", "Class"]
        assert params.include_bridges is True


class TestCommunityBoundariesParams:
    def test_defaults(self) -> None:
        params = CommunityBoundariesParams()
        assert params.level == 0
        assert params.min_coupling == 0.05

    def test_with_values(self) -> None:
        params = CommunityBoundariesParams(level=3, min_coupling=0.1)
        assert params.level == 3
        assert params.min_coupling == 0.1


class TestMerkleSyncParams:
    def test_defaults(self) -> None:
        params = MerkleSyncParams()
        assert params.remote_data == {}

    def test_with_values(self) -> None:
        params = MerkleSyncParams(remote_data={"key": "value", "hash": "abc"})
        assert params.remote_data == {"key": "value", "hash": "abc"}


class TestMerkleImportParams:
    def test_defaults(self) -> None:
        params = MerkleImportParams()
        assert params.data == {}

    def test_with_values(self) -> None:
        params = MerkleImportParams(data={"nodes": [], "edges": []})
        assert params.data == {"nodes": [], "edges": []}


class TestIntegrityCheckParams:
    def test_defaults(self) -> None:
        params = IntegrityCheckParams()
        assert params.node_id == ""
        assert params.current_state == {}

    def test_with_values(self) -> None:
        params = IntegrityCheckParams(
            node_id="n-1",
            current_state={"hash": "abc", "modified": True},
        )
        assert params.node_id == "n-1"
        assert params.current_state == {"hash": "abc", "modified": True}


class TestIntegrityBaselineParams:
    def test_defaults(self) -> None:
        params = IntegrityBaselineParams()
        assert params.node_id == ""
        assert params.state == {}

    def test_with_values(self) -> None:
        params = IntegrityBaselineParams(
            node_id="n-1",
            state={"signature": "abc", "complexity": 5},
        )
        assert params.node_id == "n-1"
        assert params.state == {"signature": "abc", "complexity": 5}
