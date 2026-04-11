"""Static semantic enricher — AST-based extraction, no LLM.

Extracts docstrings, inline comments, decorators, type annotations,
and computes source hashes purely from the AST.
"""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime

from smp.core.models import GraphNode
from smp.engine.interfaces import SemanticEnricher as SemanticEnricherInterface
from smp.logging import get_logger

log = get_logger(__name__)


def _compute_source_hash(name: str, file_path: str, start: int, end: int, signature: str) -> str:
    """Compute deterministic source hash for a node."""
    raw = f"{file_path}:{name}:{start}:{end}:{signature}"
    return hashlib.sha256(raw.encode()).hexdigest()[:8]


class LLMSemanticEnricher:
    """Legacy LLM enricher placeholder - not yet implemented."""

    def __init__(self) -> None:
        self._static = StaticSemanticEnricher()

    @property
    def has_llm(self) -> bool:
        return False

    async def enrich_node(self, node: GraphNode, force: bool = False) -> GraphNode:
        return await self._static.enrich_node(node, force=force)

    async def enrich_batch(self, nodes: list[GraphNode], force: bool = False) -> list[GraphNode]:
        return await self._static.enrich_batch(nodes, force=force)

    async def embed(self, text: str) -> list[float]:
        return []


class StaticSemanticEnricher(SemanticEnricherInterface):
    """Static AST-based semantic enricher. No LLM, no embeddings."""

    def __init__(self) -> None:
        self._enrichment_counts: dict[str, int] = {
            "enriched": 0,
            "skipped": 0,
            "no_metadata": 0,
            "failed": 0,
        }

    @property
    def has_llm(self) -> bool:
        return False

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

    async def embed(self, text: str) -> list[float]:
        """No-op embedding — static enricher does not use vectors."""
        return []

    def get_counts(self) -> dict[str, int]:
        """Return enrichment statistics."""
        return dict(self._enrichment_counts)

    def reset_counts(self) -> None:
        """Reset enrichment counters."""
        for key in self._enrichment_counts:
            self._enrichment_counts[key] = 0
