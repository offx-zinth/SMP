"""Abstract tree-sitter parser and language detection utilities."""

from __future__ import annotations

import abc
from pathlib import Path

import tree_sitter as ts

from smp.core.models import Document, GraphEdge, GraphNode, Language, NodeType, ParseError
from smp.engine.interfaces import Parser
from smp.logging import get_logger

log = get_logger(__name__)

_EXT_TO_LANG: dict[str, Language] = {
    ".py": Language.PYTHON,
    ".ts": Language.TYPESCRIPT,
    ".tsx": Language.TYPESCRIPT,
    ".js": Language.TYPESCRIPT,
    ".jsx": Language.TYPESCRIPT,
}

# Extensions that use the TSX grammar variant
_TSX_EXTS = {".tsx", ".jsx"}


def detect_language(file_path: str) -> Language:
    """Guess language from file extension."""
    suffix = Path(file_path).suffix.lower()
    return _EXT_TO_LANG.get(suffix, Language.UNKNOWN)


def is_tsx(file_path: str) -> bool:
    """Return True if the file uses JSX/TSX syntax."""
    return Path(file_path).suffix.lower() in _TSX_EXTS


def make_node_id(file_path: str, type: NodeType, name: str, start_line: int) -> str:
    """Deterministic node ID from structural coordinates."""
    return f"{file_path}::{type.value}::{name}::{start_line}"


def node_text(node: ts.Node) -> str:
    """Safely extract text from a tree-sitter node."""
    if node.text:
        return node.text.decode("utf-8", errors="replace")
    return ""


def line_range(node: ts.Node) -> tuple[int, int]:
    """Return (start_line, end_line) as 1-indexed line numbers."""
    return node.start_point[0] + 1, node.end_point[0] + 1


class TreeSitterParser(Parser, abc.ABC):
    """Abstract base for tree-sitter language parsers.

    Subclasses provide the grammar language object and extraction logic.
    The base class handles parsing, error recovery, and Document assembly.
    """

    @abc.abstractmethod
    def _language(self, file_path: str) -> ts.Language:
        """Return the tree-sitter Language object for *file_path*."""

    @abc.abstractmethod
    def _extract(
        self,
        root_node: ts.Node,
        source_bytes: bytes,
        file_path: str,
    ) -> tuple[list[GraphNode], list[GraphEdge], list[ParseError]]:
        """Extract nodes, edges, and errors from a parsed AST.

        Returns a tuple of (nodes, edges, errors).
        """

    @property
    @abc.abstractmethod
    def supported_languages(self) -> list[str]: ...

    def parse(self, source: str, file_path: str) -> Document:
        lang = detect_language(file_path)
        if lang == Language.UNKNOWN:
            return Document(
                file_path=file_path,
                language=lang,
                errors=[ParseError(message=f"Unsupported language for {file_path}")],
            )

        source_bytes = source.encode("utf-8")

        try:
            ts_lang = self._language(file_path)
            parser = ts.Parser(ts_lang)
            tree = parser.parse(source_bytes)
        except Exception as exc:
            log.error("parse_crash", file_path=file_path, error=str(exc))
            return Document(
                file_path=file_path,
                language=lang,
                errors=[ParseError(message=f"Parser crash: {exc}")],
            )

        errors: list[ParseError] = []
        nodes: list[GraphNode] = []
        edges: list[GraphEdge] = []

        try:
            nodes, edges, errors = self._extract(tree.root_node, source_bytes, file_path)
        except Exception as exc:
            log.error("extract_error", file_path=file_path, error=str(exc))
            errors.append(ParseError(message=f"Extraction error: {exc}"))

        # Detect tree-sitter error nodes
        self._collect_syntax_errors(tree.root_node, source_bytes, errors)

        log.debug(
            "file_parsed",
            file_path=file_path,
            lang=lang.value,
            nodes=len(nodes),
            edges=len(edges),
            errors=len(errors),
        )
        return Document(
            file_path=file_path,
            language=lang,
            nodes=nodes,
            edges=edges,
            errors=errors,
        )

    @staticmethod
    def _collect_syntax_errors(
        node: ts.Node,
        source: bytes,
        errors: list[ParseError],
    ) -> None:
        """Walk the tree and collect ERROR / MISSING nodes."""
        if node.is_error or node.is_missing:
            row, col = node.start_point
            text = node.text.decode("utf-8", errors="replace")[:80] if node.text else ""
            errors.append(
                ParseError(
                    message=f"Syntax {'missing' if node.is_missing else 'error'}: {text}",
                    line=row + 1,
                    column=col,
                )
            )
        for child in node.children:
            TreeSitterParser._collect_syntax_errors(child, source, errors)
