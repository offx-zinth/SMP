"""PageRank engine for calculating node importance in the structural graph.

Implements an iterative PageRank algorithm to identify central entities based on
graph connectivity (in-degree and relationship importance).
"""

from __future__ import annotations

from collections import defaultdict

from smp.core.models import GraphEdge, GraphNode
from smp.logging import get_logger
from smp.store.interfaces import GraphStore

log = get_logger(__name__)


class PageRankEngine:
    """Calculates importance scores for graph nodes using the PageRank algorithm."""

    def __init__(self, damping: float = 0.85, max_iterations: int = 100, tol: float = 1e-6) -> None:
        """Initialize PageRank engine.

        Args:
            damping: Damping factor (probability of following a link).
            max_iterations: Maximum number of iterations to run.
            tol: Convergence threshold.
        """
        self.damping = damping
        self.max_iterations = max_iterations
        self.tol = tol

    def compute(self, nodes: list[GraphNode], edges: list[GraphEdge]) -> dict[str, float]:
        """Compute PageRank scores for the given nodes and edges.

        Args:
            nodes: List of nodes in the graph.
            edges: List of directed edges in the graph.

        Returns:
            A dictionary mapping node IDs to their calculated PageRank scores.
        """
        if not nodes:
            return {}

        n = len(nodes)
        node_ids = [node.id for node in nodes]
        id_to_idx = {node_id: i for i, node_id in enumerate(node_ids)}

        # Adjacency list and out-degrees
        adj = defaultdict(list)
        out_degree = defaultdict(int)
        for edge in edges:
            if edge.source_id in id_to_idx and edge.target_id in id_to_idx:
                adj[edge.target_id].append(edge.source_id)
                out_degree[edge.source_id] += 1

        # Initial scores
        scores = [1.0 / n] * n

        for iteration in range(self.max_iterations):
            new_scores = [0.0] * n
            total_dangling_weight = 0.0

            # Handle dangling nodes (nodes with no outgoing edges)
            for i in range(n):
                if out_degree[node_ids[i]] == 0:
                    total_dangling_weight += scores[i]

            for i in range(n):
                target_id = node_ids[i]
                # Sum of PageRank from neighbors
                rank_sum = sum(scores[id_to_idx[src]] / out_degree[src] for src in adj[target_id])

                # Calculate new score
                new_scores[i] = (1.0 - self.damping) / n + self.damping * (rank_sum + total_dangling_weight / n)

            # Check convergence
            diff = sum(abs(new_scores[i] - scores[i]) for i in range(n))
            if diff < self.tol:
                log.debug("pagerank_converged", iteration=iteration, diff=diff)
                scores = new_scores
                break

            scores = new_scores

        return {node_ids[i]: scores[i] for i in range(n)}

    async def update_node_scores(self, graph_store: GraphStore) -> int:
        """Update nodes in the graph store with their computed PageRank scores.

        Args:
            graph_store: The graph store to update.

        Returns:
            Number of nodes updated.
        """
        # Use a broad search to get all nodes. In a real scenario,
        # we might want to filter by type or scope.
        nodes = await graph_store.find_nodes()

        # We need all edges to compute PageRank.
        # This is expensive for large graphs; a real implementation would use GDS.
        all_edges: list[GraphEdge] = []
        for node in nodes:
            edges = await graph_store.get_edges(node.id, direction="outgoing")
            all_edges.extend(edges)

        scores = self.compute(nodes, all_edges)

        updated_count = 0
        for node in nodes:
            score = scores.get(node.id, 0.0)
            node.semantic.score = score
            await graph_store.upsert_node(node)
            updated_count += 1

        log.info("pagerank_scores_updated", count=updated_count)
        return updated_count
