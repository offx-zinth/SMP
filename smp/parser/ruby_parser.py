"""Ruby tree-sitter parser.

Extracts classes, modules, methods, and requires from Ruby source.
"""

from __future__ import annotations

import tree_sitter as ts
import tree_sitter_ruby as tsruby  # type: ignore[import-not-found]

from smp.core.models import EdgeType, GraphEdge, GraphNode, NodeType, ParseError, StructuralProperties
from smp.logging import get_logger
from smp.parser.base import TreeSitterParser, line_range, make_node_id, node_text

log = get_logger(__name__)

_LANGUAGE = ts.Language(tsruby.language())

_QUERY_STRINGS = {
    "top": """
    (class name: (constant) @name) @class
    (module name: (constant) @name) @module
    (method name: (identifier) @name) @method
    (singleton_method name: (identifier) @name) @singleton
    """,
}


class RubyParser(TreeSitterParser):
    """Extract structural elements from Ruby source."""

    @property
    def supported_languages(self) -> list[str]:
        return ["ruby"]

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
            module_nodes = caps.get("module")
            method_nodes = caps.get("method")
            singleton_nodes = caps.get("singleton")

            if class_nodes:
                self._process_class(class_nodes[0], source_bytes, file_path, file_node.id, nodes, edges, seen_ids)
            elif module_nodes:
                self._process_module(module_nodes[0], source_bytes, file_path, file_node.id, nodes, edges, seen_ids)
            elif method_nodes:
                self._process_method(method_nodes[0], source_bytes, file_path, file_node.id, nodes, edges, seen_ids)
            elif singleton_nodes:
                self._process_method(singleton_nodes[0], source_bytes, file_path, file_node.id, nodes, edges, seen_ids)

        self._process_requires(root_node, source_bytes, file_path, file_node.id, nodes, edges)

        log.debug("ruby_parsed", file=file_path, nodes=len(nodes), edges=len(edges), errors=len(errors))
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
        superclass_node = cls.child_by_field_name("superclass")
        if superclass_node:
            base_name = node_text(superclass_node)
            sig += f" < {base_name}"
            base_id = make_node_id(file_path, NodeType.CLASS, base_name, 0)
            edges.append(GraphEdge(source_id=node_id, target_id=base_id, type=EdgeType.INHERITS))

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
            self._walk_body(body, source, file_path, node_id, name, nodes, edges, seen_ids)

    def _process_module(
        self,
        module: ts.Node,
        source: bytes,
        file_path: str,
        parent_id: str,
        nodes: list[GraphNode],
        edges: list[GraphEdge],
        seen_ids: set[str],
    ) -> None:
        name_node = module.child_by_field_name("name")
        if not name_node:
            return
        name = node_text(name_node)
        start, end = line_range(module)
        node_id = make_node_id(file_path, NodeType.CLASS, name, start)

        structural = StructuralProperties(
            name=name,
            file=file_path,
            signature=f"module {name}",
            start_line=start,
            end_line=end,
            lines=end - start + 1,
        )
        node = GraphNode(id=node_id, type=NodeType.CLASS, file_path=file_path, structural=structural)
        if not self._add_node(node, nodes, seen_ids):
            return
        edges.append(GraphEdge(source_id=parent_id, target_id=node_id, type=EdgeType.DEFINES))

        body = module.child_by_field_name("body")
        if body:
            self._walk_body(body, source, file_path, node_id, name, nodes, edges, seen_ids)

    def _walk_body(
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
        query = ts.Query(_LANGUAGE, "(method name: (identifier) @name) @method")
        cursor = ts.QueryCursor(query)
        for _, caps in cursor.matches(body):
            method_nodes = caps.get("method")
            if method_nodes:
                self._process_method(method_nodes[0], source, file_path, parent_id, nodes, edges, seen_ids)

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
        sig = f"def {name}{params_text}"

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

    def _process_requires(
        self,
        root: ts.Node,
        source: bytes,
        file_path: str,
        parent_id: str,
        nodes: list[GraphNode],
        edges: list[GraphEdge],
    ) -> None:
        call_query = ts.Query(_LANGUAGE, "(call) @call")
        cursor = ts.QueryCursor(call_query)
        for _, caps in cursor.matches(root):
            call_nodes = caps.get("call")
            if not call_nodes:
                continue
            call_node = call_nodes[0]
            method_node = call_node.child_by_field_name("method")
            if not method_node:
                continue
            method_name = node_text(method_node)
            if method_name in ("require", "require_relative", "load"):
                args_node = call_node.child_by_field_name("arguments")
                if args_node:
                    for child in args_node.children:
                        if child.type == "string":
                            module = node_text(child).strip("'\"")
                            start, _ = line_range(call_node)
                            node_id = make_node_id(file_path, NodeType.FILE, module, start)
                            structural = StructuralProperties(
                                name=module,
                                file=file_path,
                                signature=node_text(call_node),
                                start_line=start,
                                lines=1,
                            )
                            node = GraphNode(id=node_id, type=NodeType.FILE, file_path=file_path, structural=structural)
                            nodes.append(node)
                            edges.append(GraphEdge(source_id=parent_id, target_id=node_id, type=EdgeType.IMPORTS))
