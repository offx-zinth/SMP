"""Synchronisation, import, and integrity handlers.

Implements:
* ``smp/sync`` — compute the delta between a local and a remote graph
* ``smp/index/import`` — bulk-load nodes/edges from a serialised payload
* ``smp/integrity/check`` — compare a snapshot against the live graph
* ``smp/integrity/baseline`` — record a node baseline in semantic metadata

Payloads use simple dicts so they round-trip through JSON-RPC without
any custom encoder; ``msgspec.convert`` is used to validate inputs.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Any

import msgspec

from smp.core.models import (
    EdgeType,
    GraphEdge,
    GraphNode,
    IntegrityBaselineParams,
    IntegrityCheckParams,
    MerkleImportParams,
    MerkleSyncParams,
    NodeType,
    SemanticProperties,
    StructuralProperties,
)
from smp.logging import get_logger

log = get_logger(__name__)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _node_signature(node: GraphNode) -> str:
    """Deterministic content hash used to detect changed nodes."""
    payload = json.dumps(
        {
            "id": node.id,
            "type": node.type.value,
            "file": node.file_path,
            "name": node.structural.name,
            "signature": node.structural.signature,
            "start_line": node.structural.start_line,
            "end_line": node.structural.end_line,
        },
        sort_keys=True,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _node_from_dict(data: dict[str, Any]) -> GraphNode | None:
    """Build a :class:`GraphNode` from a loose JSON dict.  Returns ``None`` on failure."""
    try:
        node_type = NodeType(data.get("type", "Function"))
    except ValueError:
        return None

    structural_data = data.get("structural") or {}
    semantic_data = data.get("semantic") or {}
    structural = msgspec.convert(structural_data, StructuralProperties) if structural_data else StructuralProperties()
    semantic = (
        msgspec.convert(semantic_data, SemanticProperties)
        if semantic_data
        else SemanticProperties()
    )

    node_id = data.get("id")
    file_path = data.get("file_path") or data.get("file") or ""
    if not node_id:
        return None

    return GraphNode(
        id=node_id,
        type=node_type,
        file_path=file_path,
        structural=structural,
        semantic=semantic,
    )


def _edge_from_dict(data: dict[str, Any]) -> GraphEdge | None:
    try:
        edge_type = EdgeType(data.get("type", "CALLS"))
    except ValueError:
        return None

    source = data.get("source_id") or data.get("source")
    target = data.get("target_id") or data.get("target")
    if not source or not target:
        return None
    metadata_raw = data.get("metadata") or {}
    metadata = {str(k): str(v) for k, v in metadata_raw.items()}
    return GraphEdge(source_id=source, target_id=target, type=edge_type, metadata=metadata)


async def sync(params: dict[str, Any], ctx: dict[str, Any]) -> dict[str, Any]:
    """Handle ``smp/sync`` — compute the delta vs a remote graph snapshot."""
    p = msgspec.convert(params, MerkleSyncParams)
    graph = ctx["graph"]

    remote_nodes = p.remote_data.get("nodes", []) or []
    remote_signatures: dict[str, str] = {}
    for entry in remote_nodes:
        if isinstance(entry, dict):
            node_id = entry.get("id")
            sig = entry.get("signature") or entry.get("hash")
            if node_id and sig:
                remote_signatures[node_id] = str(sig)

    local_nodes = await graph.find_nodes()
    local_signatures = {node.id: _node_signature(node) for node in local_nodes}

    remote_ids = set(remote_signatures)
    local_ids = set(local_signatures)

    missing_locally = sorted(remote_ids - local_ids)
    missing_remotely = sorted(local_ids - remote_ids)
    changed = sorted(
        node_id
        for node_id in remote_ids & local_ids
        if remote_signatures[node_id] != local_signatures[node_id]
    )

    return {
        "in_sync": not (missing_locally or missing_remotely or changed),
        "missing_locally": missing_locally,
        "missing_remotely": missing_remotely,
        "changed": changed,
        "stats": {
            "local_count": len(local_signatures),
            "remote_count": len(remote_signatures),
            "missing_locally": len(missing_locally),
            "missing_remotely": len(missing_remotely),
            "changed": len(changed),
        },
    }


async def index_import(params: dict[str, Any], ctx: dict[str, Any]) -> dict[str, Any]:
    """Handle ``smp/index/import`` — bulk-load nodes/edges from a payload."""
    p = msgspec.convert(params, MerkleImportParams)
    graph = ctx["graph"]

    raw_nodes = p.data.get("nodes", []) or []
    raw_edges = p.data.get("edges", []) or []

    parsed_nodes: list[GraphNode] = []
    skipped_nodes = 0
    for entry in raw_nodes:
        if not isinstance(entry, dict):
            skipped_nodes += 1
            continue
        node = _node_from_dict(entry)
        if node is None:
            skipped_nodes += 1
            continue
        parsed_nodes.append(node)

    parsed_edges: list[GraphEdge] = []
    skipped_edges = 0
    for entry in raw_edges:
        if not isinstance(entry, dict):
            skipped_edges += 1
            continue
        edge = _edge_from_dict(entry)
        if edge is None:
            skipped_edges += 1
            continue
        parsed_edges.append(edge)

    if parsed_nodes:
        await graph.upsert_nodes(parsed_nodes)
    if parsed_edges:
        await graph.upsert_edges(parsed_edges)

    return {
        "imported_nodes": len(parsed_nodes),
        "imported_edges": len(parsed_edges),
        "skipped_nodes": skipped_nodes,
        "skipped_edges": skipped_edges,
    }


async def integrity_check(params: dict[str, Any], ctx: dict[str, Any]) -> dict[str, Any]:
    """Handle ``smp/integrity/check``.

    Two modes:

    * **Node-level** (``node_id`` provided): compare the supplied signature
      against the live node hash.  Returns ``matches=True`` if they agree.
    * **Store-level** (``node_id`` empty): run the full on-disk integrity
      report from :meth:`MMapGraphStore.integrity_report` when the
      backing store supports it.
    """
    p = msgspec.convert(params, IntegrityCheckParams)
    graph = ctx["graph"]

    if not p.node_id:
        if hasattr(graph, "integrity_report"):
            report = await graph.integrity_report()
            return {
                "scope": "store",
                "checked_at": _now_iso(),
                **report,
            }
        return {
            "scope": "store",
            "checked_at": _now_iso(),
            "ok": True,
            "warnings": [],
            "errors": [],
            "stats": {"unsupported": True},
        }

    node = await graph.get_node(p.node_id)
    if node is None:
        return {"node_id": p.node_id, "matches": False, "error": "node_not_found"}

    current_signature = _node_signature(node)
    expected_signature = p.current_state.get("signature") or p.current_state.get("hash")

    matches = expected_signature == current_signature if expected_signature else False
    return {
        "node_id": p.node_id,
        "matches": matches,
        "current_signature": current_signature,
        "expected_signature": expected_signature,
        "checked_at": _now_iso(),
    }


async def integrity_baseline(params: dict[str, Any], ctx: dict[str, Any]) -> dict[str, Any]:
    """Handle ``smp/integrity/baseline`` — store a baseline signature on the node."""
    p = msgspec.convert(params, IntegrityBaselineParams)
    graph = ctx["graph"]

    node = await graph.get_node(p.node_id)
    if node is None:
        return {"node_id": p.node_id, "baseline_set": False, "error": "node_not_found"}

    signature = p.state.get("signature") if p.state else None
    if not signature:
        signature = _node_signature(node)

    new_semantic = msgspec.structs.replace(
        node.semantic,
        source_hash=str(signature),
        enriched_at=_now_iso(),
    )
    updated = msgspec.structs.replace(node, semantic=new_semantic)
    await graph.upsert_node(updated)

    return {
        "node_id": p.node_id,
        "baseline_set": True,
        "signature": signature,
    }


__all__ = [
    "index_import",
    "integrity_baseline",
    "integrity_check",
    "sync",
]
