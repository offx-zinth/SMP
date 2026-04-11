"""Shared test fixtures for SMP tests."""

from __future__ import annotations

__import__("pysqlite3")
import sys

sys.modules["sqlite3"] = sys.modules.pop("pysqlite3")


import pytest

from smp.core.models import (
    EdgeType,
    GraphEdge,
    GraphNode,
    NodeType,
    SemanticProperties,
    StructuralProperties,
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
    file_path: str = "src/auth/login.py",
    structural: StructuralProperties | None = None,
    semantic: SemanticProperties | None = None,
) -> GraphNode:
    if structural is None:
        structural = StructuralProperties(
            name="login",
            file=file_path,
            signature="def login(user: User) -> Token:",
            start_line=10,
            end_line=25,
            lines=16,
        )
    if semantic is None:
        semantic = SemanticProperties(
            docstring="Authenticate user and return token.",
            status="enriched",
        )
    return GraphNode(
        id=id,
        type=type,
        file_path=file_path,
        structural=structural,
        semantic=semantic,
    )


def make_edge(
    source: str = "func_login",
    target: str = "func_validate",
    edge_type: EdgeType = EdgeType.CALLS,
) -> GraphEdge:
    return GraphEdge(source_id=source, target_id=target, type=edge_type)
