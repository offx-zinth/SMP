"""Community detection using Louvain algorithm at two resolution levels.

Implements two-level community detection (coarse L0, fine L1) per the SMP(3)
specification. Creates Community nodes, MEMBER_OF edges, BRIDGES edges,
and centroid embeddings stored in ChromaDB for smp/locate Phase 0 routing.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from smp.core.models import EdgeType, GraphEdge, GraphNode, NodeType
from smp.logging import get_logger
from smp.store.interfaces import GraphStore, VectorStore

log = get_logger(__name__)


@dataclass
class Community:
    id: str = ""
    level: int = 0
    label: str = ""
    parent_community: str = ""
    majority_path_prefix: str = ""
    top_tags: list[str] = field(default_factory=list)
    member_count: int = 0
    file_count: int = 0
    internal_edge_count: int = 0
    external_edge_count: int = 0
    modularity_score: float = 0.0
    centroid_embedding_id: str = ""
    detected_at: str = ""


class CommunityDetector:
    """Two-level Louvain community detection over the structural graph."""

    def __init__(
        self,
        graph_store: GraphStore,
        vector_store: VectorStore | None = None,
        min_community_size: int = 5,
    ) -> None:
        self._graph = graph_store
        self._vector = vector_store
        self._min_size = min_community_size
        self._communities: dict[str, Community] = {}
        self._node_communities_l0: dict[str, str] = {}
        self._node_communities_l1: dict[str, str] = {}
        self._bridges: list[dict[str, Any]] = []

    async def detect(
        self,
        resolutions: list[dict[str, Any]] | None = None,
        relationship_types: list[str] | None = None,
    ) -> dict[str, Any]:
        if resolutions is None:
            resolutions = [
                {"level": 0, "resolution": 0.5, "label": "coarse"},
                {"level": 1, "resolution": 1.5, "label": "fine"},
            ]
        if relationship_types is None:
            relationship_types = ["CALLS", "IMPORTS", "DEFINES"]

        all_nodes = await self._graph.find_nodes()
        if not all_nodes:
            return {
                "nodes_assigned": 0,
                "bridge_edges": 0,
                "levels": {},
                "coarse_communities": [],
                "fine_communities": [],
            }

        edge_types = [EdgeType(rt) for rt in relationship_types if rt in EdgeType._value2member_map_]
        adjacency = await self._build_adjacency(all_nodes, edge_types)

        all_results: dict[str, dict[str, Any]] = {}
        for res_config in resolutions:
            level = res_config.get("level", 0)
            resolution = res_config.get("resolution", 1.0)
            label = res_config.get("label", "coarse" if level == 0 else "fine")

            assignments = self._louvain(all_nodes, adjacency, resolution)
            communities = self._build_communities(assignments, all_nodes, adjacency, level, label)

            if level == 0:
                self._node_communities_l0 = assignments
            else:
                self._node_communities_l1 = assignments

            for comm in communities.values():
                self._communities[comm.id] = comm
                await self._store_community_node(comm)
                await self._write_member_of_edges(comm, all_nodes, level)

            all_results[str(level)] = {
                "communities_found": len(communities),
                "modularity": self._compute_modularity(assignments, adjacency),
            }

        self._bridges = await self._detect_bridges(all_nodes, adjacency)
        await self._write_bridges_edges()

        if self._vector is not None:
            await self._compute_centroids(all_nodes)

        coarse = [
            {
                "id": c.id,
                "label": c.label,
                "member_count": c.member_count,
                "fine_children": sum(1 for fc in self._communities.values() if fc.parent_community == c.id),
            }
            for c in self._communities.values()
            if c.level == 0
        ]
        fine = [
            {"id": c.id, "parent": c.parent_community, "label": c.label, "member_count": c.member_count}
            for c in self._communities.values()
            if c.level == 1
        ]

        total_assigned = len(self._node_communities_l0)
        return {
            "nodes_assigned": total_assigned,
            "bridge_edges": len(self._bridges),
            "levels": all_results,
            "coarse_communities": coarse,
            "fine_communities": fine,
        }

    async def list_communities(self, level: int | None = None) -> dict[str, Any]:
        communities = list(self._communities.values())
        if level is not None:
            communities = [c for c in communities if c.level == level]
        return {
            "total": len(communities),
            "communities": [
                {
                    "id": c.id,
                    "level": c.level,
                    "parent_community": c.parent_community,
                    "label": c.label,
                    "majority_path_prefix": c.majority_path_prefix,
                    "top_tags": c.top_tags,
                    "member_count": c.member_count,
                    "file_count": c.file_count,
                    "internal_edge_count": c.internal_edge_count,
                    "external_edge_count": c.external_edge_count,
                    "modularity_score": c.modularity_score,
                    "bridge_communities": [b["to_community"] for b in self._bridges if b["from_community"] == c.id],
                }
                for c in communities
            ],
        }

    async def get_community(
        self,
        community_id: str,
        node_types: list[str] | None = None,
        include_bridges: bool = False,
    ) -> dict[str, Any] | None:
        comm = self._communities.get(community_id)
        if not comm:
            return None

        assignments = self._node_communities_l1 if comm.level == 1 else self._node_communities_l0
        member_ids = [nid for nid, cid in assignments.items() if cid == community_id]

        members: list[dict[str, Any]] = []
        for mid in member_ids:
            node = await self._graph.get_node(mid)
            if node is None:
                continue
            if node_types and node.type.value not in node_types:
                continue
            members.append(
                {
                    "id": node.id,
                    "type": node.type.value,
                    "name": node.structural.name,
                    "file": node.file_path,
                    "pagerank": 0.0,
                    "heat_score": 0,
                }
            )

        bridge_edges = []
        if include_bridges:
            bridge_edges = [
                b for b in self._bridges if b["from_community"] == community_id or b["to_community"] == community_id
            ]

        return {
            "community_id": comm.id,
            "level": comm.level,
            "parent_community": comm.parent_community,
            "label": comm.label,
            "member_count": comm.member_count,
            "members": members,
            "bridge_edges": bridge_edges,
        }

    async def get_boundaries(self, level: int = 0, min_coupling: float = 0.05) -> dict[str, Any]:
        level_bridges = [
            b
            for b in self._bridges
            if any(
                self._communities.get(b["from_community"], Community()).level == level,
                self._communities.get(b["to_community"], Community()).level == level,
            )
        ]
        filtered = [b for b in level_bridges if b.get("coupling_weight", 0) >= min_coupling]
        return {
            "level": level,
            "boundaries": filtered,
        }

    async def _build_adjacency(
        self,
        nodes: list[GraphNode],
        edge_types: list[EdgeType],
    ) -> dict[str, set[str]]:
        adj: dict[str, set[str]] = defaultdict(set)
        for node in nodes:
            adj[node.id] = set()
        for node in nodes:
            for et in edge_types:
                edges = await self._graph.get_edges(node.id, et, direction="outgoing")
                for edge in edges:
                    adj[node.id].add(edge.target_id)
                    if edge.target_id in adj:
                        adj[edge.target_id].add(node.id)
        return adj

    def _louvain(
        self,
        nodes: list[GraphNode],
        adjacency: dict[str, set[str]],
        resolution: float,
    ) -> dict[str, str]:
        community: dict[str, int] = {}
        for i, node in enumerate(nodes):
            community[node.id] = i

        improved = True
        iterations = 0
        max_iterations = 50

        while improved and iterations < max_iterations:
            improved = False
            iterations += 1
            for node in nodes:
                nid = node.id
                current_comm = community[nid]
                neighbor_comms: dict[int, int] = defaultdict(int)
                for neighbor_id in adjacency.get(nid, set()):
                    neighbor_comms[community[neighbor_id]] += 1

                if not neighbor_comms:
                    continue

                best_comm = current_comm
                best_gain = 0.0
                total_edges = sum(neighbor_comms.values())
                ki = len(adjacency.get(nid, set()))

                for comm, ki_comm in neighbor_comms.items():
                    sigma_tot = sum(1 for n, c in community.items() if c == comm and n in adjacency)
                    sigma_tot = max(sigma_tot, 1)
                    gain = resolution * ki_comm - ki * sigma_tot / (2 * total_edges) if total_edges > 0 else 0
                    if gain > best_gain:
                        best_gain = gain
                        best_comm = comm

                if best_comm != current_comm:
                    community[nid] = best_comm
                    improved = True

        comm_map: dict[str, str] = {}
        for nid, comm_id in community.items():
            comm_map[nid] = f"comm_{comm_id}"
        return comm_map

    def _compute_modularity(
        self,
        assignments: dict[str, str],
        adjacency: dict[str, set[str]],
    ) -> float:
        total_edges = sum(len(neighbors) for neighbors in adjacency.values())
        if total_edges == 0:
            return 0.0
        total_edges //= 2

        e_cc: dict[str, float] = defaultdict(float)
        a_c: dict[str, float] = defaultdict(float)

        for nid, neighbors in adjacency.items():
            c_i = assignments.get(nid, "")
            a_c[c_i] += len(neighbors)
            for neighbor_id in neighbors:
                c_j = assignments.get(neighbor_id, "")
                if c_i == c_j:
                    e_cc[c_i] += 1

        modularity = 0.0
        for c in e_cc:
            modularity += (e_cc[c] / (2.0 * total_edges if total_edges > 0 else 1)) - (
                a_c[c] / (2.0 * total_edges if total_edges > 0 else 1)
            ) ** 2
        return round(modularity, 4)

    def _build_communities(
        self,
        assignments: dict[str, str],
        nodes: list[GraphNode],
        adjacency: dict[str, set[str]],
        level: int,
        label: str,
    ) -> dict[str, Community]:
        comm_members: dict[str, list[GraphNode]] = defaultdict(list)
        for node in nodes:
            cid = assignments.get(node.id, "")
            if cid:
                comm_members[cid].append(node)

        communities: dict[str, Community] = {}
        for cid, members in comm_members.items():
            if len(members) < self._min_size:
                smallest_comm = min(communities, key=lambda k: len(comm_members[k])) if communities else None
                if smallest_comm:
                    for m in members:
                        assignments[m.id] = smallest_comm
                        communities[smallest_comm].member_count += 1
                    continue

            path_counts: dict[str, int] = defaultdict(int)
            tag_counts: dict[str, int] = defaultdict(int)
            file_set: set[str] = set()
            internal_edges = 0
            external_edges = 0

            for m in members:
                path_prefix = "/".join(m.file_path.split("/")[:2]) if "/" in m.file_path else m.file_path
                path_counts[path_prefix] += 1
                for tag in m.semantic.tags:
                    tag_counts[tag] += 1
                file_set.add(m.file_path)
                for neighbor_id in adjacency.get(m.id, set()):
                    if assignments.get(neighbor_id) == cid:
                        internal_edges += 1
                    else:
                        external_edges += 1

            majority_path = max(path_counts, key=path_counts.get) if path_counts else ""
            top_tags_sorted = sorted(tag_counts, key=tag_counts.get, reverse=True)[:5]

            parent = ""
            if level == 1:
                for m in members:
                    parent = self._node_communities_l0.get(m.id, "")
                    break

            communities[cid] = Community(
                id=cid,
                level=level,
                label=label + "_" + majority_path.split("/")[-1] if majority_path else label,
                parent_community=parent,
                majority_path_prefix=majority_path,
                top_tags=top_tags_sorted,
                member_count=len(members),
                file_count=len(file_set),
                internal_edge_count=internal_edges // 2,
                external_edge_count=external_edges,
                modularity_score=0.0,
                detected_at=datetime.now(UTC).isoformat(),
            )

        return communities

    async def _store_community_node(self, comm: Community) -> None:
        comm_node = GraphNode(
            id=comm.id,
            type=NodeType("Community") if "Community" in NodeType._value2member_map_ else NodeType.FILE,
            file_path=comm.majority_path_prefix,
            structural=__import__("smp.core.models", fromlist=["StructuralProperties"]).StructuralProperties(
                name=comm.label,
                file=comm.majority_path_prefix,
            ),
            semantic=__import__("smp.core.models", fromlist=["SemanticProperties"]).SemanticProperties(
                tags=comm.top_tags,
                enriched_at=comm.detected_at,
            ),
        )
        await self._graph.upsert_node(comm_node)

    async def _write_member_of_edges(self, comm: Community, nodes: list[GraphNode], level: int) -> None:
        assignments = self._node_communities_l1 if level == 1 else self._node_communities_l0
        for node in nodes:
            if assignments.get(node.id) == comm.id:
                edge = GraphEdge(
                    source_id=node.id,
                    target_id=comm.id,
                    type=EdgeType.MEMBER_OF if "MEMBER_OF" in EdgeType._value2member_map_ else EdgeType.REFERENCES,
                    metadata={"community_level": str(level)},
                )
                await self._graph.upsert_edge(edge)

    async def _detect_bridges(
        self,
        nodes: list[GraphNode],
        adjacency: dict[str, set[str]],
    ) -> list[dict[str, Any]]:
        bridges: list[dict[str, Any]] = []
        comm_pairs: dict[tuple[str, str], list[str]] = defaultdict(list)

        for node in nodes:
            cid = self._node_communities_l1.get(node.id, "")
            if not cid:
                continue
            for neighbor_id in adjacency.get(node.id, set()):
                neighbor_cid = self._node_communities_l1.get(neighbor_id, "")
                if neighbor_cid and neighbor_cid != cid:
                    pair = tuple(sorted([cid, neighbor_cid]))
                    comm_pairs[pair].append(node.id)

        for (c1, c2), bridge_nodes in comm_pairs.items():
            coupling = len(bridge_nodes) / max(self._communities.get(c1, Community()).member_count, 1)
            bridges.append(
                {
                    "from_community": c1,
                    "to_community": c2,
                    "edge_count": len(bridge_nodes),
                    "coupling_weight": round(coupling, 4),
                    "bridge_nodes": bridge_nodes,
                }
            )
        return bridges

    async def _write_bridges_edges(self) -> None:
        for bridge in self._bridges:
            edge_type = EdgeType.BRIDGES if "BRIDGES" in EdgeType._value2member_map_ else EdgeType.REFERENCES
            edge = GraphEdge(
                source_id=bridge["from_community"],
                target_id=bridge["to_community"],
                type=edge_type,
                metadata={"coupling_weight": str(bridge.get("coupling_weight", ""))},
            )
            await self._graph.upsert_edge(edge)

    async def _compute_centroids(self, nodes: list[GraphNode]) -> None:
        if self._vector is None:
            return
        from smp.engine.seed_walk import _simple_hash_embedding

        comm_nodes: dict[str, list[GraphNode]] = defaultdict(list)
        for node in nodes:
            cid = self._node_communities_l1.get(node.id, "")
            if cid:
                comm_nodes[cid].append(node)

        for cid, members in comm_nodes.items():
            if not members:
                continue
            all_vecs: list[list[float]] = []
            for m in members:
                text = m.structural.name + " " + (m.semantic.docstring or "")
                vec = _simple_hash_embedding(text)
                all_vecs.append(vec)

            dim = len(all_vecs[0]) if all_vecs else 128
            centroid = [0.0] * dim
            for vec in all_vecs:
                for i in range(dim):
                    centroid[i] += vec[i]
            n = len(all_vecs) if all_vecs else 1
            centroid = [c / n for c in centroid]

            comm = self._communities.get(cid)
            label = comm.label if comm else cid
            majority_path = comm.majority_path_prefix if comm else ""

            await self._vector.add_code_embedding(
                node_id=f"centroid_{cid}",
                embedding=centroid,
                metadata={
                    "collection_type": "centroid",
                    "community_id": cid,
                    "label": label,
                    "majority_path_prefix": majority_path,
                    "member_count": str(len(members)),
                },
                document=label,
            )
