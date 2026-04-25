from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Final

try:
    import tree_sitter_languages
    from tree_sitter import Language, Parser

    HAS_TREE_SITTER = True
except ImportError:
    HAS_TREE_SITTER = False

LANG_PYTHON: Final[str] = "python"
LANG_UNKNOWN: Final[str] = "unknown"

_PYTHON_EXTENSIONS: Final[set[str]] = {".py", ".pyw", ".pyi"}

# Node types we care about for code graph
INTERESTING_TYPES: Final[set[str]] = {
    "module",
    "class",
    "function_definition",
    "async_function_definition",
    "method",
    "import_statement",
    "import_from_statement",
    "call",
    "identifier",
    "decorated_definition",
}


@dataclass
class ParsedNode:
    """A node extracted from source code."""

    node_id: str
    type: str
    name: str
    signature: str
    docstring: str
    start_line: int
    end_line: int
    tags: list[str] = field(default_factory=list)
    decorators: list[str] = field(default_factory=list)
    parent_id: str | None = None


@dataclass
class EdgeCandidate:
    """An unresolved edge from one node to another."""

    source_id: str
    target_name: str
    edge_type: str
    target_file_hint: str | None = None


@dataclass
class ParsedFile:
    """Result of parsing a source file."""

    file_path: str
    language: str
    line_count: int
    content_hash: str
    nodes: list[ParsedNode] = field(default_factory=list)
    edge_candidates: list[EdgeCandidate] = field(default_factory=list)
    resolved_edges: list[Any] = field(default_factory=list)


class CodeParser:
    """Wrapper around tree-sitter for parsing source code.

    Only Python is parsed structurally; other extensions yield an empty
    :class:`ParsedFile` so the graph store can still record file-level
    bookkeeping without raising.  Multi-language support is a future
    extension (see ``SPEC.md`` § Future Extensions).
    """

    def __init__(self) -> None:
        if not HAS_TREE_SITTER:
            raise ImportError("tree-sitter not installed. Run: pip install tree-sitter-python")
        self._parsers: dict[str, Parser] = {}
        self._languages: dict[str, Language] = {}
        self._python_ready = False

    def _ensure_python(self) -> None:
        """Lazily load the Python tree-sitter grammar.

        The legacy ``tree_sitter_languages`` bundle is tried first for
        backwards compatibility; if it fails (version mismatch) we fall
        back to the dedicated ``tree_sitter_python`` package.
        """
        if self._python_ready:
            return

        loaded = False
        try:
            ts_lang = tree_sitter_languages.get_language("python")
            parser = Parser()
            if hasattr(parser, "language"):
                parser.language = ts_lang
            else:
                parser.set_language(ts_lang)
            self._languages[LANG_PYTHON] = ts_lang
            self._parsers[LANG_PYTHON] = parser
            loaded = True
        except Exception:  # noqa: BLE001
            pass

        if not loaded:
            try:
                import tree_sitter as _ts
                import tree_sitter_python as _tsp

                ts_lang = _ts.Language(_tsp.language())
                parser = _ts.Parser(ts_lang)
                self._languages[LANG_PYTHON] = ts_lang
                self._parsers[LANG_PYTHON] = parser
                loaded = True
            except Exception:  # noqa: BLE001
                pass

        self._python_ready = loaded

    @staticmethod
    def _is_python(file_path: str | Path) -> bool:
        """Return True when the file should use the native Python walker."""
        return Path(file_path).suffix.lower() in _PYTHON_EXTENSIONS

    def _compute_hash(self, content: bytes) -> str:
        """Compute hash of file content."""
        return hashlib.blake2b(content, digest_size=8).hexdigest()

    def _make_node_id(self, file_path: str, node_type: str, name: str, start_line: int) -> str:
        """Create a deterministic node ID."""
        path_hash = hashlib.blake2b(Path(file_path).resolve().as_posix().encode(), digest_size=4).hexdigest()
        return f"{path_hash}::{node_type}::{name}::{start_line}"

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def parse_file(self, file_path: str | Path) -> ParsedFile:
        """Parse a source file and extract nodes.

        Python files use the built-in tree-sitter walker.  Files with other
        extensions yield an empty :class:`ParsedFile` (no nodes / no edges).
        """
        path = Path(file_path)
        if not path.exists():
            raise FileNotFoundError(f"File not found: {path}")

        content = path.read_bytes()
        if self._is_python(path):
            return self._parse_python(str(path), content)

        return self._empty_parsed_file(str(path), content)

    def parse_content(self, file_path: str, content: bytes) -> ParsedFile:
        """Parse source content (bytes) and extract nodes.

        Non-Python content yields an empty :class:`ParsedFile`.
        """
        if self._is_python(file_path):
            return self._parse_python(file_path, content)
        return self._empty_parsed_file(file_path, content)

    def parse(self, content: str | bytes, file_path: str) -> ParsedFile:
        """Convenience overload accepting raw source text."""
        if isinstance(content, str):
            content = content.encode("utf-8")
        return self.parse_content(file_path, content)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _empty_parsed_file(self, file_path: str, content: bytes) -> ParsedFile:
        text = content.decode("utf-8", errors="replace")
        return ParsedFile(
            file_path=file_path,
            language=LANG_UNKNOWN,
            line_count=len(text.splitlines()),
            content_hash=self._compute_hash(content),
        )

    # ------------------------------------------------------------------
    # Python tree-sitter walker
    # ------------------------------------------------------------------

    def _parse_python(self, file_path: str, content: bytes) -> ParsedFile:
        """Parse Python content using the native tree-sitter walker."""
        self._ensure_python()

        text = content.decode("utf-8", errors="replace")
        line_count = len(text.splitlines())
        file_hash = self._compute_hash(content)

        if LANG_PYTHON not in self._parsers:
            return ParsedFile(
                file_path=file_path,
                language=LANG_PYTHON,
                line_count=line_count,
                content_hash=file_hash,
            )

        parser = self._parsers[LANG_PYTHON]
        tree = parser.parse(content)

        nodes: list[ParsedNode] = []
        edge_candidates: list[EdgeCandidate] = []
        scope_stack: list[tuple[str, int]] = []

        self._walk_tree(
            tree.root_node,
            content,
            file_path,
            nodes,
            edge_candidates,
            scope_stack,
            LANG_PYTHON,
        )

        return ParsedFile(
            file_path=file_path,
            language=LANG_PYTHON,
            line_count=line_count,
            content_hash=file_hash,
            nodes=nodes,
            edge_candidates=edge_candidates,
        )

    def _walk_tree(
        self,
        node: Any,
        content: bytes,
        file_path: str,
        nodes: list[ParsedNode],
        edge_candidates: list[EdgeCandidate],
        scope_stack: list[tuple[str, int]],
        lang: str,
    ) -> None:
        """Walk the tree and extract nodes."""
        node_type = node.type

        if node_type in ("function_definition", "async_function_definition", "method"):
            self._handle_function(node, content, file_path, nodes, edge_candidates, scope_stack, lang)
        elif node_type == "class":
            self._handle_class(node, content, file_path, nodes, scope_stack, lang)
        elif node_type in ("import_statement", "import_from_statement"):
            self._handle_import(node, content, file_path, edge_candidates, scope_stack)
        elif node_type == "call":
            self._handle_call(node, content, file_path, edge_candidates, scope_stack)

        for child in node.children:
            self._walk_tree(child, content, file_path, nodes, edge_candidates, scope_stack, lang)

        if scope_stack and scope_stack[-1][1] == node.end_point[0]:
            scope_stack.pop()

    def _handle_function(
        self,
        node: Any,
        content: bytes,
        file_path: str,
        nodes: list[ParsedNode],
        edge_candidates: list[EdgeCandidate],
        scope_stack: list[tuple[str, int]],
        lang: str,
    ) -> None:
        """Extract a function/method definition."""
        name_node = node.child_by_field_name("name")
        if name_node is None:
            return
        name = content[name_node.start_byte : name_node.end_byte].decode("utf-8", errors="replace")

        start_line = node.start_point[0] + 1
        end_line = node.end_point[0] + 1

        param_node = node.child_by_field_name("parameters")
        if param_node:
            signature = content[param_node.start_byte : param_node.end_byte].decode("utf-8", errors="replace")
            signature = f"def {name}({signature})"
        else:
            signature = f"def {name}()"

        docstring = self._extract_docstring(node, content)
        decorators = self._extract_decorators(node, content)

        node_id = self._make_node_id(file_path, "Function", name, start_line)

        parsed_node = ParsedNode(
            node_id=node_id,
            type="Function",
            name=name,
            signature=signature,
            docstring=docstring,
            start_line=start_line,
            end_line=end_line,
            decorators=decorators,
        )

        if scope_stack:
            parsed_node.parent_id = scope_stack[-1][0]

        nodes.append(parsed_node)
        scope_stack.append((node_id, end_line))

        if lang == LANG_PYTHON:
            self._add_python_imports(node, content, file_path, node_id, edge_candidates)

    def _handle_class(
        self,
        node: Any,
        content: bytes,
        file_path: str,
        nodes: list[ParsedNode],
        scope_stack: list[tuple[str, int]],
        lang: str,
    ) -> None:
        """Extract a class definition."""
        del lang
        name_node = node.child_by_field_name("name")
        if name_node is None:
            return
        name = content[name_node.start_byte : name_node.end_byte].decode("utf-8", errors="replace")

        start_line = node.start_point[0] + 1
        end_line = node.end_point[0] + 1
        docstring = self._extract_docstring(node, content)
        decorators = self._extract_decorators(node, content)

        node_id = self._make_node_id(file_path, "Class", name, start_line)
        class_signature = f"class {name}"

        parsed_node = ParsedNode(
            node_id=node_id,
            type="Class",
            name=name,
            signature=class_signature,
            docstring=docstring,
            start_line=start_line,
            end_line=end_line,
            decorators=decorators,
        )

        if scope_stack:
            parsed_node.parent_id = scope_stack[-1][0]

        nodes.append(parsed_node)
        scope_stack.append((node_id, end_line))

    def _handle_import(
        self,
        node: Any,
        content: bytes,
        file_path: str,
        edge_candidates: list[EdgeCandidate],
        scope_stack: list[tuple[str, int]],
    ) -> None:
        """Extract import statements."""
        if scope_stack:
            source_id = scope_stack[-1][0]
        else:
            path_hash = hashlib.blake2b(Path(file_path).resolve().as_posix().encode(), digest_size=4).hexdigest()
            source_id = f"{path_hash}::Module::module::1"

        for child in node.children:
            if child.type == "identifier":
                name = content[child.start_byte : child.end_byte].decode("utf-8", errors="replace")
                if name and name[0].islower():
                    continue
                edge_candidates.append(
                    EdgeCandidate(
                        source_id=source_id,
                        target_name=name,
                        edge_type="IMPORTS",
                        target_file_hint=None,
                    )
                )

    def _handle_call(
        self,
        node: Any,
        content: bytes,
        file_path: str,
        edge_candidates: list[EdgeCandidate],
        scope_stack: list[tuple[str, int]],
    ) -> None:
        """Extract function calls."""
        del file_path
        if not scope_stack:
            return

        source_id = scope_stack[-1][0]

        func_node = node.child_by_field_name("function")
        if func_node is None:
            return

        parts: list[str] = []
        current = func_node
        while current is not None:
            if current.type == "identifier":
                name = content[current.start_byte : current.end_byte].decode("utf-8", errors="replace")
                parts.insert(0, name)
            elif current.type == "attribute":
                attr = current.child_by_field_name("attribute")
                if attr:
                    name = content[attr.start_byte : attr.end_byte].decode("utf-8", errors="replace")
                    parts.insert(0, name)
                obj = current.child_by_field_name("object")
                current = obj
                continue
            else:
                break
            current = None

        if parts:
            target_name = ".".join(parts)
            edge_candidates.append(
                EdgeCandidate(
                    source_id=source_id,
                    target_name=target_name,
                    edge_type="CALLS",
                    target_file_hint=None,
                )
            )

    def _extract_docstring(self, node: Any, content: bytes) -> str:
        """Extract docstring from function/class body."""
        body = node.child_by_field_name("body")
        if body is None:
            return ""

        first_stmt = body.child_by_field_name("body")
        if first_stmt and first_stmt.type == "expression_statement":
            expr = first_stmt.child_by_field_name("expression")
            if expr and expr.type == "string":
                doc = content[expr.start_byte : expr.end_byte].decode("utf-8", errors="replace")
                for q in ('"""', "'''", '"', "'"):
                    doc = doc.strip(q)
                return doc

        return ""

    def _extract_decorators(self, node: Any, content: bytes) -> list[str]:
        """Extract decorators applied to ``node``.

        Walks back through ``prev_sibling`` collecting any ``decorator`` nodes
        that immediately precede the definition.
        """
        decorators: list[str] = []
        sibling = node.prev_sibling
        while sibling is not None and sibling.type == "decorator":
            text = content[sibling.start_byte : sibling.end_byte].decode("utf-8", errors="replace")
            decorators.append(text.strip())
            sibling = sibling.prev_sibling
        decorators.reverse()
        return decorators

    def _add_python_imports(
        self,
        node: Any,
        content: bytes,
        file_path: str,
        node_id: str,
        edge_candidates: list[EdgeCandidate],
    ) -> None:
        """Add standard library references (no-op placeholder)."""
        del node, content, file_path, node_id, edge_candidates
