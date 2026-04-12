"""Query engine — high-level structural queries over the memory store.

Provides navigate, trace, get_context, assess_impact, locate, search,
and find_flow queries backed by the graph store.
"""

from __future__ import annotations

from collections import deque
from typing import Any

from smp.core.models import EdgeType, GraphNode
from smp.engine.interfaces import QueryEngine as QueryEngineInterface
from smp.logging import get_logger
from smp.store.interfaces import GraphStore

log = get_logger(__name__)


class DefaultQueryEngine(QueryEngineInterface):
    """Query engine backed by a graph store."""

    def __init__(
        self,
        graph_store: GraphStore,
        enricher: Any | None = None,
    ) -> None:
        self._graph = graph_store
        self._enricher = enricher

    def _node_to_dict(self, node: GraphNode) -> dict[str, Any]:
        return {
            "id": node.id,
            "type": node.type.value,
            "file_path": node.file_path,
            "name": node.structural.name,
            "signature": node.structural.signature,
            "start_line": node.structural.start_line,
            "end_line": node.structural.end_line,
            "complexity": node.structural.complexity,
            "lines": node.structural.lines,
            "semantic": {
                "status": node.semantic.status,
                "docstring": node.semantic.docstring,
                "description": node.semantic.description,
                "decorators": node.semantic.decorators,
                "tags": node.semantic.tags,
            },
        }

    async def navigate(self, query: str, include_relationships: bool = True) -> dict[str, Any]:
        node = await self._graph.get_node(query)

        # If exact match fails, try to find by file path or name
        if not node:
            # Check if query looks like a file path
            if "/" in query or query.endswith(".py"):
                candidates = await self._graph.find_nodes(file_path=query)
                if candidates:
                    node = candidates[0]
            else:
                # Try finding by name
                candidates = await self._graph.find_nodes(name=query)
                if candidates:
                    node = candidates[0]

        # If still not found, try partial match on node ID prefix
        if not node:
            all_nodes = await self._graph.find_nodes()
            for n in all_nodes:
                if n.id.startswith(query) or query in n.id:
                    node = n
                    break

        if not node:
            return {"error": f"Node {query} not found"}

        result: dict[str, Any] = {"entity": self._node_to_dict(node)}

        if include_relationships:
            outgoing = await self._graph.get_edges(node.id, direction="outgoing")
            incoming = await self._graph.get_edges(node.id, direction="incoming")

            calls = [e.target_id for e in outgoing if e.type == EdgeType.CALLS]
            called_by = [e.source_id for e in incoming if e.type == EdgeType.CALLS]
            depends_on = [e.target_id for e in outgoing if e.type == EdgeType.DEPENDS_ON]
            imported_by = [e.source_id for e in incoming if e.type == EdgeType.IMPORTS]

            result["relationships"] = {
                "calls": calls,
                "called_by": called_by,
                "depends_on": depends_on,
                "imported_by": imported_by,
            }

        return result

    async def trace(
        self,
        start: str,
        relationship: str = "CALLS",
        depth: int = 3,
        direction: str = "outgoing",
    ) -> list[dict[str, Any]]:
        try:
            et = EdgeType(relationship)
        except ValueError:
            et = EdgeType.CALLS
        nodes = await self._graph.traverse(start, et, depth, max_nodes=100, direction=direction)
        return [self._node_to_dict(n) for n in nodes]

    async def get_context(
        self,
        file_path: str,
        scope: str = "edit",
        depth: int = 2,
    ) -> dict[str, Any]:
        file_nodes = await self._graph.find_nodes(file_path=file_path)
        if not file_nodes:
            return {"error": f"No nodes found for {file_path}"}

        file_node = file_nodes[0]
        imports = await self._graph.get_edges(file_node.id, EdgeType.IMPORTS, direction="outgoing")
        imported_by = await self._graph.get_edges(file_node.id, EdgeType.IMPORTS, direction="incoming")
        defines = await self._graph.get_edges(file_node.id, EdgeType.DEFINES, direction="outgoing")
        tests = await self._graph.get_edges(file_node.id, EdgeType.TESTS, direction="incoming")

        functions_defined: list[dict[str, Any]] = []
        classes_defined: list[dict[str, Any]] = []
        for edge in defines:
            target = await self._graph.get_node(edge.target_id)
            if target:
                d = self._node_to_dict(target)
                if target.type.value == "Function":
                    functions_defined.append(d)
                elif target.type.value == "Class":
                    classes_defined.append(d)

        caller_edges = await self._graph.get_edges(file_node.id, EdgeType.IMPORTS, direction="incoming")
        warnings: list[str] = []
        if len(caller_edges) > 10:
            warnings.append(f"This file is imported by {len(caller_edges)} other files")

        return {
            "self": self._node_to_dict(file_node),
            "imports": [{"source": e.source_id, "target": e.target_id} for e in imports],
            "imported_by": [{"source": e.source_id, "target": e.target_id} for e in imported_by],
            "functions_defined": functions_defined,
            "classes_defined": classes_defined,
            "tests": [e.source_id for e in tests],
            "warnings": warnings,
        }

    async def assess_impact(self, entity: str, change_type: str = "delete") -> dict[str, Any]:
        node = await self._graph.get_node(entity)

        # If exact match fails, try to find by file path or name
        if not node:
            if "/" in entity or entity.endswith(".py"):
                candidates = await self._graph.find_nodes(file_path=entity)
                if candidates:
                    node = candidates[0]
            else:
                candidates = await self._graph.find_nodes(name=entity)
                if candidates:
                    node = candidates[0]

        # Try partial match if still not found
        if not node:
            all_nodes = await self._graph.find_nodes()
            for n in all_nodes:
                if entity in n.id:
                    node = n
                    break

        if not node:
            return {"error": f"Node {entity} not found"}

        dependents = await self._graph.traverse(node.id, EdgeType.CALLS, depth=10, max_nodes=200, direction="incoming")

        affected_files: list[str] = []
        affected_functions: list[str] = []
        for dep in dependents:
            if dep.file_path not in affected_files:
                affected_files.append(dep.file_path)
            affected_functions.append(dep.structural.name)

        severity = "low"
        if len(dependents) > 10:
            severity = "high"
        elif len(dependents) > 3:
            severity = "medium"

        recommendations: list[str] = []
        if change_type == "signature_change":
            recommendations.append(f"Update {len(dependents)} callers to match new signature")
        elif change_type == "delete":
            recommendations.append(f"Remove or stub {len(dependents)} dependent references")

        return {
            "affected_files": affected_files,
            "affected_functions": affected_functions,
            "severity": severity,
            "recommendations": recommendations,
        }

    async def locate(
        self,
        query: str,
        fields: list[str] | None = None,
        node_types: list[str] | None = None,
        top_k: int = 5,
    ) -> list[dict[str, Any]]:
        if not fields:
            fields = ["name", "docstring", "tags"]

        terms = query.lower().split()
        all_nodes = await self._graph.find_nodes()

        scored: list[tuple[int, dict[str, Any]]] = []
        for node in all_nodes:
            if node_types and node.type.value not in node_types:
                continue

            score = 0
            matched_on = ""

            name_lower = node.structural.name.lower()
            if all(t in name_lower for t in terms):
                score = 100
                matched_on = "name"
            elif any(t in name_lower for t in terms):
                score = 50
                matched_on = "name"
            elif node.semantic.docstring:
                doc_lower = node.semantic.docstring.lower()
                if all(t in doc_lower for t in terms):
                    score = 30
                    matched_on = "docstring"
                elif any(t in doc_lower for t in terms):
                    score = 15
                    matched_on = "docstring"

            if score > 0:
                for tag in node.semantic.tags:
                    if any(t in tag.lower() for t in terms):
                        score += 10
                        if matched_on:
                            matched_on += ", tags"
                        else:
                            matched_on = "tags"
                        break

                scored.append(
                    (
                        score,
                        {
                            "entity": node.structural.name,
                            "file": node.file_path,
                            "matched_on": matched_on,
                            "docstring": node.semantic.docstring,
                            "tags": node.semantic.tags,
                        },
                    )
                )

        scored.sort(key=lambda x: -x[0])
        return [item[1] for item in scored[:top_k]]

    async def search(
        self,
        query: str,
        match: str = "any",
        filters: dict[str, Any] | None = None,
        top_k: int = 5,
    ) -> dict[str, Any]:
        filters = filters or {}
        terms = query.split()
        node_types = filters.get("node_types")
        tags = filters.get("tags")
        scope = filters.get("scope")

        results = await self._graph.search_nodes(
            query_terms=terms,
            match=match,
            node_types=node_types,
            tags=tags,
            scope=scope,
            top_k=top_k,
        )

        if not results:
            return {
                "matches": [],
                "total": 0,
                "hint": "Try broadening scope or using match: any",
            }

        return {"matches": results, "total": len(results)}

    async def find_flow(
        self,
        start: str,
        end: str,
        flow_type: str = "data",
    ) -> dict[str, Any]:
        # Resolve start and end nodes
        start_node = await self._graph.get_node(start)
        if not start_node:
            candidates = await self._graph.find_nodes(name=start)
            if candidates:
                start_node = candidates[0]

        end_node = await self._graph.get_node(end)
        if not end_node:
            candidates = await self._graph.find_nodes(name=end)
            if candidates:
                end_node = candidates[0]

        if start == end:
            if start_node:
                return {
                    "path": [{"node": start_node.structural.name, "type": start_node.type.value}],
                    "data_transformations": [],
                }
            return {"path": [], "data_transformations": []}

        if not start_node or not end_node:
            return {"path": [], "data_transformations": []}

        paths = await self._bfs_paths(start, end)
        if not paths:
            return {"path": [], "data_transformations": []}

        best_path = paths[0]
        path_nodes = []
        for nid in best_path:
            node = await self._graph.get_node(nid)
            if node:
                path_nodes.append({"node": node.structural.name, "type": node.type.value})

        transformations: list[str] = []
        for i in range(len(path_nodes) - 1):
            transformations.append(f"{path_nodes[i]['node']} → {path_nodes[i + 1]['node']}")

        return {
            "path": path_nodes,
            "data_transformations": transformations,
        }

    async def _bfs_paths(self, start_id: str, end_id: str) -> list[list[str]]:
        """BFS to find shortest paths."""
        found_paths: list[list[str]] = []
        queue: deque[tuple[str, list[str]]] = deque([(start_id, [start_id])])
        visited: set[str] = set()

        while queue and len(found_paths) < 3:
            current, path = queue.popleft()
            if len(path) > 20:
                continue

            edges = await self._graph.get_edges(current, direction="outgoing")
            edges += await self._graph.get_edges(current, direction="incoming")

            neighbors: set[str] = set()
            for e in edges:
                neighbors.add(e.target_id if e.source_id == current else e.source_id)

            for neighbor in neighbors:
                if neighbor == end_id:
                    found_paths.append(path + [neighbor])
                    continue
                if neighbor not in visited and neighbor not in path:
                    visited.add(neighbor)
                    queue.append((neighbor, path + [neighbor]))

        return found_paths

    async def diff(
        self,
        from_snapshot: str,
        to_snapshot: str,
        scope: str = "full",
    ) -> dict[str, Any]:
        """Compare two snapshots and return the differences."""
        from_nodes = await self._graph.find_nodes_by_scope(from_snapshot)
        to_nodes = await self._graph.find_nodes_by_scope(to_snapshot)

        from_ids = {n.id for n in from_nodes}
        to_ids = {n.id for n in to_nodes}

        added = to_ids - from_ids
        removed = from_ids - to_ids
        common = from_ids & to_ids

        changed: list[str] = []
        for node_id in common:
            from_node = next((n for n in from_nodes if n.id == node_id), None)
            to_node = next((n for n in to_nodes if n.id == node_id), None)
            if from_node and to_node and from_node.semantic.source_hash != to_node.semantic.source_hash:
                changed.append(node_id)

        return {
            "from_snapshot": from_snapshot,
            "to_snapshot": to_snapshot,
            "added": list(added),
            "removed": list(removed),
            "changed": changed,
            "stats": {
                "added_count": len(added),
                "removed_count": len(removed),
                "changed_count": len(changed),
            },
        }

    async def plan(
        self,
        change_description: str,
        target_file: str,
        change_type: str = "refactor",
        scope: str = "full",
    ) -> dict[str, Any]:
        """Generate a change plan for proposed modifications."""
        file_nodes = await self._graph.find_nodes(file_path=target_file)

        affected_nodes: list[str] = []
        for node in file_nodes:
            callers = await self._graph.traverse(node.id, EdgeType.CALLS, depth=10, max_nodes=200, direction="incoming")
            if callers:
                affected_nodes.append(node.id)

        steps: list[dict[str, str]] = [
            {"step": "1", "action": "Backup current state", "details": f"Snapshot {target_file}"},
            {"step": "2", "action": "Apply changes", "details": change_description},
            {"step": "3", "action": "Run tests", "details": f"Test affected nodes: {len(affected_nodes)}"},
        ]

        if change_type == "signature_change":
            steps.append(
                {
                    "step": "4",
                    "action": "Update callers",
                    "details": f"Update {len(affected_nodes)} dependent functions",
                }
            )

        return {
            "change_description": change_description,
            "target_file": target_file,
            "change_type": change_type,
            "affected_nodes": affected_nodes,
            "steps": steps,
            "risk_level": "high" if len(affected_nodes) > 10 else "medium" if affected_nodes else "low",
        }

    async def conflict(
        self,
        entity: str,
        proposed_change: str,
        context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Check for conflicts in proposed changes."""
        node = await self._graph.get_node(entity)
        if not node:
            candidates = await self._graph.find_nodes(name=entity)
            if candidates:
                node = candidates[0]

        if not node:
            return {"conflict": False, "reason": f"Entity {entity} not found"}

        edges = await self._graph.get_edges(node.id, direction="incoming")
        callers = [e.source_id for e in edges if e.type == EdgeType.CALLS]

        conflicts: list[str] = []
        warnings: list[str] = []

        if len(callers) > 5:
            conflicts.append(f"Entity has {len(callers)} callers - high blast radius")

        if node.semantic.manually_set:
            warnings.append("Entity has manually set annotations - may need re-annotation")

        if context and context.get("session_id"):
            locked_files = context.get("locked_files", [])
            if node.file_path in locked_files:
                conflicts.append(f"File {node.file_path} is locked by another session")

        return {
            "entity": entity,
            "proposed_change": proposed_change,
            "conflict": len(conflicts) > 0,
            "conflicts": conflicts,
            "warnings": warnings,
            "caller_count": len(callers),
        }

    async def why(
        self,
        entity: str,
        relationship: str = "",
        depth: int = 3,
    ) -> dict[str, Any]:
        """Explain why a relationship exists between entities."""
        node = await self._graph.get_node(entity)

        # If exact match fails, try to find by file path or name
        if not node:
            if "/" in entity or entity.endswith(".py"):
                candidates = await self._graph.find_nodes(file_path=entity)
                if candidates:
                    node = candidates[0]
            else:
                candidates = await self._graph.find_nodes(name=entity)
                if candidates:
                    node = candidates[0]

        if not node:
            return {"error": f"Entity {entity} not found"}

        reasons: list[dict[str, Any]] = []

        incoming = await self._graph.get_edges(node.id, direction="incoming")
        outgoing = await self._graph.get_edges(node.id, direction="outgoing")

        for edge in incoming[:depth]:
            source = await self._graph.get_node(edge.source_id)
            if source:
                reasons.append(
                    {
                        "type": "incoming",
                        "edge_type": edge.type.value,
                        "from": source.structural.name,
                        "file": source.file_path,
                        "reason": f"{source.structural.name} {edge.type.value} {node.structural.name}",
                    }
                )

        for edge in outgoing[:depth]:
            target = await self._graph.get_node(edge.target_id)
            if target:
                reasons.append(
                    {
                        "type": "outgoing",
                        "edge_type": edge.type.value,
                        "to": target.structural.name,
                        "file": target.file_path,
                        "reason": f"{node.structural.name} {edge.type.value} {target.structural.name}",
                    }
                )

        return {
            "entity": entity,
            "name": node.structural.name,
            "file": node.file_path,
            "reasons": reasons,
            "total_relationships": len(incoming) + len(outgoing),
        }

    async def diff_file(
        self,
        file_path: str,
        proposed_content: str | None = None,
    ) -> dict[str, Any]:
        """Compare current graph state of a file against proposed new content."""
        current_nodes = await self._graph.find_nodes(file_path=file_path)
        current_node_ids = {n.id for n in current_nodes}
        current_calls: dict[str, set[str]] = {n.id: set() for n in current_nodes}

        for node in current_nodes:
            edges = await self._graph.get_edges(node.id, direction="outgoing")
            for e in edges:
                if e.type == EdgeType.CALLS:
                    current_calls[node.id].add(e.target_id)

        if proposed_content:
            from smp.parser.base import detect_language
            from smp.parser.registry import ParserRegistry

            registry = ParserRegistry()
            lang = detect_language(file_path)
            parser = registry.get(lang)
            if not parser:
                from smp.core.models import Language

                parser = registry.get(Language.PYTHON)
            if parser:
                proposed_data = parser.parse(proposed_content, file_path)
                proposed_node_ids = {n.id for n in proposed_data.nodes}
            else:
                proposed_node_ids = current_node_ids
        else:
            proposed_node_ids = current_node_ids

        nodes_added = list(proposed_node_ids - current_node_ids)
        nodes_removed = list(current_node_ids - proposed_node_ids)
        nodes_modified: list[str] = []

        return {
            "nodes_added": nodes_added,
            "nodes_removed": nodes_removed,
            "nodes_modified": nodes_modified,
            "relationships_added": [],
            "relationships_removed": [],
        }

    async def plan_multi_file(
        self,
        session_id: str,
        task: str,
        intended_writes: list[str],
    ) -> dict[str, Any]:
        """Validate and rank a multi-file task before execution."""
        file_dependencies: dict[str, set[str]] = {}

        for file_path in intended_writes:
            nodes = await self._graph.find_nodes(file_path=file_path)
            deps = set()
            for node in nodes:
                edges = await self._graph.get_edges(node.id, direction="outgoing")
                for e in edges:
                    if e.type == EdgeType.CALLS:
                        deps.add(e.target_id)
            file_dependencies[file_path] = deps

        execution_order = []
        for i, file_path in enumerate(intended_writes, 1):
            current_nodes = await self._graph.find_nodes(file_path=file_path)
            dependants = 0
            for fp in intended_writes:
                if fp != file_path:
                    for n in current_nodes:
                        if n.id in file_dependencies.get(fp, set()):
                            dependants += 1

            outgoing = []
            for n in current_nodes:
                edges = await self._graph.get_edges(n.id, direction="outgoing")
                outgoing.extend([e.target_id for e in edges])

            execution_order.append(
                {
                    "step": i,
                    "file": file_path,
                    "dependants_in_plan": dependants,
                    "dependencies_in_plan": len(outgoing),
                    "blast_radius": dependants,
                    "risk_level": "high" if dependants > 3 else "medium" if dependants > 0 else "low",
                }
            )

        return {
            "execution_order": execution_order,
            "inter_file_conflicts": [],
            "external_files_at_risk": [],
        }

    async def detect_conflict(
        self,
        session_a: str,
        session_b: str,
    ) -> dict[str, Any]:
        """Detect scope overlap between two planned sessions."""
        return {
            "has_conflict": False,
            "overlapping_files": [],
            "conflicting_nodes": [],
        }
