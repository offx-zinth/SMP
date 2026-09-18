from __future__ import annotations

import hashlib
import importlib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Final

try:
    import tree_sitter_languages  # type: ignore[import-untyped]
except ImportError:
    tree_sitter_languages = None  # type: ignore

try:
    from tree_sitter import Language, Parser

    HAS_TREE_SITTER = True
except ImportError:
    HAS_TREE_SITTER = False

LANG_PYTHON: Final[str] = "python"
LANG_UNKNOWN: Final[str] = "unknown"

_FUNCTION_KIND: Final[str] = "Function"
_CLASS_KIND: Final[str] = "Class"
_INTERFACE_KIND: Final[str] = "Interface"

# Identifier-like leaf node types collected (in document order) to build
# dotted call paths such as ``graph.upsert_node``.
_IDENTIFIER_LEAF_TYPES: Final[frozenset[str]] = frozenset(
    {
        "identifier",
        "simple_identifier",
        "property_identifier",
        "field_identifier",
        "name",
        "type_identifier",
        "constant",
    }
)

# Argument subtrees are never part of a call target (``foo(bar)`` -> ``foo``).
_ARGUMENT_SUBTREE_TYPES: Final[frozenset[str]] = frozenset(
    {
        "argument_list",
        "arguments",
        "value_arguments",
        "call_suffix",
    }
)


@dataclass(frozen=True)
class LanguageSpec:
    """Tree-sitter shapes for one language."""

    key: str
    package: str
    loader: str
    extensions: frozenset[str]
    functions: frozenset[str]
    classes: frozenset[str]
    interfaces: frozenset[str]
    calls: frozenset[str]
    #: Field on a call node holding the callee ("" = collect from children).
    call_function_field: str = "function"


_LANGUAGE_SPECS: Final[tuple[LanguageSpec, ...]] = (
    LanguageSpec(
        key="javascript",
        package="tree_sitter_javascript",
        loader="language",
        extensions=frozenset({".js", ".jsx", ".mjs", ".cjs"}),
        functions=frozenset(
            {
                "function_declaration",
                "generator_function_declaration",
                "arrow_function",
                "function_expression",
                "method_definition",
            }
        ),
        classes=frozenset({"class_declaration"}),
        interfaces=frozenset(),
        calls=frozenset({"call_expression"}),
    ),
    LanguageSpec(
        key="typescript",
        package="tree_sitter_typescript",
        loader="language_typescript",
        extensions=frozenset({".ts", ".mts", ".cts"}),
        functions=frozenset(
            {
                "function_declaration",
                "generator_function_declaration",
                "arrow_function",
                "function_expression",
                "method_definition",
            }
        ),
        classes=frozenset({"class_declaration"}),
        interfaces=frozenset({"interface_declaration"}),
        calls=frozenset({"call_expression"}),
    ),
    LanguageSpec(
        key="tsx",
        package="tree_sitter_typescript",
        loader="language_tsx",
        extensions=frozenset({".tsx"}),
        functions=frozenset(
            {
                "function_declaration",
                "generator_function_declaration",
                "arrow_function",
                "function_expression",
                "method_definition",
            }
        ),
        classes=frozenset({"class_declaration"}),
        interfaces=frozenset({"interface_declaration"}),
        calls=frozenset({"call_expression"}),
    ),
    LanguageSpec(
        key="java",
        package="tree_sitter_java",
        loader="language",
        extensions=frozenset({".java"}),
        functions=frozenset({"method_declaration", "constructor_declaration"}),
        classes=frozenset({"class_declaration", "interface_declaration", "enum_declaration"}),
        interfaces=frozenset(),
        calls=frozenset({"method_invocation", "object_creation_expression"}),
        call_function_field="",
    ),
    LanguageSpec(
        key="c",
        package="tree_sitter_c",
        loader="language",
        extensions=frozenset({".c", ".h"}),
        functions=frozenset({"function_definition"}),
        classes=frozenset(),
        interfaces=frozenset(),
        calls=frozenset({"call_expression"}),
    ),
    LanguageSpec(
        key="cpp",
        package="tree_sitter_cpp",
        loader="language",
        extensions=frozenset({".cpp", ".cc", ".cxx", ".hpp", ".hh"}),
        functions=frozenset({"function_definition"}),
        classes=frozenset({"class_specifier", "struct_specifier"}),
        interfaces=frozenset(),
        calls=frozenset({"call_expression"}),
    ),
    LanguageSpec(
        key="csharp",
        package="tree_sitter_c_sharp",
        loader="language",
        extensions=frozenset({".cs"}),
        functions=frozenset({"method_declaration", "constructor_declaration"}),
        classes=frozenset({"class_declaration", "interface_declaration", "struct_declaration"}),
        interfaces=frozenset(),
        calls=frozenset({"invocation_expression"}),
    ),
    LanguageSpec(
        key="go",
        package="tree_sitter_go",
        loader="language",
        extensions=frozenset({".go"}),
        functions=frozenset({"function_declaration", "method_declaration"}),
        classes=frozenset(),
        interfaces=frozenset(),
        calls=frozenset({"call_expression"}),
    ),
    LanguageSpec(
        key="rust",
        package="tree_sitter_rust",
        loader="language",
        extensions=frozenset({".rs"}),
        functions=frozenset({"function_item"}),
        classes=frozenset({"struct_item", "enum_item", "union_item"}),
        interfaces=frozenset(),
        calls=frozenset({"call_expression"}),
    ),
    LanguageSpec(
        key="php",
        package="tree_sitter_php",
        loader="language_php",
        extensions=frozenset({".php"}),
        functions=frozenset({"function_definition", "method_declaration"}),
        classes=frozenset({"class_declaration", "interface_declaration", "trait_declaration"}),
        interfaces=frozenset(),
        calls=frozenset({"function_call_expression", "method_call_expression"}),
    ),
    LanguageSpec(
        key="ruby",
        package="tree_sitter_ruby",
        loader="language",
        extensions=frozenset({".rb"}),
        functions=frozenset({"method", "singleton_method"}),
        classes=frozenset({"class", "module"}),
        interfaces=frozenset(),
        calls=frozenset({"call"}),
        call_function_field="",
    ),
    LanguageSpec(
        key="swift",
        package="tree_sitter_swift",
        loader="language",
        extensions=frozenset({".swift"}),
        functions=frozenset({"function_declaration"}),
        classes=frozenset({"class_declaration", "struct_declaration", "enum_declaration"}),
        interfaces=frozenset({"protocol_declaration"}),
        calls=frozenset({"call_expression"}),
        call_function_field="",
    ),
    LanguageSpec(
        key="kotlin",
        package="tree_sitter_kotlin",
        loader="language",
        extensions=frozenset({".kt", ".kts"}),
        functions=frozenset({"function_declaration"}),
        classes=frozenset({"class_declaration"}),
        interfaces=frozenset(),
        calls=frozenset({"call_expression"}),
        call_function_field="",
    ),
    LanguageSpec(
        key="matlab",
        package="tree_sitter_matlab",
        loader="language",
        extensions=frozenset({".m"}),
        functions=frozenset({"function_definition"}),
        classes=frozenset({"class_definition"}),
        interfaces=frozenset(),
        calls=frozenset({"function_call"}),
        call_function_field="name",
    ),
)

_EXTENSION_TO_LANGUAGE: Final[dict[str, str]] = {ext: spec.key for spec in _LANGUAGE_SPECS for ext in spec.extensions}
_EXTENSION_TO_LANGUAGE.update({".py": "python", ".pyw": "python", ".pyi": "python"})

_SPEC_BY_KEY: Final[dict[str, LanguageSpec]] = {spec.key: spec for spec in _LANGUAGE_SPECS}

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

    Python uses a dedicated walker (docstrings, decorators, imports);
    every other supported language goes through a table-driven generic
    walker (:data:`_LANGUAGE_SPECS`).  Extensions with no grammar yield
    an empty :class:`ParsedFile` so the graph store can still record
    file-level bookkeeping without raising.
    """

    def __init__(self) -> None:
        if not HAS_TREE_SITTER:
            raise ImportError("tree-sitter not installed. Run: pip install tree-sitter-python")
        self._parsers: dict[str, Parser] = {}
        self._languages: dict[str, Language] = {}
        self._python_ready = False
        self._unavailable: set[str] = set()

    def _ensure_python(self) -> None:
        """Lazily load the Python tree-sitter grammar.

        The legacy ``tree_sitter_languages`` bundle is tried first for
        backwards compatibility; if it fails (version mismatch) we fall
        back to the dedicated ``tree_sitter_python`` package.
        """
        if self._python_ready:
            return

        loaded = False
        if tree_sitter_languages is not None:
            try:
                ts_lang = tree_sitter_languages.get_language("python")
                parser = Parser()
                if hasattr(parser, "language"):
                    parser.language = ts_lang
                else:
                    parser.set_language(ts_lang)  # type: ignore[attr-defined]
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

    def _ensure_language(self, key: str) -> bool:
        """Lazily load the tree-sitter grammar for *key*.

        Returns True when a parser is ready, False when the grammar
        package is missing (callers then emit an empty parse).
        """
        if key == LANG_PYTHON:
            self._ensure_python()
            return LANG_PYTHON in self._parsers
        if key in self._parsers or key in self._unavailable:
            return key in self._parsers
        spec = _SPEC_BY_KEY.get(key)
        if spec is None:
            return False
        try:
            import tree_sitter as _ts

            package = importlib.import_module(spec.package)
            ts_lang = _ts.Language(getattr(package, spec.loader)())
            parser = _ts.Parser(ts_lang)
            self._languages[key] = ts_lang
            self._parsers[key] = parser
            return True
        except (ImportError, AttributeError, ValueError, OSError):
            self._unavailable.add(key)
            return False

    @staticmethod
    def _language_for_path(file_path: str | Path) -> str:
        """Map a file extension to a language key (``unknown`` if none)."""
        return _EXTENSION_TO_LANGUAGE.get(Path(file_path).suffix.lower(), LANG_UNKNOWN)

    @classmethod
    def _is_python(cls, file_path: str | Path) -> bool:
        """Return True when the file should use the native Python walker."""
        return cls._language_for_path(file_path) == LANG_PYTHON

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

        Python files use the dedicated walker; every other supported
        language uses the generic table-driven walker.  Files with
        unknown extensions yield an empty :class:`ParsedFile`.
        """
        path = Path(file_path)
        if not path.exists():
            raise FileNotFoundError(f"File not found: {path}")

        content = path.read_bytes()
        language = self._language_for_path(path)
        if language == LANG_PYTHON:
            return self._parse_python(str(path), content)
        if language != LANG_UNKNOWN:
            return self._parse_generic(str(path), content, language)
        return self._empty_parsed_file(str(path), content)

    def parse_content(self, file_path: str, content: bytes) -> ParsedFile:
        """Parse source content (bytes) and extract nodes."""
        language = self._language_for_path(file_path)
        if language == LANG_PYTHON:
            return self._parse_python(file_path, content)
        if language != LANG_UNKNOWN:
            return self._parse_generic(file_path, content, language)
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

    # ------------------------------------------------------------------
    # Generic table-driven walker (all non-Python languages)
    # ------------------------------------------------------------------

    def _parse_generic(self, file_path: str, content: bytes, language: str) -> ParsedFile:
        """Parse *content* with the grammar for *language*."""
        text = content.decode("utf-8", errors="replace")
        line_count = len(text.splitlines())
        file_hash = self._compute_hash(content)

        if not self._ensure_language(language):
            return ParsedFile(
                file_path=file_path,
                language=language,
                line_count=line_count,
                content_hash=file_hash,
            )

        parser = self._parsers[language]
        tree = parser.parse(content)

        nodes: list[ParsedNode] = []
        edge_candidates: list[EdgeCandidate] = []
        scope_stack: list[tuple[str, int]] = []

        self._walk_generic(
            tree.root_node,
            None,
            content,
            file_path,
            nodes,
            edge_candidates,
            scope_stack,
            language,
        )

        return ParsedFile(
            file_path=file_path,
            language=language,
            line_count=line_count,
            content_hash=file_hash,
            nodes=nodes,
            edge_candidates=edge_candidates,
        )

    def _walk_generic(
        self,
        node: Any,
        parent: Any | None,
        content: bytes,
        file_path: str,
        nodes: list[ParsedNode],
        edge_candidates: list[EdgeCandidate],
        scope_stack: list[tuple[str, int]],
        lang: str,
    ) -> None:
        """Walk the tree extracting definitions and calls per the language table."""
        spec = _SPEC_BY_KEY.get(lang)
        node_type = node.type

        if spec is not None:
            if node_type in spec.functions:
                self._handle_generic_definition(
                    node, parent, content, file_path, nodes, edge_candidates, scope_stack, _FUNCTION_KIND
                )
            elif node_type in spec.classes:
                self._handle_generic_definition(
                    node, parent, content, file_path, nodes, edge_candidates, scope_stack, _CLASS_KIND
                )
            elif node_type in spec.interfaces:
                self._handle_generic_definition(
                    node, parent, content, file_path, nodes, edge_candidates, scope_stack, _INTERFACE_KIND
                )
            elif node_type in spec.calls:
                self._handle_generic_call(node, content, spec, edge_candidates, scope_stack)

        for child in node.children:
            self._walk_generic(child, node, content, file_path, nodes, edge_candidates, scope_stack, lang)

        if scope_stack and scope_stack[-1][1] == node.end_point[0]:
            scope_stack.pop()

    def _handle_generic_definition(
        self,
        node: Any,
        parent: Any | None,
        content: bytes,
        file_path: str,
        nodes: list[ParsedNode],
        edge_candidates: list[EdgeCandidate],
        scope_stack: list[tuple[str, int]],
        kind: str,
    ) -> None:
        """Extract a function/class/interface definition node."""
        del edge_candidates
        name = self._definition_name(node, parent, content)
        if not name:
            return

        start_line = node.start_point[0] + 1
        end_line = node.end_point[0] + 1
        signature = self._definition_signature(node, content, name, kind)

        node_id = self._make_node_id(file_path, kind, name, start_line)
        parsed_node = ParsedNode(
            node_id=node_id,
            type=kind,
            name=name,
            signature=signature,
            docstring="",
            start_line=start_line,
            end_line=end_line,
        )
        if scope_stack:
            parsed_node.parent_id = scope_stack[-1][0]
        nodes.append(parsed_node)
        scope_stack.append((node_id, end_line))

    def _definition_name(self, node: Any, parent: Any | None, content: bytes) -> str:
        """Best-effort definition name: ``name`` field, declarator descent, or parent declarator."""
        name_node = node.child_by_field_name("name")
        if name_node is not None:
            return content[name_node.start_byte : name_node.end_byte].decode("utf-8", errors="replace")
        # C/C++: name hides inside the declarator chain (function_declarator -> identifier).
        declarator = node.child_by_field_name("declarator")
        found = self._first_identifier(declarator) if declarator is not None else None
        if found is not None:
            return content[found.start_byte : found.end_byte].decode("utf-8", errors="replace")
        # Anonymous functions assigned to a variable (JS/TS arrow functions).
        if parent is not None and parent.type in ("variable_declarator", "variable_declaration", "field_declaration"):
            parent_name = parent.child_by_field_name("name")
            if parent_name is not None:
                return content[parent_name.start_byte : parent_name.end_byte].decode("utf-8", errors="replace")
        return ""

    @staticmethod
    def _first_identifier(node: Any | None) -> Any | None:
        """First identifier-like descendant in document order (or None)."""
        if node is None:
            return None
        if node.type in _IDENTIFIER_LEAF_TYPES:
            return node
        for child in node.children:
            found = CodeParser._first_identifier(child)
            if found is not None:
                return found
        return None

    @staticmethod
    def _definition_signature(node: Any, content: bytes, name: str, kind: str) -> str:
        """Compact signature from the first parameter-like child, if any."""
        params = ""
        stack = [node]
        while stack:
            current = stack.pop(0)
            if "parameter" in current.type and current.type not in ("parameter_list",):
                params = content[current.start_byte : current.end_byte].decode("utf-8", errors="replace")
                break
            stack.extend(current.children)
        if not params:
            for child in node.children:
                if child.type in ("parameter_list", "parameters", "formal_parameters", "function_value_parameters"):
                    params = content[child.start_byte : child.end_byte].decode("utf-8", errors="replace")
                    break
        keyword = "def" if kind == _FUNCTION_KIND else "class"
        return f"{keyword} {name}{params}" if params else f"{keyword} {name}()"

    def _handle_generic_call(
        self,
        node: Any,
        content: bytes,
        spec: LanguageSpec,
        edge_candidates: list[EdgeCandidate],
        scope_stack: list[tuple[str, int]],
    ) -> None:
        """Extract a call expression as an unresolved CALLS edge."""
        if not scope_stack:
            return
        source_id = scope_stack[-1][0]
        target = self._call_target_name(node, content, spec)
        if not target:
            return
        edge_candidates.append(
            EdgeCandidate(
                source_id=source_id,
                target_name=target,
                edge_type="CALLS",
                target_file_hint=None,
            )
        )

    def _call_target_name(self, node: Any, content: bytes, spec: LanguageSpec) -> str:
        """Dotted callee path (``receiver.method``) for a call node."""
        field = spec.call_function_field
        if field:
            func_node = node.child_by_field_name(field)
            if func_node is not None:
                parts = self._collect_callee_parts(func_node, content)
            else:
                # e.g. Swift/Kotlin calls expose no function field.
                parts = self._collect_callee_parts(node, content)
        else:
            # Java method_invocation: combine object + name fields.
            obj = node.child_by_field_name("object")
            name_node = node.child_by_field_name("name")
            if obj is not None or name_node is not None:
                parts = []
                if obj is not None:
                    parts.extend(self._collect_callee_parts(obj, content))
                if name_node is not None:
                    parts.append(content[name_node.start_byte : name_node.end_byte].decode("utf-8", errors="replace"))
            else:
                # Ruby: collect identifier leaves, skipping argument lists.
                parts = self._collect_callee_parts(node, content)
        return ".".join(p for p in parts if p)

    def _collect_callee_parts(self, node: Any, content: bytes) -> list[str]:
        """Identifier-like leaf texts under *node* in document order."""
        parts: list[str] = []
        stack: list[Any] = list(node.children) if node.children else [node]
        while stack:
            current = stack.pop(0)
            if current.type in _ARGUMENT_SUBTREE_TYPES:
                continue
            if not current.children:
                if current.type in _IDENTIFIER_LEAF_TYPES:
                    text = content[current.start_byte : current.end_byte].decode("utf-8", errors="replace").strip()
                    if text and text not in ("this", "self", "super"):
                        parts.append(text)
                continue
            stack[0:0] = list(current.children)
        if not parts and node.type in _IDENTIFIER_LEAF_TYPES:
            text = content[node.start_byte : node.end_byte].decode("utf-8", errors="replace").strip()
            if text and text not in ("this", "self", "super"):
                parts.append(text)
        return parts

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
        elif node_type in ("class", "class_definition"):
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
