"""Static semantic enricher with optional LLM-based embedding."""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from smp.core.models import GraphNode
from smp.engine.interfaces import SemanticEnricher as SemanticEnricherInterface
from smp.logging import get_logger

if TYPE_CHECKING:
    from smp.engine.embedding import EmbeddingService

log = get_logger(__name__)


def _compute_source_hash(name: str, file_path: str, start: int, end: int, signature: str) -> str:
    """Compute deterministic source hash for a node."""
    raw = f"{file_path}:{name}:{start}:{end}:{signature}"
    return hashlib.sha256(raw.encode()).hexdigest()[:8]


class StaticSemanticEnricher(SemanticEnricherInterface):
    """Static AST-based semantic enricher with optional embedding support."""

    def __init__(self, embedding_service: EmbeddingService | None = None) -> None:
        self._enrichment_counts: dict[str, int] = {
            "enriched": 0,
            "skipped": 0,
            "no_metadata": 0,
            "failed": 0,
        }
        self._embedding_service = embedding_service

    def set_embedding_service(self, service: EmbeddingService) -> None:
        self._embedding_service = service

    async def enrich_node(
        self,
        node: GraphNode,
        force: bool = False,
    ) -> GraphNode:
        """Enrich a single node with static metadata."""
        sem = node.semantic
        current_hash = _compute_source_hash(
            node.structural.name,
            node.file_path,
            node.structural.start_line,
            node.structural.end_line,
            node.structural.signature,
        )

        if not force and sem.source_hash and sem.source_hash == current_hash and sem.status != "no_metadata":
            self._enrichment_counts["skipped"] += 1
            return node

        sem.source_hash = current_hash

        has_docstring = bool(sem.docstring and sem.docstring.strip())
        has_decorators = bool(sem.decorators)
        has_annotations = bool(sem.annotations and (sem.annotations.params or sem.annotations.returns))

        if not has_docstring and not has_decorators and not has_annotations:
            sem.status = "no_metadata"
            self._enrichment_counts["no_metadata"] += 1
            sem.enriched_at = datetime.now(UTC).isoformat()
            return node

        sem.status = "enriched"
        sem.enriched_at = datetime.now(UTC).isoformat()

        self._enrichment_counts["enriched"] += 1
        return node

    async def enrich_batch(
        self,
        nodes: list[GraphNode],
        force: bool = False,
    ) -> list[GraphNode]:
        """Enrich multiple nodes."""
        enriched = []
        for node in nodes:
            result = await self.enrich_node(node, force=force)
            enriched.append(result)
        return enriched

    @property
    def has_llm(self) -> bool:
        """Check if LLM-based embedding is available."""
        return self._embedding_service is not None

    async def embed(self, text: str) -> list[float]:
        """Generate embedding using the embedding service if available."""
        if self._embedding_service is None:
            return []
        return await self._embedding_service.embed(text)

    async def embed_batch(self, texts: list[str]) -> list[list[float]]:
        """Generate embeddings for multiple texts."""
        if self._embedding_service is None:
            return [[] for _ in texts]
        return await self._embedding_service.embed_batch(texts)

    def get_counts(self) -> dict[str, int]:
        """Return enrichment statistics."""
        return dict(self._enrichment_counts)

    def reset_counts(self) -> None:
        """Reset enrichment counters."""
        for key in self._enrichment_counts:
            self._enrichment_counts[key] = 0