"""Abstract base classes for the engine layer.

Defines the contracts for parsing, graph building, semantic enrichment,
and querying for SMP(3).
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
        """Parse *source* and return a :class:`Document`."""

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
        """Remove all graph data for *file_path*."""


class SemanticEnricher(abc.ABC):
    """Generate static semantic summaries from AST metadata."""

    @abc.abstractmethod
    async def enrich_node(self, node: GraphNode, force: bool = False) -> GraphNode:
        """Return a copy of *node* with :class:`SemanticProperties` populated."""

    @abc.abstractmethod
    async def enrich_batch(self, nodes: list[GraphNode], force: bool = False) -> list[GraphNode]:
        """Enrich multiple nodes."""

    @abc.abstractmethod
    async def embed(self, text: str) -> list[float]:
        """No-op for static enricher."""


class QueryEngine(abc.ABC):
    """High-level query interface over the memory store."""

    @abc.abstractmethod
    async def navigate(self, query: str, include_relationships: bool = True) -> dict[str, Any]:
        """Find entity and return basic info with relationships."""

    @abc.abstractmethod
    async def trace(
        self,
        start: str,
        relationship: str = "CALLS",
        depth: int = 3,
        direction: str = "outgoing",
    ) -> list[dict[str, Any]]:
        """Follow relationship chain from start node."""

    @abc.abstractmethod
    async def get_context(
        self,
        file_path: str,
        scope: str = "edit",
        depth: int = 2,
    ) -> dict[str, Any]:
        """Aggregate structural context for safe editing — the programmer's mental model."""

    @abc.abstractmethod
    async def assess_impact(self, entity: str, change_type: str = "delete") -> dict[str, Any]:
        """Find blast radius of a change."""

    @abc.abstractmethod
    async def locate(
        self,
        query: str,
        fields: list[str] | None = None,
        node_types: list[str] | None = None,
        top_k: int = 5,
    ) -> list[dict[str, Any]]:
        """Keyword search ranked by match quality."""

    @abc.abstractmethod
    async def search(
        self,
        query: str,
        match: str = "any",
        filters: dict[str, Any] | None = None,
        top_k: int = 5,
    ) -> dict[str, Any]:
        """Pure keyword/token search across docstrings and tags."""

    @abc.abstractmethod
    async def find_flow(
        self,
        start: str,
        end: str,
        flow_type: str = "data",
    ) -> dict[str, Any]:
        """Trace execution/data flow between two nodes."""

    @abc.abstractmethod
    async def diff(
        self,
        from_snapshot: str,
        to_snapshot: str,
        scope: str = "full",
    ) -> dict[str, Any]:
        """Compare two snapshots and return differences."""

    @abc.abstractmethod
    async def plan(
        self,
        change_description: str,
        target_file: str,
        change_type: str = "refactor",
        scope: str = "full",
    ) -> dict[str, Any]:
        """Generate a change plan for proposed modifications."""

    @abc.abstractmethod
    async def conflict(
        self,
        entity: str,
        proposed_change: str,
        context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Check for conflicts in proposed changes."""

    @abc.abstractmethod
    async def why(
        self,
        entity: str,
        relationship: str = "",
        depth: int = 3,
    ) -> dict[str, Any]:
        """Explain why a relationship exists."""
