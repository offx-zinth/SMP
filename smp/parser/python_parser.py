"""Python-specific tree-sitter parser.

Extracts functions, classes, methods, imports, decorators, inline comments,
and type annotations from Python source using the ``tree-sitter-python`` grammar.
"""

from __future__ import annotations

import re

import tree_sitter as ts
import tree_sitter_python as tsp

from smp.core.models import (
    Annotations,
    EdgeType,
    GraphEdge,
    GraphNode,
    NodeType,
    ParseError,
    SemanticProperties,
    StructuralProperties,
)
from smp.logging import get_logger
from smp.parser.base import TreeSitterParser, line_range, make_node_id, node_text

log = get_logger(__name__)

_LANGUAGE = ts.Language(tsp.language())

_CALL_QUERY = ts.Query(
    _LANGUAGE,
    """
(call function: (identifier) @callee) @call
(call function: (attribute) @callee) @call
""",
)

_COMMENT_QUERY = ts.Query(
    _LANGUAGE,
    """
(comment) @comment
""",
)


def _compute_complexity(body: ts.Node) -> int:
    """Estimate cyclomatic complexity from AST body node."""
    complexity = 1
    cursor = body.walk()
    stack: list[ts.Node] = [cursor.node] if cursor.node else []
    while stack:
        node = stack.pop()
        if node.type in (
            "if_statement",
            "elif_clause",
            "for_statement",
            "while_statement",
            "conditional_expression",
            "boolean_operator",
        ):
            complexity += 1
        for child in node.children:
            stack.append(child)
    return complexity


class PythonParser(TreeSitterParser):
    """Extract structural elements from Python source."""

    @property
    def supported_languages(self) -> list[str]:
        return ["python"]

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

        self._walk_block(
            root_node,
            source_bytes,
            file_path,
            parent_id=file_node.id,
            class_name=None,
            nodes=nodes,
            edges=edges,
            errors=errors,
            seen_ids=seen_ids,
        )
        log.debug("python_parsed", file=file_path, nodes=len(nodes), edges=len(edges), errors=len(errors))
        return nodes, edges, errors

    def _add_node(self, node: GraphNode, nodes: list[GraphNode], seen: set[str]) -> bool:
        """Add node if not already seen. Returns True if added."""
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
        parent_id: str,
        class_name: str | None,
        nodes: list[GraphNode],
        edges: list[GraphEdge],
        errors: list[ParseError],
        seen_ids: set[str],
    ) -> None:
        """Walk children of a block extracting definitions."""
        self._walk_direct_children(
            block,
            source,
            file_path,
            parent_id,
            class_name,
            nodes,
            edges,
            errors,
            seen_ids,
        )

    def _walk_direct_children(
        self,
        block: ts.Node,
        source: bytes,
        file_path: str,
        parent_id: str,
        class_name: str | None,
        nodes: list[GraphNode],
        edges: list[GraphEdge],
        errors: list[ParseError],
        seen_ids: set[str],
    ) -> None:
        """Walk direct children of a block, processing definitions."""
        for child in block.children:
            if child.type == "function_definition":
                self._process_function(
                    child,
                    source,
                    file_path,
                    parent_id,
                    class_name,
                    nodes,
                    edges,
                    errors,
                    seen_ids,
                    [],
                )
            elif child.type == "class_definition":
                self._process_class(
                    child,
                    source,
                    file_path,
                    parent_id,
                    nodes,
                    edges,
                    errors,
                    seen_ids,
                    [],
                )
            elif child.type == "decorated_definition":
                decorator_names = self._extract_decorators(child, source)
                for sub in child.children:
                    if sub.type == "function_definition":
                        self._process_function(
                            sub,
                            source,
                            file_path,
                            parent_id,
                            class_name,
                            nodes,
                            edges,
                            errors,
                            seen_ids,
                            decorator_names,
                        )
                        break
                    elif sub.type == "class_definition":
                        self._process_class(
                            sub,
                            source,
                            file_path,
                            parent_id,
                            nodes,
                            edges,
                            errors,
                            seen_ids,
                            decorator_names,
                        )
                        break
            elif child.type in ("import_statement", "import_from_statement"):
                self._process_import(child, source, file_path, parent_id, nodes, edges)
            elif child.type == "expression_statement":
                self._process_assignment(child, source, file_path, parent_id, nodes, edges)

    def _process_function(
        self,
        func: ts.Node,
        source: bytes,
        file_path: str,
        parent_id: str,
        class_name: str | None,
        nodes: list[GraphNode],
        edges: list[GraphEdge],
        errors: list[ParseError],
        seen_ids: set[str],
        decorator_names: list[str],
    ) -> None:
        name_node = func.child_by_field_name("name")
        if not name_node:
            return
        name = node_text(name_node)
        start, end = line_range(func)
        node_type = NodeType.FUNCTION if class_name is None else NodeType.FUNCTION
        sig = self._extract_signature(func, source, name)
        docstring = self._extract_docstring(func, source)
        annotations = self._extract_annotations(func, source)
        node_id = make_node_id(file_path, node_type, name, start)

        body = func.child_by_field_name("body")
        complexity = _compute_complexity(body) if body else 1
        lines = end - start + 1
        param_count = len(annotations.params) if annotations else 0

        structural = StructuralProperties(
            name=name,
            file=file_path,
            signature=sig,
            start_line=start,
            end_line=end,
            complexity=complexity,
            lines=lines,
            parameters=param_count,
        )

        semantic = SemanticProperties(
            docstring=docstring,
            decorators=decorator_names,
            annotations=annotations,
        )

        metadata: dict[str, str] = {}
        if class_name:
            metadata["class"] = class_name

        node = GraphNode(
            id=node_id,
            type=node_type,
            file_path=file_path,
            structural=structural,
            semantic=semantic,
        )
        if not self._add_node(node, nodes, seen_ids):
            return

        edges.append(GraphEdge(source_id=parent_id, target_id=node_id, type=EdgeType.DEFINES))

        if body:
            self._extract_calls(body, source, file_path, node_id, nodes, edges)

    def _process_class(
        self,
        cls: ts.Node,
        source: bytes,
        file_path: str,
        parent_id: str,
        nodes: list[GraphNode],
        edges: list[GraphEdge],
        errors: list[ParseError],
        seen_ids: set[str],
        decorator_names: list[str],
    ) -> None:
        name_node = cls.child_by_field_name("name")
        if not name_node:
            return
        name = node_text(name_node)
        start, end = line_range(cls)
        docstring = self._extract_docstring(cls, source)
        bases = self._extract_bases(cls, source)
        sig = f"class {name}"
        if bases:
            sig += f"({', '.join(bases)})"
        node_id = make_node_id(file_path, NodeType.CLASS, name, start)

        structural = StructuralProperties(
            name=name,
            file=file_path,
            signature=sig,
            start_line=start,
            end_line=end,
            lines=end - start + 1,
        )

        semantic = SemanticProperties(
            docstring=docstring,
            decorators=decorator_names,
        )

        node = GraphNode(
            id=node_id,
            type=NodeType.CLASS,
            file_path=file_path,
            structural=structural,
            semantic=semantic,
        )
        if not self._add_node(node, nodes, seen_ids):
            return

        edges.append(GraphEdge(source_id=parent_id, target_id=node_id, type=EdgeType.DEFINES))

        for base in bases:
            base_id = make_node_id(file_path, NodeType.INTERFACE, base, 0)
            edges.append(GraphEdge(source_id=node_id, target_id=base_id, type=EdgeType.IMPLEMENTS))

        body = cls.child_by_field_name("body")
        if body:
            self._walk_block(
                body,
                source,
                file_path,
                parent_id=node_id,
                class_name=name,
                nodes=nodes,
                edges=edges,
                errors=errors,
                seen_ids=seen_ids,
            )

    def _process_assignment(
        self,
        expr: ts.Node,
        source: bytes,
        file_path: str,
        parent_id: str,
        nodes: list[GraphNode],
        edges: list[GraphEdge],
    ) -> None:
        """Process top-level variable assignments."""
        for child in expr.children:
            if child.type in ("assignment", "type_alias_statement"):
                start, end = line_range(child)
                left = child.child_by_field_name("left") or child.child_by_field_name("name")
                if not left:
                    continue
                name = node_text(left)
                if not name or name.startswith("_"):
                    continue
                node_id = make_node_id(file_path, NodeType.VARIABLE, name, start)
                structural = StructuralProperties(
                    name=name,
                    file=file_path,
                    signature=node_text(child),
                    start_line=start,
                    end_line=end,
                    lines=end - start + 1,
                )
                node = GraphNode(
                    id=node_id,
                    type=NodeType.VARIABLE,
                    file_path=file_path,
                    structural=structural,
                )
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
        if imp.type == "import_from_statement":
            module_name_node = imp.child_by_field_name("module_name")
            module = node_text(module_name_node) if module_name_node else text
        else:
            module = text.replace("import ", "").split(",")[0].strip()

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
        cursor = ts.QueryCursor(_CALL_QUERY)
        seen_edges: set[tuple[str, str]] = set()
        for _, caps in cursor.matches(body):
            call_nodes = caps.get("call")
            callee_nodes = caps.get("callee")
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

    def _extract_decorators(self, decorated: ts.Node, source: bytes) -> list[str]:
        names: list[str] = []
        for child in decorated.children:
            if child.type == "decorator":
                text = node_text(child).lstrip("@").strip()
                if "(" in text:
                    text = text[: text.index("(")]
                names.append(text)
        return names

    def _extract_bases(self, cls: ts.Node, source: bytes) -> list[str]:
        bases: list[str] = []
        arg_list = cls.child_by_field_name("superclasses")
        if not arg_list:
            for child in cls.children:
                if child.type == "argument_list":
                    arg_list = child
                    break
        if arg_list:
            for child in arg_list.children:
                if child.type == "identifier":
                    bases.append(node_text(child))
        return bases

    def _extract_signature(self, func: ts.Node, source: bytes, name: str) -> str:
        params = func.child_by_field_name("parameters")
        param_text = node_text(params) if params else "()"
        return_type = ""
        for child in func.children:
            if child.type == "type":
                return_type = f" -> {node_text(child)}"
                break
        return f"def {name}{param_text}{return_type}"

    def _extract_annotations(self, func: ts.Node, source: bytes) -> Annotations:
        """Extract structured type annotations from a function."""
        params_dict: dict[str, str] = {}
        returns: str | None = None
        throws: list[str] = []

        params_node = func.child_by_field_name("parameters")
        if params_node:
            for child in params_node.children:
                if child.type == "identifier":
                    pname = node_text(child)
                    if pname in ("self", "cls"):
                        continue
                    params_dict[pname] = "Any"
                elif child.type == "typed_parameter":
                    # In tree-sitter-python, typed_parameter has 'identifier' and 'type' as direct children
                    ident = None
                    type_node = None
                    for sub in child.children:
                        if sub.type == "identifier":
                            ident = sub
                        elif sub.type == "type":
                            type_node = sub
                    pname = node_text(ident) if ident else ""
                    ptype = node_text(type_node) if type_node else "Any"
                    if pname and pname not in ("self", "cls"):
                        params_dict[pname] = ptype

        for child in func.children:
            if child.type == "type":
                returns = node_text(child)
                break

        body = func.child_by_field_name("body")
        if body:
            body_text = node_text(body)
            raise_matches = re.findall(r"raise\s+(\w+)", body_text)
            throws = list(dict.fromkeys(raise_matches))

        return Annotations(params=params_dict, returns=returns, throws=throws)

    def _extract_docstring(self, func_or_class: ts.Node, source: bytes) -> str:
        body = func_or_class.child_by_field_name("body")
        if not body:
            return ""
        for child in body.children:
            if child.type == "expression_statement":
                for sub in child.children:
                    if sub.type == "string":
                        text = node_text(sub)
                        for quote in ('"""', "'''", '"', "'"):
                            if text.startswith(quote) and text.endswith(quote):
                                text = text[len(quote) : -len(quote)]
                                break
                        return text.strip()
            else:
                break
        return ""
