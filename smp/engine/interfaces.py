"""Abstract base classes for the engine layer.

Defines the contracts for parsing, graph building, semantic enrichment,
and querying.
"""

from __future__ import annotations

import abc
from typing import Any

from smp.core.models import (
    Document,
    GraphNode,
)


class Parser(abc.ABC):
    """Extract typed AST nodes and edges from source code."""

    @abc.abstractmethod
    def parse(self, source: str, file_path: str) -> Document:
        """Parse *source* and return a :class:`Document`.

        The returned document contains extracted nodes, edges, and any
        non-fatal parse errors.  Must never raise on syntax errors —
        partial results + errors are preferred.
        """

    @property
    @abc.abstractmethod
    def supported_languages(self) -> list[str]:
        """Return language names this parser handles."""


class GraphBuilder(abc.ABC):
    """Map parsed :class:`Document` elements into a graph store."""

    @abc.abstractmethod
    async def ingest_document(self, document: Document) -> None:
        """Write the document's nodes and edges into the graph store."""

    @abc.abstractmethod
    async def remove_document(self, file_path: str) -> None:
        """Remove all graph data for *file_path* (incremental update)."""


class SemanticEnricher(abc.ABC):
    """Generate semantic summaries and embeddings for graph nodes."""

    @abc.abstractmethod
    async def enrich_node(self, node: GraphNode) -> GraphNode:
        """Return a copy of *node* with :class:`SemanticInfo` populated."""

    @abc.abstractmethod
    async def enrich_batch(self, nodes: list[GraphNode]) -> list[GraphNode]:
        """Enrich multiple nodes (may batch LLM calls)."""

    @abc.abstractmethod
    async def embed(self, text: str) -> list[float]:
        """Generate an embedding vector for *text*."""


class QueryEngine(abc.ABC):
    """High-level query interface over the memory store."""

    @abc.abstractmethod
    async def navigate(self, entity_id: str, depth: int = 1) -> dict[str, Any]:
        """Get a node and its immediate neighbours."""

    @abc.abstractmethod
    async def trace(
        self,
        start_id: str,
        edge_type: str,
        depth: int = 5,
        max_nodes: int = 100,
    ) -> list[dict[str, Any]]:
        """Recursive traversal (e.g., full call graph)."""

    @abc.abstractmethod
    async def get_context(
        self,
        file_path: str,
        scope: str = "edit",
        include_semantic: bool = True,
    ) -> dict[str, Any]:
        """Aggregate structural context for safe editing."""

    @abc.abstractmethod
    async def assess_impact(self, entity_id: str, depth: int = 10) -> dict[str, Any]:
        """Find blast radius of a change."""

    @abc.abstractmethod
    async def locate_by_intent(
        self,
        description: str,
        top_k: int = 5,
    ) -> list[dict[str, Any]]:
        """Vector search mapping back to graph nodes."""

    @abc.abstractmethod
    async def find_flow(
        self,
        start_id: str,
        end_id: str,
        max_depth: int = 20,
    ) -> list[list[dict[str, Any]]]:
        """Find paths between two nodes."""
