from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any, Final

if TYPE_CHECKING:
    pass

try:
    import tree_sitter_languages
    from tree_sitter import Language, Parser

    HAS_TREE_SITTER = True
except ImportError:
    HAS_TREE_SITTER = False

# Supported languages
LANG_PYTHON: Final[str] = "python"

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
    type: str  # NodeType.value
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
    edge_type: str  # EdgeType.value
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


class CodeParser:
    """Wrapper around tree-sitter for parsing source code."""

    def __init__(self) -> None:
        if not HAS_TREE_SITTER:
            raise ImportError("tree-sitter not installed. Run: pip install tree-sitter-python")
        self._parsers: dict[str, Parser] = {}
        self._languages: dict[str, Language] = {}
        self._load_language(LANG_PYTHON)

    def _load_language(self, lang: str) -> None:
        """Load a tree-sitter language."""
        if lang in self._languages:
            return

        lang_key = lang if lang != LANG_PYTHON else "python"
        ts_lang = tree_sitter_languages.get_language(lang_key)
        self._languages[lang] = ts_lang

        parser = Parser()
        parser.language = ts_lang
        self._parsers[lang] = parser

    def _detect_language(self, file_path: str | Path) -> str:
        """Detect language from file extension."""
        path = Path(file_path)
        ext = path.suffix.lower()
        lang_map = {
            ".py": LANG_PYTHON,
            ".pyw": LANG_PYTHON,
            ".pyi": LANG_PYTHON,
        }
        return lang_map.get(ext, LANG_PYTHON)

    def _compute_hash(self, content: bytes) -> str:
        """Compute hash of file content."""
        return hashlib.blake2b(content, digest_size=8).hexdigest()

    def _make_node_id(self, file_path: str, node_type: str, name: str, start_line: int) -> str:
        """Create a deterministic node ID."""
        path_hash = hashlib.blake2b(Path(file_path).resolve().as_posix().encode(), digest_size=4).hexdigest()
        return f"{path_hash}::{node_type}::{name}::{start_line}"

    def parse_file(self, file_path: str | Path) -> ParsedFile:
        """Parse a source file and extract nodes."""
        path = Path(file_path)
        if not path.exists():
            raise FileNotFoundError(f"File not found: {path}")

        content = path.read_bytes()
        return self.parse_content(str(path), content)

    def parse_content(self, file_path: str, content: bytes) -> ParsedFile:
        """Parse source content and extract nodes."""
        lang = self._detect_language(file_path)
        self._load_language(lang)

        parser = self._parsers[lang]
        tree = parser.parse(content)
        text = content.decode("utf-8", errors="replace")
        lines = text.splitlines()
        line_count = len(lines)

        file_hash = self._compute_hash(content)

        # Extract nodes
        nodes: list[ParsedNode] = []
        edge_candidates: list[EdgeCandidate] = []
        scope_stack: list[tuple[str, int]] = []  # (node_id, end_line)

        self._walk_tree(
            tree.root_node,
            content,
            file_path,
            nodes,
            edge_candidates,
            scope_stack,
            lang,
        )

        return ParsedFile(
            file_path=file_path,
            language=lang,
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

        # Handle function/method definitions
        if node_type in ("function_definition", "async_function_definition", "method"):
            self._handle_function(node, content, file_path, nodes, edge_candidates, scope_stack, lang)
        # Handle class definitions
        elif node_type == "class":
            self._handle_class(node, content, file_path, nodes, scope_stack, lang)
        # Handle imports
        elif node_type in ("import_statement", "import_from_statement"):
            self._handle_import(node, content, file_path, edge_candidates, scope_stack)
        # Handle calls
        elif node_type == "call":
            self._handle_call(node, content, file_path, edge_candidates, scope_stack)
        # Handle decorators
        elif node_type == "decorator":
            pass  # Handled by parent

        # Recurse into children
        for child in node.children:
            self._walk_tree(child, content, file_path, nodes, edge_candidates, scope_stack, lang)

        # Pop scope if needed
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
        # Get function name
        name_node = node.child_by_field_name("name")
        if name_node is None:
            return
        name = content[name_node.start_byte : name_node.end_byte].decode("utf-8", errors="replace")

        start_line = node.start_point[0] + 1
        end_line = node.end_point[0] + 1

        # Get signature
        param_node = node.child_by_field_name("parameters")
        signature = ""
        if param_node:
            signature = content[param_node.start_byte : param_node.end_byte].decode("utf-8", errors="replace")
            signature = f"def {name}({signature})"
        else:
            signature = f"def {name}()"

        # Get docstring
        docstring = self._extract_docstring(node, content)

        # Get decorators
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

        # Set parent from scope stack
        if scope_stack:
            parsed_node.parent_id = scope_stack[-1][0]

        nodes.append(parsed_node)
        scope_stack.append((node_id, end_line))

        # Add IMPORTS edge for known library functions
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
        source_id = ""
        if scope_stack:
            source_id = scope_stack[-1][0]
        else:
            # Module-level import
            path_hash = hashlib.blake2b(Path(file_path).resolve().as_posix().encode(), digest_size=4).hexdigest()
            source_id = f"{path_hash}::Module::module::1"

        # Get imported names
        for child in node.children:
            if child.type == "identifier":
                name = content[child.start_byte : child.end_byte].decode("utf-8", errors="replace")
                if name and name[0].islower():
                    # Likely a module name, not function
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
        if not scope_stack:
            return

        source_id = scope_stack[-1][0]

        # Get function being called
        func_node = node.child_by_field_name("function")
        if func_node is None:
            return

        # Follow attribute accesses (e.g., os.path.join)
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
                # Move to parent (object)
                obj = current.child_by_field_name("object")
                current = obj
                continue
            else:
                break
            current = None  # Exit loop

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
        # Look for string node as first child of body
        body = node.child_by_field_name("body")
        if body is None:
            return ""

        first_stmt = body.child_by_field_name("body")
        if first_stmt and first_stmt.type == "expression_statement":
            expr = first_stmt.child_by_field_name("expression")
            if expr and expr.type == "string":
                doc = content[expr.start_byte : expr.end_byte].decode("utf-8", errors="replace")
                # Remove quotes
                for q in ('"""', "'''", '"', "'"):
                    doc = doc.strip(q)
                return doc

        return ""

    def _extract_decorators(self, node: Any, content: bytes) -> list[str]:
        """Extract decorators."""
        decorators: list[str] = []
        for child in node.prev_sibling:
            if child.type == "decorator":
                text = content[child.start_byte : child.end_byte].decode("utf-8", errors="replace")
                decorators.append(text.strip())
        return decorators

    def _add_python_imports(
        self,
        node: Any,
        content: bytes,
        file_path: str,
        node_id: str,
        edge_candidates: list[EdgeCandidate],
    ) -> None:
        """Add standard library references."""
        # This is a simplified version - full impl would use AST analysis
        pass
