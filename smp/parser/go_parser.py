"""Go tree-sitter parser.

Extracts functions, methods, structs, interfaces, and imports from Go source.
"""

from __future__ import annotations

import tree_sitter as ts
import tree_sitter_go as tsg  # type: ignore[import-not-found]

from smp.core.models import EdgeType, GraphEdge, GraphNode, NodeType, ParseError, StructuralProperties
from smp.logging import get_logger
from smp.parser.base import TreeSitterParser, line_range, make_node_id, node_text

log = get_logger(__name__)

_LANGUAGE = ts.Language(tsg.language())

_QUERY_STRINGS = {
    "top": """
    (function_declaration name: (identifier) @name) @func
    (method_declaration name: (field_identifier) @name) @method
    (type_declaration) @type_decl
    (import_declaration) @import
    """,
}


class GoParser(TreeSitterParser):
    """Extract structural elements from Go source."""

    @property
    def supported_languages(self) -> list[str]:
        return ["go"]

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
            method_nodes = caps.get("method")
            type_nodes = caps.get("type_decl")
            import_nodes = caps.get("import")

            if func_nodes:
                self._process_function(func_nodes[0], source_bytes, file_path, file_node.id, nodes, edges, seen_ids)
            elif method_nodes:
                self._process_method(method_nodes[0], source_bytes, file_path, file_node.id, nodes, edges, seen_ids)
            elif type_nodes:
                self._process_type_declaration(
                    type_nodes[0], source_bytes, file_path, file_node.id, nodes, edges, seen_ids
                )
            elif import_nodes:
                self._process_import(import_nodes[0], source_bytes, file_path, file_node.id, nodes, edges)

        log.debug("go_parsed", file=file_path, nodes=len(nodes), edges=len(edges), errors=len(errors))
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
        result_text = ""
        result_node = func.child_by_field_name("result")
        if result_node:
            result_text = " " + node_text(result_node)
        sig = f"func {name}{params_text}{result_text}"

        node_id = make_node_id(file_path, NodeType.FUNCTION, name, start)
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

        receiver_node = method.child_by_field_name("receiver")
        receiver = node_text(receiver_node) if receiver_node else ""
        params_node = method.child_by_field_name("parameters")
        params_text = node_text(params_node) if params_node else "()"
        sig = f"func ({receiver}) {name}{params_text}"

        node_id = make_node_id(file_path, NodeType.FUNCTION, name, start)
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

    def _process_type_declaration(
        self,
        type_decl: ts.Node,
        source: bytes,
        file_path: str,
        parent_id: str,
        nodes: list[GraphNode],
        edges: list[GraphEdge],
        seen_ids: set[str],
    ) -> None:
        for child in type_decl.children:
            if child.type == "type_spec":
                name_node = child.child_by_field_name("name")
                type_node = child.child_by_field_name("type")
                if not name_node:
                    continue
                name = node_text(name_node)
                start, end = line_range(child)

                if type_node:
                    if type_node.type == "struct_type":
                        self._process_struct(name, child, source, file_path, parent_id, nodes, edges, seen_ids)
                    elif type_node.type == "interface_type":
                        self._process_interface(name, child, source, file_path, parent_id, nodes, edges, seen_ids)

    def _process_struct(
        self,
        name: str,
        node: ts.Node,
        source: bytes,
        file_path: str,
        parent_id: str,
        nodes: list[GraphNode],
        edges: list[GraphEdge],
        seen_ids: set[str],
    ) -> None:
        start, end = line_range(node)
        node_id = make_node_id(file_path, NodeType.CLASS, name, start)

        structural = StructuralProperties(
            name=name,
            file=file_path,
            signature=f"type {name} struct",
            start_line=start,
            end_line=end,
            lines=end - start + 1,
        )
        graph_node = GraphNode(id=node_id, type=NodeType.CLASS, file_path=file_path, structural=structural)
        if not self._add_node(graph_node, nodes, seen_ids):
            return
        edges.append(GraphEdge(source_id=parent_id, target_id=node_id, type=EdgeType.DEFINES))

    def _process_interface(
        self,
        name: str,
        node: ts.Node,
        source: bytes,
        file_path: str,
        parent_id: str,
        nodes: list[GraphNode],
        edges: list[GraphEdge],
        seen_ids: set[str],
    ) -> None:
        start, end = line_range(node)
        node_id = make_node_id(file_path, NodeType.INTERFACE, name, start)

        structural = StructuralProperties(
            name=name,
            file=file_path,
            signature=f"type {name} interface",
            start_line=start,
            end_line=end,
            lines=end - start + 1,
        )
        graph_node = GraphNode(id=node_id, type=NodeType.INTERFACE, file_path=file_path, structural=structural)
        if not self._add_node(graph_node, nodes, seen_ids):
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

        import_spec = None
        for child in imp.children:
            if child.type == "import_spec":
                import_spec = child
                break
            if child.type == "import_spec_list":
                for sub in child.children:
                    if sub.type == "import_spec":
                        self._process_import_spec(sub, source, file_path, parent_id, nodes, edges)
                return

        if import_spec:
            self._process_import_spec(import_spec, source, file_path, parent_id, nodes, edges)

    def _process_import_spec(
        self,
        spec: ts.Node,
        source: bytes,
        file_path: str,
        parent_id: str,
        nodes: list[GraphNode],
        edges: list[GraphEdge],
    ) -> None:
        start, end = line_range(spec)
        path_node = spec.child_by_field_name("path")
        if not path_node:
            return
        module = node_text(path_node).strip("\"'")

        node_id = make_node_id(file_path, NodeType.FILE, module, start)
        structural = StructuralProperties(
            name=module,
            file=file_path,
            signature=f'import "{module}"',
            start_line=start,
            end_line=end,
            lines=end - start + 1,
        )
        node = GraphNode(id=node_id, type=NodeType.FILE, file_path=file_path, structural=structural)
        nodes.append(node)
        edges.append(GraphEdge(source_id=parent_id, target_id=node_id, type=EdgeType.IMPORTS))
