"""JavaScript tree-sitter parser.

Extracts functions, classes, methods, and imports from JavaScript source.
"""

from __future__ import annotations

import tree_sitter as ts
import tree_sitter_javascript as tsjs  # type: ignore[import-not-found]

from smp.core.models import EdgeType, GraphEdge, GraphNode, NodeType, ParseError, StructuralProperties
from smp.logging import get_logger
from smp.parser.base import TreeSitterParser, line_range, make_node_id, node_text

log = get_logger(__name__)

_LANGUAGE = ts.Language(tsjs.language())

_QUERY_STRINGS = {
    "top": """
    (function_declaration name: (identifier) @name) @func
    (class_declaration name: (identifier) @name) @class
    (method_definition name: (property_identifier) @name) @method
    (import_statement) @import
    (export_statement) @export
    """,
    "arrow": """
    (lexical_declaration (variable_declarator name: (identifier) @name value: (arrow_function) @arrow)) @var
    """,
}


class JavaScriptParser(TreeSitterParser):
    """Extract structural elements from JavaScript source."""

    @property
    def supported_languages(self) -> list[str]:
        return ["javascript"]

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
            file_path=file_path,
            structural=StructuralProperties(
                name=file_path,
                file=file_path,
                start_line=1,
                end_line=root_node.end_point[0] + 1,
                lines=root_node.end_point[0] + 1,
            ),
        )
        self._add_node(file_node, nodes, seen_ids)

        query = ts.Query(_LANGUAGE, _QUERY_STRINGS["top"])
        cursor = ts.QueryCursor(query)
        for _, caps in cursor.matches(root_node):
            func_nodes = caps.get("func")
            class_nodes = caps.get("class")
            method_nodes = caps.get("method")
            import_nodes = caps.get("import")
            export_nodes = caps.get("export")

            if func_nodes:
                self._process_function(func_nodes[0], source_bytes, file_path, file_node.id, nodes, edges, seen_ids)
            elif class_nodes:
                self._process_class(class_nodes[0], source_bytes, file_path, file_node.id, nodes, edges, seen_ids)
            elif method_nodes:
                self._process_method(method_nodes[0], source_bytes, file_path, file_node.id, nodes, edges, seen_ids)
            elif import_nodes:
                self._process_import(import_nodes[0], source_bytes, file_path, file_node.id, nodes, edges)
            elif export_nodes:
                for child in export_nodes[0].children:
                    self._walk_export(child, source_bytes, file_path, file_node.id, nodes, edges, seen_ids)

        arrow_query = ts.Query(_LANGUAGE, _QUERY_STRINGS["arrow"])
        arrow_cursor = ts.QueryCursor(arrow_query)
        for _, caps in arrow_cursor.matches(root_node):
            name_nodes = caps.get("name")
            arrow_nodes = caps.get("arrow")
            if name_nodes and arrow_nodes:
                self._process_arrow(
                    name_nodes[0], arrow_nodes[0], source_bytes, file_path, file_node.id, nodes, edges, seen_ids
                )

        log.debug("javascript_parsed", file=file_path, nodes=len(nodes), edges=len(edges), errors=len(errors))
        return nodes, edges, errors

    def _add_node(self, node: GraphNode, nodes: list[GraphNode], seen: set[str]) -> bool:
        if node.id in seen:
            return False
        seen.add(node.id)
        nodes.append(node)
        return True

    def _process_function(
        self,
        func: ts.Node,
        source: bytes,
        file_path: str,
        parent_id: str,
        nodes: list[GraphNode],
        edges: list[GraphEdge],
        seen_ids: set[str],
    ) -> None:
        name_node = func.child_by_field_name("name")
        if not name_node:
            return
        name = node_text(name_node)
        start, end = line_range(func)

        params_node = func.child_by_field_name("parameters")
        params_text = node_text(params_node) if params_node else "()"
        sig = f"function {name}{params_text}"

        node_id = make_node_id(file_path, NodeType.FUNCTION, name, start)
        structural = StructuralProperties(
            name=name,
            file=file_path,
            signature=sig,
            start_line=start,
            end_line=end,
            lines=end - start + 1,
        )
        node = GraphNode(id=node_id, type=NodeType.FUNCTION, file_path=file_path, structural=structural)
        if not self._add_node(node, nodes, seen_ids):
            return
        edges.append(GraphEdge(source_id=parent_id, target_id=node_id, type=EdgeType.DEFINES))

    def _process_class(
        self,
        cls: ts.Node,
        source: bytes,
        file_path: str,
        parent_id: str,
        nodes: list[GraphNode],
        edges: list[GraphEdge],
        seen_ids: set[str],
    ) -> None:
        name_node = cls.child_by_field_name("name")
        if not name_node:
            return
        name = node_text(name_node)
        start, end = line_range(cls)
        node_id = make_node_id(file_path, NodeType.CLASS, name, start)

        sig = f"class {name}"

        structural = StructuralProperties(
            name=name,
            file=file_path,
            signature=sig,
            start_line=start,
            end_line=end,
            lines=end - start + 1,
        )
        node = GraphNode(id=node_id, type=NodeType.CLASS, file_path=file_path, structural=structural)
        if not self._add_node(node, nodes, seen_ids):
            return
        edges.append(GraphEdge(source_id=parent_id, target_id=node_id, type=EdgeType.DEFINES))

        body = cls.child_by_field_name("body")
        if body:
            method_query = ts.Query(_LANGUAGE, "(method_definition name: (property_identifier) @name) @method")
            method_cursor = ts.QueryCursor(method_query)
            for _, mcaps in method_cursor.matches(body):
                method_nodes = mcaps.get("method")
                if method_nodes:
                    self._process_method(method_nodes[0], source, file_path, node_id, nodes, edges, seen_ids)

    def _process_method(
        self,
        method: ts.Node,
        source: bytes,
        file_path: str,
        parent_id: str,
        nodes: list[GraphNode],
        edges: list[GraphEdge],
        seen_ids: set[str],
    ) -> None:
        name_node = method.child_by_field_name("name")
        if not name_node:
            return
        name = node_text(name_node)
        start, end = line_range(method)

        params_node = method.child_by_field_name("parameters")
        params_text = node_text(params_node) if params_node else "()"
        sig = f"{name}{params_text}"

        node_id = make_node_id(file_path, NodeType.FUNCTION, name, start)
        structural = StructuralProperties(
            name=name,
            file=file_path,
            signature=sig,
            start_line=start,
            end_line=end,
            lines=end - start + 1,
        )
        node = GraphNode(id=node_id, type=NodeType.FUNCTION, file_path=file_path, structural=structural)
        if not self._add_node(node, nodes, seen_ids):
            return
        edges.append(GraphEdge(source_id=parent_id, target_id=node_id, type=EdgeType.DEFINES))

    def _process_arrow(
        self,
        name_node: ts.Node,
        arrow: ts.Node,
        source: bytes,
        file_path: str,
        parent_id: str,
        nodes: list[GraphNode],
        edges: list[GraphEdge],
        seen_ids: set[str],
    ) -> None:
        name = node_text(name_node)
        start, end = line_range(arrow)

        params_node = arrow.child_by_field_name("parameters")
        params_text = node_text(params_node) if params_node else "()"
        sig = f"const {name} = ({params_text}) => ..."

        node_id = make_node_id(file_path, NodeType.FUNCTION, name, start)
        structural = StructuralProperties(
            name=name,
            file=file_path,
            signature=sig,
            start_line=start,
            end_line=end,
            lines=end - start + 1,
        )
        node = GraphNode(id=node_id, type=NodeType.FUNCTION, file_path=file_path, structural=structural)
        if not self._add_node(node, nodes, seen_ids):
            return
        edges.append(GraphEdge(source_id=parent_id, target_id=node_id, type=EdgeType.DEFINES))

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
        source_node = imp.child_by_field_name("source")
        module = node_text(source_node).strip("'\"") if source_node else text

        node_id = make_node_id(file_path, NodeType.FILE, module, start)
        structural = StructuralProperties(
            name=module,
            file=file_path,
            signature=text,
            start_line=start,
            end_line=end,
            lines=end - start + 1,
        )
        node = GraphNode(id=node_id, type=NodeType.FILE, file_path=file_path, structural=structural)
        nodes.append(node)
        edges.append(GraphEdge(source_id=parent_id, target_id=node_id, type=EdgeType.IMPORTS))

    def _walk_export(
        self,
        node: ts.Node,
        source: bytes,
        file_path: str,
        parent_id: str,
        nodes: list[GraphNode],
        edges: list[GraphEdge],
        seen_ids: set[str],
    ) -> None:
        if node.type == "function_declaration":
            self._process_function(node, source, file_path, parent_id, nodes, edges, seen_ids)
        elif node.type == "class_declaration":
            self._process_class(node, source, file_path, parent_id, nodes, edges, seen_ids)
        elif node.type == "export_statement":
            for child in node.children:
                self._walk_export(child, source, file_path, parent_id, nodes, edges, seen_ids)
