"""Handler for enrichment methods (smp/enrich, smp/enrich/batch, etc.)."""

from __future__ import annotations

from typing import Any

import msgspec

from smp.core.models import (
    EnrichBatchParams,
    EnrichParams,
    EnrichStaleParams,
    EnrichStatusParams,
)
from smp.engine.enricher import _compute_source_hash
from smp.logging import get_logger
from smp.protocol.handlers.base import MethodHandler

log = get_logger(__name__)


class EnrichHandler(MethodHandler):
    """Handles smp/enrich method."""

    @property
    def method(self) -> str:
        return "smp/enrich"

    async def handle(
        self,
        params: dict[str, Any],
        context: dict[str, Any],
    ) -> dict[str, Any]:
        ep = msgspec.convert(params, EnrichParams)
        engine = context["engine"]
        enricher = context["enricher"]

        node = await engine._graph.get_node(ep.node_id)
        if not node:
            raise ValueError(f"Node not found: {ep.node_id}")

        enriched = await enricher.enrich_node(node, force=ep.force)
        if enriched.semantic.source_hash and enriched.semantic.status == "enriched":
            await engine._graph.upsert_node(enriched)

        return {
            "node_id": enriched.id,
            "status": enriched.semantic.status,
            "docstring": enriched.semantic.docstring,
            "inline_comments": [{"line": c.line, "text": c.text} for c in enriched.semantic.inline_comments],
            "decorators": enriched.semantic.decorators,
            "annotations": {
                "params": (enriched.semantic.annotations.params if enriched.semantic.annotations else {}),
                "returns": (enriched.semantic.annotations.returns if enriched.semantic.annotations else None),
                "throws": (enriched.semantic.annotations.throws if enriched.semantic.annotations else []),
            }
            if enriched.semantic.annotations
            else {},
            "tags": enriched.semantic.tags,
            "source_hash": enriched.semantic.source_hash,
            "enriched_at": enriched.semantic.enriched_at,
        }


class EnrichBatchHandler(MethodHandler):
    """Handles smp/enrich/batch method."""

    @property
    def method(self) -> str:
        return "smp/enrich/batch"

    async def handle(
        self,
        params: dict[str, Any],
        context: dict[str, Any],
    ) -> dict[str, Any]:
        ebp = msgspec.convert(params, EnrichBatchParams)
        engine = context["engine"]
        enricher = context["enricher"]

        nodes = await engine._graph.find_nodes_by_scope(ebp.scope)
        enriched_count = 0
        skipped_count = 0
        no_metadata_count = 0
        no_metadata_nodes: list[str] = []

        for node in nodes:
            enriched = await enricher.enrich_node(node, force=ebp.force)
            if enriched.semantic.status == "enriched":
                enriched_count += 1
                await engine._graph.upsert_node(enriched)
            elif enriched.semantic.status == "skipped":
                skipped_count += 1
            elif enriched.semantic.status == "no_metadata":
                no_metadata_count += 1
                no_metadata_nodes.append(enriched.id)

        return {
            "enriched": enriched_count,
            "skipped": skipped_count,
            "no_metadata": no_metadata_count,
            "failed": 0,
            "no_metadata_nodes": no_metadata_nodes,
        }


class EnrichStaleHandler(MethodHandler):
    """Handles smp/enrich/stale method."""

    @property
    def method(self) -> str:
        return "smp/enrich/stale"

    async def handle(
        self,
        params: dict[str, Any],
        context: dict[str, Any],
    ) -> dict[str, Any]:
        esp = msgspec.convert(params, EnrichStaleParams)
        engine = context["engine"]

        nodes = await engine._graph.find_nodes_by_scope(esp.scope)
        stale_nodes = []

        for node in nodes:
            if node.semantic.source_hash:
                current = _compute_source_hash(
                    node.structural.name,
                    node.file_path,
                    node.structural.start_line,
                    node.structural.end_line,
                    node.structural.signature,
                )
                if current != node.semantic.source_hash:
                    stale_nodes.append(
                        {
                            "node_id": node.id,
                            "file": node.file_path,
                            "last_enriched": node.semantic.enriched_at,
                            "current_hash": current,
                            "enriched_hash": node.semantic.source_hash,
                        }
                    )

        return {"stale_count": len(stale_nodes), "stale_nodes": stale_nodes}


class EnrichStatusHandler(MethodHandler):
    """Handles smp/enrich/status method."""

    @property
    def method(self) -> str:
        return "smp/enrich/status"

    async def handle(
        self,
        params: dict[str, Any],
        context: dict[str, Any],
    ) -> dict[str, Any]:
        estp = msgspec.convert(params, EnrichStatusParams)
        engine = context["engine"]

        nodes = await engine._graph.find_nodes_by_scope(estp.scope)
        total = len(nodes)
        has_docstring = sum(1 for n in nodes if n.semantic.docstring)
        has_annotations = sum(
            1
            for n in nodes
            if n.semantic.annotations and (n.semantic.annotations.params or n.semantic.annotations.returns)
        )
        has_tags = sum(1 for n in nodes if n.semantic.tags)
        manually_annotated = sum(1 for n in nodes if n.semantic.manually_set)
        no_metadata = sum(1 for n in nodes if n.semantic.status == "no_metadata")
        coverage = round((total - no_metadata) / total * 100, 1) if total > 0 else 0

        return {
            "total_nodes": total,
            "has_docstring": has_docstring,
            "has_annotations": has_annotations,
            "has_tags": has_tags,
            "manually_annotated": manually_annotated,
            "no_metadata": no_metadata,
            "stale": 0,
            "coverage_pct": coverage,
        }
