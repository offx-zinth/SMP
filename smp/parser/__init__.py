"""Parser layer — AST extraction via tree-sitter."""

from smp.parser.base import TreeSitterParser, detect_language, make_node_id
from smp.parser.registry import ParserRegistry

__all__ = [
    "TreeSitterParser",
    "detect_language",
    "make_node_id",
    "ParserRegistry",
]
