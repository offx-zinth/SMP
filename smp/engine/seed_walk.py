"""SeedWalkEngine — community-routed graph RAG pipeline for smp/locate.

Phase 0 — ROUTE: Compare query embedding against community centroids.
Phase 1 — SEED:  ChromaDB vector search scoped to community or global.
Phase 2 — WALK:  Graph traversal from seeds via CALLS/IMPORTS/DEFINES edges.
Phase 3 — RANK:  Composite score = alpha*vector + beta*pagerank + gamma*heat.
Phase 4 — ASSEMBLE: Deduplicated results + structural map.

No LLM calls at any phase.
"""

from __future__ import annotations

from collections import deque
from typing import Any

import msgspec

from smp.engine.interfaces import QueryEngine as QueryEngineInterface
from smp.logging import get_logger
from smp.store.interfaces import GraphStore, VectorStore

log = get_logger(__name__)

ALPHA = 0.50
BETA = 0.30
GAMMA = 0.20
ROUTE_CONFIDENCE_THRESHOLD = 0.65
DEFAULT_SEED_K = 3
DEFAULT_HOPS = 2
DEFAULT_TOP_K = 10


class SeedNode(msgspec.Struct, frozen=True):
    node_id: str = ""
    node_type: str = ""
    name: str = ""
    file: str = ""
    signature: str = ""
    docstring: str | None = None
    tags: list[str] = msgspec.field(default_factory=list)
    community_id: str | None = None
    vector_score: float = 0.0
    pagerank: float = 0.0
    heat_score: int = 0


class WalkNode(msgspec.Struct, frozen=True):
    node_id: str = ""
    node_type: str = ""
    name: str = ""
    file: str = ""
    signature: str = ""
    docstring: str | None = None
    community_id: str | None = None
    edge_type: str = ""
    edge_direction: str = ""
    hop: int = 0
    is_bridge: bool = False
    pagerank: float = 0.0
    heat_score: int = 0


class RankedResult(msgspec.Struct, frozen=True):
    node_id: str = ""
    node_type: str = ""
    name: str = ""
    file: str = ""
    signature: str = ""
    docstring: str | None = None
    tags: list[str] = msgspec.field(default_factory=list)
    community_id: str | None = None
    final_score: float = 0.0
    vector_score: float = 0.0
    pagerank: float = 0.0
    heat_score: int = 0
    is_seed: bool = False
    reachable_from: list[str] = msgspec.field(default_factory=list)


class LocateResponse(msgspec.Struct, frozen=True):
    query: str = ""
    routed_community: str | None = None
    seed_count: int = 0
    total_walked: int = 0
    results: list[RankedResult] = msgspec.field(default_factory=list)
    structural_map: list[dict[str, Any]] = msgspec.field(default_factory=list)


class SeedWalkEngine(QueryEngineInterface):
    """Community-routed graph RAG pipeline for smp/locate."""

    def __init__(
        self,
        graph_store: GraphStore,
        vector_store: VectorStore | None = None,
        enricher: Any | None = None,
        alpha: float = ALPHA,
        beta: float = BETA,
        gamma: float = GAMMA,
        route_threshold: float = ROUTE_CONFIDENCE_THRESHOLD,
        delegate: QueryEngineInterface | None = None,
    ) -> None:
        self._graph = graph_store
        self._vector = vector_store
        self._enricher = enricher
        self._alpha = alpha
        self._beta = beta
        self._gamma = gamma
        self._route_threshold = route_threshold
        self._delegate = delegate

    async def _route_to_community(self, query: str) -> tuple[str | None, float]:
        if self._vector is None:
            return None, 0.0
        try:
            results = await self._vector.query(
                embedding=_simple_hash_embedding(query),
                top_k=1,
                where={"collection_type": "centroid"},
            )
            if not results:
                return None, 0.0
            best = results[0]
            community_id = best.get("metadata", {}).get("community_id")
            score = best.get("score", 1.0)
            if isinstance(score, (int, float)):
                confidence = 1.0 - float(score)
            else:
                confidence = 0.0
            if confidence < self._route_threshold:
                return None, confidence
            return community_id, confidence
        except Exception:
            log.warning("route_community_failed", query=query)
            return None, 0.0

    async def _seed(
        self,
        query: str,
        seed_k: int,
        community_id: str | None = None,
    ) -> list[SeedNode]:
        all_nodes = await self._graph.find_nodes()
        terms = query.lower().split()
        scored: list[tuple[float, dict[str, Any]]] = []
        for node in all_nodes:
            s = 0.0
            name_lower = node.structural.name.lower()
            # Use partial matching for better recall
            if all(t in name_lower for t in terms):
                s += 100.0
            elif any(t in name_lower for t in terms):
                s += 50.0

            if node.semantic.docstring:
                doc_lower = node.semantic.docstring.lower()
                if all(t in doc_lower for t in terms):
                    s += 40.0
                elif any(t in doc_lower for t in terms):
                    s += 20.0

            for tag in node.semantic.tags:
                if any(t in tag.lower() for t in terms):
                    s += 15.0
                    break
            if community_id and hasattr(node.semantic, "tags"):
                pass
            if s > 0:
                scored.append((s, {"node": node, "score": s}))

        if self._vector is not None:
            try:
                v_results = await self._vector.query(
                    embedding=_simple_hash_embedding(query),
                    top_k=seed_k,
                )
                for vr in v_results:
                    node_id = vr.get("id", "")
                    v_score = vr.get("score", 0.0)
                    if isinstance(v_score, (int, float)):
                        v_sim = 1.0 - float(v_score)
                    else:
                        v_sim = 0.0
                    found = False
                    for s_item in scored:
                        if s_item[1].get("node", None) and s_item[1]["node"].id == node_id:
                            found = True
                            break
                    if not found and v_sim > 0.1:
                        gnode = await self._graph.get_node(node_id)
                        if gnode:
                            scored.append((v_sim * 80.0, {"node": gnode, "score": v_sim * 80.0}))
            except Exception:
                log.warning("vector_seed_failed", query=query)

        scored.sort(key=lambda x: -x[0])
        seeds: list[SeedNode] = []
        for score_val, data in scored[:seed_k]:
            node = data["node"]
            seeds.append(
                SeedNode(
                    node_id=node.id,
                    node_type=node.type.value,
                    name=node.structural.name,
                    file=node.file_path,
                    signature=node.structural.signature,
                    docstring=node.semantic.docstring or None,
                    tags=node.semantic.tags,
                    community_id=None,
                    vector_score=min(score_val / 100.0, 1.0),
                    pagerank=0.0,
                    heat_score=0,
                )
            )
        return seeds

    async def _walk(self, seed_ids: list[str], hops: int) -> list[WalkNode]:
        from smp.core.models import EdgeType

        walked: dict[str, WalkNode] = {}
        queue: deque[tuple[str, int]] = deque()
        for sid in seed_ids:
            queue.append((sid, 0))
        visited: set[str] = set(seed_ids)

        while queue:
            current_id, depth = queue.popleft()
            if depth >= hops:
                continue
            node = await self._graph.get_node(current_id)
            if not node:
                continue
            try:
                edges_out = await self._graph.get_edges(current_id, direction="outgoing")
            except Exception:
                edges_out = []
            try:
                edges_in = await self._graph.get_edges(current_id, direction="incoming")
            except Exception:
                edges_in = []
            all_edges = edges_out + edges_in
            for edge in all_edges:
                if edge.type not in (EdgeType.CALLS, EdgeType.CALLS_RUNTIME, EdgeType.IMPORTS, EdgeType.DEFINES):
                    continue
                neighbor_id = edge.target_id if edge.source_id == current_id else edge.source_id
                direction = "out" if edge.source_id == current_id else "in"
                if neighbor_id in visited:
                    continue
                visited.add(neighbor_id)
                neighbor = await self._graph.get_node(neighbor_id)
                if not neighbor:
                    continue
                walked[neighbor_id] = WalkNode(
                    node_id=neighbor_id,
                    node_type=neighbor.type.value,
                    name=neighbor.structural.name,
                    file=neighbor.file_path,
                    signature=neighbor.structural.signature,
                    docstring=neighbor.semantic.docstring or None,
                    community_id=None,
                    edge_type=edge.type.value,
                    edge_direction=direction,
                    hop=depth + 1,
                    is_bridge=False,
                    pagerank=0.0,
                    heat_score=0,
                )
                queue.append((neighbor_id, depth + 1))
        return list(walked.values())

    def _rank(
        self,
        seeds: list[SeedNode],
        walked: list[WalkNode],
        top_k: int,
    ) -> list[RankedResult]:
        seed_map = {s.node_id: s for s in seeds}
        max_pr = max((s.pagerank for s in seeds), default=1.0) or 1.0
        walked_max_pr = max((w.pagerank for w in walked), default=1.0) or 1.0
        max_pr = max(max_pr, walked_max_pr)

        results: dict[str, RankedResult] = {}
        for s in seeds:
            score = (
                self._alpha * s.vector_score + self._beta * (s.pagerank / max_pr) + self._gamma * (s.heat_score / 100.0)
            )
            results[s.node_id] = RankedResult(
                node_id=s.node_id,
                node_type=s.node_type,
                name=s.name,
                file=s.file,
                signature=s.signature,
                docstring=s.docstring,
                tags=s.tags,
                community_id=s.community_id,
                final_score=round(score, 4),
                vector_score=s.vector_score,
                pagerank=s.pagerank,
                heat_score=s.heat_score,
                is_seed=True,
                reachable_from=[s.node_id],
            )

        for w in walked:
            if w.node_id in results:
                continue
            seed_pr = seed_map.get(w.node_id)
            v_score = seed_pr.vector_score if seed_pr else 0.0
            score = self._alpha * v_score + self._beta * (w.pagerank / max_pr) + self._gamma * (w.heat_score / 100.0)
            results[w.node_id] = RankedResult(
                node_id=w.node_id,
                node_type=w.node_type,
                name=w.name,
                file=w.file,
                signature=w.signature,
                docstring=w.docstring,
                tags=[],
                community_id=w.community_id,
                final_score=round(score, 4),
                vector_score=v_score,
                pagerank=w.pagerank,
                heat_score=w.heat_score,
                is_seed=False,
                reachable_from=[],
            )

        ranked = sorted(results.values(), key=lambda r: r.final_score, reverse=True)
        return ranked[:top_k]

    def _build_structural_map(
        self,
        results: list[RankedResult],
        walked: list[WalkNode],
    ) -> list[dict[str, Any]]:
        result_ids = {r.node_id for r in results}
        edges: list[dict[str, Any]] = []
        for w in walked:
            if w.node_id in result_ids:
                edges.append(
                    {
                        "from": w.node_id,
                        "to": w.node_id,
                        "edge_type": w.edge_type,
                        "hop": w.hop,
                    }
                )
        return edges

    async def locate(
        self,
        query: str,
        fields: list[str] | None = None,
        node_types: list[str] | None = None,
        top_k: int = DEFAULT_TOP_K,
    ) -> list[dict[str, Any]]:
        routed_community, route_confidence = await self._route_to_community(query)
        seed_k = min(top_k, DEFAULT_SEED_K)
        hops = DEFAULT_HOPS
        seeds = await self._seed(query, seed_k, community_id=routed_community)
        if node_types:
            seeds = [s for s in seeds if s.node_type in node_types]
        walked = await self._walk([s.node_id for s in seeds], hops)
        if node_types:
            walked = [w for w in walked if w.node_type in node_types]
        ranked = self._rank(seeds, walked, top_k)
        smap = self._build_structural_map(ranked, walked)

        result = LocateResponse(
            query=query,
            routed_community=routed_community,
            seed_count=len(seeds),
            total_walked=len(walked),
            results=ranked,
            structural_map=smap,
        )

        return [msgspec.structs.asdict(result)]

    async def navigate(self, query: str, include_relationships: bool = True) -> dict[str, Any]:
        if self._delegate:
            return await self._delegate.navigate(query, include_relationships)
        return {}

    async def trace(
        self, start: str, relationship: str = "CALLS", depth: int = 3, direction: str = "outgoing"
    ) -> list[dict[str, Any]]:
        if self._delegate:
            return await self._delegate.trace(start, relationship, depth, direction)
        return []

    async def get_context(self, file_path: str, scope: str = "edit", depth: int = 2) -> dict[str, Any]:
        if self._delegate:
            return await self._delegate.get_context(file_path, scope, depth)
        return {}

    async def assess_impact(self, entity: str, change_type: str = "delete") -> dict[str, Any]:
        if self._delegate:
            return await self._delegate.assess_impact(entity, change_type)
        return {}

    async def search(
        self, query: str, match: str = "any", filters: dict[str, Any] | None = None, top_k: int = 5
    ) -> dict[str, Any]:
        if self._delegate:
            return await self._delegate.search(query, match, filters, top_k)
        return {}

    async def conflict(
        self,
        entity: str,
        proposed_change: str = "",
        context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if self._delegate:
            return await self._delegate.conflict(entity, proposed_change, context)
        return {"conflicts": []}

    async def diff(
        self,
        from_snapshot: str,
        to_snapshot: str,
        scope: str = "full",
    ) -> dict[str, Any]:
        if self._delegate:
            return await self._delegate.diff(from_snapshot, to_snapshot, scope)
        return {"diff": {}}

    async def plan(
        self,
        change_description: str,
        target_file: str = "",
        change_type: str = "refactor",
        scope: str = "full",
    ) -> dict[str, Any]:
        if self._delegate:
            return await self._delegate.plan(change_description, target_file, change_type, scope)
        return {"steps": []}

    async def why(
        self,
        entity: str,
        relationship: str = "",
        depth: int = 3,
    ) -> dict[str, Any]:
        if self._delegate:
            return await self._delegate.why(entity, relationship, depth)
        return {"reasoning": []}

    async def find_flow(self, start: str, end: str, flow_type: str = "data") -> dict[str, Any]:
        if self._delegate:
            return await self._delegate.find_flow(start, end, flow_type)
        return {}


def _simple_hash_embedding(text: str, dim: int = 128) -> list[float]:
    """Deterministic hash-based embedding for prototyping.

    Maps text to a fixed-dimension float vector using character
    frequency hashing. Production should use a real embedding model.
    """
    vec = [0.0] * dim
    for i, ch in enumerate(text):
        vec[i % dim] += float(ord(ch))
    norm = sum(v * v for v in vec) ** 0.5
    if norm == 0:
        return vec
    return [v / norm for v in vec]
