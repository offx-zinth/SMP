"""Abstract base classes for store backends.

All concrete implementations must subclass these to ensure
interchangeability across graph and vector stores.
"""

from __future__ import annotations

import abc
from typing import Any, Sequence

from smp.core.models import EdgeType, GraphEdge, GraphNode, NodeType


class GraphStore(abc.ABC):
    """Abstract graph store — manages nodes and directed edges."""

    # -- Lifecycle -----------------------------------------------------------

    @abc.abstractmethod
    async def connect(self) -> None:
        """Open connection / initialise the underlying store."""

    @abc.abstractmethod
    async def close(self) -> None:
        """Release resources."""

    @abc.abstractmethod
    async def clear(self) -> None:
        """Drop all data (useful for tests)."""

    # -- Node CRUD -----------------------------------------------------------

    @abc.abstractmethod
    async def upsert_node(self, node: GraphNode) -> None:
        """Insert or update a single node."""

    @abc.abstractmethod
    async def upsert_nodes(self, nodes: Sequence[GraphNode]) -> None:
        """Batch upsert nodes."""

    @abc.abstractmethod
    async def get_node(self, node_id: str) -> GraphNode | None:
        """Retrieve a node by its *id*, or ``None``."""

    @abc.abstractmethod
    async def delete_node(self, node_id: str) -> bool:
        """Delete a node and all its edges.  Returns True if it existed."""

    @abc.abstractmethod
    async def delete_nodes_by_file(self, file_path: str) -> int:
        """Remove all nodes (and edges) belonging to *file_path*.

        Returns the number of nodes removed.
        """

    # -- Edge CRUD -----------------------------------------------------------

    @abc.abstractmethod
    async def upsert_edge(self, edge: GraphEdge) -> None:
        """Insert or update a single edge."""

    @abc.abstractmethod
    async def upsert_edges(self, edges: Sequence[GraphEdge]) -> None:
        """Batch upsert edges."""

    @abc.abstractmethod
    async def get_edges(
        self,
        node_id: str,
        edge_type: EdgeType | None = None,
        direction: str = "both",
    ) -> list[GraphEdge]:
        """Return edges connected to *node_id*.

        *direction*: ``"outgoing"`` | ``"incoming"`` | ``"both"``.
        """

    # -- Traversal -----------------------------------------------------------

    @abc.abstractmethod
    async def get_neighbors(
        self,
        node_id: str,
        edge_type: EdgeType | None = None,
        depth: int = 1,
    ) -> list[GraphNode]:
        """Return neighbours up to *depth* hops from *node_id*."""

    @abc.abstractmethod
    async def traverse(
        self,
        start_id: str,
        edge_type: EdgeType,
        depth: int,
        max_nodes: int = 100,
        direction: str = "outgoing", 
    ) -> list[GraphNode]:
        """BFS traversal from *start_id* following *edge_type* edges."""

    # -- Search --------------------------------------------------------------

    @abc.abstractmethod
    async def find_nodes(
        self,
        *,
        type: NodeType | None = None,
        file_path: str | None = None,
        name: str | None = None,
    ) -> list[GraphNode]:
        """Find nodes matching the given filters."""

    # -- Aggregation ---------------------------------------------------------

    @abc.abstractmethod
    async def count_nodes(self) -> int:
        """Return total number of nodes."""

    @abc.abstractmethod
    async def count_edges(self) -> int:
        """Return total number of edges."""

    # -- Context manager convenience -----------------------------------------

    async def __aenter__(self) -> "GraphStore":
        await self.connect()
        return self

    async def __aexit__(self, *_: Any) -> None:
        await self.close()


class VectorStore(abc.ABC):
    """Abstract vector store — manages embeddings with metadata."""

    # -- Lifecycle -----------------------------------------------------------

    @abc.abstractmethod
    async def connect(self) -> None:
        """Open connection / initialise."""

    @abc.abstractmethod
    async def close(self) -> None:
        """Release resources."""

    @abc.abstractmethod
    async def clear(self) -> None:
        """Drop all data."""

    # -- CRUD ----------------------------------------------------------------

    @abc.abstractmethod
    async def upsert(
        self,
        ids: Sequence[str],
        embeddings: Sequence[Sequence[float]],
        metadatas: Sequence[dict[str, Any]],
        documents: Sequence[str] | None = None,
    ) -> None:
        """Insert or update vectors with associated metadata."""

    @abc.abstractmethod
    async def query(
        self,
        embedding: Sequence[float],
        top_k: int = 5,
        where: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        """Return the *top_k* nearest neighbours.

        Each result is a dict with keys: ``id``, ``score``, ``metadata``,
        ``document``.
        """

    @abc.abstractmethod
    async def get(self, ids: Sequence[str]) -> list[dict[str, Any] | None]:
        """Retrieve vectors by ID."""

    @abc.abstractmethod
    async def delete(self, ids: Sequence[str]) -> int:
        """Delete vectors by ID.  Returns count of deleted items."""

    @abc.abstractmethod
    async def delete_by_file(self, file_path: str) -> int:
        """Delete all vectors whose metadata ``file_path`` matches."""

    # -- Context manager convenience -----------------------------------------

    async def __aenter__(self) -> "VectorStore":
        await self.connect()
        return self

    async def __aexit__(self, *_: Any) -> None:
        await self.close()
