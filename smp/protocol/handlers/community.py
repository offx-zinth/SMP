"""Community detection handlers (smp/community/*).

Communities are derived via connected-component analysis over the
graph store, optionally filtered by a list of relationship types.
The result is cached in ``ctx["_communities"]`` so subsequent
``list``/``get``/``boundaries`` calls return consistent ids.
"""

from __future__ import annotations

import uuid
from collections import defaultdict
from typing import Any

import msgspec

from smp.core.models import (
    CommunityBoundariesParams,
    CommunityDetectParams,
    CommunityGetParams,
    CommunityListParams,
    EdgeType,
)
from smp.logging import get_logger

log = get_logger(__name__)


def _community_store(ctx: dict[str, Any]) -> dict[str, Any]:
    return ctx.setdefault("_communities", {"by_id": {}, "node_to_id": {}, "level": 0})  # type: ignore[no-any-return]


async def _detect_components(
    graph: Any, edge_types: set[EdgeType] | None = None
) -> tuple[dict[str, list[str]], dict[str, str]]:
    """Find connected components in the undirected projection of the graph."""
    nodes = await graph.find_nodes()
    adjacency: dict[str, set[str]] = defaultdict(set)
    for node in nodes:
        edges = await graph.get_edges(node.id, direction="both")
        for edge in edges:
            if edge_types and edge.type not in edge_types:
                continue
            adjacency[edge.source_id].add(edge.target_id)
            adjacency[edge.target_id].add(edge.source_id)

    visited: set[str] = set()
    components: dict[str, list[str]] = {}
    node_to_community: dict[str, str] = {}

    for node in nodes:
        if node.id in visited:
            continue
        component_id = f"com_{uuid.uuid4().hex[:10]}"
        stack = [node.id]
        members: list[str] = []
        while stack:
            current = stack.pop()
            if current in visited:
                continue
            visited.add(current)
            members.append(current)
            node_to_community[current] = component_id
            stack.extend(adjacency.get(current, set()) - visited)
        components[component_id] = members

    return components, node_to_community


async def community_detect(params: dict[str, Any], ctx: dict[str, Any]) -> dict[str, Any]:
    """Handle ``smp/community/detect``."""
    p = msgspec.convert(params, CommunityDetectParams)
    graph = ctx["graph"]

    edge_types: set[EdgeType] | None = None
    if p.relationship_types:
        edge_types = set()
        for raw in p.relationship_types:
            try:
                edge_types.add(EdgeType(raw))
            except ValueError:
                continue
        if not edge_types:
            edge_types = None

    components, node_to_id = await _detect_components(graph, edge_types=edge_types)

    store = _community_store(ctx)
    store["by_id"] = components
    store["node_to_id"] = node_to_id
    store["level"] = max(0, len(p.resolutions) - 1) if p.resolutions else 0

    summary = [
        {
            "community_id": cid,
            "size": len(members),
            "level": store["level"],
        }
        for cid, members in components.items()
    ]
    summary.sort(key=lambda c: -c["size"])

    return {
        "level": store["level"],
        "communities": summary,
        "total": len(components),
        "node_count": sum(len(v) for v in components.values()),
    }


async def community_list(params: dict[str, Any], ctx: dict[str, Any]) -> dict[str, Any]:
    """Handle ``smp/community/list``."""
    p = msgspec.convert(params, CommunityListParams)
    graph = ctx["graph"]
    store = _community_store(ctx)

    if not store["by_id"]:
        components, node_to_id = await _detect_components(graph)
        store["by_id"] = components
        store["node_to_id"] = node_to_id
        store["level"] = 0

    level = p.level if p.level is not None else store.get("level", 0)
    summary = [
        {
            "community_id": cid,
            "size": len(members),
            "level": level,
        }
        for cid, members in store["by_id"].items()
    ]
    summary.sort(key=lambda c: -c["size"])
    return {"level": level, "communities": summary, "total": len(summary)}


async def community_get(params: dict[str, Any], ctx: dict[str, Any]) -> dict[str, Any]:
    """Handle ``smp/community/get``."""
    p = msgspec.convert(params, CommunityGetParams)
    graph = ctx["graph"]
    store = _community_store(ctx)

    if not store["by_id"]:
        components, node_to_id = await _detect_components(graph)
        store["by_id"] = components
        store["node_to_id"] = node_to_id

    members = store["by_id"].get(p.community_id, [])
    if not members:
        return {"community_id": p.community_id, "nodes": [], "bridges": [], "size": 0}

    member_set = set(members)
    type_filter = set(p.node_types) if p.node_types else None

    nodes_payload: list[dict[str, Any]] = []
    for node_id in members:
        node = await graph.get_node(node_id)
        if node is None:
            continue
        if type_filter and node.type.value not in type_filter:
            continue
        nodes_payload.append(
            {
                "id": node.id,
                "name": node.structural.name,
                "type": node.type.value,
                "file": node.file_path,
            }
        )

    bridges: list[dict[str, str]] = []
    if p.include_bridges:
        for node_id in members:
            edges = await graph.get_edges(node_id, direction="outgoing")
            for edge in edges:
                if edge.target_id not in member_set:
                    bridges.append(
                        {
                            "source": edge.source_id,
                            "target": edge.target_id,
                            "edge_type": edge.type.value,
                        }
                    )

    return {
        "community_id": p.community_id,
        "size": len(members),
        "nodes": nodes_payload,
        "bridges": bridges,
    }


async def community_boundaries(params: dict[str, Any], ctx: dict[str, Any]) -> dict[str, Any]:
    """Handle ``smp/community/boundaries``."""
    p = msgspec.convert(params, CommunityBoundariesParams)
    graph = ctx["graph"]
    store = _community_store(ctx)

    if not store["by_id"]:
        components, node_to_id = await _detect_components(graph)
        store["by_id"] = components
        store["node_to_id"] = node_to_id

    node_to_id = store["node_to_id"]
    cross_edges: dict[tuple[str, str], int] = defaultdict(int)
    cross_examples: dict[tuple[str, str], list[dict[str, str]]] = defaultdict(list)

    for community_id, members in store["by_id"].items():
        for node_id in members:
            edges = await graph.get_edges(node_id, direction="outgoing")
            for edge in edges:
                target_community = node_to_id.get(edge.target_id)
                if target_community and target_community != community_id:
                    key = (community_id, target_community)
                    cross_edges[key] += 1
                    if len(cross_examples[key]) < 3:
                        cross_examples[key].append(
                            {
                                "source": edge.source_id,
                                "target": edge.target_id,
                                "edge_type": edge.type.value,
                            }
                        )

    total_member_edges: dict[str, int] = defaultdict(int)
    for community_id, members in store["by_id"].items():
        for node_id in members:
            edges = await graph.get_edges(node_id, direction="outgoing")
            total_member_edges[community_id] += len(edges)

    boundaries: list[dict[str, Any]] = []
    for (a, b), count in cross_edges.items():
        denom = total_member_edges.get(a, 0) or 1
        coupling = count / denom
        if coupling >= p.min_coupling:
            boundaries.append(
                {
                    "from_community": a,
                    "to_community": b,
                    "edge_count": count,
                    "coupling": round(coupling, 4),
                    "examples": cross_examples[(a, b)],
                }
            )

    boundaries.sort(key=lambda b: -b["coupling"])
    return {"level": p.level, "min_coupling": p.min_coupling, "boundaries": boundaries}


__all__ = [
    "community_boundaries",
    "community_detect",
    "community_get",
    "community_list",
]
