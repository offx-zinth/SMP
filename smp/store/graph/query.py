"""Path expression query language for the memory-mapped graph store.

Implements the Phase 1 path-expression grammar described in ``SPEC.md``:

    PATTERN     := NODE_PATTERN ( EDGE_PATTERN NODE_PATTERN )*
    NODE_PATTERN := (IDENT | '*' | STRING) FILTER_LIST?
    FILTER_LIST  := '[' FILTER ( ',' FILTER )* ']'
    FILTER       := IDENT OP (STRING | IDENT)
    OP           := '=' | '!=' | '=~'
    EDGE_PATTERN := ARROW? IDENT? '+'? ARROW?
    ARROW        := '->' | '<-' | '<->'

Examples accepted by this parser/evaluator:

    Function CALLS Function                                 # all function calls
    Class -> DEFINES -> Method                              # explicit outgoing
    * IMPORTS 'requests'                                    # name match on rhs
    Function CALLS+ Function                                # transitive closure
    Function[name='login'] CALLS Function                   # filtered start
    Class[file_path=~'.*/auth/.*'] DEFINES Method           # regex filter

The query engine talks to the graph through a small protocol so it can be
unit-tested against the in-memory state of ``MMapGraphStore`` (and any other
``GraphStore`` that exposes the same async surface).
"""

from __future__ import annotations

import enum
import re
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import Any, Protocol

from smp.core.models import EdgeType, GraphEdge, GraphNode, NodeType

# ---------------------------------------------------------------------------
# Tokenizer
# ---------------------------------------------------------------------------


class TokenKind(enum.StrEnum):
    IDENT = "IDENT"
    STRING = "STRING"
    NUMBER = "NUMBER"
    ARROW_RIGHT = "ARROW_RIGHT"
    ARROW_LEFT = "ARROW_LEFT"
    ARROW_BOTH = "ARROW_BOTH"
    PLUS = "PLUS"
    STAR = "STAR"
    LBRACKET = "LBRACKET"
    RBRACKET = "RBRACKET"
    EQ = "EQ"
    NEQ = "NEQ"
    REGEX = "REGEX"
    COMMA = "COMMA"
    EOF = "EOF"


@dataclass(frozen=True)
class Token:
    kind: TokenKind
    value: str
    pos: int


class QueryError(ValueError):
    """Raised when a path expression cannot be tokenized, parsed, or evaluated."""


def tokenize(expression: str) -> list[Token]:
    """Lex *expression* into a flat list of tokens (terminated by ``EOF``)."""
    tokens: list[Token] = []
    i = 0
    n = len(expression)

    while i < n:
        c = expression[i]
        if c.isspace():
            i += 1
            continue

        if c == "<" and i + 2 < n and expression[i + 1] == "-" and expression[i + 2] == ">":
            tokens.append(Token(TokenKind.ARROW_BOTH, "<->", i))
            i += 3
            continue
        if c == "<" and i + 1 < n and expression[i + 1] == "-":
            tokens.append(Token(TokenKind.ARROW_LEFT, "<-", i))
            i += 2
            continue
        if c == "-" and i + 1 < n and expression[i + 1] == ">":
            tokens.append(Token(TokenKind.ARROW_RIGHT, "->", i))
            i += 2
            continue

        if c == "=" and i + 1 < n and expression[i + 1] == "~":
            tokens.append(Token(TokenKind.REGEX, "=~", i))
            i += 2
            continue
        if c == "!" and i + 1 < n and expression[i + 1] == "=":
            tokens.append(Token(TokenKind.NEQ, "!=", i))
            i += 2
            continue
        if c == "=":
            tokens.append(Token(TokenKind.EQ, "=", i))
            i += 1
            continue

        if c == "+":
            tokens.append(Token(TokenKind.PLUS, "+", i))
            i += 1
            continue
        if c == "*":
            tokens.append(Token(TokenKind.STAR, "*", i))
            i += 1
            continue
        if c == "[":
            tokens.append(Token(TokenKind.LBRACKET, "[", i))
            i += 1
            continue
        if c == "]":
            tokens.append(Token(TokenKind.RBRACKET, "]", i))
            i += 1
            continue
        if c == ",":
            tokens.append(Token(TokenKind.COMMA, ",", i))
            i += 1
            continue

        if c in {"'", '"'}:
            start = i
            quote = c
            i += 1
            buf: list[str] = []
            while i < n and expression[i] != quote:
                if expression[i] == "\\" and i + 1 < n:
                    buf.append(expression[i + 1])
                    i += 2
                    continue
                buf.append(expression[i])
                i += 1
            if i >= n:
                raise QueryError(f"unterminated string starting at position {start}")
            i += 1
            tokens.append(Token(TokenKind.STRING, "".join(buf), start))
            continue

        if c.isalpha() or c == "_":
            start = i
            while i < n and (expression[i].isalnum() or expression[i] == "_"):
                i += 1
            tokens.append(Token(TokenKind.IDENT, expression[start:i], start))
            continue

        if c.isdigit():
            start = i
            while i < n and expression[i].isdigit():
                i += 1
            tokens.append(Token(TokenKind.NUMBER, expression[start:i], start))
            continue

        raise QueryError(f"unexpected character {c!r} at position {i}")

    tokens.append(Token(TokenKind.EOF, "", n))
    return tokens


# ---------------------------------------------------------------------------
# AST
# ---------------------------------------------------------------------------


class FilterOp(enum.StrEnum):
    EQ = "="
    NEQ = "!="
    REGEX = "=~"


@dataclass(frozen=True)
class FilterExpr:
    """A single ``[field op value]`` clause attached to a node pattern."""

    field: str
    op: FilterOp
    value: str


@dataclass(frozen=True)
class NodePattern:
    """A node match in the path expression.

    ``type_name`` is the unquoted identifier (e.g. ``Function``).  ``name`` is a
    quoted string literal (e.g. ``'requests'``).  At most one of the two is set;
    if both are ``None`` the pattern is a wildcard.
    """

    type_name: str | None = None
    name: str | None = None
    filters: tuple[FilterExpr, ...] = ()


class Direction(enum.StrEnum):
    OUTGOING = "outgoing"
    INCOMING = "incoming"
    BOTH = "both"


@dataclass(frozen=True)
class EdgePattern:
    """An edge constraint between two node patterns."""

    type_name: str | None = None
    direction: Direction = Direction.OUTGOING
    transitive: bool = False


@dataclass(frozen=True)
class PathQuery:
    """A complete parsed path expression."""

    start: NodePattern
    hops: tuple[tuple[EdgePattern, NodePattern], ...] = ()


# ---------------------------------------------------------------------------
# Parser
# ---------------------------------------------------------------------------


class _Parser:
    def __init__(self, tokens: Sequence[Token]) -> None:
        self._tokens = list(tokens)
        self._pos = 0

    def _peek(self, offset: int = 0) -> Token:
        return self._tokens[self._pos + offset]

    def _advance(self) -> Token:
        tok = self._tokens[self._pos]
        self._pos += 1
        return tok

    def _expect(self, kind: TokenKind) -> Token:
        tok = self._peek()
        if tok.kind != kind:
            raise QueryError(f"expected {kind.value} but got {tok.kind.value} ({tok.value!r}) at position {tok.pos}")
        return self._advance()

    def parse(self) -> PathQuery:
        start = self._parse_node()
        hops: list[tuple[EdgePattern, NodePattern]] = []
        while self._peek().kind != TokenKind.EOF:
            edge = self._parse_edge()
            target = self._parse_node()
            hops.append((edge, target))
        return PathQuery(start=start, hops=tuple(hops))

    def _parse_node(self) -> NodePattern:
        tok = self._peek()
        type_name: str | None = None
        name: str | None = None
        if tok.kind == TokenKind.STAR:
            self._advance()
        elif tok.kind == TokenKind.IDENT:
            self._advance()
            type_name = tok.value
        elif tok.kind == TokenKind.STRING:
            self._advance()
            name = tok.value
        else:
            raise QueryError(
                f"expected node pattern (IDENT | '*' | STRING) but got {tok.kind.value} ({tok.value!r}) "
                f"at position {tok.pos}"
            )
        filters: tuple[FilterExpr, ...] = ()
        if self._peek().kind == TokenKind.LBRACKET:
            filters = self._parse_filters()
        return NodePattern(type_name=type_name, name=name, filters=filters)

    def _parse_filters(self) -> tuple[FilterExpr, ...]:
        self._expect(TokenKind.LBRACKET)
        filters: list[FilterExpr] = []
        if self._peek().kind == TokenKind.RBRACKET:
            self._advance()
            return ()
        filters.append(self._parse_filter())
        while self._peek().kind == TokenKind.COMMA:
            self._advance()
            filters.append(self._parse_filter())
        self._expect(TokenKind.RBRACKET)
        return tuple(filters)

    def _parse_filter(self) -> FilterExpr:
        field_tok = self._expect(TokenKind.IDENT)
        op_tok = self._advance()
        if op_tok.kind == TokenKind.EQ:
            op = FilterOp.EQ
        elif op_tok.kind == TokenKind.NEQ:
            op = FilterOp.NEQ
        elif op_tok.kind == TokenKind.REGEX:
            op = FilterOp.REGEX
        else:
            raise QueryError(
                f"expected filter operator (=, !=, =~) but got {op_tok.kind.value} ({op_tok.value!r}) "
                f"at position {op_tok.pos}"
            )
        value_tok = self._advance()
        if value_tok.kind not in (TokenKind.STRING, TokenKind.IDENT, TokenKind.NUMBER):
            raise QueryError(
                f"expected filter value (STRING, IDENT or NUMBER) but got {value_tok.kind.value} "
                f"({value_tok.value!r}) at position {value_tok.pos}"
            )
        return FilterExpr(field=field_tok.value, op=op, value=value_tok.value)

    def _parse_edge(self) -> EdgePattern:
        leading = self._consume_arrow()
        type_name: str | None = None
        transitive = False

        if leading is None:
            # Bare form: ``IDENT '+'?`` with no surrounding arrows.
            if self._peek().kind == TokenKind.IDENT:
                type_name = self._advance().value
                if self._peek().kind == TokenKind.PLUS:
                    self._advance()
                    transitive = True
        else:
            # Arrow-wrapped form: only treat an IDENT as the edge type if a
            # matching trailing arrow follows.  Otherwise leave the IDENT for
            # the next node pattern (e.g. ``Class -> Method``).
            if self._peek().kind == TokenKind.IDENT and self._lookahead_is_arrow_after_ident():
                type_name = self._advance().value
                if self._peek().kind == TokenKind.PLUS:
                    self._advance()
                    transitive = True

        trailing = self._consume_arrow()

        if leading is None and trailing is None and type_name is None:
            raise QueryError("empty edge pattern between nodes")

        if leading is not None and trailing is not None and leading.kind != trailing.kind:
            raise QueryError(
                f"mismatched arrows around edge pattern: {leading.value} ... {trailing.value} "
                f"(at position {trailing.pos})"
            )

        arrow = leading if leading is not None else trailing
        if arrow is None or arrow.kind == TokenKind.ARROW_RIGHT:
            direction = Direction.OUTGOING
        elif arrow.kind == TokenKind.ARROW_LEFT:
            direction = Direction.INCOMING
        else:
            direction = Direction.BOTH

        return EdgePattern(type_name=type_name, direction=direction, transitive=transitive)

    def _lookahead_is_arrow_after_ident(self) -> bool:
        """Return ``True`` when the IDENT at ``_peek(0)`` is followed by an arrow.

        Used to disambiguate ``-> EDGE_TYPE [+] ->`` from ``-> NODE_TYPE``.  The
        IDENT counts as an edge type only when an arrow (optionally preceded by
        ``+``) eventually closes the edge clause.
        """
        offset = 1
        if self._peek(offset).kind == TokenKind.PLUS:
            offset += 1
        return self._peek(offset).kind in (
            TokenKind.ARROW_RIGHT,
            TokenKind.ARROW_LEFT,
            TokenKind.ARROW_BOTH,
        )

    def _consume_arrow(self) -> Token | None:
        tok = self._peek()
        if tok.kind in (TokenKind.ARROW_RIGHT, TokenKind.ARROW_LEFT, TokenKind.ARROW_BOTH):
            return self._advance()
        return None


def parse(expression: str) -> PathQuery:
    """Parse a path expression string into a :class:`PathQuery`."""
    return _Parser(tokenize(expression)).parse()


# ---------------------------------------------------------------------------
# Evaluator
# ---------------------------------------------------------------------------


_NODE_FIELD_GETTERS: dict[str, Callable[[GraphNode], str]] = {
    "id": lambda n: n.id,
    "type": lambda n: n.type.value,
    "file_path": lambda n: n.file_path,
    "name": lambda n: n.structural.name,
    "signature": lambda n: n.structural.signature,
    "start_line": lambda n: str(n.structural.start_line),
    "end_line": lambda n: str(n.structural.end_line),
    "docstring": lambda n: n.semantic.docstring or "",
    "description": lambda n: n.semantic.description or "",
    "status": lambda n: n.semantic.status,
}


def _other_end(edge: GraphEdge, current_id: str, direction: Direction) -> str:
    """Return the id of the node on the *other* side of *edge* relative to ``current_id``.

    For ``OUTGOING`` we want the target; for ``INCOMING`` we want the source.
    For ``BOTH`` we follow whichever endpoint is not ``current_id``.
    """
    if direction == Direction.OUTGOING:
        return edge.target_id
    if direction == Direction.INCOMING:
        return edge.source_id
    return edge.source_id if edge.target_id == current_id else edge.target_id


def _normalize_type(name: str) -> str:
    """Return the canonical ``NodeType`` value for a user-supplied identifier.

    Accepts either the canonical mixed-case form (``Function``) or any case
    variant; falls back to the raw identifier if it is not a known node type.
    """
    for nt in NodeType:
        if nt.value.lower() == name.lower():
            return nt.value
    return name


def _normalize_edge_type(name: str) -> str:
    for et in EdgeType:
        if et.value.lower() == name.lower():
            return et.value
    return name.upper()


def _node_matches_pattern(node: GraphNode, pattern: NodePattern) -> bool:
    if pattern.type_name is not None and node.type.value != _normalize_type(pattern.type_name):
        return False
    if pattern.name is not None and node.structural.name != pattern.name:
        return False
    for f in pattern.filters:
        getter = _NODE_FIELD_GETTERS.get(f.field)
        if getter is None:
            return False
        actual = getter(node) or ""
        if f.op == FilterOp.EQ and actual != f.value:
            return False
        if f.op == FilterOp.NEQ and actual == f.value:
            return False
        if f.op == FilterOp.REGEX:
            try:
                if not re.search(f.value, actual):
                    return False
            except re.error as exc:
                raise QueryError(f"invalid regex {f.value!r}: {exc}") from exc
    return True


class GraphStoreLike(Protocol):
    """Minimal async surface required by :class:`QueryEngine`."""

    async def get_node(self, node_id: str) -> GraphNode | None: ...

    async def get_edges(
        self, node_id: str, edge_type: EdgeType | None = ..., direction: str = ...
    ) -> list[GraphEdge]: ...

    async def find_nodes(
        self,
        *,
        type: NodeType | None = ...,
        file_path: str | None = ...,
        name: str | None = ...,
    ) -> list[GraphNode]: ...


@dataclass
class QueryResult:
    """Result of executing a :class:`PathQuery` against a graph store."""

    nodes: list[GraphNode] = field(default_factory=list)
    edges: list[GraphEdge] = field(default_factory=list)
    stats: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "nodes": [_node_to_dict(n) for n in self.nodes],
            "edges": [_edge_to_dict(e) for e in self.edges],
            "stats": self.stats,
        }


def _node_to_dict(n: GraphNode) -> dict[str, Any]:
    return {
        "id": n.id,
        "type": n.type.value,
        "file_path": n.file_path,
        "name": n.structural.name,
        "signature": n.structural.signature,
        "start_line": n.structural.start_line,
        "end_line": n.structural.end_line,
    }


def _edge_to_dict(e: GraphEdge) -> dict[str, Any]:
    return {
        "source_id": e.source_id,
        "target_id": e.target_id,
        "type": e.type.value,
    }


class QueryEngine:
    """Execute parsed path expressions against a :class:`GraphStoreLike`."""

    def __init__(self, store: GraphStoreLike) -> None:
        self._store = store

    async def execute(
        self,
        query: PathQuery,
        *,
        max_results: int = 10_000,
    ) -> QueryResult:
        seen_nodes: dict[str, GraphNode] = {}
        seen_edges: dict[tuple[str, str, str], GraphEdge] = {}

        starts = await self._initial_nodes(query.start)
        for n in starts:
            seen_nodes.setdefault(n.id, n)

        current: list[GraphNode] = list(starts)
        for edge_pattern, target_pattern in query.hops:
            current = await self._step(
                current=current,
                edge_pattern=edge_pattern,
                target_pattern=target_pattern,
                seen_nodes=seen_nodes,
                seen_edges=seen_edges,
                max_results=max_results,
            )
            if not current:
                break

        return QueryResult(
            nodes=list(seen_nodes.values()),
            edges=list(seen_edges.values()),
            stats={
                "matched_nodes": len(seen_nodes),
                "matched_edges": len(seen_edges),
                "terminal_nodes": len(current),
                "hops": len(query.hops),
            },
        )

    async def _initial_nodes(self, pattern: NodePattern) -> list[GraphNode]:
        node_type: NodeType | None = None
        if pattern.type_name is not None:
            type_value = _normalize_type(pattern.type_name)
            try:
                node_type = NodeType(type_value)
            except ValueError as exc:
                raise QueryError(f"unknown node type {pattern.type_name!r}") from exc
        candidates = await self._store.find_nodes(type=node_type, name=pattern.name)
        return [n for n in candidates if _node_matches_pattern(n, pattern)]

    async def _step(
        self,
        *,
        current: list[GraphNode],
        edge_pattern: EdgePattern,
        target_pattern: NodePattern,
        seen_nodes: dict[str, GraphNode],
        seen_edges: dict[tuple[str, str, str], GraphEdge],
        max_results: int,
    ) -> list[GraphNode]:
        edge_type = self._resolve_edge_type(edge_pattern.type_name)
        next_nodes: dict[str, GraphNode] = {}

        if edge_pattern.transitive:
            for src in current:
                await self._walk_transitive(
                    src=src,
                    edge_type=edge_type,
                    direction=edge_pattern.direction,
                    target_pattern=target_pattern,
                    seen_nodes=seen_nodes,
                    seen_edges=seen_edges,
                    next_nodes=next_nodes,
                    max_results=max_results,
                )
            return list(next_nodes.values())

        for src in current:
            edges = await self._store.get_edges(src.id, edge_type, edge_pattern.direction.value)
            for edge in edges:
                target_id = _other_end(edge, src.id, edge_pattern.direction)
                target = await self._store.get_node(target_id)
                if target is None:
                    continue
                if not _node_matches_pattern(target, target_pattern):
                    continue
                seen_nodes.setdefault(target.id, target)
                seen_edges.setdefault((edge.source_id, edge.target_id, edge.type.value), edge)
                next_nodes.setdefault(target.id, target)
                if len(seen_nodes) >= max_results:
                    return list(next_nodes.values())

        return list(next_nodes.values())

    async def _walk_transitive(
        self,
        *,
        src: GraphNode,
        edge_type: EdgeType | None,
        direction: Direction,
        target_pattern: NodePattern,
        seen_nodes: dict[str, GraphNode],
        seen_edges: dict[tuple[str, str, str], GraphEdge],
        next_nodes: dict[str, GraphNode],
        max_results: int,
    ) -> None:
        visited: set[str] = {src.id}
        stack: list[str] = [src.id]
        while stack:
            cur_id = stack.pop()
            edges = await self._store.get_edges(cur_id, edge_type, direction.value)
            for edge in edges:
                target_id = _other_end(edge, cur_id, direction)
                target = await self._store.get_node(target_id)
                if target is None:
                    continue
                seen_edges.setdefault((edge.source_id, edge.target_id, edge.type.value), edge)
                if _node_matches_pattern(target, target_pattern):
                    seen_nodes.setdefault(target.id, target)
                    next_nodes.setdefault(target.id, target)
                    if len(seen_nodes) >= max_results:
                        return
                if target_id not in visited:
                    visited.add(target_id)
                    stack.append(target_id)

    def _resolve_edge_type(self, name: str | None) -> EdgeType | None:
        if name is None:
            return None
        canonical = _normalize_edge_type(name)
        try:
            return EdgeType(canonical)
        except ValueError as exc:
            raise QueryError(f"unknown edge type {name!r}") from exc


# ---------------------------------------------------------------------------
# Public helpers
# ---------------------------------------------------------------------------


async def execute_query(
    store: GraphStoreLike,
    expression: str,
    *,
    max_results: int = 10_000,
) -> QueryResult:
    """Parse and execute *expression* against *store*."""
    query = parse(expression)
    engine = QueryEngine(store)
    return await engine.execute(query, max_results=max_results)


__all__ = [
    "Direction",
    "EdgePattern",
    "FilterExpr",
    "FilterOp",
    "GraphStoreLike",
    "NodePattern",
    "PathQuery",
    "QueryEngine",
    "QueryError",
    "QueryResult",
    "Token",
    "TokenKind",
    "execute_query",
    "parse",
    "tokenize",
]
