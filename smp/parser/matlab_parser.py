"""MATLAB tree-sitter parser.

Extracts functions, classes, and scripts from MATLAB source.
"""

from __future__ import annotations

import tree_sitter as ts
import tree_sitter_matlab as tsmatlab  # type: ignore[import-not-found]

from smp.core.models import EdgeType, GraphEdge, GraphNode, NodeType, ParseError, StructuralProperties
from smp.logging import get_logger
from smp.parser.base import TreeSitterParser, line_range, make_node_id, node_text

log = get_logger(__name__)

_LANGUAGE = ts.Language(tsmatlab.language())

_QUERY_STRINGS = {
    "top": """
    (function_definition name: (identifier) @name) @func
    (class_definition name: (identifier) @name) @class
    """,
}


class MatlabParser(TreeSitterParser):
    """Extract structural elements from MATLAB source."""

    @property
    def supported_languages(self) -> list[str]:
        return ["matlab"]

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

            if func_nodes:
                self._process_function(func_nodes[0], source_bytes, file_path, file_node.id, nodes, edges, seen_ids)
            elif class_nodes:
                self._process_class(class_nodes[0], source_bytes, file_path, file_node.id, nodes, edges, seen_ids)

        log.debug("matlab_parsed", file=file_path, nodes=len(nodes), edges=len(edges), errors=len(errors))
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
        node_id = make_node_id(file_path, NodeType.FUNCTION, name, start)

        params_text = ""
        params_node = func.child_by_field_name("parameters")
        if params_node:
            params_text = node_text(params_node)
        sig = f"function {name}{params_text}"

        structural = StructuralProperties(
            name=name,
            file=file_path,
            signature=sig[:100],
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

        sig = f"classdef {name}"

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

        for child in cls.children:
            if child.type == "properties_block":
                self._process_properties(child, source, file_path, node_id, nodes, edges)
            elif child.type == "methods_block":
                self._process_methods(child, source, file_path, node_id, nodes, edges, seen_ids)

    def _process_properties(
        self,
        props: ts.Node,
        source: bytes,
        file_path: str,
        parent_id: str,
        nodes: list[GraphNode],
        edges: list[GraphEdge],
    ) -> None:
        for child in props.children:
            if child.type == "property_assignment":
                name_node = child.child_by_field_name("name")
                if name_node:
                    name = node_text(name_node)
                    start, end = line_range(child)
                    node_id = make_node_id(file_path, NodeType.VARIABLE, name, start)
                    structural = StructuralProperties(
                        name=name,
                        file=file_path,
                        signature=name,
                        start_line=start,
                        end_line=end,
                        lines=end - start + 1,
                    )
                    node = GraphNode(id=node_id, type=NodeType.VARIABLE, file_path=file_path, structural=structural)
                    nodes.append(node)
                    edges.append(GraphEdge(source_id=parent_id, target_id=node_id, type=EdgeType.DEFINES))

    def _process_methods(
        self,
        methods: ts.Node,
        source: bytes,
        file_path: str,
        parent_id: str,
        nodes: list[GraphNode],
        edges: list[GraphEdge],
        seen_ids: set[str],
    ) -> None:
        method_query = ts.Query(_LANGUAGE, "(function_definition name: (identifier) @name) @method")
        method_cursor = ts.QueryCursor(method_query)
        for _, caps in method_cursor.matches(methods):
            method_nodes = caps.get("method")
            if method_nodes:
                self._process_function(method_nodes[0], source, file_path, parent_id, nodes, edges, seen_ids)
