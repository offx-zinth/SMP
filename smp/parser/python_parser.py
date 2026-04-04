"""Python-specific tree-sitter parser.

Extracts functions, classes, methods, imports, decorators, and call edges
from Python source using the ``tree-sitter-python`` grammar.
"""

from __future__ import annotations

import tree_sitter as ts
import tree_sitter_python as tsp

from smp.core.models import EdgeType, GraphEdge, GraphNode, NodeType, ParseError
from smp.logging import get_logger
from smp.parser.base import TreeSitterParser, make_node_id, node_text, line_range

log = get_logger(__name__)

_LANGUAGE = ts.Language(tsp.language())

_CALL_QUERY = ts.Query(
    _LANGUAGE,
    """
(call function: (identifier) @callee) @call
(call function: (attribute) @callee) @call
""",
)


class PythonParser(TreeSitterParser):
    """Extract structural elements from Python source."""

    @property
    def supported_languages(self) -> list[str]:
        return ["python"]

    def _language(self, file_path: str) -> ts.Language:
        return _LANGUAGE

    def _extract(
        self,
        root_node: ts.Node,
        source_bytes: bytes,
        file_path: str,
    ) -> tuple[list[GraphNode], list[GraphEdge], list[ParseError]]:
        nodes: list[GraphNode] = []
        edges: list[GraphEdge] = []
        errors: list[ParseError] = []
        seen_ids: set[str] = set()

        file_node = GraphNode(
            id=make_node_id(file_path, NodeType.FILE, file_path, 1),
            type=NodeType.FILE,
            name=file_path,
            file_path=file_path,
            start_line=1,
            end_line=root_node.end_point[0] + 1,
        )
        self._add_node(file_node, nodes, seen_ids)

        self._walk_block(
            root_node, source_bytes, file_path,
            parent_id=file_node.id, class_name=None,
            nodes=nodes, edges=edges, errors=errors, seen_ids=seen_ids,
        )
        log.debug("python_parsed", file=file_path, nodes=len(nodes), edges=len(edges), errors=len(errors))
        return nodes, edges, errors

    def _add_node(self, node: GraphNode, nodes: list[GraphNode], seen: set[str]) -> bool:
        """Add node if not already seen. Returns True if added."""
        if node.id in seen:
            return False
        seen.add(node.id)
        nodes.append(node)
        return True

    def _walk_block(
        self,
        block: ts.Node,
        source: bytes,
        file_path: str,
        parent_id: str,
        class_name: str | None,
        nodes: list[GraphNode],
        edges: list[GraphEdge],
        errors: list[ParseError],
        seen_ids: set[str],
    ) -> None:
        """Walk children of a block extracting definitions.

        Iterates direct children to avoid matching deeply nested
        function/class definitions (tree-sitter queries are recursive).
        """
        self._walk_direct_children(
            block, source, file_path, parent_id, class_name,
            nodes, edges, errors, seen_ids,
        )

    def _walk_direct_children(
        self,
        block: ts.Node,
        source: bytes,
        file_path: str,
        parent_id: str,
        class_name: str | None,
        nodes: list[GraphNode],
        edges: list[GraphEdge],
        errors: list[ParseError],
        seen_ids: set[str],
    ) -> None:
        """Walk direct children of a block, processing definitions."""
        for child in block.children:
            if child.type == "function_definition":
                self._process_function(
                    child, source, file_path, parent_id, class_name,
                    nodes, edges, errors, seen_ids, [],
                )
            elif child.type == "class_definition":
                self._process_class(
                    child, source, file_path, parent_id,
                    nodes, edges, errors, seen_ids, [],
                )
            elif child.type == "decorated_definition":
                decorator_names = self._extract_decorators(child, source)
                for sub in child.children:
                    if sub.type == "function_definition":
                        self._process_function(
                            sub, source, file_path, parent_id, class_name,
                            nodes, edges, errors, seen_ids, decorator_names,
                        )
                        break
                    elif sub.type == "class_definition":
                        self._process_class(
                            sub, source, file_path, parent_id,
                            nodes, edges, errors, seen_ids, decorator_names,
                        )
                        break
            elif child.type in ("import_statement", "import_from_statement"):
                self._process_import(child, source, file_path, parent_id, nodes, edges)

    def _process_function(
        self,
        func: ts.Node,
        source: bytes,
        file_path: str,
        parent_id: str,
        class_name: str | None,
        nodes: list[GraphNode],
        edges: list[GraphEdge],
        errors: list[ParseError],
        seen_ids: set[str],
        decorator_names: list[str],
    ) -> None:
        name_node = func.child_by_field_name("name")
        if not name_node:
            return
        name = node_text(name_node)
        start, end = line_range(func)
        node_type = NodeType.METHOD if class_name else NodeType.FUNCTION
        sig = self._extract_signature(func, source, name)
        docstring = self._extract_docstring(func, source)
        node_id = make_node_id(file_path, node_type, name, start)

        metadata: dict[str, str] = {}
        if class_name:
            metadata["class"] = class_name
        if decorator_names:
            metadata["decorators"] = ",".join(decorator_names)

        node = GraphNode(
            id=node_id, type=node_type, name=name, file_path=file_path,
            start_line=start, end_line=end, signature=sig,
            docstring=docstring, metadata=metadata,
        )
        if not self._add_node(node, nodes, seen_ids):
            return  # already processed

        edges.append(GraphEdge(source_id=parent_id, target_id=node_id, type=EdgeType.CONTAINS))

        body = func.child_by_field_name("body")
        if body:
            self._extract_calls(body, source, file_path, node_id, nodes, edges)

    def _process_class(
        self,
        cls: ts.Node,
        source: bytes,
        file_path: str,
        parent_id: str,
        nodes: list[GraphNode],
        edges: list[GraphEdge],
        errors: list[ParseError],
        seen_ids: set[str],
        decorator_names: list[str],
    ) -> None:
        name_node = cls.child_by_field_name("name")
        if not name_node:
            return
        name = node_text(name_node)
        start, end = line_range(cls)
        docstring = self._extract_docstring(cls, source)
        bases = self._extract_bases(cls, source)
        sig = f"class {name}"
        if bases:
            sig += f"({', '.join(bases)})"
        node_id = make_node_id(file_path, NodeType.CLASS, name, start)

        metadata: dict[str, str] = {}
        if decorator_names:
            metadata["decorators"] = ",".join(decorator_names)

        node = GraphNode(
            id=node_id, type=NodeType.CLASS, name=name, file_path=file_path,
            start_line=start, end_line=end, signature=sig,
            docstring=docstring, metadata=metadata,
        )
        if not self._add_node(node, nodes, seen_ids):
            return

        edges.append(GraphEdge(source_id=parent_id, target_id=node_id, type=EdgeType.CONTAINS))

        for base in bases:
            base_id = make_node_id(file_path, NodeType.CLASS, base, 0)
            edges.append(GraphEdge(source_id=node_id, target_id=base_id, type=EdgeType.INHERITS))

        body = cls.child_by_field_name("body")
        if body:
            self._walk_block(
                body, source, file_path,
                parent_id=node_id, class_name=name,
                nodes=nodes, edges=edges, errors=errors, seen_ids=seen_ids,
            )

    def _process_import(
        self,
        imp: ts.Node,
        source: bytes,
        file_path: str,
        parent_id: str,
        nodes: list[GraphNode],
        edges: list[GraphEdge],
    ) -> None:
        start, end = line_range(imp)
        text = node_text(imp).strip()
        if imp.type == "import_from_statement":
            module_name_node = imp.child_by_field_name("module_name")
            module = node_text(module_name_node) if module_name_node else text
        else:
            module = text.replace("import ", "").split(",")[0].strip()

        node_id = make_node_id(file_path, NodeType.IMPORT, module, start)
        node = GraphNode(
            id=node_id, type=NodeType.IMPORT, name=module,
            file_path=file_path, start_line=start, end_line=end,
            signature=text,
        )
        nodes.append(node)
        edges.append(GraphEdge(source_id=parent_id, target_id=node_id, type=EdgeType.IMPORTS))

    def _extract_calls(
        self,
        body: ts.Node,
        source: bytes,
        file_path: str,
        caller_id: str,
        nodes: list[GraphNode],
        edges: list[GraphEdge],
    ) -> None:
        cursor = ts.QueryCursor(_CALL_QUERY)
        seen_edges: set[tuple[str, str]] = set()
        for _, caps in cursor.matches(body):
            call_nodes = caps.get("call")
            callee_nodes = caps.get("callee")
            if not callee_nodes or not call_nodes:
                continue
            callee_name = node_text(callee_nodes[0])
            call_node = call_nodes[0]
            start, _ = line_range(call_node)
            target_id = make_node_id(file_path, NodeType.FUNCTION, callee_name, 0)
            edge_key = (caller_id, target_id)
            if edge_key in seen_edges:
                continue
            seen_edges.add(edge_key)
            edges.append(GraphEdge(
                source_id=caller_id, target_id=target_id,
                type=EdgeType.CALLS, metadata={"line": str(start)},
            ))

    def _extract_decorators(self, decorated: ts.Node, source: bytes) -> list[str]:
        names: list[str] = []
        for child in decorated.children:
            if child.type == "decorator":
                text = node_text(child).lstrip("@").strip()
                if "(" in text:
                    text = text[: text.index("(")]
                names.append(text)
        return names

    def _extract_bases(self, cls: ts.Node, source: bytes) -> list[str]:
        bases: list[str] = []
        arg_list = cls.child_by_field_name("superclasses")
        if not arg_list:
            for child in cls.children:
                if child.type == "argument_list":
                    arg_list = child
                    break
        if arg_list:
            for child in arg_list.children:
                if child.type == "identifier":
                    bases.append(node_text(child))
        return bases

    def _extract_signature(self, func: ts.Node, source: bytes, name: str) -> str:
        params = func.child_by_field_name("parameters")
        param_text = node_text(params) if params else "()"
        return_type = ""
        for child in func.children:
            if child.type == "type":
                return_type = f" -> {node_text(child)}"
                break
        return f"def {name}{param_text}{return_type}"

    def _extract_docstring(self, func_or_class: ts.Node, source: bytes) -> str:
        body = func_or_class.child_by_field_name("body")
        if not body:
            return ""
        for child in body.children:
            if child.type == "expression_statement":
                for sub in child.children:
                    if sub.type == "string":
                        text = node_text(sub)
                        for quote in ('"""', "'''", '"', "'"):
                            if text.startswith(quote) and text.endswith(quote):
                                text = text[len(quote):-len(quote)]
                                break
                        return text.strip()
            else:
                break
        return ""
