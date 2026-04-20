"""C# tree-sitter parser.

Extracts classes, methods, interfaces, properties, and using statements from C# source.
"""

from __future__ import annotations

import tree_sitter as ts
import tree_sitter_c_sharp as tscs

from smp.core.models import EdgeType, GraphEdge, GraphNode, NodeType, ParseError, StructuralProperties
from smp.logging import get_logger
from smp.parser.base import TreeSitterParser, line_range, make_node_id, node_text

log = get_logger(__name__)

_LANGUAGE = ts.Language(tscs.language())


class CSharpParser(TreeSitterParser):
    """Extract structural elements from C# source."""

    @property
    def supported_languages(self) -> list[str]:
        return ["csharp"]

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

        self._walk_tree(root_node, source_bytes, file_path, file_node.id, nodes, edges, seen_ids)

        log.debug("csharp_parsed", file=file_path, nodes=len(nodes), edges=len(edges), errors=len(errors))
        return nodes, edges, errors

    def _add_node(self, node: GraphNode, nodes: list[GraphNode], seen: set[str]) -> bool:
        if node.id in seen:
            return False
        seen.add(node.id)
        nodes.append(node)
        return True

    def _walk_tree(
        self,
        node: ts.Node,
        source: bytes,
        file_path: str,
        parent_id: str,
        nodes: list[GraphNode],
        edges: list[GraphEdge],
        seen_ids: set[str],
    ) -> None:
        if node.type == "class_declaration":
            self._process_class(node, source, file_path, parent_id, nodes, edges, seen_ids)
        elif node.type == "interface_declaration":
            self._process_interface(node, source, file_path, parent_id, nodes, edges, seen_ids)
        elif node.type == "struct_declaration":
            self._process_struct(node, source, file_path, parent_id, nodes, edges, seen_ids)
        elif node.type == "method_declaration":
            self._process_method(node, source, file_path, parent_id, nodes, edges, seen_ids)
        elif node.type == "using_directive":
            self._process_using(node, source, file_path, parent_id, nodes, edges)
        else:
            for child in node.children:
                self._walk_tree(child, source, file_path, parent_id, nodes, edges, seen_ids)

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
        name = ""
        for child in cls.children:
            if child.type == "identifier":
                name = node_text(child)
                break

        if not name:
            return

        start, end = line_range(cls)
        node_id = make_node_id(file_path, NodeType.CLASS, name, start)

        structural = StructuralProperties(
            name=name,
            file=file_path,
            signature=f"class {name}",
            start_line=start,
            end_line=end,
            lines=end - start + 1,
        )
        node = GraphNode(id=node_id, type=NodeType.CLASS, file_path=file_path, structural=structural)
        if not self._add_node(node, nodes, seen_ids):
            return
        edges.append(GraphEdge(source_id=parent_id, target_id=node_id, type=EdgeType.DEFINES))

        for child in cls.children:
            if child.type == "declaration_list":
                for sub in child.children:
                    if sub.type == "method_declaration":
                        self._process_method(sub, source, file_path, node_id, nodes, edges, seen_ids)

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
        name = ""
        for child in iface.children:
            if child.type == "identifier":
                name = node_text(child)
                break

        if not name:
            return

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

    def _process_struct(
        self,
        struct: ts.Node,
        source: bytes,
        file_path: str,
        parent_id: str,
        nodes: list[GraphNode],
        edges: list[GraphEdge],
        seen_ids: set[str],
    ) -> None:
        name = ""
        for child in struct.children:
            if child.type == "identifier":
                name = node_text(child)
                break

        if not name:
            return

        start, end = line_range(struct)
        node_id = make_node_id(file_path, NodeType.CLASS, name, start)

        structural = StructuralProperties(
            name=name,
            file=file_path,
            signature=f"struct {name}",
            start_line=start,
            end_line=end,
            lines=end - start + 1,
        )
        node = GraphNode(id=node_id, type=NodeType.CLASS, file_path=file_path, structural=structural)
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
        name = ""
        ret_type = ""
        params_text = "()"

        for child in method.children:
            if child.type == "identifier":
                name = node_text(child)
            elif child.type == "predefined_type":
                ret_type = node_text(child)
            elif child.type == "parameter_list":
                params_text = node_text(child)

        if not name:
            return

        start, end = line_range(method)
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

    def _process_using(
        self,
        using: ts.Node,
        source: bytes,
        file_path: str,
        parent_id: str,
        nodes: list[GraphNode],
        edges: list[GraphEdge],
    ) -> None:
        start, end = line_range(using)
        text = node_text(using).strip()

        module = ""
        for child in using.children:
            if child.type == "identifier":
                module = node_text(child)
                break
            if child.type == "qualified_name":
                module = node_text(child)
                break

        if not module:
            module = text

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
