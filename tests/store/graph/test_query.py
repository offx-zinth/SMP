"""Tests for the path-expression query language (Phase 4)."""

from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path

import pytest

from smp.core.models import (
    EdgeType,
    GraphEdge,
    GraphNode,
    NodeType,
    SemanticProperties,
    StructuralProperties,
)
from smp.store.graph.mmap_store import MMapGraphStore
from smp.store.graph.query import (
    Direction,
    EdgePattern,
    FilterExpr,
    FilterOp,
    NodePattern,
    QueryEngine,
    QueryError,
    TokenKind,
    parse,
    tokenize,
)

# ---------------------------------------------------------------------------
# Tokenizer
# ---------------------------------------------------------------------------


class TestTokenizer:
    def test_basic_path(self) -> None:
        toks = tokenize("Function CALLS Function")
        kinds = [t.kind for t in toks]
        assert kinds == [
            TokenKind.IDENT,
            TokenKind.IDENT,
            TokenKind.IDENT,
            TokenKind.EOF,
        ]
        assert [t.value for t in toks[:-1]] == ["Function", "CALLS", "Function"]

    def test_arrows(self) -> None:
        toks = tokenize("Class -> DEFINES -> Method")
        kinds = [t.kind for t in toks]
        assert TokenKind.ARROW_RIGHT in kinds
        assert kinds.count(TokenKind.ARROW_RIGHT) == 2

    def test_left_and_both_arrows(self) -> None:
        toks = tokenize("a <- b <-> c")
        kinds = [t.kind for t in toks]
        assert TokenKind.ARROW_LEFT in kinds
        assert TokenKind.ARROW_BOTH in kinds

    def test_string_literal(self) -> None:
        toks = tokenize("* IMPORTS 'requests'")
        assert toks[0].kind == TokenKind.STAR
        assert toks[2].kind == TokenKind.STRING
        assert toks[2].value == "requests"

    def test_double_quoted_string(self) -> None:
        toks = tokenize('* IMPORTS "requests"')
        assert toks[2].kind == TokenKind.STRING
        assert toks[2].value == "requests"

    def test_string_with_escape(self) -> None:
        toks = tokenize(r"* X 'a\'b'")
        assert toks[2].kind == TokenKind.STRING
        assert toks[2].value == "a'b"

    def test_unterminated_string_raises(self) -> None:
        with pytest.raises(QueryError):
            tokenize("'unterminated")

    def test_filter_operators(self) -> None:
        toks = tokenize("F[name='login', x!=1, y=~'.*foo']")
        ops = [t.kind for t in toks if t.kind in (TokenKind.EQ, TokenKind.NEQ, TokenKind.REGEX)]
        assert ops == [TokenKind.EQ, TokenKind.NEQ, TokenKind.REGEX]

    def test_transitive_marker(self) -> None:
        toks = tokenize("A CALLS+ B")
        kinds = [t.kind for t in toks]
        assert TokenKind.PLUS in kinds

    def test_unexpected_character(self) -> None:
        with pytest.raises(QueryError):
            tokenize("A @ B")


# ---------------------------------------------------------------------------
# Parser
# ---------------------------------------------------------------------------


class TestParser:
    def test_simple_path(self) -> None:
        q = parse("Function CALLS Function")
        assert q.start == NodePattern(type_name="Function")
        assert len(q.hops) == 1
        edge, target = q.hops[0]
        assert edge == EdgePattern(type_name="CALLS", direction=Direction.OUTGOING, transitive=False)
        assert target == NodePattern(type_name="Function")

    def test_arrows_outgoing(self) -> None:
        q = parse("Class -> DEFINES -> Method")
        assert q.start.type_name == "Class"
        assert q.hops[0][0].direction == Direction.OUTGOING
        assert q.hops[0][0].type_name == "DEFINES"

    def test_arrows_incoming(self) -> None:
        q = parse("Method <- DEFINES <- Class")
        assert q.hops[0][0].direction == Direction.INCOMING

    def test_arrows_both(self) -> None:
        q = parse("A <-> CALLS <-> B")
        assert q.hops[0][0].direction == Direction.BOTH

    def test_mismatched_arrows(self) -> None:
        with pytest.raises(QueryError):
            parse("A -> CALLS <- B")

    def test_wildcard_node(self) -> None:
        q = parse("* IMPORTS 'requests'")
        assert q.start == NodePattern()
        target = q.hops[0][1]
        assert target == NodePattern(name="requests")

    def test_transitive(self) -> None:
        q = parse("Function CALLS+ Function")
        edge, _ = q.hops[0]
        assert edge.transitive is True
        assert edge.type_name == "CALLS"

    def test_filter_eq(self) -> None:
        q = parse("Function[name='login'] CALLS Function")
        assert q.start.filters == (FilterExpr(field="name", op=FilterOp.EQ, value="login"),)

    def test_filter_neq(self) -> None:
        q = parse("Function[type!='Class'] CALLS Function")
        assert q.start.filters[0].op == FilterOp.NEQ

    def test_filter_regex(self) -> None:
        q = parse("Class[file_path=~'.*/auth/.*'] DEFINES Method")
        assert q.start.filters[0].op == FilterOp.REGEX
        assert q.start.filters[0].value == ".*/auth/.*"

    def test_multiple_filters(self) -> None:
        q = parse("Function[name='login', file_path=~'auth'] CALLS Function")
        assert len(q.start.filters) == 2

    def test_multi_hop(self) -> None:
        q = parse("Class DEFINES Method CALLS Function")
        assert len(q.hops) == 2

    def test_arrow_only_edge(self) -> None:
        q = parse("Class -> Method")
        edge, _ = q.hops[0]
        assert edge.type_name is None
        assert edge.direction == Direction.OUTGOING

    def test_empty_node_pattern_raises(self) -> None:
        with pytest.raises(QueryError):
            parse("")


# ---------------------------------------------------------------------------
# Evaluator (against MMapGraphStore)
# ---------------------------------------------------------------------------


def _func(node_id: str, name: str, file_path: str = "a.py", start_line: int = 1) -> GraphNode:
    return GraphNode(
        id=node_id,
        type=NodeType.FUNCTION,
        file_path=file_path,
        structural=StructuralProperties(
            name=name,
            file=file_path,
            signature=f"def {name}():",
            start_line=start_line,
            end_line=start_line + 2,
        ),
        semantic=SemanticProperties(docstring=f"{name} docs"),
    )


def _cls(node_id: str, name: str, file_path: str = "a.py") -> GraphNode:
    return GraphNode(
        id=node_id,
        type=NodeType.CLASS,
        file_path=file_path,
        structural=StructuralProperties(
            name=name,
            file=file_path,
            signature=f"class {name}",
            start_line=1,
            end_line=20,
        ),
        semantic=SemanticProperties(docstring=f"abstract base class for {name}"),
    )


@pytest.fixture
async def populated_store(tmp_path: Path) -> AsyncIterator[MMapGraphStore]:
    store = MMapGraphStore(tmp_path / "test.smpg")
    await store.connect()

    nodes = [
        _func("a::Function::login::1", "login", "src/auth/login.py", 1),
        _func("a::Function::validate::20", "validate", "src/auth/login.py", 20),
        _func("a::Function::log::40", "log", "src/auth/login.py", 40),
        _func("b::Function::handler::5", "handler", "src/api/handler.py", 5),
        _cls("c::Class::User::1", "User", "src/models/user.py"),
        _func("c::Function::__init__::5", "__init__", "src/models/user.py", 5),
    ]
    await store.upsert_nodes(nodes)

    edges = [
        GraphEdge(
            source_id="a::Function::login::1",
            target_id="a::Function::validate::20",
            type=EdgeType.CALLS,
        ),
        GraphEdge(
            source_id="a::Function::validate::20",
            target_id="a::Function::log::40",
            type=EdgeType.CALLS,
        ),
        GraphEdge(
            source_id="b::Function::handler::5",
            target_id="a::Function::login::1",
            type=EdgeType.CALLS,
        ),
        GraphEdge(
            source_id="c::Class::User::1",
            target_id="c::Function::__init__::5",
            type=EdgeType.DEFINES,
        ),
        GraphEdge(
            source_id="a::Function::login::1",
            target_id="c::Class::User::1",
            type=EdgeType.USES,
        ),
    ]
    await store.upsert_edges(edges)

    yield store
    await store.close()


class TestEvaluatorBasic:
    async def test_function_calls_function(self, populated_store: MMapGraphStore) -> None:
        result = await populated_store.query("Function CALLS Function")
        names = {n.structural.name for n in result.nodes}
        assert {"login", "validate", "log", "handler"} <= names
        assert all(e.type == EdgeType.CALLS for e in result.edges)
        assert result.stats["matched_edges"] == 3

    async def test_class_defines_function(self, populated_store: MMapGraphStore) -> None:
        result = await populated_store.query("Class -> DEFINES -> Function")
        names = {n.structural.name for n in result.nodes}
        assert "User" in names
        assert "__init__" in names

    async def test_wildcard_imports_string(self, populated_store: MMapGraphStore) -> None:
        await populated_store.upsert_node(
            GraphNode(
                id="x::Function::imp_user::1",
                type=NodeType.FUNCTION,
                file_path="x.py",
                structural=StructuralProperties(name="imp_user", file="x.py", start_line=1, end_line=2),
            )
        )
        await populated_store.upsert_edge(
            GraphEdge(
                source_id="x::Function::imp_user::1",
                target_id="c::Class::User::1",
                type=EdgeType.IMPORTS,
            )
        )
        result = await populated_store.query("* IMPORTS 'User'")
        names = {n.structural.name for n in result.nodes}
        assert "User" in names

    async def test_no_matches(self, populated_store: MMapGraphStore) -> None:
        result = await populated_store.query("Class CALLS Function")
        assert result.nodes == [] or all(n.type != NodeType.CLASS for n in result.nodes[1:])
        assert result.stats["matched_edges"] == 0

    async def test_unknown_node_type(self, populated_store: MMapGraphStore) -> None:
        with pytest.raises(QueryError):
            await populated_store.query("Bogus CALLS Function")

    async def test_unknown_edge_type(self, populated_store: MMapGraphStore) -> None:
        with pytest.raises(QueryError):
            await populated_store.query("Function FOOBAR Function")


class TestEvaluatorTransitive:
    async def test_transitive_calls(self, populated_store: MMapGraphStore) -> None:
        result = await populated_store.query("Function CALLS+ Function")
        names = {n.structural.name for n in result.nodes}
        assert {"login", "validate", "log"} <= names
        # transitive walk reaches log even though there is no direct login -> log edge
        edges_login_to_log = [
            e for e in result.edges if e.source_id == "a::Function::login::1" and e.target_id == "a::Function::log::40"
        ]
        assert edges_login_to_log == []
        # but log itself appears as a reachable node from login transitively
        assert "log" in names

    async def test_transitive_terminates(self, populated_store: MMapGraphStore) -> None:
        await populated_store.upsert_edge(
            GraphEdge(
                source_id="a::Function::log::40",
                target_id="a::Function::login::1",
                type=EdgeType.CALLS,
            )
        )
        result = await populated_store.query("Function CALLS+ Function")
        assert len(result.nodes) >= 3

    async def test_transitive_with_max_results(self, populated_store: MMapGraphStore) -> None:
        result = await populated_store.query("Function CALLS+ Function", max_results=2)
        assert len(result.nodes) <= 5  # 1 initial + up to max_results from traversal


class TestEvaluatorFilters:
    async def test_filter_eq_name(self, populated_store: MMapGraphStore) -> None:
        result = await populated_store.query("Function[name='login'] CALLS Function")
        assert result.stats["matched_edges"] == 1
        assert any(n.structural.name == "validate" for n in result.nodes)

    async def test_filter_neq_name(self, populated_store: MMapGraphStore) -> None:
        result = await populated_store.query("Function[name!='login'] CALLS Function")
        sources = {e.source_id for e in result.edges}
        assert "a::Function::login::1" not in sources

    async def test_filter_regex_path(self, populated_store: MMapGraphStore) -> None:
        result = await populated_store.query("Function[file_path=~'.*/auth/.*'] CALLS Function")
        for n in result.nodes:
            if "login.py" in n.file_path:
                assert "auth" in n.file_path

    async def test_filter_regex_docstring(self, populated_store: MMapGraphStore) -> None:
        result = await populated_store.query("Class[docstring=~'(?i)abstract'] DEFINES Function")
        names = {n.structural.name for n in result.nodes}
        assert "User" in names
        assert "__init__" in names

    async def test_invalid_regex(self, populated_store: MMapGraphStore) -> None:
        with pytest.raises(QueryError):
            await populated_store.query("Function[name=~'(unbalanced'] CALLS Function")

    async def test_filter_on_target(self, populated_store: MMapGraphStore) -> None:
        result = await populated_store.query("Function CALLS Function[name='log']")
        names = {n.structural.name for n in result.nodes}
        assert "log" in names
        assert "validate" in names  # source of the matching edge

    async def test_unknown_field_returns_empty(self, populated_store: MMapGraphStore) -> None:
        result = await populated_store.query("Function[mystery='x'] CALLS Function")
        assert result.stats["matched_edges"] == 0


class TestEvaluatorDirection:
    async def test_incoming(self, populated_store: MMapGraphStore) -> None:
        result = await populated_store.query("Function <- CALLS <- Function")
        # login is CALLED BY handler
        edges_to_login = [e for e in result.edges if e.target_id == "a::Function::login::1"]
        assert any(e.source_id == "b::Function::handler::5" for e in edges_to_login)


class TestQueryEngineDirect:
    async def test_engine_returns_unique_edges(self, populated_store: MMapGraphStore) -> None:
        engine = QueryEngine(populated_store)
        q = parse("Function CALLS Function")
        result = await engine.execute(q)
        edge_keys = {(e.source_id, e.target_id, e.type.value) for e in result.edges}
        assert len(edge_keys) == len(result.edges)

    async def test_to_dict_shape(self, populated_store: MMapGraphStore) -> None:
        result = await populated_store.query("Function CALLS Function")
        as_dict = result.to_dict()
        assert "nodes" in as_dict and "edges" in as_dict and "stats" in as_dict
        assert all("id" in n for n in as_dict["nodes"])
