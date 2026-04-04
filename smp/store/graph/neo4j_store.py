"""Neo4j-backed graph store implementation.

Uses the official ``neo4j`` Python driver with async support.
"""

from __future__ import annotations

from typing import Any, Sequence

from neo4j import AsyncDriver, AsyncGraphDatabase

from smp.core.models import EdgeType, GraphEdge, GraphNode, NodeType
from smp.logging import get_logger
from smp.store.interfaces import GraphStore

log = get_logger(__name__)

# Label used on every node so we can enumerate all quickly.
_ALL_LABEL = "SMPNode"


def _node_to_props(node: GraphNode) -> dict[str, Any]:
    """Convert a GraphNode to a flat dict suitable for Neo4j properties."""
    return {
        "id": node.id,
        "type": node.type.value,
        "name": node.name,
        "file_path": node.file_path,
        "start_line": node.start_line,
        "end_line": node.end_line,
        "signature": node.signature,
        "docstring": node.docstring,
        "metadata": str(node.metadata),  # Neo4j stores strings; we JSON-encode later if needed
        "semantic_purpose": node.semantic.purpose if node.semantic else "",
        "semantic_confidence": node.semantic.confidence if node.semantic else 0.0,
    }


def _record_to_node(record: dict[str, Any]) -> GraphNode:
    """Reconstruct a GraphNode from a Neo4j record."""
    from smp.core.models import SemanticInfo

    sem_purpose = record.get("semantic_purpose", "")
    sem_conf = record.get("semantic_confidence", 0.0)
    semantic = SemanticInfo(purpose=sem_purpose, confidence=sem_conf) if sem_purpose else None

    return GraphNode(
        id=record["id"],
        type=NodeType(record["type"]),
        name=record["name"],
        file_path=record["file_path"],
        start_line=record.get("start_line", 0),
        end_line=record.get("end_line", 0),
        signature=record.get("signature", ""),
        docstring=record.get("docstring", ""),
        semantic=semantic,
    )


class Neo4jGraphStore(GraphStore):
    """Graph store backed by a Neo4j instance."""

    def __init__(
        self,
        uri: str = "bolt://localhost:7687",
        user: str = "neo4j",
        password: str = "123456789$Do",
        database: str = "neo4j",
    ) -> None:
        self._uri = uri
        self._user = user
        self._password = password
        self._database = database
        self._driver: AsyncDriver | None = None

    # -- Lifecycle -----------------------------------------------------------

    async def connect(self) -> None:
        self._driver = AsyncGraphDatabase.driver(
            self._uri, auth=(self._user, self._password)
        )
        await self._driver.verify_connectivity()
        log.info("neo4j_connected", uri=self._uri)
        # Ensure uniqueness constraint on node id
        await self._execute(
            f"CREATE CONSTRAINT IF NOT EXISTS FOR (n:{_ALL_LABEL}) REQUIRE n.id IS UNIQUE"
        )

    async def close(self) -> None:
        if self._driver:
            await self._driver.close()
            self._driver = None
            log.info("neo4j_closed")

    async def clear(self) -> None:
        await self._execute("MATCH (n) DETACH DELETE n")
        log.warning("neo4j_cleared")

    # -- Node CRUD -----------------------------------------------------------

    async def upsert_node(self, node: GraphNode) -> None:
        props = _node_to_props(node)
        # Neo4j can't have :Label(property) with hyphens in labels; use single label
        labels = f"{_ALL_LABEL}:{node.type.value}"
        cypher = f"""
        MERGE (n:{labels} {{id: $id}})
        SET n += $props
        """
        await self._execute(cypher, {"id": node.id, "props": props})
        log.debug("node_upserted", node_id=node.id)

    async def upsert_nodes(self, nodes: Sequence[GraphNode]) -> None:
        if not nodes:
            return
        # Batch using UNWIND for performance
        batch = [_node_to_props(n) for n in nodes]
        cypher = f"""
        UNWIND $batch AS row
        MERGE (n:{_ALL_LABEL} {{id: row.id}})
        SET n += row
        """
        await self._execute(cypher, {"batch": batch})
        log.info("nodes_upserted_batch", count=len(nodes))

    async def get_node(self, node_id: str) -> GraphNode | None:
        cypher = f"MATCH (n:{_ALL_LABEL} {{id: $id}}) RETURN n"
        records = await self._execute(cypher, {"id": node_id})
        if not records:
            return None
        return _record_to_node(dict(records[0]["n"]))

    async def delete_node(self, node_id: str) -> bool:
        cypher = f"MATCH (n:{_ALL_LABEL} {{id: $id}}) DETACH DELETE n RETURN count(n) AS deleted"
        records = await self._execute(cypher, {"id": node_id})
        deleted = records[0]["deleted"] if records else 0
        return deleted > 0

    async def delete_nodes_by_file(self, file_path: str) -> int:
        cypher = f"""
        MATCH (n:{_ALL_LABEL})
        WHERE n.file_path = $file_path
        DETACH DELETE n
        RETURN count(n) AS deleted
        """
        records = await self._execute(cypher, {"file_path": file_path})
        deleted = records[0]["deleted"] if records else 0
        log.info("nodes_deleted_by_file", file_path=file_path, deleted=deleted)
        return deleted

    # -- Edge CRUD -----------------------------------------------------------

    async def upsert_edge(self, edge: GraphEdge) -> None:
        rel_type = edge.type.value
        cypher = f"""
        MATCH (a:{_ALL_LABEL} {{id: $source_id}})
        MATCH (b:{_ALL_LABEL} {{id: $target_id}})
        MERGE (a)-[r:{rel_type}]->(b)
        SET r += $metadata
        """
        await self._execute(
            cypher,
            {
                "source_id": edge.source_id,
                "target_id": edge.target_id,
                "metadata": edge.metadata,
            },
        )
        log.debug("edge_upserted", src=edge.source_id, tgt=edge.target_id, type=rel_type)

    async def upsert_edges(self, edges: Sequence[GraphEdge]) -> None:
        if not edges:
            return
        # We must do per-rel-type UNWIND since Cypher can't parameterise rel type
        grouped: dict[str, list[dict[str, Any]]] = {}
        for e in edges:
            grouped.setdefault(e.type.value, []).append(
                {"source_id": e.source_id, "target_id": e.target_id, "metadata": e.metadata}
            )
        for rel_type, batch in grouped.items():
            cypher = f"""
            UNWIND $batch AS row
            MATCH (a:{_ALL_LABEL} {{id: row.source_id}})
            MATCH (b:{_ALL_LABEL} {{id: row.target_id}})
            MERGE (a)-[r:{rel_type}]->(b)
            SET r += row.metadata
            """
            await self._execute(cypher, {"batch": batch})
        log.info("edges_upserted_batch", count=len(edges))

    async def get_edges(
        self,
        node_id: str,
        edge_type: EdgeType | None = None,
        direction: str = "both",
    ) -> list[GraphEdge]:
        type_filter = f":{edge_type.value}" if edge_type else ""
        if direction == "outgoing":
            pattern = f"(a:{_ALL_LABEL} {{id: $id}})-[r{type_filter}]->(b)"
        elif direction == "incoming":
            pattern = f"(a)-[r{type_filter}]->(b:{_ALL_LABEL} {{id: $id}})"
        else:
            pattern = f"(a:{_ALL_LABEL} {{id: $id}})-[r{type_filter}]-(b)"

        cypher = f"MATCH {pattern} RETURN a.id AS source, b.id AS target, type(r) AS rel_type"
        records = await self._execute(cypher, {"id": node_id})
        return [
            GraphEdge(
                source_id=rec["source"],
                target_id=rec["target"],
                type=EdgeType(rec["rel_type"]),
            )
            for rec in records
        ]

    # -- Traversal -----------------------------------------------------------

    async def get_neighbors(
        self,
        node_id: str,
        edge_type: EdgeType | None = None,
        depth: int = 1,
    ) -> list[GraphNode]:
        type_filter = f":{edge_type.value}" if edge_type else ""
        depth_str = f"1..{depth}"
        cypher = f"""
        MATCH (start:{_ALL_LABEL} {{id: $id}})-[r{type_filter}*{depth_str}]->(neighbor:{_ALL_LABEL})
        RETURN DISTINCT neighbor
        """
        records = await self._execute(cypher, {"id": node_id})
        return [_record_to_node(dict(rec["neighbor"])) for rec in records]

    async def traverse(
        self,
        start_id: str,
        edge_type: EdgeType,
        depth: int,
        max_nodes: int = 100,
    ) -> list[GraphNode]:
        rel_type = edge_type.value
        cypher = f"""
        MATCH path = (start:{_ALL_LABEL} {{id: $id}})-[r:{rel_type}*1..{depth}]->(node:{_ALL_LABEL})
        RETURN DISTINCT node
        LIMIT $max_nodes
        """
        records = await self._execute(cypher, {"id": start_id, "max_nodes": max_nodes})
        return [_record_to_node(dict(rec["node"])) for rec in records]

    # -- Search --------------------------------------------------------------

    async def find_nodes(
        self,
        *,
        type: NodeType | None = None,
        file_path: str | None = None,
        name: str | None = None,
    ) -> list[GraphNode]:
        conditions: list[str] = []
        params: dict[str, Any] = {}
        if type:
            conditions.append("n.type = $type")
            params["type"] = type.value
        if file_path:
            conditions.append("n.file_path = $file_path")
            params["file_path"] = file_path
        if name:
            conditions.append("n.name = $name")
            params["name"] = name

        where = " AND ".join(conditions)
        where_clause = f"WHERE {where}" if where else ""
        cypher = f"MATCH (n:{_ALL_LABEL}) {where_clause} RETURN n"
        records = await self._execute(cypher, params)
        return [_record_to_node(dict(rec["n"])) for rec in records]

    # -- Aggregation ---------------------------------------------------------

    async def count_nodes(self) -> int:
        cypher = f"MATCH (n:{_ALL_LABEL}) RETURN count(n) AS cnt"
        records = await self._execute(cypher)
        return records[0]["cnt"] if records else 0

    async def count_edges(self) -> int:
        cypher = "MATCH ()-[r]->() RETURN count(r) AS cnt"
        records = await self._execute(cypher)
        return records[0]["cnt"] if records else 0

    # -- Internal helpers ----------------------------------------------------

    async def _execute(self, cypher: str, params: dict[str, Any] | None = None) -> list[Any]:
        """Execute a Cypher query and return records."""
        if not self._driver:
            raise RuntimeError("Neo4jGraphStore is not connected. Call connect() first.")
        async with self._driver.session(database=self._database) as session:
            result = await session.run(cypher, params or {})
            return [rec.data() async for rec in result]
