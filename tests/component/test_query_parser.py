from __future__ import annotations

import pytest

from smp.store.graph.query import (
    Direction,
    EdgePattern,
    FilterExpr,
    FilterOp,
    NodePattern,
    QueryError,
    TokenKind,
    parse,
    tokenize,
)


class TestTokenizer:
    def test_basic_tokens(self):
        tokens = tokenize("Function CALLS * [name='login']")
        # Function (IDENT), CALLS (IDENT), * (STAR), [ (LBRACKET), name (IDENT), = (EQ), 'login' (STRING), ] (RBRACKET)
        kinds = [t.kind for t in tokens]
        assert kinds == [
            TokenKind.IDENT,
            TokenKind.IDENT,
            TokenKind.STAR,
            TokenKind.LBRACKET,
            TokenKind.IDENT,
            TokenKind.EQ,
            TokenKind.STRING,
            TokenKind.RBRACKET,
            TokenKind.EOF,
        ]

    def test_arrows(self):
        assert [t.kind for t in tokenize("->")] == [TokenKind.ARROW_RIGHT, TokenKind.EOF]
        assert [t.kind for t in tokenize("<-")] == [TokenKind.ARROW_LEFT, TokenKind.EOF]
        assert [t.kind for t in tokenize("<->")] == [TokenKind.ARROW_BOTH, TokenKind.EOF]

    def test_operators(self):
        assert [t.kind for t in tokenize("= != =~")] == [
            TokenKind.EQ,
            TokenKind.NEQ,
            TokenKind.REGEX,
            TokenKind.EOF,
        ]

    def test_strings(self):
        assert [t.value for t in tokenize("'single'")] == ["single", ""]
        assert [t.value for t in tokenize('"double"')] == ["double", ""]
        assert [t.value for t in tokenize(r"'escaped \' quote'")] == ["escaped ' quote", ""]

    def test_numbers(self):
        assert [t.kind for t in tokenize("123 456")] == [
            TokenKind.NUMBER,
            TokenKind.NUMBER,
            TokenKind.EOF,
        ]

    def test_unterminated_string(self):
        with pytest.raises(QueryError, match="unterminated string"):
            tokenize("'no end")

    def test_unexpected_character(self):
        with pytest.raises(QueryError, match="unexpected character"):
            tokenize("Function @ Call")


class TestNodeParser:
    def test_wildcard(self):
        q = parse("*")
        assert q.start == NodePattern()
        assert not q.hops

    def test_type_only(self):
        q = parse("Function")
        assert q.start == NodePattern(type_name="Function")
        assert not q.hops

    def test_name_only(self):
        q = parse("'my_func'")
        assert q.start == NodePattern(name="my_func")
        assert not q.hops

    def test_filtered_type(self):
        q = parse("Function[name='login']")
        assert q.start == NodePattern(
            type_name="Function",
            filters=(FilterExpr("name", FilterOp.EQ, "login"),),
        )

    def test_filtered_name(self):
        q = parse("'my_func'[id='123']")
        assert q.start == NodePattern(
            name="my_func",
            filters=(FilterExpr("id", FilterOp.EQ, "123"),),
        )

    def test_filtered_wildcard(self):
        q = parse("*[type='Function']")
        assert q.start == NodePattern(
            filters=(FilterExpr("type", FilterOp.EQ, "Function"),),
        )

    def test_multiple_filters(self):
        q = parse("Function[name='login', id='123']")
        assert q.start == NodePattern(
            type_name="Function",
            filters=(
                FilterExpr("name", FilterOp.EQ, "login"),
                FilterExpr("id", FilterOp.EQ, "123"),
            ),
        )

    def test_regex_filter(self):
        q = parse("Function[file_path=~'.*/auth/.*']")
        assert q.start == NodePattern(
            type_name="Function",
            filters=(FilterExpr("file_path", FilterOp.REGEX, ".*/auth/.*"),),
        )

    def test_neq_filter(self):
        q = parse("Function[name!='main']")
        assert q.start == NodePattern(
            type_name="Function",
            filters=(FilterExpr("name", FilterOp.NEQ, "main"),),
        )


class TestEdgeParser:
    def test_default_outgoing(self):
        q = parse("A -> B")
        edge, target = q.hops[0]
        assert edge == EdgePattern(direction=Direction.OUTGOING)
        assert target == NodePattern(type_name="B")

    def test_incoming(self):
        q = parse("A <- B")
        edge, target = q.hops[0]
        assert edge == EdgePattern(direction=Direction.INCOMING)

    def test_both(self):
        q = parse("A <-> B")
        edge, target = q.hops[0]
        assert edge == EdgePattern(direction=Direction.BOTH)

    def test_typed_outgoing(self):
        q = parse("A CALLS B")
        edge, target = q.hops[0]
        assert edge == EdgePattern(type_name="CALLS", direction=Direction.OUTGOING)

    def test_explicit_typed_outgoing(self):
        q = parse("A -> CALLS -> B")
        edge, target = q.hops[0]
        assert edge == EdgePattern(type_name="CALLS", direction=Direction.OUTGOING)

    def test_explicit_typed_incoming(self):
        q = parse("A <- CALLS <- B")
        edge, target = q.hops[0]
        assert edge == EdgePattern(type_name="CALLS", direction=Direction.INCOMING)

    def test_explicit_typed_both(self):
        q = parse("A <-> CALLS <-> B")
        edge, target = q.hops[0]
        assert edge == EdgePattern(type_name="CALLS", direction=Direction.BOTH)

    def test_transitive_default(self):
        q = parse("A CALLS+ B")
        edge, target = q.hops[0]
        assert edge == EdgePattern(type_name="CALLS", direction=Direction.OUTGOING, transitive=True)

    def test_transitive_explicit_outgoing(self):
        q = parse("A -> CALLS+ -> B")
        edge, target = q.hops[0]
        assert edge == EdgePattern(type_name="CALLS", direction=Direction.OUTGOING, transitive=True)

    def test_transitive_explicit_incoming(self):
        q = parse("A <- CALLS+ <- B")
        edge, target = q.hops[0]
        assert edge == EdgePattern(type_name="CALLS", direction=Direction.INCOMING, transitive=True)

    def test_transitive_explicit_both(self):
        q = parse("A <-> CALLS+ <-> B")
        edge, target = q.hops[0]
        assert edge == EdgePattern(type_name="CALLS", direction=Direction.BOTH, transitive=True)


class TestPathQuery:
    def test_single_node(self):
        q = parse("Function")
        assert q.start == NodePattern(type_name="Function")
        assert not q.hops

    def test_simple_hop(self):
        q = parse("A -> B")
        assert q.start == NodePattern(type_name="A")
        assert len(q.hops) == 1
        assert q.hops[0][0] == EdgePattern(direction=Direction.OUTGOING)
        assert q.hops[0][1] == NodePattern(type_name="B")

    def test_multi_hop(self):
        q = parse("A -> -> B -> -> C -> -> D")
        assert len(q.hops) == 3
        assert q.hops[0][1] == NodePattern(type_name="B")
        assert q.hops[1][1] == NodePattern(type_name="C")
        assert q.hops[2][1] == NodePattern(type_name="D")

    def test_mixed_directions(self):
        q = parse("A -> -> B <- <- C")
        assert len(q.hops) == 2
        assert q.hops[0][0].direction == Direction.OUTGOING
        assert q.hops[1][0].direction == Direction.INCOMING

    def test_complex_query(self):
        expr = "Function[name='main'] -> CALLS+ -> Function[name='auth'] <-> DEPENDS <-> Module"
        q = parse(expr)
        assert q.start == NodePattern(type_name="Function", filters=(FilterExpr("name", FilterOp.EQ, "main"),))
        assert len(q.hops) == 2
        # Hop 1: CALLS+ -> Function[name='auth']
        assert q.hops[0][0] == EdgePattern(type_name="CALLS", direction=Direction.OUTGOING, transitive=True)
        assert q.hops[0][1] == NodePattern(type_name="Function", filters=(FilterExpr("name", FilterOp.EQ, "auth"),))
        # Hop 2: <-> DEPENDS <-> Module
        assert q.hops[1][0] == EdgePattern(type_name="DEPENDS", direction=Direction.BOTH)
        assert q.hops[1][1] == NodePattern(type_name="Module")

    def test_wildcards_everywhere(self):
        q = parse("* -> * -> *")
        assert q.start == NodePattern()
        assert len(q.hops) == 2
        assert q.hops[0][1] == NodePattern()
        assert q.hops[1][1] == NodePattern()


class TestQueryParserErrors:
    def test_missing_target(self):
        with pytest.raises(QueryError, match="expected node pattern"):
            parse("A ->")

    def test_missing_start(self):
        with pytest.raises(QueryError, match="expected node pattern"):
            parse("-> B")

    def test_mismatched_arrows_single_edge(self):
        with pytest.raises(QueryError, match="mismatched arrows"):
            parse("A -> CALLS <- B")

    def test_empty_edge_no_arrows(self):
        with pytest.raises(QueryError, match="expected node pattern"):
            parse("A B")

    def test_invalid_filter_operator(self):
        with pytest.raises(QueryError, match="unexpected character"):
            parse("A[name > 'a']")


# I will update the tokenizer tests to use these helpers.
