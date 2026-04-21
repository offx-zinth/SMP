"""PHP tree-sitter parser.

Extracts classes, functions, methods, traits, and use statements from PHP source.
"""

from __future__ import annotations

import tree_sitter as ts
import tree_sitter_php as tsphp  # type: ignore[import-not-found]

from smp.core.models import EdgeType, GraphEdge, GraphNode, NodeType, ParseError, StructuralProperties
from smp.logging import get_logger
from smp.parser.base import TreeSitterParser, line_range, make_node_id, node_text

log = get_logger(__name__)

_LANGUAGE = ts.Language(tsphp.language_php())

_QUERY_STRINGS = {
    "top": """
    (class_declaration name: (name) @name) @class
    (interface_declaration name: (name) @name) @interface
    (trait_declaration name: (name) @name) @trait
    (function_definition name: (name) @name) @func
    (namespace_use_declaration) @use
    """,
    "method": """
    (method_declaration name: (name) @name) @method
    """,
}


class PhpParser(TreeSitterParser):
    """Extract structural elements from PHP source."""

    @property
    def supported_languages(self) -> list[str]:
        return ["php"]

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
            class_nodes = caps.get("class")
            iface_nodes = caps.get("interface")
            trait_nodes = caps.get("trait")
            func_nodes = caps.get("func")
            use_nodes = caps.get("use")

            if class_nodes:
                self._process_class(class_nodes[0], source_bytes, file_path, file_node.id, nodes, edges, seen_ids)
            elif iface_nodes:
                self._process_interface(iface_nodes[0], source_bytes, file_path, file_node.id, nodes, edges, seen_ids)
            elif trait_nodes:
                self._process_trait(trait_nodes[0], source_bytes, file_path, file_node.id, nodes, edges, seen_ids)
            elif func_nodes:
                self._process_function(func_nodes[0], source_bytes, file_path, file_node.id, nodes, edges, seen_ids)
            elif use_nodes:
                self._process_use(use_nodes[0], source_bytes, file_path, file_node.id, nodes, edges)

        log.debug("php_parsed", file=file_path, nodes=len(nodes), edges=len(edges), errors=len(errors))
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
        node_id = make_node_id(file_path, NodeType.CLASS, name, start)

        sig = f"class {name}"
        extends_node = cls.child_by_field_name("extends")
        if extends_node:
            base_name = node_text(extends_node)
            sig += f" extends {base_name}"
            base_id = make_node_id(file_path, NodeType.CLASS, base_name, 0)
            edges.append(GraphEdge(source_id=node_id, target_id=base_id, type=EdgeType.INHERITS))

        implements_node = cls.child_by_field_name("implements")
        if implements_node:
            impl_names: list[str] = []
            for child in implements_node.children:
                if child.type == "name":
                    impl_names.append(node_text(child))
            if impl_names:
                sig += f" implements {', '.join(impl_names)}"

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
        method_query = ts.Query(_LANGUAGE, _QUERY_STRINGS["method"])
        method_cursor = ts.QueryCursor(method_query)
        for _, caps in method_cursor.matches(body):
            method_nodes = caps.get("method")
            if method_nodes:
                self._process_method(method_nodes[0], source, file_path, parent_id, class_name, nodes, edges, seen_ids)

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

    def _process_trait(
        self,
        trait: ts.Node,
        source: bytes,
        file_path: str,
        parent_id: str,
        nodes: list[GraphNode],
        edges: list[GraphEdge],
        seen_ids: set[str],
    ) -> None:
        name_node = trait.child_by_field_name("name")
        if not name_node:
            return
        name = node_text(name_node)
        start, end = line_range(trait)
        node_id = make_node_id(file_path, NodeType.CLASS, name, start)

        structural = StructuralProperties(
            name=name,
            file=file_path,
            signature=f"trait {name}",
            start_line=start,
            end_line=end,
            lines=end - start + 1,
        )
        node = GraphNode(id=node_id, type=NodeType.CLASS, file_path=file_path, structural=structural)
        if not self._add_node(node, nodes, seen_ids):
            return
        edges.append(GraphEdge(source_id=parent_id, target_id=node_id, type=EdgeType.DEFINES))

        body = trait.child_by_field_name("body")
        if body:
            self._walk_class_body(body, source, file_path, node_id, name, nodes, edges, seen_ids)

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
        ret_type = ""
        for child in func.children:
            if child.type in ("union_type", "named_type", "primitive_type"):
                ret_type = node_text(child)
                break
        sig = f"function {name}{params_text}"
        if ret_type:
            sig += f": {ret_type}"

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

    def _process_method(
        self,
        method: ts.Node,
        source: bytes,
        file_path: str,
        parent_id: str,
        class_name: str,
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
            if child.type in ("union_type", "named_type", "primitive_type"):
                ret_type = node_text(child)
                break
        sig = f"function {name}{params_text}"
        if ret_type:
            sig += f": {ret_type}"

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

    def _process_use(
        self,
        use: ts.Node,
        source: bytes,
        file_path: str,
        parent_id: str,
        nodes: list[GraphNode],
        edges: list[GraphEdge],
    ) -> None:
        start, end = line_range(use)
        text = node_text(use).strip()

        for child in use.children:
            if child.type == "namespace_use_clause":
                for sub in child.children:
                    if sub.type == "name":
                        module = node_text(sub)
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
