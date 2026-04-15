"""TypeScript-specific tree-sitter parser.

Extracts functions, classes, interfaces, methods, imports, arrow functions,
and call edges from TypeScript / TSX source using ``tree-sitter-typescript``.
Updated for SMP(3) partitioned model.
"""

from __future__ import annotations

import tree_sitter as ts
import tree_sitter_typescript as tst

from smp.core.models import (
    EdgeType,
    GraphEdge,
    GraphNode,
    NodeType,
    ParseError,
    StructuralProperties,
)
from smp.logging import get_logger
from smp.parser.base import TreeSitterParser, is_tsx, line_range, make_node_id, node_text

log = get_logger(__name__)

_TS_LANG = ts.Language(tst.language_typescript())
_TSX_LANG = ts.Language(tst.language_tsx())

_QUERY_STRINGS = {
    "top": """
(function_declaration name: (identifier) @name) @func
(class_declaration name: (type_identifier) @name) @class
(interface_declaration name: (type_identifier) @name) @interface
(import_statement) @import
(export_statement) @export
""",
    "arrow": """
(lexical_declaration (variable_declarator name: (identifier) @name value: (arrow_function) @arrow)) @var
""",
    "method": """
(method_definition name: (property_identifier) @name) @method
""",
    "call": """
(call_expression function: (identifier) @callee) @call
(call_expression function: (member_expression property: (property_identifier) @callee)) @call
""",
}

_query_cache: dict[str, dict[str, ts.Query]] = {"ts": {}, "tsx": {}}


def _get_queries(lang: ts.Language) -> dict[str, ts.Query]:
    key = "tsx" if lang is _TSX_LANG else "ts"
    if not _query_cache[key]:
        for name, qstr in _QUERY_STRINGS.items():
            _query_cache[key][name] = ts.Query(lang, qstr)
    return _query_cache[key]


class TypeScriptParser(TreeSitterParser):
    """Extract structural elements from TypeScript / TSX source."""

    @property
    def supported_languages(self) -> list[str]:
        return ["typescript"]

    def _language(self, file_path: str) -> ts.Language:
        return _TSX_LANG if is_tsx(file_path) else _TS_LANG

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

        self._walk_block(
            root_node,
            source_bytes,
            file_path,
            self._language(file_path),
            parent_id=file_node.id,
            class_name=None,
            nodes=nodes,
            edges=edges,
            errors=errors,
            seen_ids=seen_ids,
        )
        log.debug("typescript_parsed", file=file_path, nodes=len(nodes), edges=len(edges), errors=len(errors))
        return nodes, edges, errors

    def _add_node(self, node: GraphNode, nodes: list[GraphNode], seen: set[str]) -> bool:
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
        lang: ts.Language,
        parent_id: str,
        class_name: str | None,
        nodes: list[GraphNode],
        edges: list[GraphEdge],
        errors: list[ParseError],
        seen_ids: set[str],
    ) -> None:
        queries = _get_queries(lang)
        cursor = ts.QueryCursor(queries["top"])
        for _idx, caps in cursor.matches(block):
            func_nodes = caps.get("func")
            class_nodes = caps.get("class")
            iface_nodes = caps.get("interface")
            import_nodes = caps.get("import")
            export_nodes = caps.get("export")

            if func_nodes:
                self._process_function(
                    func_nodes[0],
                    source,
                    file_path,
                    parent_id,
                    class_name,
                    nodes,
                    edges,
                    seen_ids,
                )
                continue

            if class_nodes:
                self._process_class(
                    class_nodes[0],
                    source,
                    file_path,
                    lang,
                    parent_id,
                    nodes,
                    edges,
                    errors,
                    seen_ids,
                )
                continue

            if iface_nodes:
                self._process_interface(iface_nodes[0], source, file_path, parent_id, nodes, edges, seen_ids)
                continue

            if import_nodes:
                self._process_import(import_nodes[0], source, file_path, parent_id, nodes, edges)
                continue

            if export_nodes:
                for child in export_nodes[0].children:
                    self._walk_block(
                        child,
                        source,
                        file_path,
                        lang,
                        parent_id,
                        class_name,
                        nodes,
                        edges,
                        errors,
                        seen_ids,
                    )
                continue

        arrow_cursor = ts.QueryCursor(queries["arrow"])
        for _idx, caps in arrow_cursor.matches(block):
            name_nodes = caps.get("name")
            arrow_nodes = caps.get("arrow")
            if name_nodes and arrow_nodes:
                self._process_arrow_function(
                    name_nodes[0],
                    arrow_nodes[0],
                    source,
                    file_path,
                    parent_id,
                    class_name,
                    nodes,
                    edges,
                    seen_ids,
                )

        method_cursor = ts.QueryCursor(queries["method"])
        for _idx, caps in method_cursor.matches(block):
            method_nodes = caps.get("method")
            name_nodes = caps.get("name")
            if method_nodes and name_nodes:
                self._process_method(
                    method_nodes[0],
                    name_nodes[0],
                    source,
                    file_path,
                    parent_id,
                    class_name,
                    nodes,
                    edges,
                    seen_ids,
                )

    def _process_function(
        self,
        func: ts.Node,
        source: bytes,
        file_path: str,
        parent_id: str,
        class_name: str | None,
        nodes: list[GraphNode],
        edges: list[GraphEdge],
        seen_ids: set[str],
    ) -> None:
        name_node = func.child_by_field_name("name")
        if not name_node:
            return
        name = node_text(name_node)
        start, end = line_range(func)
        sig = self._extract_ts_signature(func, source, name)
        node_id = make_node_id(file_path, NodeType.FUNCTION, name, start)

        structural = StructuralProperties(
            name=name,
            file=file_path,
            signature=sig,
            start_line=start,
            end_line=end,
            lines=end - start + 1,
        )

        node = GraphNode(
            id=node_id,
            type=NodeType.FUNCTION,
            file_path=file_path,
            structural=structural,
        )
        if not self._add_node(node, nodes, seen_ids):
            return

        edges.append(GraphEdge(source_id=parent_id, target_id=node_id, type=EdgeType.DEFINES))
        body = func.child_by_field_name("body")
        if body:
            self._extract_calls(body, source, file_path, node_id, nodes, edges)

    def _process_arrow_function(
        self,
        name_node: ts.Node,
        arrow: ts.Node,
        source: bytes,
        file_path: str,
        parent_id: str,
        class_name: str | None,
        nodes: list[GraphNode],
        edges: list[GraphEdge],
        seen_ids: set[str],
    ) -> None:
        name = node_text(name_node)
        start, end = line_range(arrow)
        sig = f"const {name} = {self._extract_ts_signature(arrow, source, name)}"
        node_id = make_node_id(file_path, NodeType.FUNCTION, name, start)

        structural = StructuralProperties(
            name=name,
            file=file_path,
            signature=sig,
            start_line=start,
            end_line=end,
            lines=end - start + 1,
        )

        node = GraphNode(
            id=node_id,
            type=NodeType.FUNCTION,
            file_path=file_path,
            structural=structural,
        )
        if not self._add_node(node, nodes, seen_ids):
            return

        edges.append(GraphEdge(source_id=parent_id, target_id=node_id, type=EdgeType.DEFINES))
        body = arrow.child_by_field_name("body")
        if body:
            self._extract_calls(body, source, file_path, node_id, nodes, edges)

    def _process_method(
        self,
        method: ts.Node,
        name_node: ts.Node,
        source: bytes,
        file_path: str,
        parent_id: str,
        class_name: str | None,
        nodes: list[GraphNode],
        edges: list[GraphEdge],
        seen_ids: set[str],
    ) -> None:
        name = node_text(name_node)
        start, end = line_range(method)
        sig = self._extract_ts_signature(method, source, name)
        node_id = make_node_id(file_path, NodeType.FUNCTION, name, start)

        structural = StructuralProperties(
            name=name,
            file=file_path,
            signature=sig,
            start_line=start,
            end_line=end,
            lines=end - start + 1,
        )

        node = GraphNode(
            id=node_id,
            type=NodeType.FUNCTION,
            file_path=file_path,
            structural=structural,
        )
        if not self._add_node(node, nodes, seen_ids):
            return

        edges.append(GraphEdge(source_id=parent_id, target_id=node_id, type=EdgeType.DEFINES))
        body = method.child_by_field_name("body")
        if body:
            self._extract_calls(body, source, file_path, node_id, nodes, edges)

    def _process_class(
        self,
        cls: ts.Node,
        source: bytes,
        file_path: str,
        lang: ts.Language,
        parent_id: str,
        nodes: list[GraphNode],
        edges: list[GraphEdge],
        errors: list[ParseError],
        seen_ids: set[str],
    ) -> None:
        name_node = cls.child_by_field_name("name")
        if not name_node:
            return
        name = node_text(name_node)
        start, end = line_range(cls)
        sig = f"class {name}"
        node_id = make_node_id(file_path, NodeType.CLASS, name, start)

        for child in cls.children:
            if child.type == "class_heritage":
                for heritage_child in child.children:
                    if heritage_child.type == "extends_clause":
                        for sub in heritage_child.children:
                            if sub.type in ("type_identifier", "identifier"):
                                base_name = node_text(sub)
                                sig += f" extends {base_name}"
                                base_id = make_node_id(file_path, NodeType.INTERFACE, base_name, 0)
                                edges.append(GraphEdge(source_id=node_id, target_id=base_id, type=EdgeType.IMPLEMENTS))

        structural = StructuralProperties(
            name=name,
            file=file_path,
            signature=sig,
            start_line=start,
            end_line=end,
            lines=end - start + 1,
        )

        node = GraphNode(
            id=node_id,
            type=NodeType.CLASS,
            file_path=file_path,
            structural=structural,
        )
        if not self._add_node(node, nodes, seen_ids):
            return

        edges.append(GraphEdge(source_id=parent_id, target_id=node_id, type=EdgeType.DEFINES))
        body = cls.child_by_field_name("body")
        if body:
            self._walk_block(
                body,
                source,
                file_path,
                lang,
                parent_id=node_id,
                class_name=name,
                nodes=nodes,
                edges=edges,
                errors=errors,
                seen_ids=seen_ids,
            )

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

        node = GraphNode(
            id=node_id,
            type=NodeType.INTERFACE,
            file_path=file_path,
            structural=structural,
        )
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
        module = node_text(source_node) if source_node else text

        node_id = make_node_id(file_path, NodeType.FILE, module, start)
        structural = StructuralProperties(
            name=module,
            file=file_path,
            signature=text,
            start_line=start,
            end_line=end,
            lines=end - start + 1,
        )

        node = GraphNode(
            id=node_id,
            type=NodeType.FILE,
            file_path=file_path,
            structural=structural,
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
        queries = _get_queries(self._language(file_path))
        cursor = ts.QueryCursor(queries["call"])
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

    def _extract_ts_signature(self, node: ts.Node, source: bytes, name: str) -> str:
        params_node = node.child_by_field_name("parameters")
        params_text = node_text(params_node) if params_node else "()"
        return_type = ""
        for child in node.children:
            if child.type == "type_annotation":
                return_type = node_text(child)
                break
        if node.type == "arrow_function":
            return f"({params_text}) => {return_type or '...'}"
        return f"{name}{params_text}{return_type}"
