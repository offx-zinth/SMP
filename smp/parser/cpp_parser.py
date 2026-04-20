"""C/C++ tree-sitter parser.

Extracts functions, classes, structs, methods, and includes from C/C++ source.
"""

from __future__ import annotations

import tree_sitter as ts
import tree_sitter_c as tsc
import tree_sitter_cpp as tscpp

from smp.core.models import EdgeType, GraphEdge, GraphNode, NodeType, ParseError, StructuralProperties
from smp.logging import get_logger
from smp.parser.base import TreeSitterParser, line_range, make_node_id, node_text

log = get_logger(__name__)

_C_LANG = ts.Language(tsc.language())
_CPP_LANG = ts.Language(tscpp.language())


class CParser(TreeSitterParser):
    """Extract structural elements from C source."""

    @property
    def supported_languages(self) -> list[str]:
        return ["c"]

    def _language(self, file_path: str) -> ts.Language:
        return _C_LANG

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

        log.debug("c_parsed", file=file_path, nodes=len(nodes), edges=len(edges), errors=len(errors))
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
        if node.type == "function_definition":
            self._process_function(node, source, file_path, parent_id, nodes, edges, seen_ids)
        elif node.type == "struct_specifier":
            self._process_struct(node, source, file_path, parent_id, nodes, edges, seen_ids)
        elif node.type == "preproc_include":
            self._process_include(node, source, file_path, parent_id, nodes, edges)
        else:
            for child in node.children:
                self._walk_tree(child, source, file_path, parent_id, nodes, edges, seen_ids)

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
        name = self._extract_function_name(func)
        if not name:
            return

        start, end = line_range(func)
        node_id = make_node_id(file_path, NodeType.FUNCTION, name, start)

        sig_text = node_text(func).split("{")[0].strip()[:100]

        structural = StructuralProperties(
            name=name,
            file=file_path,
            signature=sig_text,
            start_line=start,
            end_line=end,
            lines=end - start + 1,
        )
        node = GraphNode(id=node_id, type=NodeType.FUNCTION, file_path=file_path, structural=structural)
        if not self._add_node(node, nodes, seen_ids):
            return
        edges.append(GraphEdge(source_id=parent_id, target_id=node_id, type=EdgeType.DEFINES))

    def _extract_function_name(self, func: ts.Node) -> str:
        for child in func.children:
            if child.type == "function_declarator":
                for sub in child.children:
                    if sub.type == "identifier":
                        return node_text(sub)
                    if sub.type == "field_identifier":
                        return node_text(sub)
                    if sub.type == "parenthesized_declarator":
                        for p in sub.children:
                            if p.type == "function_declarator":
                                return self._extract_function_name_from_declarator(p)
                            if p.type == "identifier":
                                return node_text(p)
                    if sub.type == "pointer_declarator":
                        for p in sub.children:
                            if p.type == "identifier":
                                return node_text(p)
        return ""

    def _extract_function_name_from_declarator(self, declarator: ts.Node) -> str:
        for child in declarator.children:
            if child.type in ("identifier", "field_identifier"):
                return node_text(child)
        return ""

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
            if child.type == "type_identifier":
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

    def _process_include(
        self,
        inc: ts.Node,
        source: bytes,
        file_path: str,
        parent_id: str,
        nodes: list[GraphNode],
        edges: list[GraphEdge],
    ) -> None:
        start, end = line_range(inc)
        text = node_text(inc).strip()

        module = ""
        for child in inc.children:
            if child.type == "system_lib_string":
                module = node_text(child).strip("<>")
            elif child.type == "string_literal":
                module = node_text(child).strip("\"'")

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


class CppParser(CParser):
    """Extract structural elements from C++ source."""

    @property
    def supported_languages(self) -> list[str]:
        return ["cpp"]

    def _language(self, file_path: str) -> ts.Language:
        return _CPP_LANG

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
        if node.type == "function_definition":
            self._process_function(node, source, file_path, parent_id, nodes, edges, seen_ids)
        elif node.type == "struct_specifier":
            self._process_struct(node, source, file_path, parent_id, nodes, edges, seen_ids)
        elif node.type == "class_specifier":
            self._process_class(node, source, file_path, parent_id, nodes, edges, seen_ids)
        elif node.type == "preproc_include":
            self._process_include(node, source, file_path, parent_id, nodes, edges)
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
            if child.type == "type_identifier":
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

        body = None
        for child in cls.children:
            if child.type == "field_declaration_list":
                body = child
                break

        if body:
            for child in body.children:
                if child.type == "function_definition":
                    self._process_function(child, source, file_path, node_id, nodes, edges, seen_ids)
