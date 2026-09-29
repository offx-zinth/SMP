"""Query engine — high-level structural queries over the memory store.

Provides navigate, trace, get_context, assess_impact, locate, search,
and find_flow queries backed by the graph store.
"""

from __future__ import annotations

from collections import deque
from typing import Any

from smp.core.models import EdgeType, GraphNode, NodeType
from smp.engine.bm25 import FIELD_WEIGHTS as _BM25_WEIGHTS
from smp.logging import get_logger
from smp.store.graph.parser import CodeParser
from smp.store.interfaces import GraphStore, VectorStore

log = get_logger(__name__)
_HTTP_VERB_DECORATORS = {"get", "post", "put", "delete", "patch", "head", "options"}

_UTILITY_PATH_SEGMENTS = {"/utils", "/lib", "/shared", "/helpers"}

_LIVE_SNAPSHOTS = frozenset({"", "live", "current"})

_DIFF_ID_CAP = 5000


def _in_scope(file_path: str, scope: str) -> bool:
    """Check whether *file_path* falls under a diff scope prefix."""
    return not scope or scope == "full" or file_path.startswith(scope)


def _cap_ids(items: list[str], limit: int = _DIFF_ID_CAP) -> tuple[list[str], bool]:
    """Truncate an id list, reporting whether anything was cut."""
    if len(items) <= limit:
        return items, False
    return items[:limit], True


class DefaultQueryEngine:
    """Query engine backed by a graph store."""

    def __init__(
        self,
        graph_store: GraphStore,
        vector_store: VectorStore | None = None,
        enricher: Any | None = None,
    ) -> None:
        self._graph = graph_store
        self._vector_store = vector_store
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
            "snippet": self._read_snippet(node.file_path, node.structural.start_line, node.structural.end_line),
            "semantic": {
                "status": node.semantic.status,
                "docstring": node.semantic.docstring,
                "description": node.semantic.description,
                "decorators": node.semantic.decorators,
                "tags": node.semantic.tags,
            },
        }

    @staticmethod
    def _read_snippet(file_path: str, start_line: int, end_line: int, max_lines: int = 25) -> str:
        """Best-effort source excerpt so agents need not re-read the file."""
        try:
            if not start_line or not end_line:
                return ""
            from pathlib import Path

            text = Path(file_path).read_text(encoding="utf-8", errors="replace").splitlines()
            lo = max(0, start_line - 1)
            hi = min(len(text), end_line, lo + max_lines)
            return "\n".join(text[lo:hi])
        except (OSError, ValueError):
            return ""

    async def navigate(self, query: str, include_relationships: bool = True) -> dict[str, Any]:
        node = await self._graph.get_node(query)

        # If exact match fails, try to find by file path or name
        if not node:
            # Check if query looks like a file path
            import os

            if "/" in query or query.endswith(".py"):
                candidates = await self._graph.find_nodes(file_path=query)
                if candidates:
                    node = candidates[0]
                else:
                    abs_path = os.path.abspath(query)
                    if abs_path != query:
                        candidates = await self._graph.find_nodes(file_path=abs_path)
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

        # BM25 fallback for multi-term queries ("MMapGraphStore upsert").
        if not node and " " in query:
            hits = await self.locate(query, top_k=1)
            if hits:
                node = await self._graph.get_node(hits[0]["id"])

        if not node:
            return {
                "error": f"Node {query} not found",
                "hint": "Try smp/locate or smp/search_code for multi-term queries",
            }

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
        *,
        include_tests: bool = True,
        risk_labels: bool = False,
        include_evidence: bool = False,
        max_nodes: int = 100,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        try:
            et = EdgeType(relationship)
        except ValueError:
            et = EdgeType.CALLS
        # Normalise codebase-memory aliases.
        aliases = {"inbound": "incoming", "outbound": "outgoing", "in": "incoming", "out": "outgoing"}
        norm_direction = aliases.get(direction, direction)
        if norm_direction not in ("incoming", "outgoing", "both"):
            norm_direction = "outgoing"
        start_id = await self._resolve_node_id(start)
        if start_id is None:
            return []
        nodes = await self._graph.traverse(start_id, et, depth, max_nodes=max_nodes, direction=norm_direction)
        filtered: list[GraphNode] = []
        for n in nodes:
            if not include_tests and self._is_test_node(n):
                continue
            filtered.append(n)
        page = filtered[offset : offset + max_nodes] if max_nodes > 0 else filtered[offset:]
        result: list[dict[str, Any]] = []
        for hop, n in enumerate(page):
            payload = self._node_to_dict(n)
            if include_evidence or risk_labels:
                try:
                    outs = await self._graph.get_edges(n.id, direction="outgoing")
                    ins = await self._graph.get_edges(n.id, direction="incoming")
                except (NotImplementedError, AttributeError):
                    outs, ins = [], []
                fan_out, fan_in = len(outs), len(ins)
                risk = "low"
                if fan_in > 10 or n.structural.complexity > 8:
                    risk = "high"
                elif fan_in > 3 or n.structural.complexity > 4:
                    risk = "medium"
                payload["hop"] = hop
                payload["fan_in"] = fan_in
                payload["fan_out"] = fan_out
                payload["risk"] = risk
                payload["is_test"] = self._is_test_node(n)
                if include_evidence:
                    payload["evidence"] = {
                        "edge_type": et.value,
                        "direction": norm_direction,
                        "depth": depth,
                        "via": start_id,
                    }
            result.append(payload)
        return result

    @staticmethod
    def _is_test_node(node: GraphNode) -> bool:
        """Heuristic test-node detection (mirrors codebase-memory include_tests=false)."""
        if node.type.value.lower() == "test":
            return True
        path = (node.file_path or "").replace("\\", "/").lower()
        segments = set(path.split("/"))
        if segments & {"test", "tests", "spec", "__tests__"}:
            return True
        name = (node.structural.name or "").lower()
        return name.startswith("test_") or name.endswith("_test")

    async def _resolve_node_id(self, query: str) -> str | None:
        """Resolve a node id, exact file path, structural name, or id fragment to a node id.

        Improved resolution strategy:
        1. Exact match by full node ID
        2. Exact match by name with preference for most connected node
        3. Deterministic file path ordering as tiebreaker
        4. File path match
        5. Partial ID match
        """
        if await self._graph.get_node(query) is not None:
            return query

        # Find all nodes with matching name
        candidates = await self._graph.find_nodes(name=query)
        if candidates:
            # If multiple candidates, prefer the one with most connections (edges),
            # then use deterministic file path ordering as tiebreaker
            if len(candidates) > 1:
                best_candidate = candidates[0]
                best_count = -1
                for candidate in sorted(candidates, key=lambda n: n.file_path):
                    outgoing = await self._graph.get_edges(candidate.id, direction="outgoing")
                    incoming = await self._graph.get_edges(candidate.id, direction="incoming")
                    count = len(outgoing) + len(incoming)
                    if count > best_count:
                        best_count = count
                        best_candidate = candidate
                return best_candidate.id
            return candidates[0].id

        if "/" in query:
            candidates = await self._graph.find_nodes(file_path=query)
            if candidates:
                return candidates[0].id

        for node in await self._graph.find_nodes():
            if node.id.startswith(query) or query in node.id:
                return node.id
        return None

    async def get_context(
        self,
        file_path: str,
        scope: str = "edit",
        depth: int = 2,
    ) -> dict[str, Any]:
        # Normalize file path for matching - try both as-is and with cwd prefix
        import os

        file_nodes = await self._graph.find_nodes(file_path=file_path)
        if not file_nodes:
            # Try absolute path
            abs_path = os.path.abspath(file_path)
            if abs_path != file_path:
                file_nodes = await self._graph.find_nodes(file_path=abs_path)
        if not file_nodes:
            # Try substring match
            all_nodes = await self._graph.find_nodes()
            file_nodes = [
                n for n in all_nodes if file_path in n.file_path or os.path.basename(file_path) in n.file_path
            ]
        if not file_nodes:
            return {"error": f"No nodes found for {file_path}"}

        file_node = file_nodes[0]
        file_id = file_node.id

        imports = await self._graph.get_edges(file_id, EdgeType.IMPORTS, direction="outgoing")
        imported_by = await self._graph.get_edges(file_id, EdgeType.IMPORTS, direction="incoming")
        defines = await self._graph.get_edges(file_id, EdgeType.DEFINES, direction="outgoing")
        tests_edges = await self._graph.get_edges(file_id, EdgeType.TESTS, direction="incoming")

        defines_nodes: list[dict[str, Any]] = []
        complexities: list[int] = []
        exported_symbols: list[str] = []
        http_decorators: list[str] = []
        test_file_paths: list[str] = []

        for edge in defines:
            target = await self._graph.get_node(edge.target_id)
            if target:
                defines_nodes.append(self._node_to_dict(target))
                complexities.append(target.structural.complexity)
                exported_symbols.append(target.structural.name)
                for dec in target.semantic.decorators:
                    dec_lower = dec.lstrip("@").lower()
                    if dec_lower in _HTTP_VERB_DECORATORS:
                        http_decorators.append(dec)

        for te in tests_edges:
            source = await self._graph.get_node(te.source_id)
            if source and source.file_path not in test_file_paths:
                test_file_paths.append(source.file_path)

        if not defines_nodes:
            # No DEFINES edges (parsers only emit them for some languages):
            # fall back to the file's own symbol nodes so defines stay useful.
            for sibling in file_nodes[:100]:
                defines_nodes.append(self._node_to_dict(sibling))
                complexities.append(sibling.structural.complexity)
                exported_symbols.append(sibling.structural.name)

        has_tests = len(test_file_paths) > 0

        related_patterns: list[dict[str, Any]] = []
        all_nodes = await self._graph.find_nodes()
        for candidate in all_nodes:
            if candidate.id == file_id or candidate.file_path == file_path:
                continue
            if candidate.type == file_node.type:
                name_sim = self._name_similarity(file_node.structural.name, candidate.structural.name)
                if name_sim > 0.5:
                    related_patterns.append(
                        {
                            "file_path": candidate.file_path,
                            "name": candidate.structural.name,
                            "similarity": round(name_sim, 2),
                        }
                    )
        related_patterns.sort(key=lambda x: -x["similarity"])
        related_patterns = related_patterns[:5]

        entry_points: list[dict[str, Any]] = []
        if http_decorators:
            for edge in defines:
                target = await self._graph.get_node(edge.target_id)
                if target:
                    target_http = [
                        d for d in target.semantic.decorators if d.lstrip("@").lower() in _HTTP_VERB_DECORATORS
                    ]
                    if target_http:
                        entry_points.append(
                            {
                                "name": target.structural.name,
                                "decorators": target_http,
                                "file_path": target.file_path,
                            }
                        )

        data_flow_in: list[dict[str, Any]] = []
        data_flow_out: list[dict[str, Any]] = []
        seen_in: set[str] = set()
        seen_out: set[str] = set()
        # CALLS edges live between functions, not file nodes: aggregate from
        # each defined symbol so data_flow is non-empty in real codebases.
        # Note: many parsers emit no DEFINES edges, in which case
        # defines_nodes holds the file's own symbol nodes as fallback.
        symbol_ids = [edge.target_id for edge in defines] or [d["id"] for d in defines_nodes[:100]]
        for symbol_id in symbol_ids:
            for caller in await self._graph.traverse(
                symbol_id, EdgeType.CALLS, depth=depth, max_nodes=50, direction="incoming"
            ):
                if caller.id not in seen_in:
                    seen_in.add(caller.id)
                    data_flow_in.append(
                        {
                            "node_id": caller.id,
                            "name": caller.structural.name,
                            "file_path": caller.file_path,
                        }
                    )
            for callee in await self._graph.traverse(
                symbol_id, EdgeType.CALLS, depth=depth, max_nodes=50, direction="outgoing"
            ):
                if callee.id not in seen_out:
                    seen_out.add(callee.id)
                    data_flow_out.append(
                        {
                            "node_id": callee.id,
                            "name": callee.structural.name,
                            "file_path": callee.file_path,
                        }
                    )

        role = self._classify_role(file_node, imported_by, defines_nodes, http_decorators)
        avg_complexity = round(sum(complexities) / max(len(complexities), 1), 1)
        max_complexity = max(complexities, default=0)
        # Blast radius: distinct files that import this file OR call into its
        # defined symbols from another file. IMPORTS-only counts miss the
        # common single-package case (no cross-file imports, plenty of calls).
        caller_files: set[str] = set()
        for edge in imported_by:
            source = await self._graph.get_node(edge.source_id)
            if source:
                caller_files.add(source.file_path)
        for symbol_id in symbol_ids:
            call_edges = await self._graph.get_edges(symbol_id, EdgeType.CALLS, direction="incoming")
            for ce in call_edges:
                other = await self._graph.get_node(ce.source_id)
                if other and other.file_path != file_node.file_path:
                    caller_files.add(other.file_path)
        # Same-file callers still matter for edit risk: count them separately.
        same_file_callers = len(data_flow_in)
        blast_radius = len(caller_files)
        blast_radius_total = blast_radius + (1 if same_file_callers else 0)

        imported_by_api = 0
        for edge in imported_by:
            source = await self._graph.get_node(edge.source_id)
            if source and "/api" in source.file_path:
                imported_by_api += 1

        is_hot_node = blast_radius > 10 or max_complexity > 8
        heat_score = blast_radius + max_complexity

        risk_basis = max(blast_radius, 1 if same_file_callers > 5 else 0)
        if risk_basis > 10 or avg_complexity > 8:
            risk_level = "high"
        elif risk_basis > 3 or avg_complexity > 4 or same_file_callers > 5:
            risk_level = "medium"
        else:
            risk_level = "low"

        summary = {
            "role": role,
            "blast_radius": blast_radius,
            "blast_radius_total": blast_radius_total,
            "same_file_callers": same_file_callers,
            "api_layer_callers": imported_by_api,
            "avg_complexity": avg_complexity,
            "max_complexity": max_complexity,
            "exported_symbols": exported_symbols,
            "has_tests": has_tests,
            "test_files": test_file_paths,
            "is_hot_node": is_hot_node,
            "heat_score": heat_score,
            "risk_level": risk_level,
        }

        return {
            "self": self._node_to_dict(file_node),
            "imports": [{"source": e.source_id, "target": e.target_id} for e in imports],
            "imported_by": [{"source": e.source_id, "target": e.target_id} for e in imported_by],
            "defines": defines_nodes,
            "functions_defined": defines_nodes,
            "related_patterns": related_patterns,
            "entry_points": entry_points,
            "data_flow_in": data_flow_in,
            "data_flow_out": data_flow_out,
            "summary": summary,
        }

    @staticmethod
    def _name_similarity(name_a: str, name_b: str) -> float:
        if not name_a or not name_b:
            return 0.0
        set_a = set(name_a.lower())
        set_b = set(name_b.lower())
        if not set_a or not set_b:
            return 0.0
        intersection = set_a & set_b
        union = set_a | set_b
        return len(intersection) / len(union)

    def _classify_role(
        self,
        file_node: GraphNode,
        imported_by: list[Any],
        defines_nodes: list[dict[str, Any]],
        http_decorators: list[str],
    ) -> str:
        path = file_node.file_path
        # Match whole path segments so /test_realworld is not a test dir.
        segments = {seg.lower() for seg in path.replace("\\", "/").split("/") if seg}
        test_markers = {"test", "tests", "spec", "__tests__"}
        if segments & test_markers or path.lower().endswith(("_test.py", ".test.ts", ".spec.ts")):
            return "test"
        if file_node.type == NodeType.CONFIG:
            return "config"
        if http_decorators:
            return "endpoint"
        if segments & {"routes", "controllers", "api", "handlers"}:
            return "endpoint"
        incoming_imports = len(imported_by)
        if segments & {"services", "service", "src", "core", "domain"} and defines_nodes:
            return "service"
        if incoming_imports > 5 and any(seg in path for seg in _UTILITY_PATH_SEGMENTS):
            return "core_utility"
        if incoming_imports == 0 and not defines_nodes:
            return "isolated"
        return "module"

    async def assess_impact(self, entity: str, change_type: str = "delete") -> dict[str, Any]:
        # Parse entity format: file_path:type:name (e.g., "api.py:fn:process")
        target_name = entity
        target_file = None
        if ":" in entity:
            parts = entity.rsplit(":", 2)
            if len(parts) == 3:
                target_file, _, target_name = parts
            elif len(parts) == 2:
                target_name = parts[1] if parts[0] in ("fn", "func", "function", "class", "struct", "file") else entity

        node = None

        # First try exact match
        node = await self._graph.get_node(entity)

        # If exact match fails, try to find by parsed file path or name
        if not node:
            if target_file:
                candidates = await self._graph.find_nodes(file_path=target_file)
                for c in candidates:
                    if c.structural and c.structural.name == target_name:
                        node = c
                        break
            if not node:
                candidates = await self._graph.find_nodes(name=target_name)
                if candidates:
                    # Filter by file if we have target_file
                    if target_file:
                        for c in candidates:
                            if c.file_path and target_file in c.file_path:
                                node = c
                                break
                    if not node and candidates:
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

        impact_edge_types = [EdgeType.CALLS, EdgeType.IMPORTS, EdgeType.DEFINES]
        dependents = await self._graph.traverse(
            node.id, impact_edge_types, depth=10, max_nodes=200, direction="incoming"
        )

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
            "impacted_nodes": affected_functions,
            "severity": severity,
            "recommendations": recommendations,
        }

    async def locate(
        self,
        query: str,
        fields: list[str] | None = None,
        node_types: list[str] | None = None,
        top_k: int = 5,
        offset: int = 0,
        match: str = "any",
    ) -> list[dict[str, Any]]:
        from smp.engine.bm25 import build_corpus, score_node, tokenize_query

        if not fields:
            fields = ["name", "docstring", "tags"]

        all_nodes = await self._graph.find_nodes()
        candidates = [n for n in all_nodes if not node_types or n.type.value in node_types]
        terms = tokenize_query(query) or [t.lower() for t in query.split() if t]
        if not terms or not candidates:
            return []

        doc_fields, idf, avgdl = build_corpus(candidates)
        scored: list[tuple[float, dict[str, Any]]] = []
        for node, fmap in zip(candidates, doc_fields, strict=True):
            # Restrict to requested fields when possible.
            hay_tokens: set[str] = set()
            use_fields = {k: v for k, v in fmap.items() if k in set(fields) | {"name", "id", "file_path"}}
            for toks in use_fields.values():
                hay_tokens.update(toks)
            present = [t for t in terms if t in hay_tokens or any(t in h for h in hay_tokens)]
            if match == "all" and len(present) < len(terms):
                continue
            if not present:
                continue
            length = sum(len(toks) * _BM25_WEIGHTS.get(f, 1.0) for f, toks in fmap.items()) or 1.0
            score, matched_on = score_node(terms, fmap, idf, avgdl, length)
            raw = query.lower()
            if raw == node.structural.name.lower():
                score += 100.0
                matched_on = "name (exact)"
            if score > 0:
                scored.append(
                    (
                        score,
                        {
                            "entity": node.structural.name,
                            "id": node.id,
                            "file": node.file_path,
                            "file_path": node.file_path,
                            "type": node.type.value,
                            "matched_on": matched_on or "name",
                            "docstring": node.semantic.docstring,
                            "tags": list(node.semantic.tags),
                            "signature": node.structural.signature,
                            "start_line": node.structural.start_line,
                            "end_line": node.structural.end_line,
                            "lines": node.structural.lines,
                            "score": round(score, 2),
                        },
                    )
                )

        scored.sort(key=lambda x: -x[0])
        page = scored[offset : offset + top_k] if top_k > 0 else scored[offset:]
        return [item[1] for item in page]

    async def locate_paged(
        self,
        query: str,
        fields: list[str] | None = None,
        node_types: list[str] | None = None,
        top_k: int = 10,
        offset: int = 0,
        match: str = "any",
    ) -> dict[str, Any]:
        """Locate with pagination metadata (codebase-memory parity)."""
        from smp.engine.bm25 import count_matches

        all_nodes = await self._graph.find_nodes()
        candidates = [n for n in all_nodes if not node_types or n.type.value in node_types]
        total = count_matches(query, candidates, match=match)
        matches = await self.locate(query, fields, node_types, top_k, offset, match)
        has_more = offset + len(matches) < total
        return {
            "matches": matches,
            "total": total,
            "returned": len(matches),
            "offset": offset,
            "has_more": has_more,
            "next_offset": offset + len(matches) if has_more else None,
        }

    async def search(
        self,
        query: str,
        match: str = "any",
        filters: dict[str, Any] | None = None,
        top_k: int = 5,
        offset: int = 0,
    ) -> dict[str, Any]:
        from smp.engine.bm25 import count_matches

        filters = filters or {}
        terms = query.split()
        node_types = filters.get("node_types")
        tags = filters.get("tags")
        scope = filters.get("scope")

        # Total before slicing: run once without pagination.
        all_nodes = await self._graph.find_nodes()
        pre: list[Any] = []
        for n in all_nodes:
            if node_types and n.type.value not in node_types:
                continue
            if tags and not any(tag in n.semantic.tags for tag in tags):
                continue
            if (
                scope
                and scope not in ("full", "full/")
                and not (n.id.startswith(scope) or n.file_path.startswith(scope))
            ):
                continue
            pre.append(n)
        total = count_matches(query, pre, match=match)

        results = await self._graph.search_nodes(
            query_terms=terms,
            match=match,
            node_types=node_types,
            tags=tags,
            scope=scope,
            top_k=top_k,
            offset=offset,
        )

        if not results:
            return {
                "matches": [],
                "total": 0,
                "returned": 0,
                "offset": offset,
                "has_more": False,
                "next_offset": None,
                "hint": "Try broadening scope or using match: any",
            }

        has_more = offset + len(results) < total
        return {
            "matches": results,
            "total": total,
            "returned": len(results),
            "offset": offset,
            "has_more": has_more,
            "next_offset": offset + len(results) if has_more else None,
        }

    async def search_code(
        self,
        query: str,
        mode: str = "compact",
        top_k: int = 10,
        offset: int = 0,
        match: str = "any",
        node_types: list[str] | None = None,
    ) -> dict[str, Any]:
        """Codebase-memory ``search_code`` parity: compact / full / files modes.

        * ``compact`` — symbols with file + lines (default, ~500 tokens).
        * ``full`` — compact plus bounded source snippets.
        * ``files`` — de-duplicated file paths only.
        """
        paged = await self.locate_paged(query, node_types=node_types, top_k=top_k, offset=offset, match=match)
        matches = paged["matches"]
        if mode == "files":
            seen: list[str] = []
            for m in matches:
                fp = m.get("file_path") or m.get("file", "")
                if fp and fp not in seen:
                    seen.append(fp)
            return {**paged, "mode": mode, "files": seen}
        if mode == "full":
            enriched: list[dict[str, Any]] = []
            for m in matches:
                node_id = m.get("id", "")
                node = await self._graph.get_node(node_id) if node_id else None
                snippet = ""
                if node is not None:
                    snippet = self._read_snippet(
                        node.file_path, node.structural.start_line, node.structural.end_line, max_lines=40
                    )
                enriched.append({**m, "snippet": snippet})
            return {**paged, "mode": mode, "matches": enriched}
        return {**paged, "mode": "compact"}

    async def file_outline(self, file_path: str, limit: int = 200, offset: int = 0) -> dict[str, Any]:
        """Declaration outline for one file (codebase-memory ``get_file_outline`` parity)."""
        import os

        nodes = await self._graph.find_nodes(file_path=file_path)
        if not nodes:
            abs_path = os.path.abspath(file_path)
            if abs_path != file_path:
                nodes = await self._graph.find_nodes(file_path=abs_path)
        if not nodes:
            all_nodes = await self._graph.find_nodes()
            base = os.path.basename(file_path)
            nodes = [n for n in all_nodes if n.file_path.endswith(base) or base in n.file_path]
        nodes.sort(key=lambda n: (n.structural.start_line, n.id))
        total = len(nodes)
        page = nodes[offset : offset + limit] if limit > 0 else nodes[offset:]
        outline = [
            {
                "id": n.id,
                "name": n.structural.name,
                "type": n.type.value,
                "file_path": n.file_path,
                "start_line": n.structural.start_line,
                "end_line": n.structural.end_line,
                "signature": n.structural.signature,
                "complexity": n.structural.complexity,
                "docstring": (n.semantic.docstring or "")[:200],
            }
            for n in page
        ]
        return {
            "file_path": file_path,
            "total": total,
            "returned": len(outline),
            "offset": offset,
            "has_more": offset + len(outline) < total,
            "outline": outline,
        }

    async def index_coverage(self, scope: str = "full") -> dict[str, Any]:
        """Best-effort coverage signal (codebase-memory ``check_index_coverage`` parity)."""
        if scope and scope != "full":
            nodes = await self._graph.find_nodes_by_scope(scope)
            if not nodes:
                # Absolute paths defeat prefix match: fall back to substring.
                all_nodes = await self._graph.find_nodes()
                nodes = [n for n in all_nodes if scope in n.file_path or scope in n.id]
        else:
            nodes = await self._graph.find_nodes()
        files: dict[str, int] = {}
        missing_lines = 0
        for n in nodes:
            files[n.file_path] = files.get(n.file_path, 0) + 1
            if not n.structural.start_line or not n.structural.end_line:
                missing_lines += 1
        return {
            "scope": scope,
            "nodes": len(nodes),
            "files": len(files),
            "files_indexed": sorted(files)[:100],
            "nodes_missing_lines": missing_lines,
            "coverage_note": (
                "Best-effort signal, not a completeness guarantee: files absent here "
                "may still be unindexed (gitignored, binary, or parse-skipped). "
                "Prefer text search for flagged ranges."
            ),
        }

    async def dead_code(self, top_k: int = 50, exclude_entry_points: bool = True) -> dict[str, Any]:
        """Zero-degree symbols (codebase-memory ``max_degree=0`` parity)."""
        nodes = await self._graph.find_nodes()
        dead: list[dict[str, Any]] = []
        for n in nodes:
            if exclude_entry_points and not self._is_test_node(n):
                # Entry points: mains, inits, dunders, exported handlers.
                lname = (n.structural.name or "").lower()
                if lname in {"main", "__main__", "__init__"} or lname.startswith("test_"):
                    continue
            try:
                outs = await self._graph.get_edges(n.id, direction="outgoing")
                ins = await self._graph.get_edges(n.id, direction="incoming")
            except (NotImplementedError, AttributeError):
                continue
            if not outs and not ins and n.type.value in ("Function", "Class"):
                dead.append(self._node_to_dict(n))
            if len(dead) >= top_k:
                break
        return {"total": len(dead), "nodes": dead}

    async def semantic_search(
        self,
        query: str,
        top_k: int = 5,
        where: dict[str, Any] | None = None,
        instruction: str | None = None,
    ) -> dict[str, Any]:
        """Semantic search over stored vectors using a text query."""
        if self._vector_store is None:
            return {"matches": [], "total": 0, "hint": "No vector store configured"}

        results = await self._vector_store.semantic_search(
            query=query,
            top_k=top_k,
            where=where,
            instruction=instruction,
        )
        return {"matches": results, "total": len(results)}

    async def find_flow(
        self,
        start: str,
        end: str,
        flow_type: str = "data",
    ) -> dict[str, Any]:
        # Resolve start and end nodes (id, name, or id fragment).
        start_id = await self._resolve_node_id(start)
        end_id = await self._resolve_node_id(end)
        start_node = await self._graph.get_node(start_id) if start_id else None
        end_node = await self._graph.get_node(end_id) if end_id else None
        if start_node is None and not start_id:
            candidates = await self._graph.find_nodes(name=start)
            if candidates:
                start_node = candidates[0]
                start_id = start_node.id
        if end_node is None and not end_id:
            candidates = await self._graph.find_nodes(name=end)
            if candidates:
                end_node = candidates[0]
                end_id = end_node.id

        if start == end:
            if start_node:
                return {
                    "path": [{"node": start_node.structural.name, "type": start_node.type.value}],
                    "data_transformations": [],
                    "found": True,
                }
            return {"path": [], "data_transformations": [], "found": False, "hint": "start node not found"}

        if not start_node or not end_node or not start_id or not end_id:
            return {
                "path": [],
                "data_transformations": [],
                "found": False,
                "hint": "start or end node not found; check names with smp/locate",
            }

        # Define edge types based on flow_type
        if flow_type == "data" or flow_type == "control" or flow_type == "calls":
            edges_to_follow = [EdgeType.CALLS, EdgeType.DEFINES]
        elif flow_type == "dependency":
            edges_to_follow = [EdgeType.IMPORTS, EdgeType.DEFINES]
        else:
            edges_to_follow = [EdgeType.CALLS, EdgeType.DEFINES]

        # Try outgoing first, then incoming, then bidirectional: callers often
        # ask callee->caller (reverse) without realising it.
        paths = await self._bfs_paths(start_id, end_id, edges_to_follow, "outgoing")
        direction_used = "outgoing"
        if not paths:
            paths = await self._bfs_paths(start_id, end_id, edges_to_follow, "incoming")
            direction_used = "incoming"
        if not paths:
            paths = await self._bfs_paths(start_id, end_id, edges_to_follow, "both")
            direction_used = "both"
        if not paths:
            return {
                "path": [],
                "data_transformations": [],
                "found": False,
                "hint": f"no {flow_type} path within 10 hops; try smp/trace from both ends",
            }

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
            "found": True,
            "direction": direction_used,
        }

    async def _bfs_paths(
        self,
        start_id: str,
        end_id: str,
        edge_types: list[EdgeType],
        direction: str = "outgoing",
    ) -> list[list[str]]:
        """BFS to find shortest paths following specific edge types."""
        found_paths: list[list[str]] = []
        queue: deque[tuple[str, list[str]]] = deque([(start_id, [start_id])])
        visited: set[str] = {start_id}
        max_depth = 10
        max_paths = 5

        while queue and len(found_paths) < max_paths:
            current, path = queue.popleft()
            if len(path) > max_depth:
                continue

            # Get edges in the specified direction
            edges = await self._graph.get_edges(current, edge_type=None, direction=direction)

            # Filter edges by type
            filtered_edges = [e for e in edges if e.type in edge_types]

            neighbors: set[str] = set()
            for e in filtered_edges:
                # Outgoing follows source -> target; incoming follows
                # target -> source; both follows either endpoint.
                if direction == "outgoing":
                    if e.source_id == current:
                        neighbors.add(e.target_id)
                elif direction == "incoming":
                    if e.target_id == current:
                        neighbors.add(e.source_id)
                else:  # both
                    if e.source_id == current:
                        neighbors.add(e.target_id)
                    elif e.target_id == current:
                        neighbors.add(e.source_id)

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
        """Compare two snapshots and return the differences.

        Each snapshot is either a checkpoint id (``ckpt_...``, as returned by
        ``smp/checkpoint``) or a live alias (``""``, ``"live"``, ``"current"``)
        meaning the current graph state. ``scope`` optionally restricts the
        comparison to files under a path prefix.
        """
        from_counters, from_index = await self._resolve_snapshot(from_snapshot, scope)
        to_counters, to_index = await self._resolve_snapshot(to_snapshot, scope)

        base: dict[str, Any] = {
            "from_snapshot": from_snapshot,
            "to_snapshot": to_snapshot,
            "added": [],
            "removed": [],
            "changed": [],
            "files_added": [],
            "files_removed": [],
            "files_changed": [],
            "node_detail": "full",
            "truncated": {},
            "stats": {
                "added_count": 0,
                "removed_count": 0,
                "changed_count": 0,
                "files_added": 0,
                "files_removed": 0,
                "files_changed": 0,
            },
        }
        if from_counters is None or to_counters is None:
            base["error"] = "snapshot_not_found"
            base["missing_snapshot"] = from_snapshot if from_counters is None else to_snapshot
            return base

        from_files = set(from_counters)
        to_files = set(to_counters)
        files_added = sorted(to_files - from_files)
        files_removed = sorted(from_files - to_files)
        files_changed = sorted(f for f in from_files & to_files if from_counters[f] != to_counters[f])

        added: set[str] = set()
        removed: set[str] = set()
        changed: set[str] = set()
        legacy = from_index is None or to_index is None
        if not legacy:
            assert from_index is not None and to_index is not None
            for file_path in sorted(from_files & to_files):
                if from_counters[file_path] == to_counters[file_path]:
                    continue
                from_ids = set(from_index[file_path])
                to_ids = set(to_index[file_path])
                added |= to_ids - from_ids
                removed |= from_ids - to_ids
                changed |= {n for n in from_ids & to_ids if from_index[file_path][n] != to_index[file_path][n]}
            for file_path in files_added:
                added |= set(to_index[file_path])
            for file_path in files_removed:
                removed |= set(from_index[file_path])

        capped_added, trunc_added = _cap_ids(sorted(added))
        capped_removed, trunc_removed = _cap_ids(sorted(removed))
        capped_changed, trunc_changed = _cap_ids(sorted(changed))
        base.update(
            {
                "added": capped_added,
                "removed": capped_removed,
                "changed": capped_changed,
                "files_added": files_added,
                "files_removed": files_removed,
                "files_changed": files_changed,
                "node_detail": "files_only" if legacy else "full",
                "truncated": {
                    "added": trunc_added,
                    "removed": trunc_removed,
                    "changed": trunc_changed,
                },
                "stats": {
                    "added_count": len(added),
                    "removed_count": len(removed),
                    "changed_count": len(changed),
                    "files_added": len(files_added),
                    "files_removed": len(files_removed),
                    "files_changed": len(files_changed),
                },
            }
        )
        return base

    async def _resolve_snapshot(
        self, snapshot: str, scope: str
    ) -> tuple[dict[str, dict[str, int]] | None, dict[str, dict[str, str]] | None]:
        """Resolve a snapshot to per-file fingerprint counters plus an optional
        per-file ``{node_id: content_hash}`` index.

        Returns ``(counters, node_index)``; ``counters`` is ``None`` when the
        snapshot id is unknown. ``node_index`` is ``None`` for legacy
        checkpoints (fingerprints only), which support file-level diffs.
        """
        if snapshot in _LIVE_SNAPSHOTS:
            if scope and scope != "full":
                nodes = await self._graph.find_nodes_by_scope(scope)
            else:
                nodes = await self._graph.find_nodes()
            counters: dict[str, dict[str, int]] = {}
            index: dict[str, dict[str, str]] = {}
            for node in nodes:
                fp = node.content_hash()
                file_counts = counters.setdefault(node.file_path, {})
                file_counts[fp] = file_counts.get(fp, 0) + 1
                index.setdefault(node.file_path, {})[node.id] = fp
            return counters, index
        try:
            record = await self._graph.get_session(snapshot)
        except (NotImplementedError, AttributeError):
            return None, None
        if not isinstance(record, dict) or record.get("kind") != "checkpoint":
            return None, None
        raw_index = record.get("node_index")
        if isinstance(raw_index, dict) and raw_index:
            counters = {}
            index = {}
            for file_path, ids in raw_index.items():
                if not isinstance(ids, dict) or not _in_scope(file_path, scope):
                    continue
                file_counts = counters.setdefault(file_path, {})
                file_index = index.setdefault(file_path, {})
                for node_id, fp in ids.items():
                    fp_str = str(fp)
                    file_counts[fp_str] = file_counts.get(fp_str, 0) + 1
                    file_index[str(node_id)] = fp_str
            return counters, index
        counters = {}
        legacy = record.get("fingerprints") or {}
        for file_path, fps in legacy.items():
            if not _in_scope(file_path, scope) or not isinstance(fps, list):
                continue
            file_counts = counters.setdefault(file_path, {})
            for fp in fps:
                fp_str = str(fp)
                file_counts[fp_str] = file_counts.get(fp_str, 0) + 1
        return counters, None

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
        affected: list[dict[str, Any]] = []
        total_callers = 0
        for node in file_nodes:
            callers = await self._graph.traverse(node.id, EdgeType.CALLS, depth=10, max_nodes=200, direction="incoming")
            if callers:
                affected_nodes.append(node.id)
                affected.append(
                    {
                        "node_id": node.id,
                        "name": node.structural.name,
                        "callers": len(callers),
                    }
                )
                total_callers += len(callers)

        affected.sort(key=lambda a: -a["callers"])
        top_names = ", ".join(a["name"] for a in affected[:5])
        steps: list[dict[str, str]] = [
            {"step": "1", "action": "Backup current state", "details": f"Snapshot {target_file}"},
            {
                "step": "2",
                "action": "Apply changes",
                "details": f"{change_description} ({len(affected)} functions: {top_names})"
                if top_names
                else change_description,
            },
            {
                "step": "3",
                "action": "Run tests",
                "details": f"Test affected nodes: {len(affected_nodes)} (blast radius: {total_callers} callers)",
            },
        ]

        if change_type == "signature_change":
            steps.append(
                {
                    "step": "4",
                    "action": "Update callers",
                    "details": (f"Update {total_callers} callers across {len(affected_nodes)} functions: {top_names}"),
                }
            )

        return {
            "change_description": change_description,
            "target_file": target_file,
            "change_type": change_type,
            "affected_nodes": affected_nodes,
            "affected": affected,
            "total_callers": total_callers,
            "steps": steps,
            "risk_level": "high" if total_callers > 10 else "medium" if affected_nodes else "low",
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
            parser = CodeParser()
            try:
                proposed_data = parser.parse(proposed_content, file_path)
                proposed_node_ids = {n.node_id for n in proposed_data.nodes}
            except Exception:  # noqa: BLE001
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
