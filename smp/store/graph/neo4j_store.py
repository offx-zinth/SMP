"""Neo4j-backed graph store implementation.

Uses the official ``neo4j`` Python driver with async support.
Updated for SMP(3) partitioned schema (structural + semantic).
"""

from __future__ import annotations

import os
from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any

from neo4j import AsyncDriver, AsyncGraphDatabase

from smp.core.models import (
    Annotations,
    EdgeType,
    GraphEdge,
    GraphNode,
    InlineComment,
    NodeType,
    SemanticProperties,
    StructuralProperties,
)
from smp.logging import get_logger
from smp.store.interfaces import GraphStore

log = get_logger(__name__)

_ALL_LABEL = "SMPNode"
_SESSION_LABEL = "SMPSession"
_LOCK_LABEL = "SMPLck"


def _node_to_props(node: GraphNode) -> dict[str, Any]:
    """Convert a GraphNode to flat Neo4j properties."""
    return {
        "id": node.id,
        "type": node.type.value,
        "file_path": node.file_path,
        "structural_name": node.structural.name,
        "structural_file": node.structural.file,
        "structural_signature": node.structural.signature,
        "structural_start_line": node.structural.start_line,
        "structural_end_line": node.structural.end_line,
        "structural_complexity": node.structural.complexity,
        "structural_lines": node.structural.lines,
        "structural_parameters": node.structural.parameters,
        "semantic_status": node.semantic.status,
        "semantic_docstring": node.semantic.docstring,
        "semantic_description": node.semantic.description or "",
        "semantic_decorators": str(node.semantic.decorators),
        "semantic_tags": str(node.semantic.tags),
        "semantic_manually_set": node.semantic.manually_set,
        "semantic_source_hash": node.semantic.source_hash,
        "semantic_enriched_at": node.semantic.enriched_at,
        "semantic_annotations": str(node.semantic.annotations) if node.semantic.annotations else "",
        "semantic_inline_comments": str(node.semantic.inline_comments),
    }


def _record_to_node(record: dict[str, Any]) -> GraphNode:
    """Reconstruct a GraphNode from a Neo4j record."""
    structural = StructuralProperties(
        name=record.get("structural_name", ""),
        file=record.get("structural_file", ""),
        signature=record.get("structural_signature", ""),
        start_line=record.get("structural_start_line", 0),
        end_line=record.get("structural_end_line", 0),
        complexity=record.get("structural_complexity", 0),
        lines=record.get("structural_lines", 0),
        parameters=record.get("structural_parameters", 0),
    )

    annotations_raw = record.get("semantic_annotations", "")
    annotations: Annotations | None = None
    if annotations_raw and annotations_raw != "":
        try:
            import ast

            parsed = ast.literal_eval(annotations_raw)
            if isinstance(parsed, dict):
                annotations = Annotations(
                    params=parsed.get("params", {}),
                    returns=parsed.get("returns"),
                    throws=parsed.get("throws", []),
                )
        except (ValueError, SyntaxError):
            pass

    decorators_raw = record.get("semantic_decorators", "[]")
    try:
        import ast

        decorators = ast.literal_eval(decorators_raw) if decorators_raw else []
        if not isinstance(decorators, list):
            decorators = []
    except (ValueError, SyntaxError):
        decorators = []

    tags_raw = record.get("semantic_tags", "[]")
    try:
        import ast

        tags = ast.literal_eval(tags_raw) if tags_raw else []
        if not isinstance(tags, list):
            tags = []
    except (ValueError, SyntaxError):
        tags = []

    comments_raw = record.get("semantic_inline_comments", "[]")
    inline_comments: list[InlineComment] = []
    try:
        import ast

        parsed_comments = ast.literal_eval(comments_raw) if comments_raw else []
        if isinstance(parsed_comments, list):
            for c in parsed_comments:
                if isinstance(c, dict):
                    inline_comments.append(InlineComment(line=c.get("line", 0), text=c.get("text", "")))
                elif isinstance(c, InlineComment):
                    inline_comments.append(c)
    except (ValueError, SyntaxError):
        pass

    semantic = SemanticProperties(
        status=record.get("semantic_status", "no_metadata"),
        docstring=record.get("semantic_docstring", ""),
        description=record.get("semantic_description") or None,
        inline_comments=inline_comments,
        decorators=decorators,
        annotations=annotations,
        tags=tags,
        manually_set=record.get("semantic_manually_set", False),
        source_hash=record.get("semantic_source_hash", ""),
        enriched_at=record.get("semantic_enriched_at", ""),
    )

    return GraphNode(
        id=record["id"],
        type=NodeType(record["type"]),
        file_path=record["file_path"],
        structural=structural,
        semantic=semantic,
    )


class Neo4jGraphStore(GraphStore):
    """Graph store backed by a Neo4j instance."""

    def __init__(
        self,
        uri: str = "",
        user: str = "",
        password: str = "",
        database: str = "neo4j",
    ) -> None:
        self._uri = uri or os.environ.get("SMP_NEO4J_URI", "bolt://localhost:7687")
        self._user = user or os.environ.get("SMP_NEO4J_USER", "neo4j")
        self._password = password or os.environ.get("SMP_NEO4J_PASSWORD", "")
        self._database = database
        self._driver: AsyncDriver | None = None

    async def connect(self) -> None:
        self._driver = AsyncGraphDatabase.driver(self._uri, auth=(self._user, self._password))
        await self._driver.verify_connectivity()
        log.info("neo4j_connected", uri=self._uri)
        await self._execute(f"CREATE CONSTRAINT IF NOT EXISTS FOR (n:{_ALL_LABEL}) REQUIRE n.id IS UNIQUE")

        # Create full-text index for search
        await self._execute(
            f"CREATE FULLTEXT INDEX node_search_index IF NOT EXISTS FOR (n:{_ALL_LABEL}) "
            "ON EACH [n.semantic_docstring, n.semantic_description, n.structural_name, n.file_path]"
        )

    async def close(self) -> None:
        if self._driver:
            await self._driver.close()
            self._driver = None
            log.info("neo4j_closed")

    async def clear(self) -> None:
        await self._execute("MATCH (n) DETACH DELETE n")
        log.warning("neo4j_cleared")

    async def upsert_node(self, node: GraphNode) -> None:
        props = _node_to_props(node)
        cypher = f"""
        MERGE (n:{_ALL_LABEL} {{id: $id}})
        SET n += $props
        """
        await self._execute(cypher, {"id": node.id, "props": props})
        log.debug("node_upserted", node_id=node.id)

    async def upsert_session(self, session: Any) -> None:
        """Store or update a session in the graph."""
        props = {
            "session_id": session.session_id,
            "agent_id": session.agent_id,
            "task": session.task,
            "mode": session.mode,
            "opened_at": session.opened_at,
            "expires_at": session.expires_at,
            "status": session.status,
            "files_written": session.files_written,
            "files_read": session.files_read,
        }
        cypher = f"""
        MERGE (n:{_SESSION_LABEL} {{session_id: $session_id}})
        SET n += $props
        """
        await self._execute(cypher, {"session_id": session.session_id, "props": props})
        log.debug("session_upserted", session_id=session.session_id)

    async def get_session(self, session_id: str) -> dict[str, Any] | None:
        """Retrieve a session by ID."""
        cypher = f"MATCH (n:{_SESSION_LABEL} {{session_id: $session_id}}) RETURN n"
        records = await self._execute(cypher, {"session_id": session_id})
        if not records:
            return None
        return dict(records[0]["n"])

    async def delete_session(self, session_id: str) -> bool:
        """Delete a session from the graph."""
        cypher = f"MATCH (n:{_SESSION_LABEL} {{session_id: $session_id}}) DETACH DELETE n RETURN count(n) AS deleted"
        records = await self._execute(cypher, {"session_id": session_id})
        deleted = records[0]["deleted"] if records else 0
        return deleted > 0

    async def upsert_lock(self, file_path: str, session_id: str) -> None:
        """Store a file lock."""
        props = {
            "file_path": file_path,
            "session_id": session_id,
            "acquired_at": datetime.now(UTC).isoformat(),
        }
        cypher = f"""
        MERGE (n:{_LOCK_LABEL} {{file_path: $file_path, session_id: $session_id}})
        SET n += $props
        """
        await self._execute(cypher, {"file_path": file_path, "session_id": session_id, "props": props})
        log.debug("lock_upserted", file_path=file_path, session_id=session_id)

    async def get_lock(self, file_path: str) -> dict[str, Any] | None:
        """Get lock info for a file."""
        cypher = f"MATCH (n:{_LOCK_LABEL} {{file_path: $file_path}}) RETURN n LIMIT 1"
        records = await self._execute(cypher, {"file_path": file_path})
        if not records:
            return None
        return dict(records[0]["n"])

    async def release_lock(self, file_path: str, session_id: str) -> bool:
        """Release a file lock."""
        cypher = f"""
        MATCH (n:{_LOCK_LABEL} {{file_path: $file_path, session_id: $session_id}})
        DETACH DELETE n
        RETURN count(n) AS deleted
        """
        records = await self._execute(cypher, {"file_path": file_path, "session_id": session_id})
        deleted = records[0]["deleted"] if records else 0
        if deleted > 0:
            log.debug("lock_released", file_path=file_path, session_id=session_id)
        return deleted > 0

    async def release_all_locks(self, session_id: str) -> int:
        """Release all locks held by a session."""
        cypher = f"""
        MATCH (n:{_LOCK_LABEL} {{session_id: $session_id}})
        DETACH DELETE n
        RETURN count(n) AS deleted
        """
        records = await self._execute(cypher, {"session_id": session_id})
        deleted = records[0]["deleted"] if records else 0
        log.info("locks_released_by_session", session_id=session_id, count=deleted)
        return deleted

    async def upsert_nodes(self, nodes: Sequence[GraphNode]) -> None:
        if not nodes:
            return
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
        stem = file_path.rsplit("/", 1)[-1] if "/" in file_path else file_path
        cypher = f"""
        MATCH (n:{_ALL_LABEL})
        WHERE n.file_path = $file_path OR n.file_path = $stem
        DETACH DELETE n
        RETURN count(n) AS deleted
        """
        records = await self._execute(cypher, {"file_path": file_path, "stem": stem})
        deleted = records[0]["deleted"] if records else 0
        log.info("nodes_deleted_by_file", file_path=file_path, deleted=deleted)
        return deleted

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
        direction: str = "outgoing",
    ) -> list[GraphNode]:
        rel_type = edge_type.value
        if direction == "incoming":
            cypher = f"""
            MATCH path = (start:{_ALL_LABEL} {{id: $id}})<-[r:{rel_type}*1..{depth}]-(node:{_ALL_LABEL})
            RETURN DISTINCT node
            LIMIT $max_nodes
            """
        else:
            cypher = f"""
            MATCH path = (start:{_ALL_LABEL} {{id: $id}})-[r:{rel_type}*1..{depth}]->(node:{_ALL_LABEL})
            RETURN DISTINCT node
            LIMIT $max_nodes
            """
        records = await self._execute(cypher, {"id": start_id, "max_nodes": max_nodes})
        return [_record_to_node(dict(rec["node"])) for rec in records]

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
            stem = file_path.rsplit("/", 1)[-1] if "/" in file_path else file_path
            conditions.append("(n.file_path = $file_path OR n.file_path = $stem)")
            params["file_path"] = file_path
            params["stem"] = stem
        if name:
            conditions.append("n.structural_name = $name")
            params["name"] = name

        where = " AND ".join(conditions)
        where_clause = f"WHERE {where}" if where else ""
        cypher = f"MATCH (n:{_ALL_LABEL}) {where_clause} RETURN n"
        records = await self._execute(cypher, params)
        return [_record_to_node(dict(rec["n"])) for rec in records]

    async def find_nodes_by_scope(self, scope: str) -> list[GraphNode]:
        """Find nodes matching a scope prefix (package:path or file:path)."""
        if scope == "full":
            cypher = f"MATCH (n:{_ALL_LABEL}) RETURN n"
            records = await self._execute(cypher)
            return [_record_to_node(dict(rec["n"])) for rec in records]

        if scope.startswith("package:"):
            prefix = scope[len("package:") :]
            cypher = f"MATCH (n:{_ALL_LABEL}) WHERE n.file_path STARTS WITH $prefix RETURN n"
            records = await self._execute(cypher, {"prefix": prefix})
            return [_record_to_node(dict(rec["n"])) for rec in records]

        if scope.startswith("file:"):
            fp = scope[len("file:") :]
            cypher = f"MATCH (n:{_ALL_LABEL}) WHERE n.file_path = $fp RETURN n"
            records = await self._execute(cypher, {"fp": fp})
            return [_record_to_node(dict(rec["n"])) for rec in records]

        return []

    async def get_node_degree(self, node_id: str) -> tuple[int, int]:
        """Return (in_degree, out_degree) for a node."""
        cypher = f"""
        MATCH (n:{_ALL_LABEL} {{id: $id}})
        OPTIONAL MATCH (n)-[out]->()
        OPTIONAL MATCH ()-[inp]->(n)
        RETURN count(DISTINCT out) AS out_degree, count(DISTINCT inp) AS in_degree
        """
        records = await self._execute(cypher, {"id": node_id})
        if records:
            return records[0]["in_degree"], records[0]["out_degree"]
        return 0, 0

    async def count_nodes(self) -> int:
        cypher = f"MATCH (n:{_ALL_LABEL}) RETURN count(n) AS cnt"
        records = await self._execute(cypher)
        return records[0]["cnt"] if records else 0

    async def count_edges(self) -> int:
        cypher = "MATCH ()-[r]->() RETURN count(r) AS cnt"
        records = await self._execute(cypher)
        return records[0]["cnt"] if records else 0

    async def search_nodes(
        self,
        query_terms: list[str],
        match: str = "any",
        node_types: list[str] | None = None,
        tags: list[str] | None = None,
        scope: str | None = None,
        top_k: int = 5,
    ) -> list[dict[str, Any]]:
        """Keyword search using Neo4j full-text index (BM25)."""
        search_query = " OR ".join(query_terms) if match == "any" else " AND ".join(query_terms)

        # If search_query is empty, return empty list
        if not search_query:
            return []

        conditions: list[str] = []
        params: dict[str, Any] = {"search_query": search_query, "limit": top_k}

        if scope and scope != "full":
            if scope.startswith("package:"):
                prefix = scope[len("package:") :]
                conditions.append("node.file_path STARTS WITH $scope_prefix")
                params["scope_prefix"] = prefix
            elif scope.startswith("file:"):
                fp = scope[len("file:") :]
                conditions.append("node.file_path = $scope_file")
                params["scope_file"] = fp

        if node_types:
            placeholders = ", ".join(f"$nt{i}" for i in range(len(node_types)))
            conditions.append(f"node.type IN [{placeholders}]")
            for i, nt in enumerate(node_types):
                params[f"nt{i}"] = nt

        where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else ""

        cypher = f"""
        CALL db.index.fulltext.queryNodes('node_search_index', $search_query) 
        YIELD node, score
        {where_clause}
        RETURN node, score
        LIMIT $limit
        """

        records = await self._execute(cypher, params)

        results: list[dict[str, Any]] = []
        for rec in records:
            node_data = dict(rec["node"])
            node = _record_to_node(node_data)
            results.append(
                {
                    "node_id": node.id,
                    "node_type": node.type.value,
                    "file": node.file_path,
                    "name": node.structural.name,
                    "docstring": node.semantic.docstring,
                    "tags": node.semantic.tags,
                    "score": rec["score"],
                }
            )
        return results

    async def _execute(self, cypher: str, params: dict[str, Any] | None = None) -> list[Any]:
        """Execute a Cypher query and return records."""
        if not self._driver:
            raise RuntimeError("Neo4jGraphStore is not connected. Call connect() first.")
        async with self._driver.session(database=self._database) as session:
            result = await session.run(cypher, params or {})
            return [rec.data() async for rec in result]
