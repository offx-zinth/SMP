"""Shared test fixtures for SMP tests."""

from __future__ import annotations

# Monkey-patch sqlite3 with pysqlite3-binary (required by ChromaDB on older systems)
__import__("pysqlite3")
import sys
sys.modules["sqlite3"] = sys.modules.pop("pysqlite3")

import asyncio

import pytest

from smp.core.models import (
    EdgeType,
    GraphEdge,
    GraphNode,
    NodeType,
    SemanticInfo,
)
from smp.store.graph.neo4j_store import Neo4jGraphStore
from smp.store.vector.chroma_store import ChromaVectorStore


# ---------------------------------------------------------------------------
# Neo4j fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="session")
def neo4j_store() -> Neo4jGraphStore:
    """Provide a connected Neo4j graph store (session-scoped)."""
    store = Neo4jGraphStore()
    # connect/close are async; we use event_loop below
    return store


@pytest.fixture()
async def clean_graph(neo4j_store: Neo4jGraphStore):
    """Provide a clean Neo4j store, clearing data before and after each test."""
    await neo4j_store.connect()
    await neo4j_store.clear()
    yield neo4j_store
    await neo4j_store.clear()
    await neo4j_store.close()


# ---------------------------------------------------------------------------
# ChromaDB fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
async def vector_store():
    """Provide a clean in-memory ChromaDB vector store."""
    import uuid
    store = ChromaVectorStore(collection_name=f"smp_test_{uuid.uuid4().hex[:8]}")
    await store.connect()
    yield store
    await store.close()


# ---------------------------------------------------------------------------
# Sample data factories
# ---------------------------------------------------------------------------

def make_node(
    id: str = "func_login",
    type: NodeType = NodeType.FUNCTION,
    name: str = "login",
    file_path: str = "src/auth/login.py",
    start_line: int = 10,
    end_line: int = 25,
    signature: str = "def login(user: User) -> Token:",
    semantic: SemanticInfo | None = None,
) -> GraphNode:
    return GraphNode(
        id=id,
        type=type,
        name=name,
        file_path=file_path,
        start_line=start_line,
        end_line=end_line,
        signature=signature,
        semantic=semantic,
    )


def make_edge(
    source: str = "func_login",
    target: str = "func_validate",
    edge_type: EdgeType = EdgeType.CALLS,
) -> GraphEdge:
    return GraphEdge(source_id=source, target_id=target, type=edge_type)
