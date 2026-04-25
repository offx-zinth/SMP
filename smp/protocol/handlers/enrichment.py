"""Enrichment and annotation handlers (smp/enrich, smp/annotate, smp/tag).

Each handler is a plain ``async def`` accepting ``(params, ctx)`` and
returning a JSON-serialisable dict.  ``ctx`` is expected to provide a
``graph`` (a :class:`~smp.store.interfaces.GraphStore`).
"""

from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
from typing import Any

import msgspec

from smp.core.models import (
    AnnotateBulkParams,
    AnnotateParams,
    EnrichBatchParams,
    EnrichParams,
    EnrichStaleParams,
    EnrichStatusParams,
    GraphNode,
    SemanticProperties,
    TagParams,
)
from smp.logging import get_logger

log = get_logger(__name__)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _replace_semantic(node: GraphNode, **changes: Any) -> GraphNode:
    """Return a copy of *node* with ``semantic`` replaced via msgspec."""
    new_semantic = msgspec.structs.replace(node.semantic, **changes)
    return msgspec.structs.replace(node, semantic=new_semantic)


async def enrich(params: dict[str, Any], ctx: dict[str, Any]) -> dict[str, Any]:
    """Handle ``smp/enrich`` — mark a single node as enriched."""
    p = msgspec.convert(params, EnrichParams)
    graph = ctx["graph"]

    node = await graph.get_node(p.node_id)
    if node is None:
        return {"node_id": p.node_id, "enriched": False, "error": "node_not_found"}

    if not p.force and node.semantic.status == "enriched":
        return {"node_id": p.node_id, "enriched": False, "skipped": True, "reason": "already_enriched"}

    updated = _replace_semantic(
        node,
        status="enriched",
        enriched_at=_now_iso(),
    )
    await graph.upsert_node(updated)
    return {"node_id": p.node_id, "enriched": True}


async def enrich_batch(params: dict[str, Any], ctx: dict[str, Any]) -> dict[str, Any]:
    """Handle ``smp/enrich/batch`` — enrich all nodes within a scope."""
    p = msgspec.convert(params, EnrichBatchParams)
    graph = ctx["graph"]

    nodes = await graph.find_nodes_by_scope(p.scope) if p.scope and p.scope != "full" else await graph.find_nodes()

    enriched = 0
    skipped = 0
    timestamp = _now_iso()
    for node in nodes:
        if not p.force and node.semantic.status == "enriched":
            skipped += 1
            continue
        updated = _replace_semantic(node, status="enriched", enriched_at=timestamp)
        await graph.upsert_node(updated)
        enriched += 1

    return {"scope": p.scope, "enriched": enriched, "skipped": skipped, "total": len(nodes)}


async def enrich_stale(params: dict[str, Any], ctx: dict[str, Any]) -> dict[str, Any]:
    """Handle ``smp/enrich/stale`` — enrich nodes flagged as stale."""
    p = msgspec.convert(params, EnrichStaleParams)
    graph = ctx["graph"]

    nodes = await graph.find_nodes_by_scope(p.scope) if p.scope and p.scope != "full" else await graph.find_nodes()

    stale_statuses = {"no_metadata", "stale"}
    timestamp = _now_iso()
    enriched = 0
    for node in nodes:
        if node.semantic.status in stale_statuses:
            updated = _replace_semantic(node, status="enriched", enriched_at=timestamp)
            await graph.upsert_node(updated)
            enriched += 1

    return {"scope": p.scope, "enriched": enriched, "total": len(nodes)}


async def enrich_status(params: dict[str, Any], ctx: dict[str, Any]) -> dict[str, Any]:
    """Handle ``smp/enrich/status`` — count nodes grouped by enrichment status."""
    p = msgspec.convert(params, EnrichStatusParams)
    graph = ctx["graph"]

    nodes = await graph.find_nodes_by_scope(p.scope) if p.scope and p.scope != "full" else await graph.find_nodes()

    counts: Counter[str] = Counter(node.semantic.status or "no_metadata" for node in nodes)
    return {
        "scope": p.scope,
        "total": len(nodes),
        "by_status": dict(counts),
    }


async def annotate(params: dict[str, Any], ctx: dict[str, Any]) -> dict[str, Any]:
    """Handle ``smp/annotate`` — set description and tags on a node."""
    p = msgspec.convert(params, AnnotateParams)
    graph = ctx["graph"]

    node = await graph.get_node(p.node_id)
    if node is None:
        return {"node_id": p.node_id, "annotated": False, "error": "node_not_found"}

    if not p.force and node.semantic.manually_set:
        return {"node_id": p.node_id, "annotated": False, "skipped": True, "reason": "manually_set"}

    merged_tags = list(dict.fromkeys([*node.semantic.tags, *p.tags]))
    updated = _replace_semantic(
        node,
        description=p.description or node.semantic.description,
        tags=merged_tags,
        manually_set=True,
        enriched_at=_now_iso(),
    )
    await graph.upsert_node(updated)
    return {"node_id": p.node_id, "annotated": True, "tags": merged_tags}


async def annotate_bulk(params: dict[str, Any], ctx: dict[str, Any]) -> dict[str, Any]:
    """Handle ``smp/annotate/bulk`` — annotate multiple nodes in one request."""
    bp = msgspec.convert(params, AnnotateBulkParams)
    graph = ctx["graph"]

    annotated = 0
    missing: list[str] = []
    for item in bp.annotations:
        node = await graph.get_node(item.node_id)
        if node is None:
            missing.append(item.node_id)
            continue
        merged_tags = list(dict.fromkeys([*node.semantic.tags, *item.tags]))
        updated = _replace_semantic(
            node,
            description=item.description or node.semantic.description,
            tags=merged_tags,
            manually_set=True,
            enriched_at=_now_iso(),
        )
        await graph.upsert_node(updated)
        annotated += 1

    return {"annotated": annotated, "missing": missing, "total": len(bp.annotations)}


async def tag(params: dict[str, Any], ctx: dict[str, Any]) -> dict[str, Any]:
    """Handle ``smp/tag`` — add/remove/set tags across a scope."""
    p = msgspec.convert(params, TagParams)
    graph = ctx["graph"]

    if p.scope and p.scope != "full":
        nodes = await graph.find_nodes_by_scope(p.scope)
    else:
        nodes = await graph.find_nodes()

    action = p.action.lower()
    new_tags = list(p.tags)
    updated_count = 0
    for node in nodes:
        existing: list[str] = list(node.semantic.tags)
        if action == "add":
            merged = list(dict.fromkeys([*existing, *new_tags]))
        elif action == "remove":
            removal = set(new_tags)
            merged = [t for t in existing if t not in removal]
        elif action == "set":
            merged = list(dict.fromkeys(new_tags))
        else:
            merged = existing

        if merged != existing:
            await graph.upsert_node(_replace_semantic(node, tags=merged))
            updated_count += 1

    return {"scope": p.scope, "action": action, "updated": updated_count, "total": len(nodes)}


__all__ = [
    "annotate",
    "annotate_bulk",
    "enrich",
    "enrich_batch",
    "enrich_stale",
    "enrich_status",
    "tag",
]


# Keep ``SemanticProperties`` available for downstream consumers using
# ``from smp.protocol.handlers.enrichment import *``.
_ = SemanticProperties
