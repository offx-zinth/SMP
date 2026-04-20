"""Java-specific tree-sitter parser.

Extracts classes, methods, fields, imports, and call relationships from Java source.
"""

from __future__ import annotations

import tree_sitter as ts
import tree_sitter_java as tsj  # type: ignore[import-not-found]

from smp.core.models import EdgeType, GraphEdge, GraphNode, NodeType, ParseError, StructuralProperties
from smp.logging import get_logger
from smp.parser.base import TreeSitterParser, line_range, make_node_id, node_text

log = get_logger(__name__)

_LANGUAGE = ts.Language(tsj.language())

_QUERY_STRINGS = {
    "top": """
    (class_declaration name: (identifier) @name) @class
    (interface_declaration name: (identifier) @name) @interface
    (method_declaration name: (identifier) @name) @method
    (import_declaration) @import
    """,
    "field": """
    (field_declaration declarator: (variable_declarator name: (identifier) @name)) @field
    """,
    "call": """
    (method_invocation name: (identifier) @callee) @call
    """,
}


class JavaParser(TreeSitterParser):
    """Extract structural elements from Java source."""

    @property
    def supported_languages(self) -> list[str]:
        return ["java"]

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

        top_query = ts.Query(_LANGUAGE, _QUERY_STRINGS["top"])
        cursor = ts.QueryCursor(top_query)
        for _, caps in cursor.matches(root_node):
            class_nodes = caps.get("class")
            iface_nodes = caps.get("interface")
            method_nodes = caps.get("method")
            import_nodes = caps.get("import")

            if class_nodes:
                self._process_class(class_nodes[0], source_bytes, file_path, file_node.id, nodes, edges, seen_ids)
            elif iface_nodes:
                self._process_interface(iface_nodes[0], source_bytes, file_path, file_node.id, nodes, edges, seen_ids)
            elif method_nodes:
                self._process_method(
                    method_nodes[0], source_bytes, file_path, file_node.id, None, nodes, edges, seen_ids
                )
            elif import_nodes:
                self._process_import(import_nodes[0], source_bytes, file_path, file_node.id, nodes, edges)

        log.debug("java_parsed", file=file_path, nodes=len(nodes), edges=len(edges), errors=len(errors))
        return nodes, edges, errors

    def _add_node(self, node: GraphNode, nodes: list[GraphNode], seen: set[str]) -> bool:
        if node.id in seen:
            return False
        seen.add(node.id)
        nodes.append(node)
        return True

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

        sig = f"class {name}"
        for child in cls.children:
            if child.type == "superclass":
                for sub in child.children:
                    if sub.type == "type_identifier":
                        base = node_text(sub)
                        sig += f" extends {base}"
                        base_id = make_node_id(file_path, NodeType.INTERFACE, base, 0)
                        src_id = make_node_id(file_path, NodeType.CLASS, name, start)
                        edges.append(GraphEdge(source_id=src_id, target_id=base_id, type=EdgeType.IMPLEMENTS))
            elif child.type == "interfaces":
                impl_names: list[str] = []
                for sub in child.children:
                    if sub.type == "type_identifier":
                        impl_names.append(node_text(sub))
                if impl_names:
                    sig += f" implements {', '.join(impl_names)}"

        node_id = make_node_id(file_path, NodeType.CLASS, name, start)
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
            self._walk_class_body(body, source, file_path, node_id, name, nodes, edges, seen_ids)

    def _walk_class_body(
        self,
        body: ts.Node,
        source: bytes,
        file_path: str,
        parent_id: str,
        class_name: str,
        nodes: list[GraphNode],
        edges: list[GraphEdge],
        seen_ids: set[str],
    ) -> None:
        method_query = ts.Query(_LANGUAGE, "(method_declaration name: (identifier) @name) @method")
        field_query = ts.Query(_LANGUAGE, _QUERY_STRINGS["field"])

        method_cursor = ts.QueryCursor(method_query)
        for _, caps in method_cursor.matches(body):
            method_nodes = caps.get("method")
            if method_nodes:
                self._process_method(method_nodes[0], source, file_path, parent_id, class_name, nodes, edges, seen_ids)

        field_cursor = ts.QueryCursor(field_query)
        for _, caps in field_cursor.matches(body):
            field_nodes = caps.get("field")
            name_nodes = caps.get("name")
            if field_nodes and name_nodes:
                self._process_field(field_nodes[0], name_nodes[0], source, file_path, parent_id, nodes, edges)

    def _process_interface(
        self,
        iface: ts.Node,
        source: bytes,
        file_path: str,
        parent_id: str,
        nodes: list[GraphNode],
        edges: list[GraphEdge],
        seen_ids: set[str],
    ) -> None:
        name_node = iface.child_by_field_name("name")
        if not name_node:
            return
        name = node_text(name_node)
        start, end = line_range(iface)
        node_id = make_node_id(file_path, NodeType.INTERFACE, name, start)

        structural = StructuralProperties(
            name=name,
            file=file_path,
            signature=f"interface {name}",
            start_line=start,
            end_line=end,
            lines=end - start + 1,
        )
        node = GraphNode(id=node_id, type=NodeType.INTERFACE, file_path=file_path, structural=structural)
        if not self._add_node(node, nodes, seen_ids):
            return
        edges.append(GraphEdge(source_id=parent_id, target_id=node_id, type=EdgeType.DEFINES))

    def _process_method(
        self,
        method: ts.Node,
        source: bytes,
        file_path: str,
        parent_id: str,
        class_name: str | None,
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
        ret_type = ""
        for child in method.children:
            if child.type == "type_identifier":
                ret_type = node_text(child)
                break
        sig = f"{ret_type} {name}{params_text}" if ret_type else f"{name}{params_text}"

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

        body = method.child_by_field_name("body")
        if body:
            self._extract_calls(body, source, file_path, node_id, nodes, edges)

    def _process_field(
        self,
        field: ts.Node,
        name_node: ts.Node,
        source: bytes,
        file_path: str,
        parent_id: str,
        nodes: list[GraphNode],
        edges: list[GraphEdge],
    ) -> None:
        name = node_text(name_node)
        start, end = line_range(field)
        node_id = make_node_id(file_path, NodeType.VARIABLE, name, start)

        structural = StructuralProperties(
            name=name,
            file=file_path,
            signature=node_text(field),
            start_line=start,
            end_line=end,
            lines=end - start + 1,
        )
        node = GraphNode(id=node_id, type=NodeType.VARIABLE, file_path=file_path, structural=structural)
        nodes.append(node)
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
        module = text.replace("import ", "").replace(";", "").strip()

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

    def _extract_calls(
        self,
        body: ts.Node,
        source: bytes,
        file_path: str,
        caller_id: str,
        nodes: list[GraphNode],
        edges: list[GraphEdge],
    ) -> None:
        query = ts.Query(_LANGUAGE, _QUERY_STRINGS["call"])
        cursor = ts.QueryCursor(query)
        seen_edges: set[tuple[str, str]] = set()

        for _, caps in cursor.matches(body):
            callee_nodes = caps.get("callee")
            call_nodes = caps.get("call")
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
            edges.append(
                GraphEdge(
                    source_id=caller_id,
                    target_id=target_id,
                    type=EdgeType.CALLS,
                    metadata={"line": str(start)},
                )
            )
