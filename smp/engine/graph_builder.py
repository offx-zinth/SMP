"""Graph builder — maps parsed Documents into the graph store.

Phase 2 will implement full ingestion logic.
"""

from __future__ import annotations

from smp.core.models import Document
from smp.engine.interfaces import GraphBuilder as GraphBuilderInterface
from smp.logging import get_logger
from smp.store.interfaces import GraphStore

log = get_logger(__name__)


class DefaultGraphBuilder(GraphBuilderInterface):
    """GraphBuilder that writes document nodes/edges into a GraphStore."""

    def __init__(self, graph_store: GraphStore) -> None:
        self._store = graph_store

    async def ingest_document(self, document: Document) -> None:
        if document.nodes:
            await self._store.upsert_nodes(document.nodes)
        if document.edges:
            await self._store.upsert_edges(document.edges)
        log.info("document_ingested", file_path=document.file_path, nodes=len(document.nodes), edges=len(document.edges))

    async def remove_document(self, file_path: str) -> None:
        deleted = await self._store.delete_nodes_by_file(file_path)
        log.info("document_removed", file_path=file_path, deleted=deleted)
