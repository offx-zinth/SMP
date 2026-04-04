"""Query engine — high-level queries over the memory store.

Provides navigate, trace, get_context, assess_impact, locate_by_intent,
and find_flow queries backed by graph + vector stores.
"""

from __future__ import annotations

from collections import deque
from typing import Any

from smp.core.models import EdgeType, GraphNode
from smp.engine.interfaces import QueryEngine as QueryEngineInterface
from smp.logging import get_logger
from smp.store.interfaces import GraphStore, VectorStore

log = get_logger(__name__)


class DefaultQueryEngine(QueryEngineInterface):
    """Query engine backed by a graph store and vector store."""

    def __init__(
        self,
        graph_store: GraphStore,
        vector_store: VectorStore,
        enricher: Any | None = None,
    ) -> None:
        self._graph = graph_store
        self._vector = vector_store
        self._enricher = enricher  # SemanticEnricher for embeddings

    def _node_to_dict(self, node: GraphNode) -> dict[str, Any]:
        return {
            "id": node.id,
            "type": node.type.value,
            "name": node.name,
            "file_path": node.file_path,
            "start_line": node.start_line,
            "end_line": node.end_line,
            "signature": node.signature,
            "semantic": {
                "purpose": node.semantic.purpose,
                "confidence": node.semantic.confidence,
            }
            if node.semantic
            else None,
        }

    # -----------------------------------------------------------------------
    # navigate
    # -----------------------------------------------------------------------

    async def navigate(self, entity_id: str, depth: int = 1) -> dict[str, Any]:
        node = await self._graph.get_node(entity_id)
        if not node:
            return {"error": f"Node {entity_id} not found"}
        neighbors = await self._graph.get_neighbors(entity_id, depth=depth)
        edges = await self._graph.get_edges(entity_id)
        return {
            "node": self._node_to_dict(node),
            "neighbors": [self._node_to_dict(n) for n in neighbors],
            "edges": [{"source": e.source_id, "target": e.target_id, "type": e.type.value} for e in edges],
        }

    # -----------------------------------------------------------------------
    # trace
    # -----------------------------------------------------------------------

    async def trace(
        self,
        start_id: str,
        edge_type: str = "CALLS",
        depth: int = 5,
        max_nodes: int = 100,
    ) -> list[dict[str, Any]]:
        et = EdgeType(edge_type)
        nodes = await self._graph.traverse(start_id, et, depth, max_nodes)
        return [self._node_to_dict(n) for n in nodes]

    # -----------------------------------------------------------------------
    # get_context
    # -----------------------------------------------------------------------

    async def get_context(
        self,
        file_path: str,
        scope: str = "edit",
        include_semantic: bool = True,
    ) -> dict[str, Any]:
        nodes = await self._graph.find_nodes(file_path=file_path)
        all_edges: list[dict[str, Any]] = []
        for node in nodes:
            edges = await self._graph.get_edges(node.id)
            all_edges.extend({"source": e.source_id, "target": e.target_id, "type": e.type.value} for e in edges)
        result: dict[str, Any] = {
            "file_path": file_path,
            "scope": scope,
            "nodes": [self._node_to_dict(n) for n in nodes],
            "edges": all_edges,
        }
        return result

    # -----------------------------------------------------------------------
    # assess_impact
    # -----------------------------------------------------------------------

    async def assess_impact(self, entity_id: str, depth: int = 10) -> dict[str, Any]:
        node = await self._graph.get_node(entity_id)
        if not node:
            return {"error": f"Node {entity_id} not found"}
        dependents = await self._graph.traverse(entity_id, EdgeType.CALLS, depth, max_nodes=200, direction="incoming")
        return {
            "entity": self._node_to_dict(node),
            "affected_nodes": [self._node_to_dict(n) for n in dependents],
            "total_affected": len(dependents),
        }

    # -----------------------------------------------------------------------
    # locate_by_intent
    # -----------------------------------------------------------------------

    async def locate_by_intent(
        self,
        description: str,
        top_k: int = 5,
    ) -> list[dict[str, Any]]:
        if not description.strip():
            return []

        # Embed the query
        if self._enricher:
            embedding = await self._enricher.embed(description)
        else:
            raise RuntimeError("Semantic search requires an enricher. Start the server with NV_API set.")

        # Search vector store
        results = await self._vector.query(embedding, top_k=top_k)
        if not results:
            return []

        # Map back to graph nodes
        output: list[dict[str, Any]] = []
        for r in results:
            node = await self._graph.get_node(r["id"])
            if node:
                output.append(
                    {
                        "node": self._node_to_dict(node),
                        "score": round(r["score"], 4),
                        "purpose": r.get("document", ""),
                    }
                )
            else:
                output.append(
                    {
                        "node_id": r["id"],
                        "score": round(r["score"], 4),
                        "purpose": r.get("document", ""),
                    }
                )

        log.debug("locate_by_intent", query=description[:50], results=len(output))
        return output

    # -----------------------------------------------------------------------
    # find_flow — BFS path finding
    # -----------------------------------------------------------------------

    async def find_flow(
        self,
        start_id: str,
        end_id: str,
        max_depth: int = 20,
    ) -> list[list[dict[str, Any]]]:
        """Find paths between two nodes using bidirectional BFS.

        Returns up to 3 shortest paths.
        """
        if start_id == end_id:
            node = await self._graph.get_node(start_id)
            if node:
                return [[self._node_to_dict(node)]]
            return []

        # Verify both nodes exist
        start_node = await self._graph.get_node(start_id)
        end_node = await self._graph.get_node(end_id)
        if not start_node or not end_node:
            return []

        paths = await self._bfs_paths(start_id, end_id, max_depth)
        return paths

    async def _bfs_paths(
        self,
        start_id: str,
        end_id: str,
        max_depth: int,
    ) -> list[list[dict[str, Any]]]:
        """BFS to find up to 3 shortest paths between start and end."""
        found_paths: list[list[str]] = []
        # queue: (current_node, path_so_far)
        queue: deque[tuple[str, list[str]]] = deque([(start_id, [start_id])])
        visited: set[str] = set()

        while queue and len(found_paths) < 3:
            current, path = queue.popleft()

            if len(path) > max_depth + 1:
                continue

            # Get all connected nodes (both directions)
            edges = await self._graph.get_edges(current, direction="outgoing")
            edges += await self._graph.get_edges(current, direction="incoming")

            neighbors: set[str] = set()
            for e in edges:
                if e.source_id == current:
                    neighbors.add(e.target_id)
                else:
                    neighbors.add(e.source_id)

            for neighbor in neighbors:
                if neighbor == end_id:
                    found_paths.append(path + [neighbor])
                    continue
                if neighbor not in visited and neighbor not in path:
                    visited.add(neighbor)
                    queue.append((neighbor, path + [neighbor]))

        # Convert paths to node dicts
        result: list[list[dict[str, Any]]] = []
        for path_ids in found_paths:
            path_nodes: list[dict[str, Any]] = []
            for nid in path_ids:
                node = await self._graph.get_node(nid)
                if node:
                    path_nodes.append(self._node_to_dict(node))
            if path_nodes:
                result.append(path_nodes)

        return result
