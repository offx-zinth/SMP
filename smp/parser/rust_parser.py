"""Rust tree-sitter parser.

Extracts functions, structs, enums, traits, impls, and use statements from Rust source.
"""

from __future__ import annotations

import tree_sitter as ts
import tree_sitter_rust as tsr

from smp.core.models import EdgeType, GraphEdge, GraphNode, NodeType, ParseError, StructuralProperties
from smp.logging import get_logger
from smp.parser.base import TreeSitterParser, line_range, make_node_id, node_text

log = get_logger(__name__)

_LANGUAGE = ts.Language(tsr.language())


class RustParser(TreeSitterParser):
    """Extract structural elements from Rust source."""

    @property
    def supported_languages(self) -> list[str]:
        return ["rust"]

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

        log.debug("rust_parsed", file=file_path, nodes=len(nodes), edges=len(edges), errors=len(errors))
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
        if node.type == "function_item":
            self._process_function(node, source, file_path, parent_id, nodes, edges, seen_ids)
        elif node.type == "struct_item":
            self._process_struct(node, source, file_path, parent_id, nodes, edges, seen_ids)
        elif node.type == "enum_item":
            self._process_enum(node, source, file_path, parent_id, nodes, edges, seen_ids)
        elif node.type == "trait_item":
            self._process_trait(node, source, file_path, parent_id, nodes, edges, seen_ids)
        elif node.type == "impl_item":
            self._process_impl(node, source, file_path, parent_id, nodes, edges, seen_ids)
        elif node.type == "use_declaration":
            self._process_use(node, source, file_path, parent_id, nodes, edges)
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
        name = ""
        params_text = "()"
        ret_text = ""

        for child in func.children:
            if child.type == "identifier":
                name = node_text(child)
            elif child.type == "parameters":
                params_text = node_text(child)
            elif child.type == "type":
                ret_text = " " + node_text(child)

        if not name:
            return

        start, end = line_range(func)
        sig = f"fn {name}{params_text}{ret_text}"

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

    def _process_enum(
        self,
        enum: ts.Node,
        source: bytes,
        file_path: str,
        parent_id: str,
        nodes: list[GraphNode],
        edges: list[GraphEdge],
        seen_ids: set[str],
    ) -> None:
        name = ""
        for child in enum.children:
            if child.type == "identifier":
                name = node_text(child)
                break

        if not name:
            return

        start, end = line_range(enum)
        node_id = make_node_id(file_path, NodeType.CLASS, name, start)

        structural = StructuralProperties(
            name=name,
            file=file_path,
            signature=f"enum {name}",
            start_line=start,
            end_line=end,
            lines=end - start + 1,
        )
        node = GraphNode(id=node_id, type=NodeType.CLASS, file_path=file_path, structural=structural)
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
        name = ""
        for child in trait.children:
            if child.type == "type_identifier":
                name = node_text(child)
                break

        if not name:
            return

        start, end = line_range(trait)
        node_id = make_node_id(file_path, NodeType.INTERFACE, name, start)

        structural = StructuralProperties(
            name=name,
            file=file_path,
            signature=f"trait {name}",
            start_line=start,
            end_line=end,
            lines=end - start + 1,
        )
        node = GraphNode(id=node_id, type=NodeType.INTERFACE, file_path=file_path, structural=structural)
        if not self._add_node(node, nodes, seen_ids):
            return
        edges.append(GraphEdge(source_id=parent_id, target_id=node_id, type=EdgeType.DEFINES))

    def _process_impl(
        self,
        impl: ts.Node,
        source: bytes,
        file_path: str,
        parent_id: str,
        nodes: list[GraphNode],
        edges: list[GraphEdge],
        seen_ids: set[str],
    ) -> None:
        impl_name = ""
        trait_name = ""

        for child in impl.children:
            if child.type == "type_identifier":
                impl_name = node_text(child)
            elif child.type == "forall_type":
                for sub in child.children:
                    if sub.type == "type_identifier":
                        trait_name = node_text(sub)

        if impl_name:
            start, end = line_range(impl)
            node_id = make_node_id(file_path, NodeType.CLASS, impl_name, start)

            structural = StructuralProperties(
                name=impl_name,
                file=file_path,
                signature=f"impl {impl_name}",
                start_line=start,
                end_line=end,
                lines=end - start + 1,
            )
            node = GraphNode(id=node_id, type=NodeType.CLASS, file_path=file_path, structural=structural)
            if self._add_node(node, nodes, seen_ids):
                edges.append(GraphEdge(source_id=parent_id, target_id=node_id, type=EdgeType.DEFINES))

                if trait_name:
                    trait_id = make_node_id(file_path, NodeType.INTERFACE, trait_name, 0)
                    edges.append(GraphEdge(source_id=node_id, target_id=trait_id, type=EdgeType.IMPLEMENTS))

            for child in impl.children:
                if child.type == "declaration_list":
                    for sub in child.children:
                        if sub.type == "function_item":
                            self._process_function(sub, source, file_path, node_id, nodes, edges, seen_ids)

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

        module = ""
        for child in use.children:
            if child.type == "use_clause":
                for sub in child.children:
                    if sub.type == "identifier":
                        module = node_text(sub)
                        break
                    if sub.type == "scoped_identifier":
                        module = node_text(sub)
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
