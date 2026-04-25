"""Analysis and telemetry handlers.

Wires up engine methods that already exist in
:class:`~smp.engine.query.DefaultQueryEngine` (``diff``, ``plan``,
``conflict``, ``why``) plus three telemetry endpoints that summarise
graph-wide counts and per-node degree.
"""

from __future__ import annotations

from typing import Any

import msgspec

from smp.core.models import (
    ConflictParams,
    DiffParams,
    PlanParams,
    TelemetryHotParams,
    TelemetryNodeParams,
    TelemetryParams,
    WhyParams,
)
from smp.logging import get_logger

log = get_logger(__name__)


async def diff(params: dict[str, Any], ctx: dict[str, Any]) -> dict[str, Any]:
    """Handle ``smp/diff``."""
    p = msgspec.convert(params, DiffParams)
    engine = ctx["engine"]
    return await engine.diff(p.from_snapshot, p.to_snapshot, p.scope)


async def plan(params: dict[str, Any], ctx: dict[str, Any]) -> dict[str, Any]:
    """Handle ``smp/plan``."""
    p = msgspec.convert(params, PlanParams)
    engine = ctx["engine"]
    return await engine.plan(p.change_description, p.target_file, p.change_type, p.scope)


async def conflict(params: dict[str, Any], ctx: dict[str, Any]) -> dict[str, Any]:
    """Handle ``smp/conflict``."""
    p = msgspec.convert(params, ConflictParams)
    engine = ctx["engine"]
    return await engine.conflict(p.entity, p.proposed_change, p.context)


async def why(params: dict[str, Any], ctx: dict[str, Any]) -> dict[str, Any]:
    """Handle ``smp/why``."""
    p = msgspec.convert(params, WhyParams)
    engine = ctx["engine"]
    return await engine.why(p.entity, p.relationship, p.depth)


async def _hot_nodes(graph: Any, threshold: int, top_k: int) -> list[dict[str, Any]]:
    """Compute the highest-degree nodes for telemetry summaries."""
    nodes = await graph.find_nodes()
    scored: list[tuple[int, dict[str, Any]]] = []
    for node in nodes:
        in_deg, out_deg = await graph.get_node_degree(node.id)
        degree = in_deg + out_deg
        if degree >= threshold:
            scored.append(
                (
                    degree,
                    {
                        "node_id": node.id,
                        "name": node.structural.name,
                        "file": node.file_path,
                        "type": node.type.value,
                        "degree": degree,
                        "in_degree": in_deg,
                        "out_degree": out_deg,
                    },
                )
            )
    scored.sort(key=lambda x: -x[0])
    return [item[1] for item in scored[:top_k]]


async def telemetry(params: dict[str, Any], ctx: dict[str, Any]) -> dict[str, Any]:
    """Handle ``smp/telemetry`` — return graph-wide telemetry."""
    p = msgspec.convert(params, TelemetryParams)
    graph = ctx["graph"]

    action = (p.action or "get_stats").lower()
    threshold = p.threshold if p.threshold is not None else 5

    if action in {"get_stats", "stats", "summary"}:
        node_count = await graph.count_nodes()
        edge_count = await graph.count_edges()
        return {
            "action": action,
            "nodes": node_count,
            "edges": edge_count,
            "hot_nodes": await _hot_nodes(graph, threshold=threshold, top_k=5),
        }

    if action == "hot_nodes":
        return {"action": action, "hot_nodes": await _hot_nodes(graph, threshold=threshold, top_k=10)}

    if action == "node" and p.node_id:
        return await telemetry_node({"node_id": p.node_id}, ctx)

    return {"action": action, "nodes": await graph.count_nodes(), "edges": await graph.count_edges()}


async def telemetry_hot(params: dict[str, Any], ctx: dict[str, Any]) -> dict[str, Any]:
    """Handle ``smp/telemetry/hot`` — degree report for a single node."""
    p = msgspec.convert(params, TelemetryHotParams)
    graph = ctx["graph"]

    node = await graph.get_node(p.node_id)
    if node is None:
        return {"node_id": p.node_id, "is_hot": False, "error": "node_not_found"}

    in_deg, out_deg = await graph.get_node_degree(p.node_id)
    degree = in_deg + out_deg
    return {
        "node_id": p.node_id,
        "name": node.structural.name,
        "file": node.file_path,
        "in_degree": in_deg,
        "out_degree": out_deg,
        "degree": degree,
        "is_hot": degree > 10 or node.structural.complexity > 8,
        "complexity": node.structural.complexity,
    }


async def telemetry_node(params: dict[str, Any], ctx: dict[str, Any]) -> dict[str, Any]:
    """Handle ``smp/telemetry/node`` — detailed per-node telemetry."""
    p = msgspec.convert(params, TelemetryNodeParams)
    graph = ctx["graph"]

    node = await graph.get_node(p.node_id)
    if node is None:
        return {"node_id": p.node_id, "error": "node_not_found"}

    edges_out = await graph.get_edges(p.node_id, direction="outgoing")
    edges_in = await graph.get_edges(p.node_id, direction="incoming")

    by_type_out: dict[str, int] = {}
    for edge in edges_out:
        by_type_out[edge.type.value] = by_type_out.get(edge.type.value, 0) + 1

    by_type_in: dict[str, int] = {}
    for edge in edges_in:
        by_type_in[edge.type.value] = by_type_in.get(edge.type.value, 0) + 1

    return {
        "node_id": p.node_id,
        "name": node.structural.name,
        "file": node.file_path,
        "type": node.type.value,
        "in_degree": len(edges_in),
        "out_degree": len(edges_out),
        "edges_by_type_out": by_type_out,
        "edges_by_type_in": by_type_in,
        "complexity": node.structural.complexity,
        "lines": node.structural.lines,
        "tags": node.semantic.tags,
    }


__all__ = [
    "conflict",
    "diff",
    "plan",
    "telemetry",
    "telemetry_hot",
    "telemetry_node",
    "why",
]
