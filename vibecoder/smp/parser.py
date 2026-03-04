from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, TypedDict

from tree_sitter import Language, Node, Parser


class ParsedNode(TypedDict, total=False):
    id: str
    type: str
    name: str
    file_path: str
    start_line: int
    end_line: int
    signature: str
    module: str
    calls: list[str]
    text: str


@dataclass(frozen=True)
class LanguageConfig:
    language: Language
    function_types: tuple[str, ...]
    class_types: tuple[str, ...]
    import_types: tuple[str, ...]
    call_types: tuple[str, ...]


class ASTParser:
    """Parse Python and TypeScript/JavaScript files using tree-sitter AST only."""

    def __init__(self) -> None:
        self._python = self._build_python_config()
        self._javascript = self._build_javascript_config()
        self._parser = Parser()

    def _build_python_config(self) -> LanguageConfig:
        from tree_sitter_python import language as py_language

        return LanguageConfig(
            language=Language(py_language()),
            function_types=("function_definition",),
            class_types=("class_definition",),
            import_types=("import_statement", "import_from_statement"),
            call_types=("call",),
        )

    def _build_javascript_config(self) -> LanguageConfig:
        from tree_sitter_javascript import language as js_language

        return LanguageConfig(
            language=Language(js_language()),
            function_types=(
                "function_declaration",
                "method_definition",
                "function",
                "arrow_function",
            ),
            class_types=("class_declaration",),
            import_types=("import_statement",),
            call_types=("call_expression",),
        )

    def parse_file(self, file_path: str | Path) -> list[ParsedNode]:
        path = Path(file_path)
        source = path.read_bytes()
        config = self._select_config(path)
        self._parser.language = config.language
        tree = self._parser.parse(source)

        nodes: list[ParsedNode] = []
        self._walk_tree(tree.root_node, source, str(path), config, nodes)
        return nodes

    def _select_config(self, path: Path) -> LanguageConfig:
        suffix = path.suffix.lower()
        if suffix == ".py":
            return self._python
        if suffix in {".ts", ".tsx", ".js", ".jsx"}:
            return self._javascript
        raise ValueError(f"Unsupported file extension for AST parse: {suffix}")

    def _walk_tree(
        self,
        node: Node,
        source: bytes,
        file_path: str,
        config: LanguageConfig,
        output: list[ParsedNode],
    ) -> None:
        if node.type in config.class_types:
            parsed = self._class_node(node, source, file_path)
            if parsed:
                output.append(parsed)
        elif node.type in config.function_types:
            parsed = self._function_node(node, source, file_path, config)
            if parsed:
                output.append(parsed)
        elif node.type in config.import_types:
            parsed = self._import_node(node, source, file_path)
            if parsed:
                output.extend(parsed)

        for child in node.children:
            self._walk_tree(child, source, file_path, config, output)

    def _class_node(self, node: Node, source: bytes, file_path: str) -> ParsedNode | None:
        name_node = node.child_by_field_name("name")
        if name_node is None:
            return None
        name = self._text(name_node, source)
        return {
            "id": f"{file_path}:class:{name}:{node.start_point[0]+1}",
            "type": "class",
            "name": name,
            "file_path": file_path,
            "start_line": node.start_point[0] + 1,
            "end_line": node.end_point[0] + 1,
            "signature": self._signature(node, source),
            "text": self._text(node, source),
        }

    def _function_node(
        self,
        node: Node,
        source: bytes,
        file_path: str,
        config: LanguageConfig,
    ) -> ParsedNode | None:
        name_node = node.child_by_field_name("name")
        if name_node is None and node.type in {"arrow_function", "function"}:
            return None
        if name_node is None:
            return None

        name = self._text(name_node, source)
        calls = self._collect_calls(node, source, config)
        return {
            "id": f"{file_path}:function:{name}:{node.start_point[0]+1}",
            "type": "function",
            "name": name,
            "file_path": file_path,
            "start_line": node.start_point[0] + 1,
            "end_line": node.end_point[0] + 1,
            "signature": self._signature(node, source),
            "calls": calls,
            "text": self._text(node, source),
        }

    def _import_node(self, node: Node, source: bytes, file_path: str) -> list[ParsedNode] | None:
        imports: list[ParsedNode] = []
        text = self._text(node, source)
        for token in text.replace(",", " ").replace(";", " ").split():
            if token in {"import", "from", "as"}:
                continue
            if token.startswith("'") or token.startswith('"'):
                cleaned = token.strip("'\"")
                if cleaned:
                    imports.append(
                        {
                            "id": f"{file_path}:import:{cleaned}:{node.start_point[0]+1}",
                            "type": "import",
                            "name": cleaned,
                            "module": cleaned,
                            "file_path": file_path,
                            "start_line": node.start_point[0] + 1,
                            "end_line": node.end_point[0] + 1,
                            "text": text,
                        }
                    )
        if imports:
            return imports
        return None

    def _collect_calls(self, root: Node, source: bytes, config: LanguageConfig) -> list[str]:
        calls: set[str] = set()
        stack = [root]
        while stack:
            current = stack.pop()
            if current.type in config.call_types:
                target = current.child_by_field_name("function")
                if target is None and current.children:
                    target = current.children[0]
                if target is not None:
                    call_name = self._text(target, source)
                    if call_name:
                        calls.add(call_name)
            stack.extend(current.children)
        return sorted(calls)

    @staticmethod
    def _text(node: Node, source: bytes) -> str:
        return source[node.start_byte : node.end_byte].decode("utf-8", errors="ignore")

    @staticmethod
    def _signature(node: Node, source: bytes) -> str:
        text = source[node.start_byte : node.end_byte].decode("utf-8", errors="ignore")
        first_line = text.splitlines()[0] if text else ""
        return first_line.strip()


def parse_file(file_path: str | Path) -> list[ParsedNode]:
    return ASTParser().parse_file(file_path)
